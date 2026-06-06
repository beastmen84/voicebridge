import argparse
import importlib
import os
import sys
import wave
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any

from voicebridge.file_checks import RequiredFileSpec, required_files_ready, validate_output_path
from voicebridge.local_tts_presets import (
    DEFAULT_LOCAL_TTS_PRESET_KEY,
    LOCAL_TTS_PRESETS,
    local_tts_preset_label,
    local_tts_preset_settings,
    normalize_local_tts_preset_key,
)
from voicebridge.tts_text import (
    TTS_MAX_CHUNK_CHARS,
    prepare_tts_chunk_for_generation,
    split_tts_text_for_tts,
)
from voicebridge.tts_text import (
    normalize_tts_text as shared_normalize_tts_text,
)
from voicebridge.tts_timeline import write_local_tts_chunk_timeline

DEFAULT_XTTS_MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"
XTTS_MODEL_CACHE_NAME = "tts_models--multilingual--multi-dataset--xtts_v2"
XTTS_MODEL_REQUIRED_FILES = ("config.json", "model.pth", "speakers_xtts.pth", "vocab.json")
XTTS_MODEL_REQUIRED_FILE_SPECS = (
    RequiredFileSpec("config.json", 32),
    RequiredFileSpec("model.pth", 1024 * 1024),
    RequiredFileSpec("speakers_xtts.pth", 1024),
    RequiredFileSpec("vocab.json", 32),
)
XTTS_MAX_CHUNK_CHARS = TTS_MAX_CHUNK_CHARS
XTTS_CHUNK_SILENCE_SECONDS = 0.25
XTTS_STABLE_INFERENCE_SETTINGS = local_tts_preset_settings("stable")


def status(message):
    print(f"STATUS: {message}", flush=True)


def progress(percent):
    percent = max(0, min(100, int(round(percent))))
    print(f"PROGRESS: {percent}", flush=True)


def project_root():
    return Path(__file__).resolve().parent


def load_optional_module(module_name: str) -> Any:
    return importlib.import_module(module_name)


def configure_model_cache(model_root):
    model_root = Path(model_root)
    tts_home = model_root
    huggingface_home = model_root / "huggingface"
    tts_home.mkdir(parents=True, exist_ok=True)
    huggingface_home.mkdir(parents=True, exist_ok=True)
    os.environ["TTS_HOME"] = str(tts_home)
    os.environ["COQUI_TTS_HOME"] = str(tts_home)
    os.environ["HF_HOME"] = str(huggingface_home)


def xtts_model_cache_dir(model_dir):
    return Path(model_dir) / "tts" / XTTS_MODEL_CACHE_NAME


def xtts_model_ready(model_dir):
    model_path = xtts_model_cache_dir(model_dir)
    return required_files_ready(model_path, XTTS_MODEL_REQUIRED_FILE_SPECS)


def xtts_terms_path(model_dir):
    return xtts_model_cache_dir(model_dir) / "tos_agreed.txt"


def xtts_terms_agreed(model_dir):
    return xtts_terms_path(model_dir).is_file() or os.environ.get("COQUI_TOS_AGREED") == "1"


def write_xtts_terms_agreement(model_dir):
    terms_path = xtts_terms_path(model_dir)
    terms_path.parent.mkdir(parents=True, exist_ok=True)
    terms_path.write_text("I have read, understood and agreed to the Terms and Conditions.", encoding="utf-8")


def normalize_tts_language(language):
    if not language:
        return "it"
    language = language.strip().lower().replace("_", "-")
    if language in {"zh-cn"}:
        return language
    return language.split("-", 1)[0]


def resolve_runtime_device(device):
    torch = load_optional_module("torch")

    if device == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cuda" and not torch.cuda.is_available():
        raise ValueError(
            "CUDA was selected, but this local TTS runtime cannot access an NVIDIA CUDA GPU. "
            "Use CPU only, or bundle a CUDA-enabled PyTorch runtime."
        )
    return device


def read_text(path):
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace").strip()
    if not text:
        raise ValueError("The selected input file contains no readable text.")
    return text


def normalize_tts_text(text):
    return shared_normalize_tts_text(text)


def split_tts_text_for_xtts(text, max_chars=XTTS_MAX_CHUNK_CHARS):
    return split_tts_text_for_tts(text, max_chars)


def wav_audio_signature(params):
    return params.nchannels, params.sampwidth, params.framerate, params.comptype


def wav_duration_seconds(path):
    with wave.open(str(path), "rb") as wav_file:
        return wav_file.getnframes() / max(1, wav_file.getframerate())


