import math
import struct
import wave
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

PCM16_MAX_ABS = 32767
PCM16_CLIP_THRESHOLD = 32700
PCM16_SILENCE_THRESHOLD = 350
PCM16_LOW_SNR_DB = 18.0


@dataclass(frozen=True)
class Pcm16Analysis:
    duration_seconds: float
    peak: int
    peak_percent: float
    rms: float
    rms_percent: float
    clipped_percent: float


@dataclass(frozen=True)
class Pcm16ProcessingResult:
    pcm_data: bytes
    original_duration_seconds: float
    duration_seconds: float
    trimmed_seconds: float
    source_analysis: Pcm16Analysis
    analysis: Pcm16Analysis
    noise_rms: float
    noise_rms_percent: float
    snr_db: float | None
    messages: tuple[str, ...]


def pcm16_duration_seconds(byte_count: int, sample_rate: int, channel_count: int) -> float:
    frame_size = max(1, channel_count * 2)
    return max(0.0, byte_count / max(1, sample_rate * frame_size))


def trim_pcm16_to_frames(pcm_data: bytes, channel_count: int) -> bytes:
    frame_size = max(1, channel_count * 2)
    usable_size = len(pcm_data) - (len(pcm_data) % frame_size)
    return pcm_data[:usable_size]


def pcm16_peak_abs(pcm_data: bytes, channel_count: int = 1) -> int:
    peak = 0
    for sample in _iter_pcm16_samples(trim_pcm16_to_frames(pcm_data, channel_count)):
        peak = max(peak, min(abs(sample), PCM16_MAX_ABS))
    return peak


def analyze_pcm16_audio(pcm_data: bytes, sample_rate: int, channel_count: int) -> Pcm16Analysis:
    pcm_data = trim_pcm16_to_frames(pcm_data, channel_count)
    samples: list[int] = list(_iter_pcm16_samples(pcm_data))
    duration = pcm16_duration_seconds(len(pcm_data), sample_rate, channel_count)
    if not samples:
        return Pcm16Analysis(
            duration_seconds=duration,
            peak=0,
            peak_percent=0.0,
            rms=0.0,
            rms_percent=0.0,
            clipped_percent=0.0,
        )

    peak = max(min(abs(sample), PCM16_MAX_ABS) for sample in samples)
    square_sum = sum(sample * sample for sample in samples)
    rms = math.sqrt(square_sum / len(samples))
    clipped_count = sum(1 for sample in samples if abs(sample) >= PCM16_CLIP_THRESHOLD)
    return Pcm16Analysis(
        duration_seconds=duration,
        peak=peak,
        peak_percent=peak / PCM16_MAX_ABS,
        rms=rms,
        rms_percent=rms / PCM16_MAX_ABS,
        clipped_percent=clipped_count / len(samples) * 100,
    )


def trim_pcm16_silence(
    pcm_data: bytes,
    sample_rate: int,
    channel_count: int,
    *,
    threshold: int = PCM16_SILENCE_THRESHOLD,
    padding_ms: int = 150,
) -> bytes:
    pcm_data = trim_pcm16_to_frames(pcm_data, channel_count)
    samples = list(_iter_pcm16_samples(pcm_data))
    if not samples:
        return b""

    channel_count = max(1, channel_count)
    frame_count = len(samples) // channel_count
    bounds = _sound_frame_bounds(samples, channel_count, threshold)
    if bounds is None:
        return b""
    first_sound_frame, last_sound_frame = bounds

    padding_frames = int(sample_rate * max(0, padding_ms) / 1000)
    start_frame = max(0, first_sound_frame - padding_frames)
    end_frame = min(frame_count, last_sound_frame + padding_frames + 1)
    start_byte = start_frame * channel_count * 2
    end_byte = end_frame * channel_count * 2
    return pcm_data[start_byte:end_byte]


def normalize_pcm16_peak(
    pcm_data: bytes,
    channel_count: int = 1,
    *,
    target_peak: int = 26_000,
    max_gain: float = 4.0,
) -> bytes:
    pcm_data = trim_pcm16_to_frames(pcm_data, channel_count)
    peak = pcm16_peak_abs(pcm_data, channel_count)
    if peak <= 0:
        return pcm_data

    target_peak = max(1, min(target_peak, PCM16_MAX_ABS))
    gain = min(max_gain, target_peak / peak)
    if 0.98 <= gain <= 1.02:
        return pcm_data

    normalized = bytearray()
    for sample in _iter_pcm16_samples(pcm_data):
        scaled_sample = int(round(sample * gain))
        scaled_sample = max(-PCM16_MAX_ABS, min(PCM16_MAX_ABS, scaled_sample))
        normalized.extend(struct.pack("<h", scaled_sample))
    return bytes(normalized)


