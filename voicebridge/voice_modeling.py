import json
import subprocess
import urllib.request
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, TypedDict
from uuid import uuid4

from voicebridge.app_paths import (
    external_base_dir,
    local_tts_dvae_path,
    local_tts_dvae_ready,
    local_tts_mel_stats_path,
    local_tts_mel_stats_ready,
    local_tts_model_cache_dir,
    local_tts_model_ready,
    local_tts_model_required_file_specs,
    ml_python_path,
    voice_modeling_worker_path,
)
from voicebridge.file_checks import (
    available_disk_bytes,
    ensure_free_space,
    format_bytes,
    partial_download_files,
    required_file_issue,
    validate_output_path,
)
from voicebridge.modeling_datasets import (
    MODELING_DATASET_GOOD,
    MODELING_DATASET_USABLE,
    format_modeling_dataset_duration,
    modeling_dataset_exports_root,
)
from voicebridge.stt_preflight import SttRuntimeInfo, inspect_stt_runtime
from voicebridge.voice_profiles import safe_voice_profile_audio_stem

VOICE_MODELING_OUTPUTS_DIR = "voice_models"
VOICE_MODELING_JOB_CONFIG = "job_config.json"
VOICE_MODELING_TRAINING_STATE = "training_state.json"
VOICE_MODELING_PREPARED_DIR = "prepared_dataset"
VOICE_MODELING_TRAIN_METADATA = "metadata_train.csv"
VOICE_MODELING_EVAL_METADATA = "metadata_eval.csv"
VOICE_MODELING_COMMAND = "training_command.txt"
VOICE_MODELING_LOG = "training.log"
VOICE_MODELING_DEVICE_KEYS = {"auto", "cpu", "cuda"}
VOICE_MODELING_MIN_EPOCHS = 1
VOICE_MODELING_MAX_EPOCHS = 500
VOICE_MODELING_MIN_BATCH_SIZE = 1
VOICE_MODELING_MAX_BATCH_SIZE = 16
VOICE_MODELING_DEFAULT_GRAD_ACCUM_STEPS = 1
VOICE_MODELING_DEFAULT_MAX_AUDIO_SECONDS = 11
XTTS_DVAE_DOWNLOAD_URL = "https://huggingface.co/coqui/XTTS-v2/resolve/main/dvae.pth?download=true"
XTTS_DVAE_SHA256 = "b29bc227d410d4991e0a8c09b858f77415013eeb9fba9650258e96095557d97a"
XTTS_MEL_STATS_DOWNLOAD_URL = "https://huggingface.co/coqui/XTTS-v2/resolve/main/mel_stats.pth?download=true"
XTTS_TRAINING_ASSETS_MIN_FREE_BYTES = 512 * 1024 * 1024
VOICE_MODELING_MIN_FREE_BYTES = 2 * 1024 * 1024 * 1024


class VoiceModelingExportInfo(TypedDict):
    dataset_dir: str
    name: str
    language_code: str
    readiness: str
    ready_clips: int
    ready_duration_seconds: float
    metadata_path: str
    dataset_json_path: str
    wavs_dir: str
    metadata_rows: int


class VoiceModelingJobConfig(TypedDict):
    id: str
    status: str
    training_backend: str
    dataset_dir: str
    output_dir: str
    resume_checkpoint: str
    device: str
    max_epochs: int
    batch_size: int
    dataset: VoiceModelingExportInfo
    created_at: str
    updated_at: str


class VoiceModelingJobSummary(TypedDict):
    config_path: str
    output_dir: str
    dataset_name: str
    status: str
    created_at: str
    updated_at: str


class VoiceModelingTrainingPlan(TypedDict):
    config_path: str
    output_dir: str
    dataset_dir: str
    prepared_dir: str
    train_csv_path: str
    eval_csv_path: str
    command_path: str
    log_path: str
    train_rows: int
    eval_rows: int
    total_rows: int
    device: str
    command: list[str]
    command_text: str


class VoiceModelingTrainingState(TypedDict):
    config_path: str
    output_dir: str
    status: str
    message: str
    updated_at: str


class CoquiRuntimeInfo(TypedDict):
    coqui_ok: bool
    coqui_version: str
    detail: str