def merge_wav_files(input_paths: Sequence[str | Path], output_path: str | Path) -> None:
    input_paths = [Path(path) for path in input_paths]
    if not input_paths:
        raise ValueError("No local TTS audio chunks were generated.")

    with wave.open(str(input_paths[0]), "rb") as first:
        params = first.getparams()
        signature = wav_audio_signature(params)
        with wave.open(str(output_path), "wb") as output:
            output.setparams(params)
            output.writeframes(first.readframes(first.getnframes()))
            for input_path in input_paths[1:]:
                output.writeframes(silent_wav_frames(params, XTTS_CHUNK_SILENCE_SECONDS))
                with wave.open(str(input_path), "rb") as part:
                    if wav_audio_signature(part.getparams()) != signature:
                        raise RuntimeError("Local TTS generated incompatible WAV chunks.")
                    output.writeframes(part.readframes(part.getnframes()))


def silent_wav_frames(params, seconds):
    frame_count = int(params.framerate * seconds)
    return b"\x00" * frame_count * params.nchannels * params.sampwidth


def synthesize_text_chunks(tts, chunks, speaker_wav, language, output_path: str | Path, inference_settings=None):
    output_path = Path(output_path)
    if not chunks:
        raise ValueError("The selected input file contains no readable text after cleanup.")

    settings = dict(inference_settings or XTTS_STABLE_INFERENCE_SETTINGS)
    chunk_paths = []
    try:
        if len(chunks) == 1:
            status("Generating local TTS audio chunk 1/1...")
            tts.tts_to_file(
                text=prepare_tts_chunk_for_generation(chunks[0]),
                speaker_wav=speaker_wav[0] if len(speaker_wav) == 1 else speaker_wav,
                language=language,
                file_path=str(output_path),
                **settings,
            )
            progress(92)
            duration = wav_duration_seconds(output_path)
            return [
                {
                    "id": "block-0001",
                    "index": 1,
                    "source_block_index": 1,
                    "chunk_index": 1,
                    "start_seconds": 0.0,
                    "end_seconds": duration,
                    "duration_seconds": duration,
                    "text": chunks[0],
                }
            ]

        generation_start = 35
        generation_end = 92
        timeline_chunks = []
        cursor = 0.0
        for index, chunk in enumerate(chunks, start=1):
            status(f"Generating local TTS audio chunk {index}/{len(chunks)}...")
            chunk_path = output_path.with_name(f"{output_path.stem}.part-{index:03d}{output_path.suffix}")
            chunk_paths.append(chunk_path)
            tts.tts_to_file(
                text=prepare_tts_chunk_for_generation(chunk),
                speaker_wav=speaker_wav[0] if len(speaker_wav) == 1 else speaker_wav,
                language=language,
                file_path=str(chunk_path),
                **settings,
            )
            duration = wav_duration_seconds(chunk_path)
            timeline_chunks.append(
                {
                    "id": f"block-0001-chunk-{index:04d}",
                    "index": index,
                    "source_block_index": 1,
                    "chunk_index": index,
                    "start_seconds": cursor,
                    "end_seconds": cursor + duration,
                    "duration_seconds": duration,
                    "text": chunk,
                }
            )
            cursor += duration
            if index < len(chunks):
                cursor += XTTS_CHUNK_SILENCE_SECONDS
            progress(generation_start + ((generation_end - generation_start) * index / len(chunks)))
        status("Merging local TTS audio chunks...")
        merge_wav_files(chunk_paths, output_path)
        progress(94)
        return timeline_chunks
    finally:
        for chunk_path in chunk_paths:
            with suppress(OSError):
                chunk_path.unlink(missing_ok=True)


def reference_audio_paths(paths):
    references = [Path(path).resolve() for path in paths]
    if not references:
        raise ValueError("At least one voice reference audio file is required.")
    missing = [path for path in references if not path.is_file()]
    if missing:
        raise ValueError(f"Voice reference audio file not found: {missing[0]}")
    return [str(path) for path in references]


def load_tts_api():
    try:
        tts_api_module = load_optional_module("TTS.api")
    except ImportError as exc:
        raise RuntimeError(
            "The local TTS runtime is missing coqui-tts. Install it in the ML environment with "
            "`.venv-ml\\Scripts\\python.exe -m pip install coqui-tts`."
        ) from exc
    return tts_api_module.TTS


def xtts_tts_api_model_path(model_path: Path) -> str:
    """Work around Coqui's XTTS path loader expecting a directory for checkpoint_dir."""
    if model_path.name == "model.pth" and (model_path.parent / "vocab.json").is_file():
        return str(model_path.parent)
    return str(model_path)


