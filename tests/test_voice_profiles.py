from pathlib import Path

import pytest

from voicebridge.voice_profiles import (
    VOICE_PROFILE_MODELING,
    VOICE_PROFILE_REFERENCE,
    build_voice_profile,
    clean_profile_name,
    load_voice_profiles,
    ready_voice_profiles,
    safe_voice_profile_audio_stem,
    save_voice_profiles,
    validate_voice_profile,
    voice_profile_display_label,
    voice_profile_recording_path,
    voice_profile_status,
)


def test_clean_profile_name_collapses_whitespace() -> None:
    assert clean_profile_name("  Marco   IT  ") == "Marco IT"
    assert clean_profile_name(None) == ""


def test_voice_profile_recording_path_uses_safe_stem(tmp_path: Path) -> None:
    assert safe_voice_profile_audio_stem("  Marco Rossi!  ") == "marco-rossi"
    assert safe_voice_profile_audio_stem("!!!") == "voice-profile"

    path = voice_profile_recording_path("Marco Rossi!", timestamp="20260530-120000", audio_dir=tmp_path)

    assert path == tmp_path / "marco-rossi-20260530-120000.wav"


def test_reference_profile_ready_status(tmp_path: Path) -> None:
    reference = tmp_path / "voice.wav"
    reference.write_bytes(b"RIFF")
    profile = build_voice_profile(
        name="Marco",
        language_code="it",
        profile_type=VOICE_PROFILE_REFERENCE,
        reference_paths=[str(reference)],
        consent_confirmed=True,
    )

    assert voice_profile_status(profile) == "Ready"
    validate_voice_profile(profile)


def test_profile_validation_rejects_missing_consent(tmp_path: Path) -> None:
    reference = tmp_path / "voice.wav"
    reference.write_bytes(b"RIFF")
    profile = build_voice_profile(
        name="Marco",
        language_code="it",
        profile_type=VOICE_PROFILE_REFERENCE,
        reference_paths=[str(reference)],
        consent_confirmed=False,
    )

    assert voice_profile_status(profile) == "Consent required"
    with pytest.raises(ValueError, match="Consent"):
        validate_voice_profile(profile)


def test_modeling_profile_status(tmp_path: Path) -> None:
    reference = tmp_path / "dataset.flac"
    reference.write_bytes(b"fLaC")
    profile = build_voice_profile(
        name="Dataset",
        language_code="en",
        profile_type=VOICE_PROFILE_MODELING,
        reference_paths=[str(reference)],
        consent_confirmed=True,
    )

    assert voice_profile_status(profile) == "Modeling dataset"


def test_save_and_load_voice_profiles(tmp_path: Path) -> None:
    reference = tmp_path / "voice.mp3"
    reference.write_bytes(b"ID3")
    profile = build_voice_profile(
        name="Reference",
        language_code="it",
        profile_type=VOICE_PROFILE_REFERENCE,
        reference_paths=[str(reference)],
        consent_confirmed=True,
        notes="Studio mic",
    )
    config_path = tmp_path / "voice_profiles.json"

    save_voice_profiles([profile], config_path)
    loaded = load_voice_profiles(config_path)

    assert loaded == [profile]


def test_ready_voice_profiles_only_returns_reference_profiles(tmp_path: Path) -> None:
    reference = tmp_path / "voice.wav"
    reference.write_bytes(b"RIFF")
    ready = build_voice_profile(
        name="Ready",
        language_code="it",
        profile_type=VOICE_PROFILE_REFERENCE,
        reference_paths=[str(reference)],
        consent_confirmed=True,
    )
    modeling = build_voice_profile(
        name="Dataset",
        language_code="it",
        profile_type=VOICE_PROFILE_MODELING,
        reference_paths=[str(reference)],
        consent_confirmed=True,
    )

    assert ready_voice_profiles([modeling, ready]) == [ready]
    assert voice_profile_display_label(ready) == "Ready (Italian)"
