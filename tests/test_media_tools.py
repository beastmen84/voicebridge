from pathlib import Path

import pytest

from voicebridge.media_tools import (
    BURN_QUALITY_HIGH,
    BURN_QUALITY_STANDARD,
    auto_burn_quality,
    first_srt_timestamp_seconds,
    freezeframes_filter_complex,
    isolated_black_frame_numbers,
    parse_srt_timestamp,
    removeframes_filter_complex,
    suggest_video_cleanup_output_path,
    suggest_video_subtitle_output_path,
)


def test_parse_srt_timestamp_and_first_timestamp(tmp_path: Path) -> None:
    srt_path = tmp_path / "sample.srt"
    srt_path.write_text(
        "1\n00:00:03,250 --> 00:00:04,000\nHello\n",
        encoding="utf-8",
    )

    assert parse_srt_timestamp("01:02:03,456") == pytest.approx(3723.456)
    assert first_srt_timestamp_seconds(srt_path) == pytest.approx(3.5)


@pytest.mark.parametrize(
    ("media_path", "mode", "expected"),
    [
        ("clip.mp4", "embed", "clip_subtitled.mp4"),
        ("clip.avi", "embed", "clip_subtitled.mkv"),
        ("clip.mov", "burn", "clip_burned.mp4"),
    ],
)
def test_suggest_video_subtitle_output_path(media_path: str, mode: str, expected: str) -> None:
    assert suggest_video_subtitle_output_path(media_path, mode) == expected


def test_suggest_video_cleanup_output_path_uses_safe_suffix() -> None:
    assert suggest_video_cleanup_output_path("source.mov") == "source_cleaned.mov"
    assert suggest_video_cleanup_output_path("source.webm") == "source_cleaned.mp4"


def test_isolated_black_frame_numbers_splits_runs() -> None:
    frames = [
        {"frame": 0, "pblack": 99, "pts": 0, "time": 0.0},
        {"frame": 5, "pblack": 99, "pts": 5, "time": 0.2},
        {"frame": 8, "pblack": 99, "pts": 8, "time": 0.32},
        {"frame": 9, "pblack": 99, "pts": 9, "time": 0.36},
    ]

    isolated, longer_runs = isolated_black_frame_numbers(frames)

    assert isolated == [5]
    assert [[frame["frame"] for frame in run] for run in longer_runs] == [[0], [8, 9]]


def test_freezeframes_filter_complex_replaces_selected_frames() -> None:
    graph = freezeframes_filter_complex([4, 2, 2])

    assert "split=3[base][ref0][ref1]" in graph
    assert "first=2:last=2:replace=1" in graph
    assert "first=4:last=4:replace=3" in graph


def test_removeframes_filter_complex_can_include_audio_slice_removal() -> None:
    graph = removeframes_filter_complex([10], frame_times_seconds=[0.4], fps=25, has_audio=True)

    assert "[0:v]select=not(eq(n\\,10)),setpts=N/FRAME_RATE/TB[vclean]" in graph
    assert "[0:a]aselect=not(between(t\\,0.400000\\,0.440000)),asetpts=N/SR/TB[aclean]" in graph


def test_auto_burn_quality_prefers_high_for_large_or_high_bitrate_sources() -> None:
    assert auto_burn_quality(source_video_width=3840, source_video_height=2160) == BURN_QUALITY_HIGH
    assert auto_burn_quality(source_video_bitrate_kbps=15000, source_video_width=1920, source_video_height=1080) == (
        BURN_QUALITY_HIGH
    )
    assert auto_burn_quality(source_video_bitrate_kbps=6000, source_video_width=1920, source_video_height=1080) == (
        BURN_QUALITY_STANDARD
    )