def load_xtts_model(args, device):
    tts_api = load_tts_api()
    if args.model_path:
        if not args.config_path:
            raise ValueError("A config path is required when using a trained local model.")
        model_path = Path(args.model_path).resolve()
        config_path = Path(args.config_path).resolve()
        if not model_path.is_file():
            raise ValueError(f"Trained local model file not found: {model_path}")
        if not config_path.is_file():
            raise ValueError(f"Trained local model config not found: {config_path}")
        return tts_api(
            model_path=xtts_tts_api_model_path(model_path),
            config_path=str(config_path),
            progress_bar=False,
        ).to(device)

    model_dir = Path(args.model_dir or (project_root() / "models" / "coqui")).resolve()
    if not xtts_model_ready(model_dir):
        raise ValueError("XTTS-v2 model is not downloaded yet. Use Download XTTS-v2 before Local TTS generation.")
    return tts_api(args.model).to(device)


def download_xtts_model(args):
    model_dir = Path(args.model_dir or (project_root() / "models" / "coqui")).resolve()
    configure_model_cache(model_dir)
    if args.accept_license:
        os.environ["COQUI_TOS_AGREED"] = "1"
    if not xtts_terms_agreed(model_dir):
        raise ValueError(
            "XTTS-v2 requires acceptance of the non-commercial Coqui Public Model License before download."
        )

    try:
        model_manager_module = load_optional_module("TTS.utils.manage")
    except ImportError as exc:
        raise RuntimeError(
            "The local TTS runtime is missing coqui-tts. Install it in the ML environment with "
            "`.venv-ml\\Scripts\\python.exe -m pip install coqui-tts`."
        ) from exc

    progress(2)
    if xtts_model_ready(model_dir):
        status("XTTS-v2 model is already downloaded.")
        progress(100)
        return

    status("Downloading XTTS-v2 model. This can take several minutes...")
    manager = model_manager_module.ModelManager(output_prefix=model_dir, progress_bar=False)
    manager.download_model(args.model)
    if args.accept_license:
        write_xtts_terms_agreement(model_dir)
    if not xtts_model_ready(model_dir):
        raise RuntimeError("XTTS-v2 download finished, but required model files are missing.")
    status(f"XTTS-v2 model ready: {xtts_model_cache_dir(model_dir)}")
    progress(100)


def synthesize(args):
    model_dir = Path(args.model_dir or (project_root() / "models" / "coqui")).resolve()
    configure_model_cache(model_dir)
    if args.offline:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"

    text_path = Path(args.text_file).resolve()
    output_path = Path(args.output).resolve()
    output_path = validate_output_path(output_path, source_path=text_path, create_parent=True)
    if not text_path.is_file():
        raise ValueError(f"Text file not found: {text_path}")

    chunks = split_tts_text_for_xtts(read_text(text_path))
    speaker_wav = reference_audio_paths(args.speaker_wav)
    language = normalize_tts_language(args.language)
    device = resolve_runtime_device(args.device)
    progress(2)
    status(f"Loading XTTS model on {device}...")
    tts = load_xtts_model(args, device)
    progress(35)

    preset_key = normalize_local_tts_preset_key(args.preset)
    status(f"Prepared {len(chunks)} local TTS chunk(s).")
    status(f"Using XTTS preset: {local_tts_preset_label(preset_key)}.")
    timeline_chunks = synthesize_text_chunks(
        tts,
        chunks,
        speaker_wav,
        language,
        output_path,
        local_tts_preset_settings(preset_key),
    )
    progress(95)
    if not output_path.is_file() or output_path.stat().st_size <= 0:
        raise RuntimeError("Local TTS did not create an audio file.")
    if args.timeline_json:
        write_local_tts_chunk_timeline(
            args.timeline_json,
            audio_path=output_path,
            chunks=timeline_chunks,
            total_duration_seconds=wav_duration_seconds(output_path),
        )
    status(f"Done: {output_path}")
    progress(100)


def parse_args():
    parser = argparse.ArgumentParser(description="Offline local TTS worker using Coqui XTTS.")
    parser.add_argument("--download-model", action="store_true")
    parser.add_argument("--accept-license", action="store_true")
    parser.add_argument("--text-file")
    parser.add_argument("--output")
    parser.add_argument("--speaker-wav", action="append", default=[])
    parser.add_argument("--language", default="it")
    parser.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda"])
    parser.add_argument("--preset", default=DEFAULT_LOCAL_TTS_PRESET_KEY, choices=list(LOCAL_TTS_PRESETS))
    parser.add_argument("--model", default=DEFAULT_XTTS_MODEL)
    parser.add_argument("--model-path")
    parser.add_argument("--config-path")
    parser.add_argument("--model-dir")
    parser.add_argument("--timeline-json")
    parser.add_argument("--offline", action="store_true")
    return parser.parse_args()


def main():
    try:
        args = parse_args()
        if args.download_model:
            download_xtts_model(args)
        else:
            if not args.text_file:
                raise ValueError("Text file path is required.")
            if not args.output:
                raise ValueError("Output file path is required.")
            synthesize(args)
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
