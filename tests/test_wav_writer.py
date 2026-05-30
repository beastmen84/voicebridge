import struct
import wave
from pathlib import Path

from voicebridge.wav_writer import (
    normalize_pcm16_peak,
    pcm16_duration_seconds,
    pcm16_peak_abs,
    prepare_voice_reference_pcm,
    trim_pcm16_silence,
    trim_pcm16_to_frames,
    write_pcm16_wav,
)


def pcm16_bytes(samples: list[int]) -> bytes:
    return b"".join(struct.pack("<h", sample) for sample in samples)


def pcm16_samples(pcm_data: bytes) -> list[int]:
    return [sample[0] for sample in struct.iter_unpack("<h", pcm_data)]


def test_pcm16_duration_seconds_uses_frame_size() -> None:
    assert pcm16_duration_seconds(48_000, sample_rate=24_000, channel_count=1) == 1.0


def test_trim_pcm16_to_complete_frames() -> None:
    assert trim_pcm16_to_frames(b"12345", channel_count=1) == b"1234"
    assert trim_pcm16_to_frames(b"12345", channel_count=2) == b"1234"


def test_trim_pcm16_silence_keeps_padding() -> None:
    pcm_data = pcm16_bytes([0] * 10 + [1000] * 20 + [0] * 10)

    trimmed = trim_pcm16_silence(pcm_data, sample_rate=10, channel_count=1, threshold=100, padding_ms=100)

    assert pcm16_samples(trimmed) == [0] + [1000] * 20 + [0]


def test_normalize_pcm16_peak_scales_to_target() -> None:
    pcm_data = pcm16_bytes([1000, -1000])

    normalized = normalize_pcm16_peak(pcm_data, target_peak=2000)

    assert pcm16_samples(normalized) == [2000, -2000]
    assert pcm16_peak_abs(normalized) == 2000


def test_prepare_voice_reference_pcm_trims_and_normalizes() -> None:
    pcm_data = pcm16_bytes([0] * 10 + [5000] * 10 + [0] * 10)

    result = prepare_voice_reference_pcm(pcm_data, sample_rate=10, channel_count=1)

    assert result.original_duration_seconds == 3.0
    assert result.duration_seconds < result.original_duration_seconds
    assert result.trimmed_seconds > 0
    assert result.analysis.peak == 20_000
    assert "Level normalized." in result.messages


def test_write_pcm16_wav(tmp_path: Path) -> None:
    wav_path = tmp_path / "recording.wav"
    write_pcm16_wav(wav_path, b"\x00\x00\x01\x00", sample_rate=24_000, channel_count=1)

    with wave.open(str(wav_path), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 24_000
        assert wav_file.getnframes() == 2
