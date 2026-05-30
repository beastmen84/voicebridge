import wave
from pathlib import Path


def pcm16_duration_seconds(byte_count: int, sample_rate: int, channel_count: int) -> float:
    frame_size = max(1, channel_count * 2)
    return max(0.0, byte_count / max(1, sample_rate * frame_size))


def trim_pcm16_to_frames(pcm_data: bytes, channel_count: int) -> bytes:
    frame_size = max(1, channel_count * 2)
    usable_size = len(pcm_data) - (len(pcm_data) % frame_size)
    return pcm_data[:usable_size]


def write_pcm16_wav(path: str | Path, pcm_data: bytes, sample_rate: int, channel_count: int) -> None:
    audio_path = Path(path)
    pcm_data = trim_pcm16_to_frames(pcm_data, channel_count)
    if not pcm_data:
        raise ValueError("No recorded audio data is available.")

    audio_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(audio_path), "wb") as wav_file:
        wav_file.setnchannels(channel_count)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_data)
