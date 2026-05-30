import argparse
import os
import re
import sys
import wave
from contextlib import suppress
from pathlib import Path

DEFAULT_XTTS_MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"
XTTS_MODEL_CACHE_NAME = "tts_models--multilingual--multi-dataset--xtts_v2"
XTTS_MODEL_REQUIRED_FILES = ("config.json", "model.pth", "speakers_xtts.pth", "vocab.json")
XTTS_MAX_CHUNK_CHARS = 240


def status(message):
    print(f"STATUS: {message}", flush=True)


def progress(percent):
    percent = max(0, min(100, int(round(percent))))
    print(f"PROGRESS: {percent}", flush=True)


def project_root():
    return Path(__file__).resolve().parent


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
    return all((model_path / filename).is_file() for filename in XTTS_MODEL_REQUIRED_FILES)


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
    import torch

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
    text = text.replace("\ufeff", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00a0", " ").replace("\u200b", "")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" *\n+ *", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([,.;:!?])([^\s,.;:!?])", r"\1 \2", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def split_words_for_xtts(text, max_chars=XTTS_MAX_CHUNK_CHARS):
    chunks = []
    current = []
    current_length = 0
    for word in text.split():
        candidate_length = len(word) if not current else current_length + 1 + len(word)
        if current and candidate_length > max_chars:
            chunks.append(" ".join(current))
            current = [word]
            current_length = len(word)
        else:
            current.append(word)
            current_length = candidate_length
    if current:
        chunks.append(" ".join(current))
    return chunks


def pack_text_fragments_for_xtts(fragments, max_chars=XTTS_MAX_CHUNK_CHARS):
    chunks = []
    current = ""
    for fragment in fragments:
        clean_fragment = fragment.strip()
        if not clean_fragment:
            continue
        if len(clean_fragment) <= max_chars:
            candidates = [clean_fragment]
        else:
            candidates = split_words_for_xtts(clean_fragment, max_chars)
        for candidate in candidates:
            joined = candidate if not current else f"{current} {candidate}"
            if current and len(joined) > max_chars:
                chunks.append(current)
                current = candidate
            else:
                current = joined
    if current:
        chunks.append(current)
    return chunks


def split_tts_text_for_xtts(text, max_chars=XTTS_MAX_CHUNK_CHARS):
    text = normalize_tts_text(text)
    if not text:
        return []
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks = []
    for sentence in sentences:
        clean_sentence = sentence.strip()
        if not clean_sentence:
            continue
        if len(clean_sentence) <= max_chars:
            chunks.append(clean_sentence)
        else:
            chunks.extend(
                pack_text_fragments_for_xtts(re.split(r"(?<=[,;:])\s+", clean_sentence), max_chars)
            )
    return chunks


def wav_audio_signature(params):
    return params.nchannels, params.sampwidth, params.framerate, params.comptype


def merge_wav_files(input_paths, output_path):
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
                with wave.open(str(input_path), "rb") as part:
                    if wav_audio_signature(part.getparams()) != signature:
                        raise RuntimeError("Local TTS generated incompatible WAV chunks.")
                    output.writeframes(part.readframes(part.getnframes()))


def synthesize_text_chunks(tts, chunks, speaker_wav, language, output_path):
    if not chunks:
        raise ValueError("The selected input file contains no readable text after cleanup.")

    chunk_paths = []
    try:
        if len(chunks) == 1:
            status("Generating local TTS audio chunk 1/1...")
            tts.tts_to_file(
                text=chunks[0],
                speaker_wav=speaker_wav[0] if len(speaker_wav) == 1 else speaker_wav,
                language=language,
                file_path=str(output_path),
            )
            progress(92)
            return

        generation_start = 35
        generation_end = 92
        for index, chunk in enumerate(chunks, start=1):
            status(f"Generating local TTS audio chunk {index}/{len(chunks)}...")
            chunk_path = output_path.with_name(f"{output_path.stem}.part-{index:03d}{output_path.suffix}")
            chunk_paths.append(chunk_path)
            tts.tts_to_file(
                text=chunk,
                speaker_wav=speaker_wav[0] if len(speaker_wav) == 1 else speaker_wav,
                language=language,
                file_path=str(chunk_path),
            )
            progress(generation_start + ((generation_end - generation_start) * index / len(chunks)))
        status("Merging local TTS audio chunks...")
        merge_wav_files(chunk_paths, output_path)
        progress(94)
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
        from TTS.api import TTS
    except ImportError as exc:
        raise RuntimeError(
            "The local TTS runtime is missing coqui-tts. Install it in the ML environment with "
            "`.venv-ml\\Scripts\\python.exe -m pip install coqui-tts`."
        ) from exc
    return TTS


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
        from TTS.utils.manage import ModelManager
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
    manager = ModelManager(output_prefix=model_dir, progress_bar=False)
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
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not text_path.is_file():
        raise ValueError(f"Text file not found: {text_path}")

    chunks = split_tts_text_for_xtts(read_text(text_path))
    speaker_wav = reference_audio_paths(args.speaker_wav)
    language = normalize_tts_language(args.language)
    device = resolve_runtime_device(args.device)
    TTS = load_tts_api()
    if not xtts_model_ready(model_dir):
        raise ValueError("XTTS-v2 model is not downloaded yet. Use Download XTTS-v2 before Local TTS generation.")

    progress(2)
    status(f"Loading XTTS model on {device}...")
    tts = TTS(args.model).to(device)
    progress(35)

    status(f"Prepared {len(chunks)} local TTS chunk(s).")
    synthesize_text_chunks(tts, chunks, speaker_wav, language, output_path)
    progress(95)
    if not output_path.is_file() or output_path.stat().st_size <= 0:
        raise RuntimeError("Local TTS did not create an audio file.")
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
    parser.add_argument("--model", default=DEFAULT_XTTS_MODEL)
    parser.add_argument("--model-dir")
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
