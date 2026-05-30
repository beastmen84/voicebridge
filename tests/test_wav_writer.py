import wave
from pathlib import Path

from voicebridge.wav_writer import pcm16_duration_seconds, trim_pcm16_to_frames, write_pcm16_wav


def test_pcm16_duration_seconds_uses_frame_size() -> None:
    assert pcm16_duration_seconds(48_000, sample_rate=24_000, channel_count=1) == 1.0


def test_trim_pcm16_to_complete_frames() -> None:
    assert trim_pcm16_to_frames(b"12345", channel_count=1) == b"1234"
    assert trim_pcm16_to_frames(b"12345", channel_count=2) == b"1234"


def test_write_pcm16_wav(tmp_path: Path) -> None:
    wav_path = tmp_path / "recording.wav"
    write_pcm16_wav(wav_path, b"\x00\x00\x01\x00", sample_rate=24_000, channel_count=1)

    with wave.open(str(wav_path), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 24_000
        assert wav_file.getnframes() == 2
