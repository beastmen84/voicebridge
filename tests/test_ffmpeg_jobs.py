import pytest

from voicebridge.ffmpeg_jobs import (
    FfmpegJobResult,
    FfmpegProgressEvent,
    ffmpeg_out_time_seconds,
    ffmpeg_progress_percent,
    is_ffmpeg_progress_line,
    parse_ffmpeg_progress_event,
    parse_out_time_seconds,
    should_keep_ffmpeg_log_line,
    split_ffmpeg_progress_line,
)


def test_parse_out_time_seconds_from_ffmpeg_timestamp() -> None:
    assert parse_out_time_seconds("01:02:03.500000") == pytest.approx(3723.5)


def test_ffmpeg_out_time_ms_parses_microsecond_counter() -> None:
    assert ffmpeg_out_time_seconds("out_time_ms", "5000000") == pytest.approx(5.0)


def test_ffmpeg_out_time_us_parses_microsecond_counter() -> None:
    assert ffmpeg_out_time_seconds("out_time_us", "2500000") == pytest.approx(2.5)


def test_ffmpeg_progress_percent_uses_duration_and_caps_before_complete() -> None:
    assert ffmpeg_progress_percent("out_time=00:00:05.000000", 10.0) == 50
    assert ffmpeg_progress_percent("out_time_us=20000000", 10.0) == 99
    assert ffmpeg_progress_percent("frame=100", 10.0) is None
    assert ffmpeg_progress_percent("out_time=00:00:01.000000", None) is None


def test_ffmpeg_progress_line_detection() -> None:
    assert is_ffmpeg_progress_line("out_time_ms=5000000") is True
    assert is_ffmpeg_progress_line("progress=end") is True
    assert is_ffmpeg_progress_line("speed=1.25x") is True
    assert is_ffmpeg_progress_line("frame:42 pblack:99 pts:42 t:1.680") is False
    assert is_ffmpeg_progress_line("encoder warning") is False


def test_ffmpeg_log_line_filtering_excludes_progress_and_blank_lines() -> None:
    assert should_keep_ffmpeg_log_line("Conversion warning") is True
    assert should_keep_ffmpeg_log_line("out_time_us=1000000") is False
    assert should_keep_ffmpeg_log_line("progress=continue") is False
    assert should_keep_ffmpeg_log_line("   ") is False


def test_parse_ffmpeg_progress_event_includes_seconds_and_percent() -> None:
    event = parse_ffmpeg_progress_event("out_time=00:00:02.500000", duration_seconds=10.0)

    assert event == FfmpegProgressEvent(
        line="out_time=00:00:02.500000",
        key="out_time",
        value="00:00:02.500000",
        seconds=2.5,
        percent=25,
    )


def test_split_ffmpeg_progress_line_and_result_model() -> None:
    assert split_ffmpeg_progress_line(" speed = 1.5x ") == ("speed", "1.5x")
    assert split_ffmpeg_progress_line("not progress") is None
    assert FfmpegJobResult(return_code=1, cancelled=True, recent_output=("error",)).recent_output == ("error",)
