from pathlib import Path

from voicebridge.app_paths import (
    stt_model_dir,
    stt_models_root,
    stt_python_path,
    stt_runtime_site_packages,
    stt_worker_path,
)

STT_ALIGNMENT_MODELS = {
    "en": "wav2vec2_fairseq_base_ls960_asr_ls960.pth",
    "it": "wav2vec2_voxpopuli_base_10k_asr_it.pt",
}


def check_stt_preflight():
    checks = []

    def add_check(label, path, ok=None):
        path = Path(path)
        exists = path.exists() if ok is None else ok
        checks.append((label, exists, path))

    python_path = stt_python_path()
    worker_path = stt_worker_path()
    model_dir = stt_model_dir()
    models_root = stt_models_root()

    add_check("STT Python runtime", python_path, python_path.is_file())
    add_check("STT worker", worker_path, worker_path.is_file())
    add_check("Whisper large-v3 model", model_dir / "model.bin")
    add_check("Whisper config", model_dir / "config.json")
    add_check("Whisper preprocessor config", model_dir / "preprocessor_config.json")
    add_check("Whisper tokenizer", model_dir / "tokenizer.json")
    add_check("Whisper vocabulary", model_dir / "vocabulary.json")
    for language, filename in STT_ALIGNMENT_MODELS.items():
        add_check(f"Alignment model {language}", model_dir / filename)
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
        summary = f"STT offline package incomplete: {len(missing)} missing item(s). Open details for paths."
    else:
        summary = (
            "Offline STT ready: large-v3, English/Italian alignment, VAD, ffmpeg and CPU runtime found. "
            "Other SRT alignment languages can be downloaded on request."
        )

    details = []
    for label, exists, path in checks:
        marker = "OK" if exists else "MISSING"
        details.append(f"{marker}: {label} - {path}")
    details.append("INFO: CPU-only STT runtime included.")
    return not missing, summary, details