class VoiceModelingPreflightResult(TypedDict):
    ok: bool
    summary: str
    details: list[str]
    runtime_info: SttRuntimeInfo
    coqui_info: CoquiRuntimeInfo
    xtts_model_ready: bool
    dvae_ready: bool


def utc_timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def file_timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def voice_modeling_outputs_root() -> Path:
    return external_base_dir() / VOICE_MODELING_OUTPUTS_DIR


def download_file_to_path(
    source_url: str,
    target_path: str | Path,
    *,
    expected_sha256: str = "",
    progress_callback=None,
) -> Path:
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_target = target.with_suffix(f"{target.suffix}.part")
    request = urllib.request.Request(source_url, headers={"User-Agent": "VoiceBridge"})
    digest = sha256()
    downloaded_bytes = 0
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        total_header = response.headers.get("Content-Length", "")
        try:
            total_bytes = int(total_header)
        except ValueError:
            total_bytes = 0
        with temporary_target.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                digest.update(chunk)
                downloaded_bytes += len(chunk)
                if progress_callback and total_bytes:
                    progress_callback(min(100.0, downloaded_bytes * 100.0 / total_bytes))
    actual_sha256 = digest.hexdigest()
    if expected_sha256 and actual_sha256.lower() != expected_sha256.lower():
        temporary_target.unlink(missing_ok=True)
        raise ValueError(
            f"Downloaded file checksum mismatch. Expected {expected_sha256}, got {actual_sha256}."
        )
    temporary_target.replace(target)
    if progress_callback:
        progress_callback(100.0)
    return target


def download_xtts_dvae(progress_callback=None) -> Path:
    return download_file_to_path(
        XTTS_DVAE_DOWNLOAD_URL,
        local_tts_dvae_path(),
        expected_sha256=XTTS_DVAE_SHA256,
        progress_callback=progress_callback,
    )


def download_xtts_training_assets(progress_callback=None) -> list[Path]:
    downloads: list[tuple[str, Path, str]] = []
    if not local_tts_dvae_ready():
        downloads.append((XTTS_DVAE_DOWNLOAD_URL, local_tts_dvae_path(), XTTS_DVAE_SHA256))
    if not local_tts_mel_stats_ready():
        downloads.append((XTTS_MEL_STATS_DOWNLOAD_URL, local_tts_mel_stats_path(), ""))

    if not downloads:
        if progress_callback:
            progress_callback(100.0)
        return [local_tts_dvae_path(), local_tts_mel_stats_path()]

    ensure_free_space(
        local_tts_model_cache_dir(),
        XTTS_TRAINING_ASSETS_MIN_FREE_BYTES,
        "XTTS-v2 training asset download",
    )

    completed: list[Path] = []
    total = len(downloads)
    for index, (source_url, target_path, expected_sha256) in enumerate(downloads):
        start = index * 100.0 / total
        end = (index + 1) * 100.0 / total

        def mapped_progress(percent: float, *, progress_start=start, progress_end=end) -> None:
            if progress_callback:
                progress_callback(progress_start + ((progress_end - progress_start) * percent / 100.0))

        completed.append(
            download_file_to_path(
                source_url,
                target_path,
                expected_sha256=expected_sha256,
                progress_callback=mapped_progress,
            )
        )
    if progress_callback:
        progress_callback(100.0)
    return completed