def prepare_voice_reference_pcm(pcm_data: bytes, sample_rate: int, channel_count: int) -> Pcm16ProcessingResult:
    pcm_data = trim_pcm16_to_frames(pcm_data, channel_count)
    source_analysis = analyze_pcm16_audio(pcm_data, sample_rate, channel_count)
    noise_pcm = pcm16_silence_regions(pcm_data, channel_count)
    noise_analysis = analyze_pcm16_audio(noise_pcm, sample_rate, channel_count)
    trimmed_pcm = trim_pcm16_silence(pcm_data, sample_rate, channel_count)
    if not trimmed_pcm:
        empty_analysis = analyze_pcm16_audio(b"", sample_rate, channel_count)
        return Pcm16ProcessingResult(
            pcm_data=b"",
            original_duration_seconds=source_analysis.duration_seconds,
            duration_seconds=0.0,
            trimmed_seconds=source_analysis.duration_seconds,
            source_analysis=source_analysis,
            analysis=empty_analysis,
            noise_rms=noise_analysis.rms,
            noise_rms_percent=noise_analysis.rms_percent,
            snr_db=None,
            messages=("No usable speech detected.",),
        )

    before_peak = pcm16_peak_abs(trimmed_pcm, channel_count)
    source_speech_analysis = analyze_pcm16_audio(trimmed_pcm, sample_rate, channel_count)
    normalized_pcm = normalize_pcm16_peak(trimmed_pcm, channel_count)
    analysis = analyze_pcm16_audio(normalized_pcm, sample_rate, channel_count)
    snr_db = estimate_snr_db(source_speech_analysis.rms, noise_analysis.rms)
    trimmed_seconds = max(0.0, source_analysis.duration_seconds - analysis.duration_seconds)
    messages: list[str] = []
    if trimmed_seconds >= 0.2:
        messages.append(f"Trimmed {trimmed_seconds:.1f}s silence.")
    if before_peak and normalized_pcm != trimmed_pcm:
        messages.append("Level normalized.")
    if source_analysis.clipped_percent >= 0.1:
        messages.append("Input may be clipped; lower microphone gain.")
    if snr_db is not None and snr_db < PCM16_LOW_SNR_DB:
        messages.append("Background noise is high; record in a quieter room.")
    elif analysis.peak_percent < 0.25:
        messages.append("Input level is low; move closer to the microphone.")

    return Pcm16ProcessingResult(
        pcm_data=normalized_pcm,
        original_duration_seconds=source_analysis.duration_seconds,
        duration_seconds=analysis.duration_seconds,
        trimmed_seconds=trimmed_seconds,
        source_analysis=source_analysis,
        analysis=analysis,
        noise_rms=noise_analysis.rms,
        noise_rms_percent=noise_analysis.rms_percent,
        snr_db=snr_db,
        messages=tuple(messages),
    )


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


def _iter_pcm16_samples(pcm_data: bytes) -> Iterator[int]:
    usable_size = len(pcm_data) - (len(pcm_data) % 2)
    yield from (sample[0] for sample in struct.iter_unpack("<h", pcm_data[:usable_size]))


def pcm16_silence_regions(
    pcm_data: bytes,
    channel_count: int,
    *,
    threshold: int = PCM16_SILENCE_THRESHOLD,
) -> bytes:
    pcm_data = trim_pcm16_to_frames(pcm_data, channel_count)
    samples = list(_iter_pcm16_samples(pcm_data))
    if not samples:
        return b""

    channel_count = max(1, channel_count)
    bounds = _sound_frame_bounds(samples, channel_count, threshold)
    if bounds is None:
        return pcm_data

    first_sound_frame, last_sound_frame = bounds
    first_sound_byte = first_sound_frame * channel_count * 2
    after_sound_byte = (last_sound_frame + 1) * channel_count * 2
    return pcm_data[:first_sound_byte] + pcm_data[after_sound_byte:]


def estimate_snr_db(signal_rms: float, noise_rms: float) -> float | None:
    if signal_rms <= 0 or noise_rms <= 0:
        return None
    return max(0.0, 20 * math.log10(signal_rms / noise_rms))


def _sound_frame_bounds(
    samples: list[int],
    channel_count: int,
    threshold: int,
) -> tuple[int, int] | None:
    frame_count = len(samples) // channel_count
    first_sound_frame = None
    last_sound_frame = None
    for frame_index in range(frame_count):
        start = frame_index * channel_count
        frame = samples[start : start + channel_count]
        if any(abs(sample) >= threshold for sample in frame):
            first_sound_frame = frame_index if first_sound_frame is None else first_sound_frame
            last_sound_frame = frame_index
    if first_sound_frame is None or last_sound_frame is None:
        return None
    return first_sound_frame, last_sound_frame
