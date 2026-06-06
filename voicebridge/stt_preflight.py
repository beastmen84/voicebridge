import subprocess
from pathlib import Path
from typing import TypedDict

from voicebridge.app_paths import (
    stt_alignment_model_files,
    stt_model_dir,
    stt_models_root,
    stt_python_path,
    stt_runtime_site_packages,
    stt_whisper_model_required_file_specs,
    stt_worker_path,
)
from voicebridge.file_checks import partial_download_files, required_file_issue

STT_RUNTIME_INSPECTION_TIMEOUT_SECONDS = 45
STT_RUNTIME_INSPECTION_RETRY_TIMEOUT_SECONDS = 90


class SttRuntimeInfo(TypedDict):
    torch_ok: bool
    torch_version: str
    cuda_build: str
    cuda_available: bool
    cuda_device_count: int
    cuda_device_name: str
    cuda_total_memory_bytes: int
    detail: str


def inspect_stt_runtime(
    python_path: Path,
    timeout_seconds: int = STT_RUNTIME_INSPECTION_TIMEOUT_SECONDS,
) -> SttRuntimeInfo:
    default_info: SttRuntimeInfo = {
        "torch_ok": False,
        "torch_version": "",
        "cuda_build": "",
        "cuda_available": False,
        "cuda_device_count": 0,
        "cuda_device_name": "",
        "cuda_total_memory_bytes": 0,
        "detail": "Torch runtime was not inspected.",
    }
    if not python_path.is_file():
        default_info["detail"] = f"Python runtime not found: {python_path}"
        return default_info

    script = (
        "import torch\n"
        "print('torch_ok=1')\n"
        "print('torch_version=' + str(torch.__version__))\n"
        "print('cuda_build=' + str(torch.version.cuda or ''))\n"
        "available = torch.cuda.is_available()\n"
        "total_memory = 0\n"
        "if available:\n"
        "    try:\n"
        "        total_memory = int(torch.cuda.get_device_properties(0).total_memory)\n"
        "    except Exception:\n"
        "        total_memory = 0\n"
        "print('cuda_available=' + ('1' if available else '0'))\n"
        "print('cuda_device_count=' + str(torch.cuda.device_count()))\n"
        "print('cuda_device_name=' + (torch.cuda.get_device_name(0) if available else ''))\n"
        "print('cuda_total_memory_bytes=' + str(total_memory))\n"
    )

    try:
        result = subprocess.run(
            [str(python_path), "-c", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        default_info["detail"] = f"Could not inspect Torch runtime: {exc}"
        return default_info

    output = f"{result.stdout or ''}\n{result.stderr or ''}".strip()
    if result.returncode != 0:
        default_info["detail"] = output or f"Torch runtime inspection failed with code {result.returncode}."
        return default_info

    values = {}
    for line in output.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()

    try:
        cuda_device_count = int(values.get("cuda_device_count", "0"))
    except ValueError:
        cuda_device_count = 0
    try:
        cuda_total_memory_bytes = int(values.get("cuda_total_memory_bytes", "0"))
    except ValueError:
        cuda_total_memory_bytes = 0

    cuda_available = values.get("cuda_available") == "1"
    cuda_build = values.get("cuda_build", "")
    cuda_device_name = values.get("cuda_device_name", "")
    torch_version = values.get("torch_version", "")
    if cuda_available:
        detail = f"Torch {torch_version}; CUDA {cuda_build}; {cuda_device_name or 'CUDA device available'}."
    elif cuda_build:
        detail = f"Torch {torch_version}; CUDA build {cuda_build}, but no CUDA device is available."
    else:
        detail = f"Torch {torch_version}; CPU runtime."

    return {
        "torch_ok": values.get("torch_ok") == "1",
        "torch_version": torch_version,
        "cuda_build": cuda_build,
        "cuda_available": cuda_available,
        "cuda_device_count": cuda_device_count,
        "cuda_device_name": cuda_device_name,
        "cuda_total_memory_bytes": max(0, cuda_total_memory_bytes),
        "detail": detail,
    }


def inspect_stt_runtime_with_retry(python_path: Path) -> SttRuntimeInfo:
    if not python_path.is_file():
        return inspect_stt_runtime(python_path)

    first_result = inspect_stt_runtime(
        python_path,
        timeout_seconds=STT_RUNTIME_INSPECTION_TIMEOUT_SECONDS,
    )
    if first_result["torch_ok"]:
        return first_result

    retry_result = inspect_stt_runtime(
        python_path,
        timeout_seconds=STT_RUNTIME_INSPECTION_RETRY_TIMEOUT_SECONDS,
    )
    if retry_result["torch_ok"]:
        retry_result["detail"] = f"{retry_result['detail']} Torch inspection passed after one retry."
        return retry_result

    retry_result["detail"] = (
        f"{retry_result['detail']} Torch inspection was retried once after an initial failure: "
        f"{first_result['detail']}"
    )
    return retry_result


def check_stt_preflight():
    checks = []
    optional_checks = []

    def add_check(label, check_path, ok=None):
        resolved_path = Path(check_path)
        exists = resolved_path.exists() if ok is None else ok
        checks.append((label, exists, resolved_path))

    def add_optional_check(label, check_path, ok=None):
        resolved_path = Path(check_path)
        exists = resolved_path.exists() if ok is None else ok
        optional_checks.append((label, exists, resolved_path))

    python_path = stt_python_path()
    worker_path = stt_worker_path()
    model_dir = stt_model_dir()
    models_root = stt_models_root()
    runtime_info = inspect_stt_runtime_with_retry(python_path)

    add_check("STT Python runtime", python_path, python_path.is_file())
    add_check("Torch runtime", python_path, runtime_info["torch_ok"])
    add_check("STT worker", worker_path, worker_path.is_file())
    for spec in stt_whisper_model_required_file_specs():
        path = model_dir / spec.filename
        add_check(
            f"Whisper large-v3 {spec.filename}",
            path,
            ok=not required_file_issue(path, min_bytes=spec.min_bytes),
        )
    for partial_path in partial_download_files(model_dir):
        add_optional_check("Partial download file", partial_path, ok=False)
    for language, filename in stt_alignment_model_files().items():
        add_optional_check(f"Alignment model {language}", model_dir / filename)
    add_check(
        "Silero VAD cache",
        models_root / "torch" / "hub" / "snakers4_silero-vad_master",
    )
    add_check(
        "NLTK English punctuation",
        models_root / "nltk" / "tokenizers" / "punkt_tab" / "english",
    )
    add_check(
        "NLTK Italian punctuation",
        models_root / "nltk" / "tokenizers" / "punkt_tab" / "italian",
    )

    ffmpeg_dir = stt_runtime_site_packages() / "imageio_ffmpeg" / "binaries"
    add_check("Bundled ffmpeg", ffmpeg_dir, ffmpeg_dir.is_dir() and any(ffmpeg_dir.glob("ffmpeg*.exe")))

    missing = [(label, path) for label, exists, path in checks if not exists]
    if missing:
        summary = f"STT core package incomplete: {len(missing)} missing item(s). Open details for paths."
    elif runtime_info["cuda_available"]:
        device_name = runtime_info["cuda_device_name"] or "CUDA device"
        summary = (
            "Offline STT ready: large-v3, VAD, ffmpeg and CUDA runtime found. "
            f"GPU: {device_name}. SRT alignment languages can be downloaded on request."
        )
    else:
        summary = (
            "Offline STT ready: large-v3, VAD, ffmpeg and CPU runtime found. "
            "SRT alignment languages can be downloaded on request."
        )

    details = []
    for label, exists, path in checks:
        marker = "OK" if exists else "MISSING"
        details.append(f"{marker}: {label} - {path}")
    for label, exists, path in optional_checks:
        marker = "OK" if exists else "OPTIONAL"
        details.append(f"{marker}: {label} - {path}")
    details.append(f"INFO: {runtime_info['detail']}")
    return not missing, summary, details, runtime_info
