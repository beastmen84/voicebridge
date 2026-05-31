import re
import shutil
import subprocess
import sys
from array import array
from contextlib import suppress
from pathlib import Path
from typing import TypedDict

from voicebridge.app_paths import external_base_dir

STT_VIDEO_SUFFIXES = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"}
SUPPORTED_AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
MP4_SUBTITLE_SUFFIXES = {".mp4", ".mov", ".m4v"}
VIDEO_CLEANUP_MAX_REPAIR_FRAMES = 200
VIDEO_CLEANUP_BLACK_AMOUNT = 98
VIDEO_CLEANUP_BLACK_THRESHOLD = 32
VIDEO_CLEANUP_METHOD_FREEZE = "freeze"
VIDEO_CLEANUP_METHOD_REMOVE = "remove"
AUDIO_CLEANUP_REMOVE = "remove"
AUDIO_CLEANUP_SILENCE = "silence"
AUDIO_CLEANUP_FADE = "fade"
AUDIO_CLEANUP_DEFAULT_FADE_SECONDS = 0.08
AUDIO_WAVEFORM_DEFAULT_BINS = 24000
AUDIO_WAVEFORM_SAMPLE_RATE = 2000
BURN_QUALITY_AUTO = "auto"
BURN_QUALITY_STANDARD = "crf20"
BURN_QUALITY_HIGH = "crf18"
BURN_QUALITY_MAXIMUM = "crf16"
BURN_QUALITY_ORIGINAL_BITRATE = "original_bitrate"
BURN_QUALITY_CRF_VALUES = {
    BURN_QUALITY_STANDARD: "20",
    BURN_QUALITY_HIGH: "18",
    BURN_QUALITY_MAXIMUM: "16",
}


class VideoInfo(TypedDict):
    width: int | None
    height: int | None
    bitrate_kbps: int | None
    duration_seconds: float | None
    fps: float | None
    has_audio: bool


class AudioInfo(TypedDict):
    duration_seconds: float | None
    has_audio: bool


class BlackFrame(TypedDict):
    frame: int
    pblack: int
    pts: int
    time: float


class SubtitleStyle(TypedDict):
    font_size: int
    outline: int
    margin_v: int
    alignment: int


def ffmpeg_candidates():
    base_dir = external_base_dir()
    candidates = [
        base_dir / ".stt-bin" / "ffmpeg.exe",
    ]

    search_dirs = [
        base_dir / "python-ml" / "Lib" / "site-packages" / "imageio_ffmpeg" / "binaries",
        base_dir / ".venv-ml" / "Lib" / "site-packages" / "imageio_ffmpeg" / "binaries",
    ]
    for search_dir in search_dirs:
        if search_dir.is_dir():
            candidates.extend(sorted(search_dir.glob("ffmpeg*.exe")))

    path_ffmpeg = shutil.which("ffmpeg")
    if path_ffmpeg:
        candidates.append(Path(path_ffmpeg))

    return candidates


def find_ffmpeg_exe():
    for candidate in ffmpeg_candidates():
        if candidate.is_file():
            return candidate
    return None


def escape_ffmpeg_concat_path(path):
    return str(path).replace("\\", "/").replace("'", r"'\''")


def escape_ffmpeg_filter_path(path):
    value = str(Path(path).resolve()).replace("\\", "/")
    for old, new in (
        ("\\", "\\\\"),
        ("'", r"\'"),
        (":", r"\:"),
        (",", r"\,"),
        ("[", r"\["),
        ("]", r"\]"),
    ):
        value = value.replace(old, new)
    return value


def subtitle_force_style(subtitle_style: SubtitleStyle | None = None):
    if not subtitle_style:
        return ""
    return ",".join(
        (
            f"Fontsize={int(subtitle_style.get('font_size', 28))}",
            f"Outline={int(subtitle_style.get('outline', 2))}",
            f"MarginV={int(subtitle_style.get('margin_v', 36))}",
            f"Alignment={int(subtitle_style.get('alignment', 2))}",
            "BorderStyle=1",
            "Shadow=0",
        )
    )


