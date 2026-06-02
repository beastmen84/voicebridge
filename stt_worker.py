import argparse
import difflib
import importlib
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from voicebridge.file_checks import RequiredFileSpec, required_file_issues, validate_output_path

SAMPLE_RATE = 16000
DEFAULT_MODEL = "large-v3"
SRT_MODES = {"auto_srt", "align_text"}
MISSING_ALIGNMENT_PREFIX = "MISSING_ALIGNMENT_MODEL:"
WHISPER_MODEL_REQUIRED_FILE_SPECS = (
    RequiredFileSpec("config.json", 32),
    RequiredFileSpec("model.bin", 1024 * 1024),
    RequiredFileSpec("preprocessor_config.json", 32),
    RequiredFileSpec("tokenizer.json", 32),
    RequiredFileSpec("vocabulary.json", 32),
)


class AlignmentModelMissing(RuntimeError):
    def __init__(self, language):
        self.language = language
        super().__init__(
            f"Alignment model for language '{language}' is not available in the local STT package."
        )


def status(message):
    print(f"STATUS: {message}", flush=True)


def progress(percent):
    percent = max(0, min(100, int(round(percent))))
    print(f"PROGRESS: {percent}", flush=True)


def progress_range(start, end):
    span = end - start

    def callback(percent):
        progress(start + span * (float(percent) / 100))

    return callback


def project_root():
    return Path(__file__).resolve().parent


def load_optional_module(module_name: str) -> Any:
    return importlib.import_module(module_name)


def configure_model_cache(model_root):
    model_root = Path(model_root)
    torch_home = model_root / "torch"
    nltk_data = model_root / "nltk"
    huggingface_home = model_root / "huggingface"

    torch_home.mkdir(parents=True, exist_ok=True)
    nltk_data.mkdir(parents=True, exist_ok=True)
    huggingface_home.mkdir(parents=True, exist_ok=True)

    os.environ["TORCH_HOME"] = str(torch_home)
    os.environ["HF_HOME"] = str(huggingface_home)
    os.environ["NLTK_DATA"] = str(nltk_data)


def ensure_ffmpeg_on_path():
    imageio_ffmpeg = load_optional_module("imageio_ffmpeg")

    source = Path(imageio_ffmpeg.get_ffmpeg_exe())
    bin_dir = project_root() / ".stt-bin"
    bin_dir.mkdir(exist_ok=True)
    target = bin_dir / "ffmpeg.exe"

    if not target.exists() or target.stat().st_size != source.stat().st_size:
        shutil.copy2(source, target)

    os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"


