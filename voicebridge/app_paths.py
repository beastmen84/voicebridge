import sys
from pathlib import Path

from voicebridge.file_checks import RequiredFileSpec, required_files_ready


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


def bundled_models_root():
    return external_base_dir() / "models"


def source_tree_models_root():
    base_dir = external_base_dir()
    if getattr(sys, "frozen", False):
        if base_dir.parent.name.lower() == "dist":
            return base_dir.parent.parent / "models"
        return None
    if base_dir.parent.name.lower() == "dist":
        return base_dir.parent.parent / "models"
    return base_dir / "models"


def unique_paths(paths):
    unique = []
    seen = set()
    for path in paths:
        if path is None:
            continue
        resolved = Path(path).resolve()
        key = str(resolved).casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(resolved)
    return unique


def model_root_candidates():
    return unique_paths([bundled_models_root(), source_tree_models_root()])


def models_download_root():
    source_models = source_tree_models_root()
    if source_models is not None and source_models.parent.exists():
        return source_models.resolve()
    return bundled_models_root().resolve()


def model_subdir(root, *parts):
    path = Path(root)
    for part in parts:
        path /= part
    return path


def resolve_models_root(*subdir_parts, required_specs=()):
    candidates = model_root_candidates()
    if required_specs:
        for root in candidates:
            if required_files_ready(model_subdir(root, *subdir_parts), required_specs):
                return root
    for root in candidates:
        if model_subdir(root, *subdir_parts).exists():
            return root
    return models_download_root()


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
    return resolve_models_root("whisperx", required_specs=stt_whisper_model_required_file_specs())


def stt_model_dir():
    return stt_models_root() / "whisperx"


def stt_whisper_model_required_files():
    return "config.json", "model.bin", "preprocessor_config.json", "tokenizer.json", "vocabulary.json"


def stt_whisper_model_required_file_specs():
    return (
        RequiredFileSpec("config.json", 32),
        RequiredFileSpec("model.bin", 1024 * 1024),
        RequiredFileSpec("preprocessor_config.json", 32),
        RequiredFileSpec("tokenizer.json", 32),
        RequiredFileSpec("vocabulary.json", 32),
    )


def stt_whisper_model_ready():
    return required_files_ready(stt_model_dir(), stt_whisper_model_required_file_specs())


def stt_alignment_model_files():
    return {
        "en": "wav2vec2_fairseq_base_ls960_asr_ls960.pth",
        "it": "wav2vec2_voxpopuli_base_10k_asr_it.pt",
    }


def stt_alignment_model_ready(language_code):
    filename = stt_alignment_model_files().get(language_code)
    return bool(filename and (stt_model_dir() / filename).is_file())


def local_tts_model_dir():
    return resolve_models_root(
        "coqui",
        "tts",
        "tts_models--multilingual--multi-dataset--xtts_v2",
        required_specs=local_tts_model_required_file_specs(),
    ) / "coqui"


def local_tts_model_cache_dir():
    return local_tts_model_dir() / "tts" / "tts_models--multilingual--multi-dataset--xtts_v2"


def local_tts_model_required_files():
    return "config.json", "model.pth", "speakers_xtts.pth", "vocab.json"


def local_tts_model_required_file_specs():
    return (
        RequiredFileSpec("config.json", 32),
        RequiredFileSpec("model.pth", 1024 * 1024),
        RequiredFileSpec("speakers_xtts.pth", 1024),
        RequiredFileSpec("vocab.json", 32),
    )


def local_tts_model_ready():
    return required_files_ready(local_tts_model_cache_dir(), local_tts_model_required_file_specs())


def local_tts_dvae_path():
    return local_tts_model_cache_dir() / "dvae.pth"


def local_tts_dvae_ready():
    return required_files_ready(local_tts_model_cache_dir(), [RequiredFileSpec("dvae.pth", 1024 * 1024)])


def local_tts_mel_stats_path():
    return local_tts_model_cache_dir() / "mel_stats.pth"


def local_tts_mel_stats_ready():
    return required_files_ready(local_tts_model_cache_dir(), [RequiredFileSpec("mel_stats.pth", 32)])


def voice_modeling_worker_path():
    return external_base_dir() / "voice_modeling_worker.py"


def video_anomaly_worker_path():
    return external_base_dir() / "video_anomaly_worker.py"


def stt_runtime_site_packages():
    base_dir = external_base_dir()
    if (base_dir / "python-ml").is_dir():
        return base_dir / "python-ml" / "Lib" / "site-packages"
    return base_dir / ".venv-ml" / "Lib" / "site-packages"