def subtitle_filter_for_srt(srt_path, subtitle_style: SubtitleStyle | None = None):
    subtitle_filter = f"subtitles=filename='{escape_ffmpeg_filter_path(srt_path)}'"
    force_style = subtitle_force_style(subtitle_style)
    if force_style:
        subtitle_filter = f"{subtitle_filter}:force_style='{force_style}'"
    return subtitle_filter


def parse_srt_timestamp(value):
    match = re.match(r"(\d+):(\d+):(\d+),(\d+)", value.strip())
    if not match:
        return None
    return (
        int(match.group(1)) * 3600
        + int(match.group(2)) * 60
        + int(match.group(3))
        + int(match.group(4)) / 1000
    )


def first_srt_timestamp_seconds(srt_path):
    try:
        text = Path(srt_path).read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return 1.0
    match = re.search(r"(\d+:\d+:\d+,\d+)\s*-->", text)
    if not match:
        return 1.0
    return max(0.0, (parse_srt_timestamp(match.group(1)) or 1.0) + 0.25)


def concatenate_mp3_files(parts, output_path):
    ffmpeg = find_ffmpeg_exe()
    if not ffmpeg:
        raise RuntimeError(
            "Could not find ffmpeg to merge multi-voice MP3 parts. "
            "Use the full VoiceBridge bundle with the offline STT package included."
        )

    output_path = Path(output_path)
    list_path = output_path.with_suffix(".voicebridge-concat.txt")
    list_text = "\n".join(
        f"file '{escape_ffmpeg_concat_path(Path(part).resolve())}'"
        for part in parts
    )

    try:
        list_path.write_text(list_text + "\n", encoding="utf-8")
        command = [
            str(ffmpeg),
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-c",
            "copy",
            str(output_path),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)

        if result.returncode != 0:
            command = [
                str(ffmpeg),
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_path),
                "-c:a",
                "libmp3lame",
                "-q:a",
                "4",
                str(output_path),
            ]
            result = subprocess.run(command, capture_output=True, text=True, check=False)

        if result.returncode != 0:
            error_text = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(error_text or f"ffmpeg exited with code {result.returncode}.")
    finally:
        with suppress(OSError):
            list_path.unlink(missing_ok=True)


def convert_audio_to_mp3(input_path, output_path):
    ffmpeg = find_ffmpeg_exe()
    if not ffmpeg:
        raise RuntimeError(
            "Could not find ffmpeg to convert local TTS audio to MP3. "
            "Use the full VoiceBridge bundle with the offline ML package included."
        )

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(ffmpeg),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-vn",
        "-codec:a",
        "libmp3lame",
        "-q:a",
        "4",
        str(output_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, errors="replace", check=False)
    if result.returncode != 0:
        error_text = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(error_text or f"ffmpeg exited with code {result.returncode}.")


def can_create_video_subtitles(srt_path, media_path):
    srt_path = Path(srt_path) if srt_path else None
    media_path = Path(media_path) if media_path else None
    return bool(
        srt_path
        and media_path
        and srt_path.is_file()
        and srt_path.suffix.lower() == ".srt"
        and media_path.is_file()
        and media_path.suffix.lower() in STT_VIDEO_SUFFIXES
    )


def suggest_video_subtitle_output_path(media_path, mode):
    media_path = Path(media_path)
    suffix = media_path.suffix.lower()
    if mode == "embed":
        output_suffix = ".mp4" if suffix in MP4_SUBTITLE_SUFFIXES else ".mkv"
        name_suffix = "_subtitled"
    else:
        output_suffix = ".mp4"
        name_suffix = "_burned"
    return str(media_path.with_name(f"{media_path.stem}{name_suffix}").with_suffix(output_suffix))


