import os
from pathlib import Path

from voicebridge.file_checks import validate_output_path
from voicebridge.media_tools import STT_VIDEO_SUFFIXES, find_ffmpeg_exe, probe_video_info


def qt_file_filter(filetypes):
    parts = []
    for label, patterns in filetypes:
        parts.append(f"{label} ({patterns})")
    return ";;".join(parts)


def open_path(path):
    if path and Path(path).exists():
        os.startfile(str(path))


def normalize_video_subtitle_output_path(output_path, mode, default_suffix=""):
    path = Path(output_path)
    if path.suffix:
        return str(path)
    fallback = default_suffix or (".mp4" if mode == "burn" else ".mkv")
    return str(path.with_suffix(fallback))


def validate_video_subtitle_inputs(mode, media_path, srt_path, output_path):
    media = Path(media_path) if media_path else None
    srt = Path(srt_path) if srt_path else None
    output = Path(output_path) if output_path else None
    if mode not in {"embed", "burn"}:
        raise ValueError("Choose a valid video subtitle mode.")
    if not media or not media.is_file():
        raise ValueError("Select an existing video file.")
    if media.suffix.lower() not in STT_VIDEO_SUFFIXES:
        raise ValueError("The selected media file must be a video.")
    ffmpeg = find_ffmpeg_exe()
    if ffmpeg:
        info = probe_video_info(ffmpeg, media)
        if not info.get("width") or not info.get("height") or not info.get("duration_seconds"):
            raise ValueError("The selected video file could not be inspected or has no readable video stream.")
    if not srt or not srt.is_file() or srt.suffix.lower() != ".srt":
        raise ValueError("Select an existing .srt subtitle file.")
    if not output:
        raise ValueError("Choose where to save the subtitled video.")
    if mode == "embed" and output.suffix.lower() not in {".mp4", ".mkv"}:
        raise ValueError("Embedded subtitles can be saved as .mp4 or .mkv.")
    if mode == "burn" and output.suffix.lower() != ".mp4":
        raise ValueError("Burned subtitles are saved as .mp4.")
    validate_output_path(
        output,
        source_path=media,
        expected_suffixes={".mp4", ".mkv"} if mode == "embed" else {".mp4"},
    )
