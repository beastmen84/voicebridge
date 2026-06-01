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


def ml_python_path():
    base_dir = external_base_dir()
    bundled_ml_python = base_dir / "python-ml" / "python.exe"
    if bundled_ml_python.is_file():
        return bundled_ml_python
    ml_venv_python = base_dir / ".venv-ml" / "Scripts" / "python.exe"
    if ml_venv_python.is_file():
        return ml_venv_python
    return ml_venv_python


def stt_python_path():
    return ml_python_path()


def stt_worker_path():
    return external_base_dir() / "stt_worker.py"


def local_tts_worker_path():
    return external_base_dir() / "local_tts_worker.py"


def stt_models_root():
    return external_base_dir() / "models"


def stt_model_dir():
    return stt_models_root() / "whisperx"


def stt_whisper_model_required_files():
    return ("config.json", "model.bin", "preprocessor_config.json", "tokenizer.json", "vocabulary.json")


def stt_whisper_model_ready():
    model_dir = stt_model_dir()
    return all((model_dir / filename).is_file() for filename in stt_whisper_model_required_files())


def stt_alignment_model_files():
    return {
        "en": "wav2vec2_fairseq_base_ls960_asr_ls960.pth",
        "it": "wav2vec2_voxpopuli_base_10k_asr_it.pt",
    }


def stt_alignment_model_ready(language_code):
    filename = stt_alignment_model_files().get(language_code)
    return bool(filename and (stt_model_dir() / filename).is_file())


def local_tts_model_dir():
    return stt_models_root() / "coqui"


def local_tts_model_cache_dir():
    return local_tts_model_dir() / "tts" / "tts_models--multilingual--multi-dataset--xtts_v2"


def local_tts_model_required_files():
    return ("config.json", "model.pth", "speakers_xtts.pth", "vocab.json")


def local_tts_model_ready():
    model_dir = local_tts_model_cache_dir()
    return all((model_dir / filename).is_file() for filename in local_tts_model_required_files())


def local_tts_dvae_path():
    return local_tts_model_cache_dir() / "dvae.pth"


def local_tts_dvae_ready():
    return local_tts_dvae_path().is_file()


def stt_runtime_site_packages():
    base_dir = external_base_dir()
    if (base_dir / "python-ml").is_dir():
        return base_dir / "python-ml" / "Lib" / "site-packages"
    return base_dir / ".venv-ml" / "Lib" / "site-packages"
