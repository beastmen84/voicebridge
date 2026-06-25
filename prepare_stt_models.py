import importlib
import os
import time
import warnings
from pathlib import Path
from typing import Any

STT_MODEL = "large-v3"
ALIGN_LANGUAGES = ("en", "it")
TORCHCODEC_AUDIO_DECODING_WARNING = (
    r"\s*torchcodec is not installed correctly so built-in audio decoding will fail\..*"
)


def ignore_torchcodec_audio_decoding_warning() -> None:
    warnings.filterwarnings(
        "ignore",
        message=TORCHCODEC_AUDIO_DECODING_WARNING,
        category=UserWarning,
        module=r"pyannote\.audio\.core\.io",
    )


ignore_torchcodec_audio_decoding_warning()


def configure_cache(root):
    model_root = root / "models"
    whisperx_dir = model_root / "whisperx"
    torch_home = model_root / "torch"
    nltk_data = model_root / "nltk"
    huggingface_home = model_root / "huggingface"

    for path in (whisperx_dir, torch_home, nltk_data, huggingface_home):
        path.mkdir(parents=True, exist_ok=True)

    os.environ["TORCH_HOME"] = str(torch_home)
    os.environ["HF_HOME"] = str(huggingface_home)
    os.environ["NLTK_DATA"] = str(nltk_data)
    os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"
    os.environ["HF_XET_HIGH_PERFORMANCE"] = "1"
    return whisperx_dir, nltk_data


def load_optional_module(module_name: str) -> Any:
    if module_name == "whisperx":
        with warnings.catch_warnings():
            ignore_torchcodec_audio_decoding_warning()
            return importlib.import_module(module_name)
    return importlib.import_module(module_name)


def run_with_retries(label, callback, attempts=4):
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            print(f"{label} (attempt {attempt}/{attempts})...", flush=True)
            return callback()
        except (ImportError, OSError, RuntimeError, TimeoutError, ValueError) as exc:
            last_error = exc
            if attempt == attempts:
                break
            print(f"{label} failed: {exc}. Retrying in 20 seconds...", flush=True)
            time.sleep(20)
    raise last_error


def main():
    root = Path(__file__).resolve().parent
    whisperx_dir, nltk_data = configure_cache(root)

    print(f"Downloading Faster Whisper {STT_MODEL} into {whisperx_dir}...", flush=True)
    faster_whisper_utils = load_optional_module("faster_whisper.utils")
    download_model = faster_whisper_utils.download_model

    run_with_retries(
        f"Downloading Faster Whisper {STT_MODEL}",
        lambda: download_model(STT_MODEL, output_dir=str(whisperx_dir)),
    )

    print("Downloading Silero VAD...", flush=True)
    torch = load_optional_module("torch")

    run_with_retries(
        "Downloading Silero VAD",
        lambda: torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            force_reload=False,
            onnx=False,
            trust_repo=True,
        ),
    )

    print("Downloading NLTK punctuation data...", flush=True)
    nltk = load_optional_module("nltk")

    run_with_retries(
        "Downloading NLTK punctuation data",
        lambda: nltk.download("punkt_tab", download_dir=str(nltk_data), quiet=False),
    )

    print("Downloading WhisperX alignment models...", flush=True)
    whisperx = load_optional_module("whisperx")

    for language_code in ALIGN_LANGUAGES:
        run_with_retries(
            f"Downloading alignment model for {language_code}",
            lambda selected_language=language_code: whisperx.load_align_model(
                selected_language,
                "cpu",
                model_dir=str(whisperx_dir),
            ),
        )

    print("STT models are ready.", flush=True)


if __name__ == "__main__":
    with warnings.catch_warnings():
        ignore_torchcodec_audio_decoding_warning()
        main()
