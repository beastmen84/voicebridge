from pathlib import Path

import pytest

from voicebridge.voice_profiles import (
    VOICE_PROFILE_MODELING,
    VOICE_PROFILE_REFERENCE,
    build_voice_profile,
    clean_profile_name,
    load_voice_profiles,
    save_voice_profiles,
    validate_voice_profile,
    voice_profile_status,
)


def test_clean_profile_name_collapses_whitespace() -> None:
    assert clean_profile_name("  Marco   IT  ") == "Marco IT"
    assert clean_profile_name(None) == ""


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