def suggest_video_cleanup_output_path(media_path):
    media_path = Path(media_path)
    suffix = media_path.suffix.lower() if media_path.suffix else ".mp4"
    if suffix not in {".mp4", ".mkv", ".mov", ".m4v"}:
        suffix = ".mp4"
    return str(media_path.with_name(f"{media_path.stem}_cleaned").with_suffix(suffix))


def suggest_audio_cleanup_output_path(audio_path):
    audio_path = Path(audio_path)
    suffix = audio_path.suffix.lower() if audio_path.suffix.lower() in SUPPORTED_AUDIO_SUFFIXES else ".mp3"
    return str(audio_path.with_name(f"{audio_path.stem}_cleaned").with_suffix(suffix))


def audio_waveform_command(ffmpeg, media_path, sample_rate=AUDIO_WAVEFORM_SAMPLE_RATE):
    return [
        str(ffmpeg),
        "-hide_banner",
        "-nostdin",
        "-nostats",
        "-loglevel",
        "error",
        "-i",
        str(media_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(int(sample_rate)),
        "-f",
        "s16le",
        "pipe:1",
    ]


def pcm_s16le_peak_bins(pcm_data, bin_count=AUDIO_WAVEFORM_DEFAULT_BINS) -> list[float]:
    if bin_count <= 0:
        raise ValueError("Waveform bin count must be greater than zero.")
    if not pcm_data:
        return []

    even_length = len(pcm_data) - (len(pcm_data) % 2)
    samples = array("h")
    samples.frombytes(pcm_data[:even_length])
    if sys.byteorder != "little":
        samples.byteswap()
    sample_count = len(samples)
    if sample_count == 0:
        return []

    target_bins = min(int(bin_count), sample_count)
    peaks = []
    for bin_index in range(target_bins):
        start = int((bin_index * sample_count) / target_bins)
        end = int(((bin_index + 1) * sample_count) / target_bins)
        if end <= start:
            end = min(sample_count, start + 1)
        peak = 0
        for sample_index in range(start, end):
            peak = max(peak, abs(samples[sample_index]))
        peaks.append(min(1.0, peak / 32768.0))
    return peaks


def audio_waveform_peaks(
    ffmpeg,
    media_path,
    bin_count=AUDIO_WAVEFORM_DEFAULT_BINS,
    sample_rate=AUDIO_WAVEFORM_SAMPLE_RATE,
) -> list[float]:
    result = subprocess.run(
        audio_waveform_command(ffmpeg, media_path, sample_rate=sample_rate),
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        error_text = (result.stderr or b"").decode("utf-8", errors="replace").strip()
        raise RuntimeError(error_text or f"ffmpeg exited with code {result.returncode}.")
    return pcm_s16le_peak_bins(result.stdout, bin_count=bin_count)


def _ffmpeg_input_info(ffmpeg, media_path):
    command = [str(ffmpeg), "-hide_banner", "-i", str(media_path)]
    result = subprocess.run(command, capture_output=True, text=True, errors="replace", check=False)
    return f"{result.stdout or ''}\n{result.stderr or ''}"


def parse_ffmpeg_duration(output):
    duration_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", output)
    if not duration_match:
        return None
    hours = int(duration_match.group(1))
    minutes = int(duration_match.group(2))
    seconds = float(duration_match.group(3))
    return hours * 3600 + minutes * 60 + seconds


def probe_audio_info(ffmpeg, media_path) -> AudioInfo:
    output = _ffmpeg_input_info(ffmpeg, media_path)
    return {
        "duration_seconds": parse_ffmpeg_duration(output),
        "has_audio": any("Audio:" in line for line in output.splitlines()),
    }


def probe_video_info(ffmpeg, media_path) -> VideoInfo:
    output = _ffmpeg_input_info(ffmpeg, media_path)
    info: VideoInfo = {
        "width": None,
        "height": None,
        "bitrate_kbps": None,
        "duration_seconds": None,
        "fps": None,
        "has_audio": False,
    }

    info["duration_seconds"] = parse_ffmpeg_duration(output)

    for line in output.splitlines():
        if "Video:" not in line:
            if "Audio:" in line:
                info["has_audio"] = True
            continue
        size_match = re.search(r"(?<!\d)(\d{2,5})x(\d{2,5})(?!\d)", line)
        if size_match:
            info["width"] = int(size_match.group(1))
            info["height"] = int(size_match.group(2))

        bitrate_match = re.search(r"(?<![A-Za-z])(\d+(?:\.\d+)?)\s*kb/s", line, re.IGNORECASE)
        if bitrate_match:
            info["bitrate_kbps"] = max(1, round(float(bitrate_match.group(1))))

        fps_match = re.search(r"(?<![\d.])(\d+(?:\.\d+)?)\s*fps", line, re.IGNORECASE)
        if not fps_match:
            fps_match = re.search(r"(?<![\d.])(\d+(?:\.\d+)?)\s*tbr", line, re.IGNORECASE)
        if fps_match:
            info["fps"] = max(1.0, float(fps_match.group(1)))

    if not info["has_audio"]:
        info["has_audio"] = any("Audio:" in line for line in output.splitlines())

    if not info["bitrate_kbps"]:
        match = re.search(r"bitrate:\s*(\d+(?:\.\d+)?)\s*kb/s", output, re.IGNORECASE)
        if match:
            info["bitrate_kbps"] = max(1, round(float(match.group(1))))

    return info


def audio_cleanup_codec_args(output_path):
    suffix = Path(output_path).suffix.lower()
    if suffix == ".wav":
        return ["-c:a", "pcm_s16le"]
    if suffix == ".flac":
        return ["-c:a", "flac"]
    if suffix in {".m4a", ".aac"}:
        return ["-c:a", "aac", "-b:a", "192k"]
    if suffix == ".ogg":
        return ["-c:a", "libvorbis", "-q:a", "5"]
    return ["-c:a", "libmp3lame", "-q:a", "4"]


def audio_cleanup_filter_complex(action, start_seconds, end_seconds, duration_seconds=None):
    start = max(0.0, float(start_seconds))
    end = max(start, float(end_seconds))
    duration = float(duration_seconds) if duration_seconds else None
    if end <= start:
        raise ValueError("Cleanup end time must be greater than start time.")

    if action == AUDIO_CLEANUP_REMOVE:
        if duration is not None and start <= 0 and end >= duration:
            raise ValueError("Cannot remove the entire audio file.")
        if start <= 0:
            return f"[0:a]atrim=start={end:.6f},asetpts=PTS-STARTPTS[aclean]"
        if duration is not None and end >= duration:
            return f"[0:a]atrim=end={start:.6f},asetpts=PTS-STARTPTS[aclean]"
        return (
            f"[0:a]atrim=end={start:.6f},asetpts=PTS-STARTPTS[a0];"
            f"[0:a]atrim=start={end:.6f},asetpts=PTS-STARTPTS[a1];"
            "[a0][a1]concat=n=2:v=0:a=1[aclean]"
        )

    if action == AUDIO_CLEANUP_SILENCE:
        return f"[0:a]volume=enable='between(t\\,{start:.6f}\\,{end:.6f})':volume=0[aclean]"

    if action == AUDIO_CLEANUP_FADE:
        range_seconds = end - start
        fade_seconds = min(AUDIO_CLEANUP_DEFAULT_FADE_SECONDS, range_seconds / 2)
        if fade_seconds <= 0:
            return f"[0:a]volume=enable='between(t\\,{start:.6f}\\,{end:.6f})':volume=0[aclean]"
        middle_start = start + fade_seconds
        middle_end = end - fade_seconds
        filters = [f"afade=t=out:st={start:.6f}:d={fade_seconds:.6f}"]
        if middle_end > middle_start:
            filters.append(
                f"volume=enable='between(t\\,{middle_start:.6f}\\,{middle_end:.6f})':volume=0"
            )
        filters.append(f"afade=t=in:st={middle_end:.6f}:d={fade_seconds:.6f}")
        return "[0:a]" + ",".join(filters) + "[aclean]"

    raise ValueError(f"Unsupported audio cleanup action: {action}")


def audio_cleanup_command(ffmpeg, input_path, output_path, action, start_seconds, end_seconds, duration_seconds=None):
    filter_complex = audio_cleanup_filter_complex(action, start_seconds, end_seconds, duration_seconds)
    return [
        str(ffmpeg),
        "-y",
        "-hide_banner",
        "-nostats",
        "-loglevel",
        "error",
        "-progress",
        "pipe:1",
        "-i",
        str(input_path),
        "-filter_complex",
        filter_complex,
        "-map",
        "[aclean]",
        "-vn",
        *audio_cleanup_codec_args(output_path),
        str(output_path),
    ]


BLACKFRAME_RE = re.compile(
    r"frame:(?P<frame>\d+)\s+pblack:(?P<pblack>\d+)\s+pts:(?P<pts>-?\d+)\s+t:(?P<time>\d+(?:\.\d+)?)"
)


def parse_blackframe_line(line) -> BlackFrame | None:
    match = BLACKFRAME_RE.search(line)
    if not match:
        return None
    return {
        "frame": int(match.group("frame")),
        "pblack": int(match.group("pblack")),
        "pts": int(match.group("pts")),
        "time": float(match.group("time")),
    }


def black_frame_detect_command(
    ffmpeg,
    media_path,
    black_amount=VIDEO_CLEANUP_BLACK_AMOUNT,
    black_threshold=VIDEO_CLEANUP_BLACK_THRESHOLD,
):
    return [
        str(ffmpeg),
        "-y",
        "-hide_banner",
        "-nostats",
        "-loglevel",
        "info",
        "-progress",
        "pipe:1",
        "-i",
        media_path,
        "-vf",
        f"blackframe=amount={int(black_amount)}:threshold={int(black_threshold)}",
        "-an",
        "-f",
        "null",
        "-",
    ]


def video_frame_preview_command(ffmpeg, media_path, frame_number, output_path, width=360):
    frame_number = max(0, int(frame_number))
    return [
        str(ffmpeg),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        media_path,
        "-vf",
        f"select=eq(n\\,{frame_number}),scale={int(width)}:-1",
        "-frames:v",
        "1",
        output_path,
    ]


def video_subtitle_preview_command(
    ffmpeg,
    media_path,
    srt_path,
    output_path,
    subtitle_style: SubtitleStyle | None = None,
    timestamp_seconds=1.0,
):
    return [
        str(ffmpeg),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        media_path,
        "-ss",
        f"{max(0.0, float(timestamp_seconds)):.3f}",
        "-vf",
        subtitle_filter_for_srt(srt_path, subtitle_style),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        output_path,
    ]


def black_frame_runs(black_frames: list[BlackFrame]) -> list[list[BlackFrame]]:
    frames = sorted({frame["frame"]: frame for frame in black_frames}.values(), key=lambda item: item["frame"])
    if not frames:
        return []

    runs = []
    current = [frames[0]]
    for frame in frames[1:]:
        if frame["frame"] == current[-1]["frame"] + 1:
            current.append(frame)
        else:
            runs.append(current)
            current = [frame]
    runs.append(current)
    return runs


def isolated_black_frame_numbers(
    black_frames: list[BlackFrame],
    max_run_length=1,
) -> tuple[list[int], list[list[BlackFrame]]]:
    isolated = []
    longer_runs = []
    for run in black_frame_runs(black_frames):
        if len(run) <= max_run_length and run[0]["frame"] > 0:
            isolated.extend(frame["frame"] for frame in run)
        else:
            longer_runs.append(run)
    return isolated, longer_runs


def freezeframes_filter_complex(frame_numbers):
    frame_numbers = sorted(set(int(frame) for frame in frame_numbers if int(frame) > 0))
    if not frame_numbers:
        raise ValueError("No repairable frame numbers were provided.")
    if len(frame_numbers) > VIDEO_CLEANUP_MAX_REPAIR_FRAMES:
        raise ValueError(
            f"Too many isolated frames to repair at once ({len(frame_numbers)}). "
            f"Limit: {VIDEO_CLEANUP_MAX_REPAIR_FRAMES}."
        )

    labels = ["base"] + [f"ref{index}" for index in range(len(frame_numbers))]
    graph = f"[0:v]split={len(labels)}" + "".join(f"[{label}]" for label in labels) + ";"
    current = "base"
    for index, frame in enumerate(frame_numbers):
        output = "vclean" if index == len(frame_numbers) - 1 else f"vclean{index}"
        graph += (
            f"[{current}][ref{index}]"
            f"freezeframes=first={frame}:last={frame}:replace={frame - 1}"
            f"[{output}]"
        )
        if index != len(frame_numbers) - 1:
            graph += ";"
        current = output
    return graph


def removeframes_filter_complex(frame_numbers, frame_times_seconds=None, fps=None, has_audio=True):
    frame_numbers = sorted(set(int(frame) for frame in frame_numbers if int(frame) > 0))
    if not frame_numbers:
        raise ValueError("No removable frame numbers were provided.")
    if len(frame_numbers) > VIDEO_CLEANUP_MAX_REPAIR_FRAMES:
        raise ValueError(
            f"Too many isolated frames to remove at once ({len(frame_numbers)}). "
            f"Limit: {VIDEO_CLEANUP_MAX_REPAIR_FRAMES}."
        )

    frame_expression = "+".join(f"eq(n\\,{frame})" for frame in frame_numbers)
    graph = f"[0:v]select=not({frame_expression}),setpts=N/FRAME_RATE/TB[vclean]"

    if has_audio:
        safe_fps = float(fps or 25.0)
        frame_duration = 1.0 / max(1.0, safe_fps)
        times = list(frame_times_seconds or [])
        if len(times) != len(frame_numbers):
            times = [frame / safe_fps for frame in frame_numbers]
        time_expression = "+".join(
            f"between(t\\,{max(0.0, float(start)):.6f}\\,{max(0.0, float(start) + frame_duration):.6f})"
            for start in times
        )
        graph = f"{graph};[0:a]aselect=not({time_expression}),asetpts=N/SR/TB[aclean]"

    return graph


def video_cleanup_quality_args(
    cleanup_quality=BURN_QUALITY_AUTO,
    source_video_bitrate_kbps=None,
    source_video_width=None,
    source_video_height=None,
):
    return burn_video_quality_args(
        cleanup_quality,
        source_video_bitrate_kbps,
        source_video_width,
        source_video_height,
    )


def video_cleanup_repair_commands(
    ffmpeg,
    media_path,
    output_path,
    frame_numbers,
    repair_method=VIDEO_CLEANUP_METHOD_FREEZE,
    cleanup_quality=BURN_QUALITY_AUTO,
    source_video_bitrate_kbps=None,
    source_video_width=None,
    source_video_height=None,
    source_video_fps=None,
    source_has_audio=True,
    frame_times_seconds=None,
):
    if repair_method == VIDEO_CLEANUP_METHOD_REMOVE:
        filter_complex = removeframes_filter_complex(
            frame_numbers,
            frame_times_seconds=frame_times_seconds,
            fps=source_video_fps,
            has_audio=source_has_audio,
        )
        audio_map = ["-map", "[aclean]"] if source_has_audio else ["-an"]
        audio_variants = [
            ["-c:a", "aac", "-b:a", "192k"] if source_has_audio else [],
        ]
        timing_variants = [
            ["-fps_mode", "vfr"],
            [],
        ]
    else:
        filter_complex = freezeframes_filter_complex(frame_numbers)
        audio_map = ["-map", "0:a?"]
        audio_variants = [
            ["-c:a", "copy"],
            ["-c:a", "aac", "-b:a", "192k"],
        ]
        timing_variants = [
            ["-fps_mode", "passthrough"],
            ["-vsync", "0"],
            [],
        ]
    output_suffix = Path(output_path).suffix.lower()
    movflags = ["-movflags", "+faststart"] if output_suffix in MP4_SUBTITLE_SUFFIXES else []
    base = [
        str(ffmpeg),
        "-y",
        "-hide_banner",
        "-nostats",
        "-loglevel",
        "error",
        "-progress",
        "pipe:1",
        "-i",
        media_path,
        "-filter_complex",
        filter_complex,
        "-map",
        "[vclean]",
        *audio_map,
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        *video_cleanup_quality_args(
            cleanup_quality,
            source_video_bitrate_kbps,
            source_video_width,
            source_video_height,
        ),
        "-sn",
        *movflags,
    ]
    return [
        [*base, *timing_args, *audio_args, output_path]
        for timing_args in timing_variants
        for audio_args in audio_variants
    ]


def auto_burn_quality(source_video_bitrate_kbps=None, source_video_width=None, source_video_height=None):
    width = source_video_width or 0
    height = source_video_height or 0
    long_edge = max(width, height)
    short_edge = min(width, height) if width and height else 0

    if short_edge >= 2160 or long_edge >= 3000:
        return BURN_QUALITY_HIGH
    if short_edge >= 1080 and source_video_bitrate_kbps and source_video_bitrate_kbps >= 12000:
        return BURN_QUALITY_HIGH
    return BURN_QUALITY_STANDARD


def burn_video_quality_args(
    burn_quality=BURN_QUALITY_AUTO,
    source_video_bitrate_kbps=None,
    source_video_width=None,
    source_video_height=None,
):
    if burn_quality == BURN_QUALITY_AUTO:
        burn_quality = auto_burn_quality(
            source_video_bitrate_kbps,
            source_video_width,
            source_video_height,
        )

    if burn_quality == BURN_QUALITY_ORIGINAL_BITRATE:
        if not source_video_bitrate_kbps:
            raise ValueError("Could not detect the original video bitrate.")
        return ["-b:v", f"{source_video_bitrate_kbps}k"]

    crf = BURN_QUALITY_CRF_VALUES.get(burn_quality, BURN_QUALITY_CRF_VALUES[BURN_QUALITY_STANDARD])
    return ["-crf", crf]


def video_subtitle_commands(
    mode,
    ffmpeg,
    media_path,
    srt_path,
    output_path,
    burn_quality=BURN_QUALITY_AUTO,
    source_video_bitrate_kbps=None,
    source_video_width=None,
    source_video_height=None,
    subtitle_style: SubtitleStyle | None = None,
):
    common = [str(ffmpeg), "-y", "-hide_banner", "-nostats", "-loglevel", "error", "-progress", "pipe:1"]
    if mode == "embed":
        output_suffix = Path(output_path).suffix.lower()
        subtitle_codec = "mov_text" if output_suffix == ".mp4" else "srt"
        return [[
            *common,
            "-i", media_path,
            "-i", srt_path,
            "-map", "0",
            "-map", "1",
            "-c", "copy",
            "-c:s", subtitle_codec,
            "-metadata:s:s:0", "title=VoiceBridge subtitles",
            output_path,
        ]]

    subtitle_filter = subtitle_filter_for_srt(srt_path, subtitle_style)
    base = [
        *common,
        "-i", media_path,
        "-map", "0:v:0",
        "-map", "0:a?",
        "-vf", subtitle_filter,
        "-c:v", "libx264",
        "-preset", "medium",
        *burn_video_quality_args(
            burn_quality,
            source_video_bitrate_kbps,
            source_video_width,
            source_video_height,
        ),
        "-sn",
        "-movflags", "+faststart",
    ]
    timing_variants = [
        ["-fps_mode", "passthrough"],
        ["-vsync", "0"],
        [],
    ]
    audio_variants = [
        ["-c:a", "copy"],
        ["-c:a", "aac", "-b:a", "192k"],
    ]
    return [
        [*base, *timing_args, *audio_args, output_path]
        for timing_args in timing_variants
        for audio_args in audio_variants
    ]
