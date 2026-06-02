from __future__ import annotations

import re
from dataclasses import dataclass

FFMPEG_PROGRESS_KEYS = frozenset(
    {
        "bitrate",
        "drop_frames",
        "dup_frames",
        "fps",
        "frame",
        "out_time",
        "out_time_ms",
        "out_time_us",
        "progress",
        "speed",
        "stream_0_0_q",
        "total_size",
    }
)

FFMPEG_OUT_TIME_KEYS = frozenset({"out_time", "out_time_ms", "out_time_us"})
_OUT_TIME_RE = re.compile(r"(\d+):(\d+):(\d+(?:\.\d+)?)")


@dataclass(frozen=True)
class FfmpegProgressEvent:
    line: str
    key: str
    value: str
    seconds: float | None = None
    percent: int | None = None


@dataclass(frozen=True)
class FfmpegJobResult:
    return_code: int
    cancelled: bool
    recent_output: tuple[str, ...]


def split_ffmpeg_progress_line(line: str) -> tuple[str, str] | None:
    if "=" not in line:
        return None
    key, value = line.strip().split("=", 1)
    key = key.strip()
    if not key:
        return None
    return key, value.strip()


def is_ffmpeg_progress_key(key: str) -> bool:
    return key.strip() in FFMPEG_PROGRESS_KEYS


def is_ffmpeg_progress_line(line: str) -> bool:
    parsed = split_ffmpeg_progress_line(line)
    return parsed is not None and is_ffmpeg_progress_key(parsed[0])


def should_keep_ffmpeg_log_line(line: str) -> bool:
    return bool(line.strip()) and not is_ffmpeg_progress_line(line)


def parse_out_time_seconds(value: str) -> float | None:
    value = value.strip()
    time_match = _OUT_TIME_RE.fullmatch(value)
    if time_match:
        return int(time_match.group(1)) * 3600 + int(time_match.group(2)) * 60 + float(time_match.group(3))
    try:
        return float(value) / 1_000_000
    except ValueError:
        return None


def ffmpeg_out_time_seconds(key: str, value: str) -> float | None:
    key = key.strip()
    if key not in FFMPEG_OUT_TIME_KEYS:
        return None
    return parse_out_time_seconds(value)


def ffmpeg_progress_percent(line: str, duration_seconds: float | None) -> int | None:
    if not duration_seconds:
        return None
    parsed = split_ffmpeg_progress_line(line)
    if parsed is None:
        return None
    seconds = ffmpeg_out_time_seconds(*parsed)
    if seconds is None:
        return None
    return min(99, max(0, round((seconds / duration_seconds) * 100)))


def parse_ffmpeg_progress_event(line: str, duration_seconds: float | None = None) -> FfmpegProgressEvent | None:
    parsed = split_ffmpeg_progress_line(line)
    if parsed is None:
        return None
    key, value = parsed
    if not is_ffmpeg_progress_key(key):
        return None
    seconds = ffmpeg_out_time_seconds(key, value)
    percent = ffmpeg_progress_percent(line, duration_seconds)
    return FfmpegProgressEvent(
        line=line.strip(),
        key=key,
        value=value,
        seconds=seconds,
        percent=percent,
    )
