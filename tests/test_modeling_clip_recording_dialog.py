import struct

from voicebridge.modeling_clip_recording_dialog import (
    ModelingClipRecordingDialog,
    build_recording_quality_details,
    build_recording_status_message,
)
from voicebridge.wav_writer import prepare_voice_reference_pcm


def pcm16_bytes(samples: list[int]) -> bytes:
    return b"".join(struct.pack("<h", sample) for sample in samples)


def test_estimated_target_seconds_caps_to_maximum() -> None:
    long_text = "word " * 400

    assert ModelingClipRecordingDialog.estimated_target_seconds("", 60) == 60
    assert ModelingClipRecordingDialog.estimated_target_seconds("short clip", 60) == 12
    assert ModelingClipRecordingDialog.estimated_target_seconds(long_text, 60) == 60


def test_modeling_recording_status_reports_auto_stop() -> None:
    recording = prepare_voice_reference_pcm(pcm16_bytes([5000] * 300), sample_rate=10, channel_count=1)

    status = build_recording_status_message(recording, auto_stopped=True)

    assert "Maximum clip length reached" in status


def test_modeling_recording_quality_details_include_snr() -> None:
    recording = prepare_voice_reference_pcm(pcm16_bytes([100] * 20 + [5000] * 30 + [100] * 20), 10, 1)

    details = build_recording_quality_details(recording, sample_rate=10, channel_count=1)

    assert "Estimated SNR:" in details
