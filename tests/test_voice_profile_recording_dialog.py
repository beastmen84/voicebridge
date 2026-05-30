import struct

from voicebridge.voice_profile_recording_dialog import build_recording_quality_details, build_recording_status_message
from voicebridge.voice_profile_scripts import (
    VOICE_PROFILE_RECORDING_SCRIPTS,
    voice_profile_recording_script,
    voice_profile_recording_script_languages,
)
from voicebridge.voice_profiles import VOICE_PROFILE_LANGUAGES
from voicebridge.wav_writer import prepare_voice_reference_pcm


def pcm16_bytes(samples: list[int]) -> bytes:
    return b"".join(struct.pack("<h", sample) for sample in samples)


def test_recording_scripts_cover_all_profile_languages() -> None:
    assert voice_profile_recording_script_languages() == set(VOICE_PROFILE_LANGUAGES)
    assert len(VOICE_PROFILE_RECORDING_SCRIPTS) == 17
    for language_code in VOICE_PROFILE_LANGUAGES:
        script = voice_profile_recording_script(language_code)
        assert len(script) >= 120
        assert any(mark in script for mark in ("?", "؟", "？"))
        assert any(mark in script for mark in ("!", "！"))


def test_unknown_recording_script_falls_back_to_english() -> None:
    assert voice_profile_recording_script("unknown") == VOICE_PROFILE_RECORDING_SCRIPTS["en"]


def test_recording_quality_details_include_cleanup_metrics() -> None:
    pcm_data = pcm16_bytes([0] * 10 + [5000] * 20 + [0] * 10)
    recording = prepare_voice_reference_pcm(pcm_data, sample_rate=10, channel_count=1)

    details = build_recording_quality_details(
        recording,
        sample_rate=10,
        channel_count=1,
        recorder_messages=("input overflow",),
    )
    long_recording = prepare_voice_reference_pcm(pcm16_bytes([5000] * 300), sample_rate=10, channel_count=1)
    status = build_recording_status_message(long_recording, ("input overflow",), auto_stopped=True)

    assert "Sample rate: 10 Hz" in details
    assert "Cleaned duration:" in details
    assert "Trimmed silence:" in details
    assert "input overflow" in details
    assert "Maximum reference length reached" in status


def test_recording_status_warns_when_usable_speech_is_short() -> None:
    recording = prepare_voice_reference_pcm(pcm16_bytes([5000] * 20), sample_rate=10, channel_count=1)

    status = build_recording_status_message(recording, auto_stopped=True)

    assert "Usable speech is short" in status