def format_srt_timestamp(seconds):
    milliseconds = max(0, round(seconds * 1000))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    seconds, milliseconds = divmod(milliseconds, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def clean_text(text):
    return " ".join(text.replace("\r\n", "\n").replace("\r", "\n").split())


def normalize_word(word):
    return re.sub(r"[^\w]+", "", word.lower(), flags=re.UNICODE)


def read_provided_text(path):
    for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return Path(path).read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Could not read provided transcript text with common encodings.")


def write_markdown(result, media_path, output_path, model_name):
    language = result.get("language", "unknown")
    segments = result.get("segments", [])
    full_text = clean_text(" ".join(segment.get("text", "") for segment in segments))

    lines = [
        "# Transcript",
        "",
        f"- Source: `{Path(media_path).name}`",
        f"- Detected language: `{language}`",
        f"- Model: `{model_name}`",
        "",
        "## Text",
        "",
        full_text,
        "",
        "## Timed Segments",
        "",
    ]

    for segment in segments:
        start = format_srt_timestamp(float(segment.get("start", 0))).replace(",", ".")
        end = format_srt_timestamp(float(segment.get("end", 0))).replace(",", ".")
        text = clean_text(segment.get("text", ""))
        if text:
            lines.append(f"- `{start} - {end}` {text}")

    Path(output_path).write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def write_srt_from_segments(segments, language, output_path):
    subtitles_module = load_optional_module("whisperx.SubtitlesProcessor")
    subtitles_processor_class = subtitles_module.SubtitlesProcessor

    processor = subtitles_processor_class(segments, language or "en")
    processor.save(str(output_path), advanced_splitting=True)


def resolve_whisper_model_source(model_name, model_dir, offline):
    model_dir = Path(model_dir)
    if offline:
        issues = required_file_issues(model_dir, WHISPER_MODEL_REQUIRED_FILE_SPECS)
        if issues:
            missing_text = ", ".join(issues)
            raise ValueError(
                f"Offline Whisper model is incomplete in {model_dir}. Required file issue(s): {missing_text}."
            )
        return str(model_dir)

    if (model_dir / "model.bin").is_file():
        return str(model_dir)
    return model_name


def allocate_text_to_segments(text, source_segments):
    provided_words = clean_text(text).split()
    if not provided_words:
        raise ValueError("Provided transcript text is empty.")

    usable_segments = [
        segment for segment in source_segments
        if segment.get("end", 0) > segment.get("start", 0)
    ]
    if not usable_segments:
        duration = source_segments[-1].get("end", 0) if source_segments else 0
        usable_segments = [{"start": 0, "end": max(duration, 1), "text": ""}]

    asr_words = []
    segment_starts = []
    for segment in usable_segments:
        segment_starts.append(len(asr_words))
        asr_words.extend(clean_text(segment.get("text", "")).split())

    if not asr_words:
        return allocate_text_by_weight(provided_words, usable_segments)

    source_items = [
        (index, normalized)
        for index, word in enumerate(asr_words)
        if (normalized := normalize_word(word))
    ]
    target_items = [
        (index, normalized)
        for index, word in enumerate(provided_words)
        if (normalized := normalize_word(word))
    ]
    source_norm = [word for _index, word in source_items]
    target_norm = [word for _index, word in target_items]

    if not source_norm or not target_norm:
        return allocate_text_by_weight(provided_words, usable_segments)

    matcher = difflib.SequenceMatcher(None, source_norm, target_norm, autojunk=False)
    match_ratio = matcher.ratio()
    if match_ratio < 0.35:
        status(
            "Warning: provided transcript differs substantially from the detected speech; "
            "subtitle timing may be less accurate."
        )

    matched_pairs = []
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            matched_pairs.append((
                source_items[block.a + offset][0],
                target_items[block.b + offset][0],
            ))

    if len(matched_pairs) < max(3, len(usable_segments) // 2):
        return allocate_text_by_weight(provided_words, usable_segments)

    source_to_target = dict(matched_pairs)
    source_boundaries = segment_starts + [len(asr_words)]
    target_boundaries = [0]
    previous_target = 0

    for source_boundary in source_boundaries[1:-1]:
        before = [pair for pair in matched_pairs if pair[0] < source_boundary]
        after = [pair for pair in matched_pairs if pair[0] >= source_boundary]

        if before and after:
            before_source, before_target = before[-1]
            after_source, after_target = after[0]
            span = max(1, after_source - before_source)
            position = (source_boundary - before_source) / span
            boundary = round(before_target + position * (after_target - before_target))
        elif source_boundary in source_to_target:
            boundary = source_to_target[source_boundary]
        else:
            boundary = round((source_boundary / max(1, len(asr_words))) * len(provided_words))

        boundary = max(previous_target, min(boundary, len(provided_words)))
        target_boundaries.append(boundary)
        previous_target = boundary

    target_boundaries.append(len(provided_words))

    allocated = []
    for index, segment in enumerate(usable_segments):
        start_index = target_boundaries[index]
        end_index = target_boundaries[index + 1]
        chunk_words = provided_words[start_index:end_index]
        if not chunk_words:
            continue
        allocated.append({
            "start": float(segment["start"]),
            "end": float(segment["end"]),
            "text": " ".join(chunk_words),
        })

    return allocated or allocate_text_by_weight(provided_words, usable_segments)


def allocate_text_by_weight(words, usable_segments):
    weights = [
        max(1, len(clean_text(segment.get("text", "")).split()))
        for segment in usable_segments
    ]
    total_weight = sum(weights)

    allocated = []
    start_index = 0
    cumulative_weight = 0
    for index, (segment, weight) in enumerate(zip(usable_segments, weights, strict=False)):
        cumulative_weight += weight
        if index == len(usable_segments) - 1:
            end_index = len(words)
        else:
            end_index = round((cumulative_weight / total_weight) * len(words))
            end_index = max(start_index + 1, min(end_index, len(words)))

        chunk_words = words[start_index:end_index]
        start_index = end_index
        if not chunk_words:
            continue

        allocated.append({
            "start": float(segment["start"]),
            "end": float(segment["end"]),
            "text": " ".join(chunk_words),
        })

    return allocated


def normalize_stt_language(language):
    if not language or language == "auto":
        return "auto"
    return language.lower().replace("_", "-").split("-", 1)[0]


def resolve_runtime_options(device, compute_type):
    torch = load_optional_module("torch")

    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    elif device == "cuda" and not torch.cuda.is_available():
        raise ValueError(
            "CUDA was selected, but this STT runtime cannot access an NVIDIA CUDA GPU. "
            "Use CPU only, or bundle a CUDA-enabled PyTorch runtime."
        )
    if compute_type == "auto":
        compute_type = "float16" if device == "cuda" else "float32"
    return device, compute_type


def transcribe_only(media_path, model_name, model_dir, device, compute_type, batch_size, language, offline):
    whisperx = load_optional_module("whisperx")

    device, compute_type = resolve_runtime_options(device, compute_type)
    language = normalize_stt_language(language)

    model_source = resolve_whisper_model_source(model_name, model_dir, offline)
    model_label = model_name if model_source == model_name else f"{model_name} from local bundle"
    progress(2)
    status(f"Loading WhisperX model {model_label} on {device} ({compute_type})...")
    model = whisperx.load_model(
        model_source,
        device=device,
        compute_type=compute_type,
        language=None if language == "auto" else language,
        download_root=str(model_dir),
        local_files_only=offline,
        vad_method="silero",
        threads=max(1, os.cpu_count() or 4),
    )
    progress(8)

    status("Loading audio/video stream...")
    audio = whisperx.load_audio(str(media_path))
    progress(12)

    status("Transcribing speech...")
    result = model.transcribe(
        audio,
        batch_size=batch_size,
        chunk_size=30,
        print_progress=False,
        progress_callback=progress_range(12, 58),
        verbose=False,
    )
    progress(60)

    del model

    detected_language = language if language != "auto" else result.get("language", "en")
    result["language"] = normalize_stt_language(detected_language)
    return result, audio, device


def load_alignment_model(language, model_dir, device, offline):
    whisperx = load_optional_module("whisperx")

    language = normalize_stt_language(language)
    status(f"Detected language: {language}. Loading alignment model...")
    try:
        return whisperx.load_align_model(
            language,
            device,
            model_dir=str(model_dir),
            model_cache_only=offline,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        if offline:
            print(f"{MISSING_ALIGNMENT_PREFIX} {language}", flush=True)
            raise AlignmentModelMissing(language) from exc
        raise


def align_segments(result, audio, model_dir, device, offline):
    whisperx = load_optional_module("whisperx")

    detected_language = normalize_stt_language(result.get("language", "en"))
    align_model, align_metadata = load_alignment_model(detected_language, model_dir, device, offline)
    progress(68)

    status("Aligning words to audio...")
    aligned = whisperx.align(
        result["segments"],
        align_model,
        align_metadata,
        audio,
        device,
        return_char_alignments=False,
        print_progress=False,
        progress_callback=progress_range(68, 90),
    )
    progress(90)
    aligned["language"] = detected_language
    return aligned


def download_alignment_model(language, model_dir, device):
    language = normalize_stt_language(language)
    if language == "auto":
        raise ValueError("A concrete language code is required to download an alignment model.")

    device, _compute_type = resolve_runtime_options(device, "auto")
    progress(2)
    status(f"Downloading alignment model for language: {language}...")
    load_alignment_model(language, model_dir, device, offline=False)
    progress(100)
    status(f"Alignment model ready for language: {language}.")


def download_whisper_model(model_name, model_dir):
    nltk = load_optional_module("nltk")
    torch = load_optional_module("torch")
    faster_whisper_utils = load_optional_module("faster_whisper.utils")
    download_model = faster_whisper_utils.download_model

    progress(2)
    status(f"Downloading Faster Whisper {model_name}...")
    download_model(model_name, output_dir=str(model_dir))
    progress(50)

    status("Downloading Silero VAD...")
    torch.hub.load(
        repo_or_dir="snakers4/silero-vad",
        model="silero_vad",
        force_reload=False,
        onnx=False,
        trust_repo=True,
    )
    progress(75)

    status("Downloading NLTK punctuation data...")
    nltk.download("punkt_tab", download_dir=str(model_dir.parent / "nltk"), quiet=False)
    progress(100)
    status(f"Whisper model ready: {model_dir}.")


def align_provided_text(
    media_path,
    text_path,
    model_name,
    model_dir,
    device,
    compute_type,
    batch_size,
    language,
    offline,
):
    provided_text = read_provided_text(text_path)
    detected_result, audio, device = transcribe_only(
        media_path,
        model_name,
        model_dir,
        device,
        compute_type,
        batch_size,
        language,
        offline,
    )
    language = normalize_stt_language(detected_result.get("language", "en"))
    align_model, align_metadata = load_alignment_model(language, model_dir, device, offline)
    progress(68)
    provided_segments = allocate_text_to_segments(provided_text, detected_result["segments"])

    status("Force-aligning provided transcript text...")
    whisperx = load_optional_module("whisperx")

    aligned = whisperx.align(
        provided_segments,
        align_model,
        align_metadata,
        audio,
        device,
        return_char_alignments=False,
        print_progress=False,
        progress_callback=progress_range(68, 96),
    )
    progress(96)
    aligned["language"] = language
    return aligned


def run(args):
    ensure_ffmpeg_on_path()
    model_dir = Path(args.model_dir or (project_root() / "models" / "whisperx")).resolve()
    configure_model_cache(model_dir.parent)
    if args.offline:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
    model_dir.mkdir(parents=True, exist_ok=True)

    if args.mode == "download_align":
        download_alignment_model(args.language, model_dir, args.device)
        return
    if args.mode == "download_whisper":
        download_whisper_model(args.model, model_dir)
        return

    if not args.media:
        raise ValueError("Media file path is required.")
    if not args.output:
        raise ValueError("Output file path is required.")

    media_path = Path(args.media).resolve()
    if not media_path.is_file():
        raise ValueError(f"Media file not found: {media_path}")
    output_path = validate_output_path(
        Path(args.output).resolve(),
        source_path=media_path,
        expected_suffixes={".md", ".srt"},
        create_parent=True,
    )

    if args.mode == "align_text":
        if not args.text or not Path(args.text).is_file():
            raise ValueError("Provided transcript text file is required for align_text mode.")
        result = align_provided_text(
            media_path,
            args.text,
            args.model,
            model_dir,
            args.device,
            args.compute_type,
            args.batch_size,
            args.language,
            args.offline,
        )
    else:
        result, audio, device = transcribe_only(
            media_path,
            args.model,
            model_dir,
            args.device,
            args.compute_type,
            args.batch_size,
            args.language,
            args.offline,
        )
        if args.mode == "auto_srt":
            result = align_segments(result, audio, model_dir, device, args.offline)

    status("Writing output file...")
    progress(98)
    if args.mode == "transcript":
        write_markdown(result, media_path, output_path, args.model)
    elif args.mode in SRT_MODES:
        write_srt_from_segments(result["segments"], result.get("language", "en"), output_path)
    else:
        raise ValueError(f"Unsupported mode: {args.mode}")

    status(f"Done: {output_path}")
    progress(100)


def parse_args():
    parser = argparse.ArgumentParser(description="Offline speech-to-text worker.")
    parser.add_argument("--media")
    parser.add_argument("--output")
    parser.add_argument(
        "--mode",
        choices=["transcript", "auto_srt", "align_text", "download_align", "download_whisper"],
        required=True,
    )
    parser.add_argument("--text")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--model-dir")
    parser.add_argument("--language", default="auto")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda"])
    parser.add_argument("--compute-type", default="auto")
    parser.add_argument("--batch-size", type=int, default=4)
    return parser.parse_args()


def main():
    try:
        run(parse_args())
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        raise


if __name__ == "__main__":
    main()
