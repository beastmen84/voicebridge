import sys
from pathlib import Path


def resource_path(relative_path):
    base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base_path / relative_path


def external_base_dir():
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        if exe_dir.name.lower() == "dist":
            return exe_dir.parent
        return exe_dir
    return Path(__file__).resolve().parent


def stt_python_path():
    base_dir = external_base_dir()
    bundled_python = base_dir / "python-stt" / "python.exe"
    if bundled_python.is_file():
        return bundled_python
    return base_dir / ".venv-stt" / "Scripts" / "python.exe"


def stt_worker_path():
    return external_base_dir() / "stt_worker.py"


def stt_models_root():
    return external_base_dir() / "models"


def stt_model_dir():
    return stt_models_root() / "whisperx"


def stt_runtime_site_packages():
    base_dir = external_base_dir()
    if (base_dir / "python-stt").is_dir():
        return base_dir / "python-stt" / "Lib" / "site-packages"
    return base_dir / ".venv-stt" / "Lib" / "site-packages"
