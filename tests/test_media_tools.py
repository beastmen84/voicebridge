from pathlib import Path

import pytest

from voicebridge.media_tools import (
    AUDIO_CLEANUP_FADE,
    AUDIO_CLEANUP_REMOVE,
    AUDIO_CLEANUP_SILENCE,
    BURN_QUALITY_HIGH,
    BURN_QUALITY_STANDARD,
    audio_cleanup_command,
    audio_cleanup_filter_complex,
    audio_waveform_command,
    auto_burn_quality,
    first_srt_timestamp_seconds,
    freezeframes_filter_complex,
    isolated_black_frame_numbers,
    parse_ffmpeg_duration,
    parse_srt_timestamp,
    pcm_s16le_peak_bins,
    removeframes_filter_complex,
    suggest_audio_cleanup_output_path,
    suggest_video_cleanup_output_path,
    suggest_video_subtitle_output_path,
    video_filmstrip_frame_numbers,
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


def test_suggest_audio_cleanup_output_path_keeps_audio_suffix() -> None:
    assert suggest_audio_cleanup_output_path("source.wav") == "source_cleaned.wav"
    assert suggest_audio_cleanup_output_path("source.unknown") == "source_cleaned.mp3"


def test_parse_ffmpeg_duration() -> None:
    output = "Duration: 01:02:03.45, start: 0.000000, bitrate: 128 kb/s"

    assert parse_ffmpeg_duration(output) == pytest.approx(3723.45)


def test_audio_cleanup_remove_filter_removes_middle_range() -> None:
    graph = audio_cleanup_filter_complex(AUDIO_CLEANUP_REMOVE, 1.0, 2.0, duration_seconds=4.0)

    assert "[0:a]atrim=end=1.000000,asetpts=PTS-STARTPTS[a0]" in graph
    assert "[0:a]atrim=start=2.000000,asetpts=PTS-STARTPTS[a1]" in graph
    assert "[a0][a1]concat=n=2:v=0:a=1[aclean]" in graph


def test_audio_cleanup_silence_filter_keeps_timing() -> None:
    graph = audio_cleanup_filter_complex(AUDIO_CLEANUP_SILENCE, 1.0, 2.0, duration_seconds=4.0)

    assert "volume=enable='between(t\\,1.000000\\,2.000000)':volume=0[aclean]" in graph


def test_audio_cleanup_fade_filter_adds_fades() -> None:
    graph = audio_cleanup_filter_complex(AUDIO_CLEANUP_FADE, 1.0, 2.0, duration_seconds=4.0)

    assert "afade=t=out:st=1.000000" in graph
    assert "afade=t=in:st=1.920000" in graph


def test_audio_cleanup_command_maps_clean_audio() -> None:
    command = audio_cleanup_command("ffmpeg", "in.mp3", "out.mp3", AUDIO_CLEANUP_SILENCE, 1.0, 2.0, 4.0)

    assert "-filter_complex" in command
    assert command[-3:] == ["-q:a", "4", "out.mp3"]
    assert "[aclean]" in command


def test_audio_waveform_command_outputs_mono_pcm() -> None:
    command = audio_waveform_command("ffmpeg", "in.mp3", sample_rate=1000)

    assert command[-2:] == ["s16le", "pipe:1"]
    assert command[command.index("-ac"):command.index("-ac") + 2] == ["-ac", "1"]
    assert command[command.index("-ar"):command.index("-ar") + 2] == ["-ar", "1000"]


def test_pcm_s16le_peak_bins_normalizes_samples() -> None:
    samples = [0, 32767, 0, 16384]
    pcm_data = b"".join(int(sample).to_bytes(2, "little", signed=True) for sample in samples)

    assert pcm_s16le_peak_bins(pcm_data, bin_count=2) == pytest.approx([32767 / 32768, 0.5])


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


def test_video_filmstrip_frame_numbers_samples_fit_and_zoom_windows() -> None:
    assert video_filmstrip_frame_numbers(10, max_items=20) == list(range(10))

    fit = video_filmstrip_frame_numbers(1000, max_items=5)
    assert fit == [0, 250, 500, 749, 999]

    zoomed = video_filmstrip_frame_numbers(1000, start_frame=100, window_frames=10, max_items=20)
    assert zoomed == list(range(100, 110))


def test_auto_burn_quality_prefers_high_for_large_or_high_bitrate_sources() -> None:
    assert auto_burn_quality(source_video_width=3840, source_video_height=2160) == BURN_QUALITY_HIGH
    assert auto_burn_quality(source_video_bitrate_kbps=15000, source_video_width=1920, source_video_height=1080) == (
        BURN_QUALITY_HIGH
    )
    assert auto_burn_quality(source_video_bitrate_kbps=6000, source_video_width=1920, source_video_height=1080) == (
        BURN_QUALITY_STANDARD
    )