def validate_voice_modeling_export(dataset_dir: str | Path) -> VoiceModelingExportInfo:
    export_dir = Path(dataset_dir).expanduser()
    if not export_dir.is_dir():
        raise ValueError("Select an existing exported dataset folder.")

    metadata_path = export_dir / "metadata.csv"
    dataset_json_path = export_dir / "dataset.json"
    wavs_dir = export_dir / "wavs"
    if not metadata_path.is_file():
        raise ValueError("The exported dataset is missing metadata.csv.")
    if not dataset_json_path.is_file():
        raise ValueError("The exported dataset is missing dataset.json.")
    if not wavs_dir.is_dir():
        raise ValueError("The exported dataset is missing the wavs folder.")

    try:
        dataset_data = json.loads(dataset_json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("dataset.json is not valid JSON.") from exc
    if not isinstance(dataset_data, dict):
        raise ValueError("dataset.json must contain an object.")

    summary = dataset_data.get("summary", {})
    if not isinstance(summary, dict):
        raise ValueError("dataset.json is missing the summary object.")
    readiness = summary.get("readiness")
    if readiness not in {MODELING_DATASET_USABLE, MODELING_DATASET_GOOD}:
        raise ValueError("Voice Modeling requires an exported dataset with Usable or Good readiness.")

    metadata_rows = parse_voice_modeling_metadata(metadata_path, export_dir)
    if not metadata_rows:
        raise ValueError("metadata.csv contains no usable rows.")

    name = dataset_data.get("name")
    language_code = dataset_data.get("language_code")
    return {
        "dataset_dir": str(export_dir.resolve()),
        "name": name if isinstance(name, str) and name else export_dir.name,
        "language_code": language_code if isinstance(language_code, str) and language_code else "unknown",
        "readiness": readiness,
        "ready_clips": _int(summary.get("ready_clips")),
        "ready_duration_seconds": _float(summary.get("ready_duration_seconds")),
        "metadata_path": str(metadata_path.resolve()),
        "dataset_json_path": str(dataset_json_path.resolve()),
        "wavs_dir": str(wavs_dir.resolve()),
        "metadata_rows": len(metadata_rows),
    }


def inspect_coqui_runtime(python_path: Path) -> CoquiRuntimeInfo:
    default_info: CoquiRuntimeInfo = {
        "coqui_ok": False,
        "coqui_version": "",
        "detail": "Coqui TTS runtime was not inspected.",
    }
    if not python_path.is_file():
        default_info["detail"] = f"Python runtime not found: {python_path}"
        return default_info

    script = (
        "import importlib.metadata as metadata\n"
        "from TTS.api import TTS\n"
        "version = ''\n"
        "for package_name in ('coqui-tts', 'TTS'):\n"
        "    try:\n"
        "        version = metadata.version(package_name)\n"
        "        break\n"
        "    except metadata.PackageNotFoundError:\n"
        "        pass\n"
        "print('coqui_ok=1')\n"
        "print('coqui_version=' + version)\n"
    )
    try:
        result = subprocess.run(
            [str(python_path), "-c", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        default_info["detail"] = f"Could not inspect Coqui TTS runtime: {exc}"
        return default_info

    output = f"{result.stdout or ''}\n{result.stderr or ''}".strip()
    if result.returncode != 0:
        default_info["detail"] = output or f"Coqui TTS runtime inspection failed with code {result.returncode}."
        return default_info

    values = {}
    for line in output.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()

    coqui_version = values.get("coqui_version", "")
    detail = f"Coqui TTS import ready{f' ({coqui_version})' if coqui_version else ''}."
    return {
        "coqui_ok": values.get("coqui_ok") == "1",
        "coqui_version": coqui_version,
        "detail": detail,
    }


def check_voice_modeling_preflight(
    export_info: VoiceModelingExportInfo | None = None,
    *,
    output_dir: str | Path | None = None,
    resume_checkpoint: str | Path | None = None,
    device: str = "auto",
) -> VoiceModelingPreflightResult:
    checks: list[tuple[str, bool, str]] = []

    def add_check(label: str, ok: bool, detail: str | Path) -> None:
        checks.append((label, ok, str(detail)))

    python_path = ml_python_path()
    runtime_info = inspect_stt_runtime(python_path)
    coqui_info = inspect_coqui_runtime(python_path)
    normalized_device = normalize_voice_modeling_device(device)
    model_cache_dir = local_tts_model_cache_dir()

    add_check("ML Python runtime", python_path.is_file(), python_path)
    add_check("Torch runtime", runtime_info["torch_ok"], runtime_info["detail"])
    add_check("Coqui TTS runtime", coqui_info["coqui_ok"], coqui_info["detail"])
    for spec in local_tts_model_required_file_specs():
        path = model_cache_dir / spec.filename
        add_check(
            f"XTTS-v2 {spec.filename}",
            not required_file_issue(path, min_bytes=spec.min_bytes),
            path,
        )
    add_check("XTTS-v2 model package", local_tts_model_ready(), model_cache_dir)
    add_check(
        "XTTS-v2 DVAE checkpoint",
        not required_file_issue(local_tts_dvae_path(), min_bytes=1024 * 1024),
        local_tts_dvae_path(),
    )
    add_check(
        "XTTS-v2 mel stats",
        not required_file_issue(local_tts_mel_stats_path(), min_bytes=32),
        local_tts_mel_stats_path(),
    )
    for partial_path in partial_download_files(model_cache_dir):
        add_check("Partial model download", False, partial_path)

    if export_info:
        try:
            validated_export = validate_voice_modeling_export(export_info["dataset_dir"])
        except ValueError as exc:
            add_check("Selected modeling export", False, str(exc))
        else:
            add_check("Selected modeling export", True, validated_export["dataset_dir"])
    else:
        add_check("Selected modeling export", False, "No dataset export selected.")

    if output_dir:
        output_path = Path(output_dir).expanduser()
        output_parent = output_path.parent if output_path.name else output_path
        output_parent_ready = output_parent.exists() or output_parent.parent.exists()
        add_check("Model output folder", not output_path.is_file(), output_path)
        add_check("Model output parent", output_parent_ready, output_parent)
        try:
            validate_output_path(output_path / ".voicebridge-output-check", create_parent=True)
        except ValueError as exc:
            add_check("Model output writable", False, str(exc))
        else:
            add_check("Model output writable", True, output_path)
        free_bytes = available_disk_bytes(output_path)
        add_check(
            "Model output free space",
            not free_bytes or free_bytes >= VOICE_MODELING_MIN_FREE_BYTES,
            f"{format_bytes(free_bytes)} available; {format_bytes(VOICE_MODELING_MIN_FREE_BYTES)} recommended minimum",
        )
    else:
        add_check("Model output folder", False, "No output folder selected.")

    if resume_checkpoint:
        resume_path = Path(resume_checkpoint).expanduser()
        add_check("Resume checkpoint", resume_path.is_file(), resume_path)

    if normalized_device == "cuda":
        add_check("CUDA device selection", runtime_info["cuda_available"], runtime_info["detail"])

    missing = [(label, detail) for label, ok, detail in checks if not ok]
    if missing:
        summary = f"Voice Modeling preflight incomplete: {len(missing)} missing item(s)."
    elif normalized_device == "cuda" or (normalized_device == "auto" and runtime_info["cuda_available"]):
        device_name = runtime_info["cuda_device_name"] or "CUDA device"
        summary = f"Voice Modeling preflight ready. CUDA available: {device_name}."
    else:
        summary = "Voice Modeling preflight ready for CPU. Training may be slow."

    details = []
    for label, ok, detail in checks:
        marker = "OK" if ok else "MISSING"
        details.append(f"{marker}: {label} - {detail}")
    details.append(f"INFO: {runtime_info['detail']}")
    details.append(f"INFO: {coqui_info['detail']}")
    details.append("INFO: Training worker is available from Local Voices > Training.")

    return {
        "ok": not missing,
        "summary": summary,
        "details": details,
        "runtime_info": runtime_info,
        "coqui_info": coqui_info,
        "xtts_model_ready": local_tts_model_ready(),
        "dvae_ready": local_tts_dvae_ready(),
    }


def list_voice_modeling_exports(exports_root: str | Path | None = None) -> list[VoiceModelingExportInfo]:
    root = Path(exports_root).expanduser() if exports_root else modeling_dataset_exports_root()
    if not root.is_dir():
        return []
    try:
        export_dirs = list(root.iterdir())
    except OSError:
        return []
    exports: list[tuple[float, VoiceModelingExportInfo]] = []
    for export_dir in export_dirs:
        if not export_dir.is_dir():
            continue
        try:
            export_info = validate_voice_modeling_export(export_dir)
            modified_at = export_dir.stat().st_mtime
        except (OSError, ValueError):
            continue
        exports.append((modified_at, export_info))
    return [
        export_info
        for _modified_at, export_info in sorted(
            exports,
            key=lambda item: (item[0], item[1]["dataset_dir"]),
            reverse=True,
        )
    ]


def parse_voice_modeling_metadata(metadata_path: Path, export_dir: Path) -> list[tuple[str, str]]:
    rows = []
    for line_number, raw_line in enumerate(metadata_path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if "|" not in line:
            raise ValueError(f"metadata.csv line {line_number} must use wav_path|text format.")
        wav_path, transcript = line.split("|", 1)
        wav_path = wav_path.strip()
        transcript = transcript.strip()
        if not wav_path or not transcript:
            raise ValueError(f"metadata.csv line {line_number} has an empty wav path or transcript.")
        resolved_wav = (export_dir / wav_path).resolve()
        try:
            resolved_wav.relative_to(export_dir.resolve())
        except ValueError as exc:
            raise ValueError(f"metadata.csv line {line_number} points outside the export folder.") from exc
        if not resolved_wav.is_file():
            raise ValueError(f"metadata.csv line {line_number} references a missing WAV file.")
        rows.append((wav_path, transcript))
    return rows


def default_voice_modeling_output_dir(
    export_info: VoiceModelingExportInfo,
    *,
    timestamp: str | None = None,
) -> Path:
    safe_name = safe_voice_profile_audio_stem(export_info["name"])
    return voice_modeling_outputs_root() / f"{safe_name}-{timestamp or file_timestamp()}"


def build_voice_modeling_job_config(
    export_info: VoiceModelingExportInfo,
    *,
    output_dir: str | Path | None = None,
    resume_checkpoint: str | Path | None = None,
    device: str = "auto",
    max_epochs: int = 50,
    batch_size: int = 2,
    job_id: str | None = None,
) -> VoiceModelingJobConfig:
    normalized_device = normalize_voice_modeling_device(device)
    normalized_epochs = min(max(int(max_epochs), VOICE_MODELING_MIN_EPOCHS), VOICE_MODELING_MAX_EPOCHS)
    normalized_batch_size = min(max(int(batch_size), VOICE_MODELING_MIN_BATCH_SIZE), VOICE_MODELING_MAX_BATCH_SIZE)
    output_path = Path(output_dir).expanduser() if output_dir else default_voice_modeling_output_dir(export_info)
    resume_path = Path(resume_checkpoint).expanduser() if resume_checkpoint else None
    if resume_path and not resume_path.is_file():
        raise ValueError("Resume checkpoint must be an existing file.")
    validate_output_path(output_path / ".voicebridge-output-check", create_parent=True)
    ensure_free_space(output_path, VOICE_MODELING_MIN_FREE_BYTES, "voice model training output")
    timestamp = utc_timestamp()
    return {
        "id": job_id or uuid4().hex,
        "status": "configured",
        "training_backend": "xtts_v2",
        "dataset_dir": export_info["dataset_dir"],
        "output_dir": str(output_path),
        "resume_checkpoint": str(resume_path) if resume_path else "",
        "device": normalized_device,
        "max_epochs": normalized_epochs,
        "batch_size": normalized_batch_size,
        "dataset": export_info,
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def save_voice_modeling_job_config(config: VoiceModelingJobConfig) -> Path:
    output_dir = Path(config["output_dir"]).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    config_path = output_dir / VOICE_MODELING_JOB_CONFIG
    config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return config_path


def load_voice_modeling_job_config(config_path: str | Path) -> VoiceModelingJobConfig:
    path = Path(config_path).expanduser()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Training config is not readable JSON: {path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Training config must contain an object: {path}")
    dataset = data.get("dataset")
    if not isinstance(dataset, dict):
        raise ValueError(f"Training config is missing dataset metadata: {path}")
    output_dir = data.get("output_dir")
    if not isinstance(output_dir, str) or not output_dir:
        raise ValueError(f"Training config is missing output_dir: {path}")
    return data


def update_voice_modeling_job_status(config_path: str | Path, status: str) -> VoiceModelingJobConfig:
    config = dict(load_voice_modeling_job_config(config_path))
    config["status"] = status
    config["updated_at"] = utc_timestamp()
    save_voice_modeling_job_config(config)  # type: ignore[arg-type]
    return config  # type: ignore[return-value]


def voice_modeling_training_state_path(config_path: str | Path) -> Path:
    config = load_voice_modeling_job_config(config_path)
    return Path(config["output_dir"]).expanduser() / VOICE_MODELING_TRAINING_STATE


def write_voice_modeling_training_state(
    config_path: str | Path,
    *,
    status: str,
    message: str = "",
    extra: dict[str, Any] | None = None,
) -> Path:
    config = load_voice_modeling_job_config(config_path)
    output_dir = Path(config["output_dir"]).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    state: dict[str, Any] = {
        "config_path": str(Path(config_path).expanduser().resolve()),
        "output_dir": str(output_dir),
        "status": status,
        "message": message,
        "updated_at": utc_timestamp(),
    }
    if extra:
        state.update(extra)
    state_path = output_dir / VOICE_MODELING_TRAINING_STATE
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return state_path


def voice_modeling_job_summary(config_path: str | Path) -> VoiceModelingJobSummary:
    path = Path(config_path).expanduser().resolve()
    config = load_voice_modeling_job_config(path)
    dataset = config.get("dataset", {})
    dataset_name = dataset.get("name") if isinstance(dataset, dict) else ""
    return {
        "config_path": str(path),
        "output_dir": config["output_dir"],
        "dataset_name": dataset_name if isinstance(dataset_name, str) and dataset_name else "Unknown dataset",
        "status": config.get("status", "") if isinstance(config.get("status"), str) else "",
        "created_at": config.get("created_at", "") if isinstance(config.get("created_at"), str) else "",
        "updated_at": config.get("updated_at", "") if isinstance(config.get("updated_at"), str) else "",
    }


def list_voice_modeling_job_configs(outputs_root: str | Path | None = None) -> list[VoiceModelingJobSummary]:
    root = Path(outputs_root).expanduser() if outputs_root else voice_modeling_outputs_root()
    if not root.is_dir():
        return []
    summaries = []
    for config_path in root.rglob(VOICE_MODELING_JOB_CONFIG):
        if not config_path.is_file():
            continue
        try:
            summary = voice_modeling_job_summary(config_path)
            modified_at = config_path.stat().st_mtime
        except (OSError, ValueError):
            continue
        summaries.append((modified_at, summary))
    return [
        summary
        for _modified_at, summary in sorted(
            summaries,
            key=lambda item: (item[0], item[1]["config_path"]),
            reverse=True,
        )
    ]


def voice_modeling_job_label(job: VoiceModelingJobSummary) -> str:
    timestamp = job["updated_at"] or job["created_at"] or Path(job["output_dir"]).name
    status = job["status"].replace("_", " ").title() if job["status"] else "Configured"
    return f"{job['dataset_name']} | {status} | {timestamp}"


def split_voice_modeling_metadata_rows(
    rows: list[tuple[str, str]],
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    if len(rows) <= 1:
        return rows, []
    eval_count = max(1, round(len(rows) * 0.15))
    eval_count = min(eval_count, len(rows) - 1)
    return rows[:-eval_count], rows[-eval_count:]


def write_coqui_metadata(path: Path, rows: list[tuple[str, str]], *, speaker_name: str = "voicebridge") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["audio_file|text|speaker_name"]
    for audio_file, text in rows:
        safe_text = " ".join(text.replace("|", ",").split())
        lines.append(f"{audio_file}|{safe_text}|{speaker_name}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_voice_modeling_training_command(
    config_path: str | Path,
    *,
    dry_run: bool = False,
    python_path: str | Path | None = None,
    worker_path: str | Path | None = None,
) -> list[str]:
    command = [
        str(Path(python_path).expanduser() if python_path else ml_python_path()),
        "-u",
        str(Path(worker_path).expanduser() if worker_path else voice_modeling_worker_path()),
        "--config",
        str(Path(config_path).expanduser().resolve()),
    ]
    if dry_run:
        command.append("--dry-run")
    return command


def prepare_voice_modeling_training_job(config_path: str | Path) -> VoiceModelingTrainingPlan:
    resolved_config_path = Path(config_path).expanduser().resolve()
    config = load_voice_modeling_job_config(resolved_config_path)
    export_info = validate_voice_modeling_export(config["dataset_dir"])
    rows = parse_voice_modeling_metadata(Path(export_info["metadata_path"]), Path(export_info["dataset_dir"]))
    train_rows, eval_rows = split_voice_modeling_metadata_rows(rows)
    if not train_rows:
        raise ValueError("Training requires at least one train metadata row.")

    output_dir = Path(config["output_dir"]).expanduser()
    prepared_dir = output_dir / VOICE_MODELING_PREPARED_DIR
    train_csv = prepared_dir / VOICE_MODELING_TRAIN_METADATA
    eval_csv = prepared_dir / VOICE_MODELING_EVAL_METADATA
    command_path = output_dir / VOICE_MODELING_COMMAND
    log_path = output_dir / VOICE_MODELING_LOG

    write_coqui_metadata(train_csv, train_rows)
    write_coqui_metadata(eval_csv, eval_rows or train_rows[-1:])
    command = build_voice_modeling_training_command(resolved_config_path)
    command_text = subprocess.list2cmdline(command)
    output_dir.mkdir(parents=True, exist_ok=True)
    command_path.write_text(command_text + "\n", encoding="utf-8")
    update_voice_modeling_job_status(resolved_config_path, "prepared")
    write_voice_modeling_training_state(
        resolved_config_path,
        status="prepared",
        message="Training metadata prepared.",
        extra={
            "prepared_dir": str(prepared_dir),
            "train_csv_path": str(train_csv),
            "eval_csv_path": str(eval_csv),
            "train_rows": len(train_rows),
            "eval_rows": len(eval_rows or train_rows[-1:]),
            "total_rows": len(rows),
            "command_path": str(command_path),
            "log_path": str(log_path),
        },
    )
    return {
        "config_path": str(resolved_config_path),
        "output_dir": str(output_dir),
        "dataset_dir": export_info["dataset_dir"],
        "prepared_dir": str(prepared_dir),
        "train_csv_path": str(train_csv),
        "eval_csv_path": str(eval_csv),
        "command_path": str(command_path),
        "log_path": str(log_path),
        "train_rows": len(train_rows),
        "eval_rows": len(eval_rows or train_rows[-1:]),
        "total_rows": len(rows),
        "device": normalize_voice_modeling_device(config.get("device")),
        "command": command,
        "command_text": command_text,
    }


def voice_modeling_training_plan_text(plan: VoiceModelingTrainingPlan) -> str:
    return "\n".join(
        [
            f"Config: {plan['config_path']}",
            f"Dataset: {plan['dataset_dir']}",
            f"Output: {plan['output_dir']}",
            f"Prepared rows: {plan['train_rows']} train, {plan['eval_rows']} eval, {plan['total_rows']} total",
            f"Device: {plan['device']}",
            f"Train CSV: {plan['train_csv_path']}",
            f"Eval CSV: {plan['eval_csv_path']}",
            f"Log: {plan['log_path']}",
            "",
            "Command:",
            plan["command_text"],
        ]
    )


def voice_modeling_export_summary_text(export_info: VoiceModelingExportInfo) -> str:
    return "\n".join(
        [
            f"Dataset: {export_info['name']}",
            f"Language: {export_info['language_code']}",
            f"Readiness: {export_info['readiness'].replace('_', ' ').title()}",
            f"Ready clips: {export_info['ready_clips']}",
            f"Metadata rows: {export_info['metadata_rows']}",
            f"Ready duration: {format_modeling_dataset_duration(export_info['ready_duration_seconds'])}",
            f"Folder: {export_info['dataset_dir']}",
        ]
    )


def voice_modeling_export_label(export_info: VoiceModelingExportInfo) -> str:
    folder_name = Path(export_info["dataset_dir"]).name
    readiness = export_info["readiness"].replace("_", " ").title()
    duration = format_modeling_dataset_duration(export_info["ready_duration_seconds"])
    return (
        f"{export_info['name']} | {folder_name} | {export_info['language_code']} | "
        f"{readiness} | {export_info['ready_clips']} clip(s), {duration}"
    )


def normalize_voice_modeling_device(device: Any) -> str:
    return device if isinstance(device, str) and device in VOICE_MODELING_DEVICE_KEYS else "auto"


def _float(value: Any) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0
