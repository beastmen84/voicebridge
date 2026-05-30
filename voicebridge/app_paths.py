import sys
from pathlib import Path


def source_base_dir():
    return Path(__file__).resolve().parents[1]


def resource_path(relative_path):
    base_path = Path(getattr(sys, "_MEIPASS", source_base_dir()))
    return base_path / relative_path


def external_base_dir():
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        if exe_dir.name.lower() == "dist":
            return exe_dir.parent
        return exe_dir
    return source_base_dir()


def stt_python_path():
    base_dir = external_base_dir()
    bundled_ml_python = base_dir / "python-ml" / "python.exe"
    if bundled_ml_python.is_file():
        return bundled_ml_python
    bundled_python = base_dir / "python-stt" / "python.exe"
    if bundled_python.is_file():
        return bundled_python
    ml_venv_python = base_dir / ".venv-ml" / "Scripts" / "python.exe"
    if ml_venv_python.is_file():
        return ml_venv_python
    return base_dir / ".venv-stt" / "Scripts" / "python.exe"


def stt_worker_path():
    return external_base_dir() / "stt_worker.py"


def stt_models_root():
    return external_base_dir() / "models"


def stt_model_dir():
    return stt_models_root() / "whisperx"


def stt_runtime_site_packages():
    base_dir = external_base_dir()
    if (base_dir / "python-ml").is_dir():
        return base_dir / "python-ml" / "Lib" / "site-packages"
    if (base_dir / "python-stt").is_dir():
        return base_dir / "python-stt" / "Lib" / "site-packages"
    if (base_dir / ".venv-ml").is_dir():
        return base_dir / ".venv-ml" / "Lib" / "site-packages"
    return base_dir / ".venv-stt" / "Lib" / "site-packages"
