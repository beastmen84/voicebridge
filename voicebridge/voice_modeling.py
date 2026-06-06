import json
import shutil
import subprocess
import urllib.request
from contextlib import suppress
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, NotRequired, TypedDict
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
    existing_parent,
    format_bytes,
    partial_download_files,
    required_file_issue,
    validate_output_path,
)
from voicebridge.json_schemas import (
    VOICE_MODELING_JOB_CONFIG_JSON_KIND,
    VOICE_MODELING_TRAINING_STATE_JSON_KIND,
    app_json_version_supported,
    with_schema_metadata,
)
from voicebridge.modeling_datasets import (
    MODELING_DATASET_EXPORT_JSON_KIND,
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
VOICE_MODELING_DEFAULT_MAX_EPOCHS = 15
VOICE_MODELING_DEFAULT_BATCH_SIZE = 2
VOICE_MODELING_DEFAULT_GRAD_ACCUM_STEPS = 1
VOICE_MODELING_DEFAULT_MAX_AUDIO_SECONDS = 11
VOICE_MODELING_XTTS_MAX_TEXT_CHARS = 200
XTTS_DVAE_DOWNLOAD_URL = "https://huggingface.co/coqui/XTTS-v2/resolve/main/dvae.pth?download=true"
XTTS_DVAE_SHA256 = "b29bc227d410d4991e0a8c09b858f77415013eeb9fba9650258e96095557d97a"
XTTS_MEL_STATS_DOWNLOAD_URL = "https://huggingface.co/coqui/XTTS-v2/resolve/main/mel_stats.pth?download=true"
XTTS_TRAINING_ASSETS_MIN_FREE_BYTES = 512 * 1024 * 1024
VOICE_MODELING_MIN_FREE_BYTES = 2 * 1024 * 1024 * 1024


class VoiceModelingDownloadCancelled(Exception):
    pass


class VoiceModelingExportInfo(TypedDict):
    dataset_dir: str
    dataset_id: str
    profile_id: str
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
    max_audio_seconds: NotRequired[int]
    grad_accum_steps: NotRequired[int]
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


class VoiceModelingTrainingDefaults(TypedDict):
    max_epochs: int
    batch_size: int


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


def voice_modeling_logs_root() -> Path:
    return external_base_dir() / "logs" / "voice_modeling"


def managed_voice_modeling_output_dir(path: str | Path) -> Path | None:
    output_path = Path(path).expanduser().resolve()
    root = voice_modeling_outputs_root().resolve()
    try:
        output_path.relative_to(root)
    except ValueError:
        return None
    return output_path if output_path != root else None


def download_file_to_path(
    source_url: str,
    target_path: str | Path,
    *,
    expected_sha256: str = "",
    progress_callback=None,
    should_cancel=None,
) -> Path:
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_target = target.with_suffix(f"{target.suffix}.part")
    request = urllib.request.Request(source_url, headers={"User-Agent": "VoiceBridge"})
    digest = sha256()
    downloaded_bytes = 0
    try:
        if should_cancel and should_cancel():
            raise VoiceModelingDownloadCancelled("Training assets download cancelled.")
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
            total_header = response.headers.get("Content-Length", "")
            try:
                total_bytes = int(total_header)
            except ValueError:
                total_bytes = 0
            with temporary_target.open("wb") as output:
                while True:
                    if should_cancel and should_cancel():
                        raise VoiceModelingDownloadCancelled("Training assets download cancelled.")
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    digest.update(chunk)
                    downloaded_bytes += len(chunk)
                    if progress_callback and total_bytes:
                        progress_callback(min(100.0, downloaded_bytes * 100.0 / total_bytes))
        if should_cancel and should_cancel():
            raise VoiceModelingDownloadCancelled("Training assets download cancelled.")
    except VoiceModelingDownloadCancelled:
        temporary_target.unlink(missing_ok=True)
        raise
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


def download_xtts_dvae(progress_callback=None, should_cancel=None) -> Path:
    return download_file_to_path(
        XTTS_DVAE_DOWNLOAD_URL,
        local_tts_dvae_path(),
        expected_sha256=XTTS_DVAE_SHA256,
        progress_callback=progress_callback,
        should_cancel=should_cancel,
    )


def download_xtts_training_assets(progress_callback=None, should_cancel=None) -> list[Path]:
    downloads: list[tuple[str, Path, str]] = []
    if not local_tts_dvae_ready():
        downloads.append((XTTS_DVAE_DOWNLOAD_URL, local_tts_dvae_path(), XTTS_DVAE_SHA256))
    if not local_tts_mel_stats_ready():
        downloads.append((XTTS_MEL_STATS_DOWNLOAD_URL, local_tts_mel_stats_path(), ""))

    if not downloads:
        if should_cancel and should_cancel():
            raise VoiceModelingDownloadCancelled("Training assets download cancelled.")
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
        if should_cancel and should_cancel():
            raise VoiceModelingDownloadCancelled("Training assets download cancelled.")
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
                should_cancel=should_cancel,
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
    if not app_json_version_supported(dataset_data, kind=MODELING_DATASET_EXPORT_JSON_KIND):
        raise ValueError("dataset.json schema version is not supported.")

    summary = dataset_data.get("summary", {})
    if not isinstance(summary, dict):
        raise ValueError("dataset.json is missing the summary object.")
    readiness = summary.get("readiness")
    if not isinstance(readiness, str) or readiness not in {MODELING_DATASET_USABLE, MODELING_DATASET_GOOD}:
        raise ValueError("Voice Modeling requires an exported dataset with Usable or Good readiness.")
    readiness_text = str(readiness)

    metadata_rows = parse_voice_modeling_metadata(metadata_path, export_dir)
    if not metadata_rows:
        raise ValueError("metadata.csv contains no usable rows.")

    name = dataset_data.get("name")
    language_code = dataset_data.get("language_code")
    dataset_id = dataset_data.get("dataset_id")
    profile_id = dataset_data.get("profile_id")
    return {
        "dataset_dir": str(export_dir.resolve()),
        "dataset_id": dataset_id if isinstance(dataset_id, str) else "",
        "profile_id": profile_id if isinstance(profile_id, str) else "",
        "name": name if isinstance(name, str) and name else export_dir.name,
        "language_code": language_code if isinstance(language_code, str) and language_code else "unknown",
        "readiness": readiness_text,
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
            validate_voice_modeling_output_location(output_path)
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


def recommended_voice_modeling_training_defaults(
    export_info: VoiceModelingExportInfo,
    *,
    cuda_total_memory_bytes: int | None = None,
) -> VoiceModelingTrainingDefaults:
    ready_duration = max(0.0, float(export_info.get("ready_duration_seconds", 0.0) or 0.0))
    metadata_rows = max(0, int(export_info.get("metadata_rows", 0) or 0))
    batch_size = recommended_voice_modeling_batch_size(cuda_total_memory_bytes)

    if ready_duration < 5 * 60 or metadata_rows < 25:
        max_epochs = 10
    elif ready_duration < 15 * 60 or metadata_rows < 80:
        max_epochs = 20
    elif ready_duration < 30 * 60 or metadata_rows < 180:
        max_epochs = 30
    elif ready_duration < 60 * 60:
        max_epochs = 40
    elif ready_duration < 3 * 60 * 60:
        max_epochs = 30
    else:
        max_epochs = 20

    if batch_size <= 2 and max_epochs > 20:
        max_epochs -= 5
    return {"max_epochs": max_epochs, "batch_size": batch_size}


def recommended_voice_modeling_batch_size(cuda_total_memory_bytes: int | None = None) -> int:
    if not cuda_total_memory_bytes:
        return 2
    gib = cuda_total_memory_bytes / (1024**3)
    if gib >= 24:
        return 16
    if gib >= 16:
        return 8
    if gib >= 12:
        return 6
    if gib >= 8:
        return 4
    return 2


def build_voice_modeling_job_config(
    export_info: VoiceModelingExportInfo,
    *,
    output_dir: str | Path | None = None,
    resume_checkpoint: str | Path | None = None,
    device: str = "auto",
    max_epochs: int | None = None,
    batch_size: int | None = None,
    job_id: str | None = None,
) -> VoiceModelingJobConfig:
    normalized_device = normalize_voice_modeling_device(device)
    defaults = recommended_voice_modeling_training_defaults(export_info)
    max_epochs = defaults["max_epochs"] if max_epochs is None else max_epochs
    batch_size = defaults["batch_size"] if batch_size is None else batch_size
    normalized_epochs = min(max(int(max_epochs), VOICE_MODELING_MIN_EPOCHS), VOICE_MODELING_MAX_EPOCHS)
    normalized_batch_size = min(max(int(batch_size), VOICE_MODELING_MIN_BATCH_SIZE), VOICE_MODELING_MAX_BATCH_SIZE)
    output_path = Path(output_dir).expanduser() if output_dir else default_voice_modeling_output_dir(export_info)
    resume_path = Path(resume_checkpoint).expanduser() if resume_checkpoint else None
    if resume_path and not resume_path.is_file():
        raise ValueError("Resume checkpoint must be an existing file.")
    validate_voice_modeling_output_location(output_path)
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


def validate_voice_modeling_output_location(output_dir: str | Path) -> Path:
    output_path = Path(output_dir).expanduser()
    if not str(output_path).strip():
        raise ValueError("Choose a model output folder.")
    if output_path.exists() and not output_path.is_dir():
        raise ValueError(f"Model output path points to a file, not a folder: {output_path}")
    write_test_dir = output_path if output_path.is_dir() else existing_parent(output_path)
    if not write_test_dir.is_dir():
        raise ValueError(f"The model output parent folder does not exist: {write_test_dir}")
    validate_output_path(write_test_dir / ".voicebridge-output-check", create_parent=False)
    return output_path


def save_voice_modeling_job_config(config: VoiceModelingJobConfig) -> Path:
    output_dir = Path(config["output_dir"]).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    config_path = output_dir / VOICE_MODELING_JOB_CONFIG
    config_path.write_text(
        json.dumps(
            with_schema_metadata(dict(config), VOICE_MODELING_JOB_CONFIG_JSON_KIND),
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return config_path


def load_voice_modeling_job_config(config_path: str | Path) -> VoiceModelingJobConfig:
    path = Path(config_path).expanduser()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Training config is not readable JSON: {path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Training config must contain an object: {path}")
    if not app_json_version_supported(data, kind=VOICE_MODELING_JOB_CONFIG_JSON_KIND):
        raise ValueError(f"Training config schema version is not supported: {path}")
    dataset = data.get("dataset")
    if not isinstance(dataset, dict):
        raise ValueError(f"Training config is missing dataset metadata: {path}")
    output_dir = data.get("output_dir")
    if not isinstance(output_dir, str) or not output_dir:
        raise ValueError(f"Training config is missing output_dir: {path}")
    dataset_info: VoiceModelingExportInfo = {
        "dataset_dir": _string_or_default(dataset.get("dataset_dir")),
        "name": _string_or_default(dataset.get("name"), "Unknown dataset"),
        "language_code": _string_or_default(dataset.get("language_code"), "unknown"),
        "readiness": _string_or_default(dataset.get("readiness")),
        "ready_clips": _int(dataset.get("ready_clips")),
        "ready_duration_seconds": _float(dataset.get("ready_duration_seconds")),
        "metadata_path": _string_or_default(dataset.get("metadata_path")),
        "dataset_json_path": _string_or_default(dataset.get("dataset_json_path")),
        "wavs_dir": _string_or_default(dataset.get("wavs_dir")),
        "metadata_rows": _int(dataset.get("metadata_rows")),
    }
    defaults = recommended_voice_modeling_training_defaults(dataset_info)
    configured_epochs = _int(data.get("max_epochs")) or defaults["max_epochs"]
    configured_batch_size = _int(data.get("batch_size")) or defaults["batch_size"]
    job_config: VoiceModelingJobConfig = {
        "id": _string_or_default(data.get("id")),
        "status": _string_or_default(data.get("status"), "configured"),
        "training_backend": _string_or_default(data.get("training_backend"), "xtts_v2"),
        "dataset_dir": _string_or_default(data.get("dataset_dir"), dataset_info["dataset_dir"]),
        "output_dir": output_dir,
        "resume_checkpoint": _string_or_default(data.get("resume_checkpoint")),
        "device": normalize_voice_modeling_device(data.get("device")),
        "max_epochs": min(max(configured_epochs, VOICE_MODELING_MIN_EPOCHS), VOICE_MODELING_MAX_EPOCHS),
        "batch_size": min(max(configured_batch_size, VOICE_MODELING_MIN_BATCH_SIZE), VOICE_MODELING_MAX_BATCH_SIZE),
        "dataset": dataset_info,
        "created_at": _string_or_default(data.get("created_at")),
        "updated_at": _string_or_default(data.get("updated_at")),
    }
    return job_config


def update_voice_modeling_job_status(config_path: str | Path, status: str) -> VoiceModelingJobConfig:
    config = load_voice_modeling_job_config(config_path)
    config["status"] = status
    config["updated_at"] = utc_timestamp()
    save_voice_modeling_job_config(config)
    return config


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
    state_path.write_text(
        json.dumps(
            with_schema_metadata(state, VOICE_MODELING_TRAINING_STATE_JSON_KIND),
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )
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


def cleanup_incomplete_voice_modeling_job(
    config_path: str | Path,
    *,
    reason: str,
) -> dict[str, str]:
    config = load_voice_modeling_job_config(config_path)
    archive_dir = archive_voice_modeling_job_logs(config_path, reason=reason)
    deleted_output_dir = delete_managed_voice_modeling_output_dir(config["output_dir"])
    return {
        "archive_dir": str(archive_dir) if archive_dir else "",
        "deleted_output_dir": str(deleted_output_dir) if deleted_output_dir else "",
    }


def cleanup_completed_voice_modeling_training_artifacts(
    config_path: str | Path,
    trainer_output_dir: str | Path,
) -> dict[str, str]:
    config = load_voice_modeling_job_config(config_path)
    output_dir = Path(config["output_dir"]).expanduser().resolve()
    managed_output_dir = managed_voice_modeling_output_dir(output_dir)
    archive_dir = archive_voice_modeling_job_logs(config_path, reason="completed")
    result = {
        "archive_dir": str(archive_dir) if archive_dir else "",
        "deleted_training_dir": "",
    }
    if not managed_output_dir:
        return result

    training_dir = Path(trainer_output_dir).expanduser().resolve()
    run_dir = output_dir / "run"
    try:
        training_dir.relative_to(run_dir.resolve())
    except ValueError:
        return result
    if not training_dir.exists() or training_dir == run_dir.resolve():
        return result

    try:
        shutil.rmtree(training_dir)
    except OSError:
        return result
    result["deleted_training_dir"] = str(training_dir)
    prune_empty_voice_modeling_run_dirs(run_dir)
    return result


def prune_empty_voice_modeling_run_dirs(run_dir: Path) -> None:
    for candidate in (run_dir / "training", run_dir):
        with suppress(OSError):
            candidate.rmdir()


def prune_previous_voice_modeling_outputs(config_path: str | Path) -> list[Path]:
    current_config_path = Path(config_path).expanduser().resolve()
    current_config = load_voice_modeling_job_config(current_config_path)
    current_output_dir = Path(current_config["output_dir"]).expanduser().resolve()
    current_identity = voice_modeling_config_identity(current_config)
    if not current_identity:
        return []

    root = voice_modeling_outputs_root()
    if not root.is_dir():
        return []

    deleted: list[Path] = []
    for candidate_config_path in list(root.rglob(VOICE_MODELING_JOB_CONFIG)):
        other_config_path = candidate_config_path.resolve()
        if other_config_path == current_config_path:
            continue
        try:
            other_config = load_voice_modeling_job_config(other_config_path)
        except (OSError, ValueError):
            continue
        if other_config.get("status") == "running":
            continue
        other_output_dir = Path(other_config.get("output_dir") or other_config_path.parent).expanduser().resolve()
        if other_output_dir == current_output_dir:
            continue
        if not voice_modeling_config_matches_identity(other_config, current_identity):
            continue
        archive_voice_modeling_job_logs(other_config_path, reason="replaced")
        deleted_output_dir = delete_managed_voice_modeling_output_dir(other_output_dir)
        if deleted_output_dir:
            deleted.append(deleted_output_dir)
    return deleted


def archive_voice_modeling_job_logs(config_path: str | Path, *, reason: str) -> Path | None:
    try:
        config = load_voice_modeling_job_config(config_path)
    except (OSError, ValueError):
        return None
    output_dir = Path(config["output_dir"]).expanduser()
    dataset = config.get("dataset", {})
    dataset_name = dataset.get("name") if isinstance(dataset, dict) else ""
    base_name = safe_voice_profile_audio_stem(dataset_name if isinstance(dataset_name, str) else "")
    if not base_name:
        base_name = safe_voice_profile_audio_stem(output_dir.name) or "voice-modeling"
    reason_name = safe_voice_profile_audio_stem(reason) or "job"
    archive_dir = unique_voice_modeling_log_dir(
        voice_modeling_logs_root() / f"{base_name}-{file_timestamp()}-{reason_name}"
    )
    archive_dir.mkdir(parents=True, exist_ok=False)
    summary = {
        "reason": reason,
        "archived_at": utc_timestamp(),
        "config_path": str(Path(config_path).expanduser().resolve()),
        "output_dir": str(output_dir.expanduser().resolve()),
        "status": config.get("status", ""),
        "dataset": config.get("dataset", {}),
    }
    (archive_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    for source_path in voice_modeling_log_sources(config_path, output_dir):
        copy_voice_modeling_log_file(source_path, archive_dir)
    return archive_dir


def voice_modeling_log_sources(config_path: str | Path, output_dir: Path) -> list[Path]:
    candidates = [
        Path(config_path).expanduser(),
        output_dir / VOICE_MODELING_TRAINING_STATE,
        output_dir / VOICE_MODELING_COMMAND,
        output_dir / VOICE_MODELING_LOG,
    ]
    if output_dir.is_dir():
        with suppress(OSError):
            candidates.extend(output_dir.rglob("*.log"))
        with suppress(OSError):
            candidates.extend(output_dir.rglob("trainer_*_log.txt"))
    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            continue
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def copy_voice_modeling_log_file(source_path: Path, archive_dir: Path) -> None:
    try:
        if source_path.stat().st_size > 25 * 1024 * 1024:
            return
        target_name = source_path.name
        target_path = archive_dir / target_name
        if target_path.exists():
            target_path = archive_dir / f"{source_path.parent.name}-{target_name}"
        shutil.copy2(source_path, target_path)
    except OSError:
        return


def delete_managed_voice_modeling_output_dir(output_dir: str | Path) -> Path | None:
    managed_output_dir = managed_voice_modeling_output_dir(output_dir)
    if not managed_output_dir or not managed_output_dir.exists():
        return None
    try:
        shutil.rmtree(managed_output_dir)
    except OSError:
        return None
    return managed_output_dir


def unique_voice_modeling_log_dir(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 1000):
        candidate = path.with_name(f"{path.name}-{index}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Could not create a unique log directory for {path}.")


def voice_modeling_config_identity(config: dict[str, Any]) -> dict[str, str]:
    dataset = config.get("dataset", {})
    dataset = dataset if isinstance(dataset, dict) else {}
    dataset_json = read_voice_modeling_dataset_json(dataset, config)
    return {
        "dataset_id": _string_or_default(dataset.get("dataset_id") or dataset_json.get("dataset_id")),
        "profile_id": _string_or_default(dataset.get("profile_id") or dataset_json.get("profile_id")),
        "name": _string_or_default(dataset.get("name") or dataset_json.get("name")),
        "language_code": _string_or_default(dataset.get("language_code") or dataset_json.get("language_code")),
    }


def read_voice_modeling_dataset_json(dataset: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    candidate_values = [
        dataset.get("dataset_json_path"),
        Path(_string_or_default(config.get("dataset_dir"))) / "dataset.json"
        if _string_or_default(config.get("dataset_dir"))
        else "",
    ]
    for value in candidate_values:
        path = Path(value).expanduser() if isinstance(value, str | Path) and value else None
        if path is None or not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and app_json_version_supported(data, kind=MODELING_DATASET_EXPORT_JSON_KIND):
            return data
    return {}


def voice_modeling_config_matches_identity(config: dict[str, Any], identity: dict[str, str]) -> bool:
    other = voice_modeling_config_identity(config)
    if identity.get("profile_id") and other.get("profile_id"):
        return identity["profile_id"] == other["profile_id"]
    if identity.get("dataset_id") and other.get("dataset_id"):
        return identity["dataset_id"] == other["dataset_id"]
    return bool(
        identity.get("name")
        and other.get("name")
        and identity["name"] == other["name"]
        and identity.get("language_code")
        and identity["language_code"] == other.get("language_code")
    )


def split_voice_modeling_metadata_rows(
    rows: list[tuple[str, str]],
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    if len(rows) <= 1:
        return rows, []
    eval_count = max(1, round(len(rows) * 0.15))
    eval_count = min(eval_count, len(rows) - 1)
    return rows[:-eval_count], rows[-eval_count:]


def validate_voice_modeling_training_rows(rows: list[tuple[str, str]]) -> None:
    too_long_rows = [
        (index, text)
        for index, (_wav_path, text) in enumerate(rows, start=1)
        if len(text) > VOICE_MODELING_XTTS_MAX_TEXT_CHARS
    ]
    if not too_long_rows:
        return
    first_index, first_text = too_long_rows[0]
    preview = first_text[:120].rstrip()
    raise ValueError(
        "XTTS-v2 training requires shorter transcript rows. "
        f"{len(too_long_rows)} metadata row(s) exceed {VOICE_MODELING_XTTS_MAX_TEXT_CHARS} characters. "
        f"First long row: {first_index} ({len(first_text)} characters): {preview}..."
    )


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
    validate_voice_modeling_training_rows(rows)
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


def _string_or_default(value: Any, default: str = "") -> str:
    return value if isinstance(value, str) else default
