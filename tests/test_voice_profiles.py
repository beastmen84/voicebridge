import json
from pathlib import Path

import pytest

from voicebridge.json_schemas import VOICE_PROFILES_JSON_KIND, current_schema_version
from voicebridge.modeling_datasets import ModelingDataset, build_modeling_dataset_for_profile
from voicebridge.pages.voice_profiles import VoiceProfilesWorkflowMixin
from voicebridge.voice_profiles import (
    VOICE_PROFILE_MODELING,
    VOICE_PROFILE_REFERENCE,
    VoiceProfile,
    build_voice_profile,
    clean_profile_name,
    delete_voice_profile_audio_files,
    load_voice_profiles,
    ready_voice_profiles,
    safe_voice_profile_audio_stem,
    save_voice_profiles,
    validate_voice_profile,
    voice_profile_display_label,
    voice_profile_owned_audio_paths,
    voice_profile_recording_path,
    voice_profile_status,
)


class FakeStatusLabel:
    def __init__(self) -> None:
        self.text = ""

    def setText(self, text: str) -> None:
        self.text = text


class DummyVoiceProfilesWindow(VoiceProfilesWorkflowMixin):
    def __init__(self, profiles: list[VoiceProfile], datasets: list[ModelingDataset]) -> None:
        self.voice_profiles = profiles
        self.modeling_datasets = datasets
        self.selected_voice_profile_id = profiles[0]["id"] if profiles else ""
        self.profile_status_label = FakeStatusLabel()
        self.errors: list[tuple[str, str]] = []
        self.synced_modeling_datasets = False
        self.new_profile_started = False
        self.voice_profiles_list_refreshed = False
        self.local_voice_profile_combo_refreshed = False
        self.local_voice_tabs_updated = False

    def voice_profile_is_recording(self) -> bool:
        return False

    def show_error(self, title: str, message: str) -> None:
        self.errors.append((title, message))

    def sync_modeling_datasets_with_profiles(self, *, save: bool = True) -> None:
        self.synced_modeling_datasets = True

    def new_voice_profile(self) -> None:
        self.new_profile_started = True
        self.selected_voice_profile_id = ""

    def refresh_voice_profiles_list(self) -> None:
        self.voice_profiles_list_refreshed = True

    def refresh_local_voice_profile_combo(self, selected_profile_id: str = "") -> None:
        self.local_voice_profile_combo_refreshed = True

    def update_local_voice_tabs(self) -> None:
        self.local_voice_tabs_updated = True


def write_audio_marker(path: Path) -> None:
    path.write_bytes(b"RIFF" + (b"\0" * 64))


def test_clean_profile_name_collapses_whitespace() -> None:
    assert clean_profile_name("  Marco   IT  ") == "Marco IT"
    assert clean_profile_name(None) == ""


def test_voice_profile_recording_path_uses_safe_stem(tmp_path: Path) -> None:
    assert safe_voice_profile_audio_stem("  Marco Rossi!  ") == "marco-rossi"
    assert safe_voice_profile_audio_stem("!!!") == "voice-profile"

    path = voice_profile_recording_path("Marco Rossi!", timestamp="20260530-120000", audio_dir=tmp_path)

    assert path == tmp_path / "reference_clone" / "marco-rossi" / "marco-rossi-20260530-120000.wav"


def test_reference_profile_ready_status(tmp_path: Path) -> None:
    reference = tmp_path / "voice.wav"
    write_audio_marker(reference)
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
    write_audio_marker(reference)
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
    profile = build_voice_profile(
        name="Dataset",
        language_code="en",
        profile_type=VOICE_PROFILE_MODELING,
        reference_paths=[],
        consent_confirmed=True,
    )

    assert voice_profile_status(profile) == "Modeling dataset"
    validate_voice_profile(profile)


def test_save_and_load_voice_profiles(tmp_path: Path) -> None:
    reference = tmp_path / "voice.mp3"
    write_audio_marker(reference)
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
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    loaded = load_voice_profiles(config_path)

    assert saved["schema_version"] == current_schema_version(VOICE_PROFILES_JSON_KIND)
    assert saved["kind"] == VOICE_PROFILES_JSON_KIND
    assert loaded == [profile]


def test_ready_voice_profiles_only_returns_reference_profiles(tmp_path: Path) -> None:
    reference = tmp_path / "voice.wav"
    write_audio_marker(reference)
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


def test_voice_profile_owned_audio_paths_only_returns_recorded_wavs(tmp_path: Path) -> None:
    audio_dir = tmp_path / "voice_profiles"
    recorded_wav = audio_dir / "reference_clone" / "reference" / "recorded.wav"
    recorded_wav.parent.mkdir(parents=True)
    write_audio_marker(recorded_wav)
    external_wav = tmp_path / "external.wav"
    write_audio_marker(external_wav)
    recorded_mp3 = audio_dir / "reference_clone" / "reference" / "recorded.mp3"
    write_audio_marker(recorded_mp3)
    profile = build_voice_profile(
        name="Reference",
        language_code="it",
        profile_type=VOICE_PROFILE_REFERENCE,
        reference_paths=[str(recorded_wav), str(external_wav), str(recorded_mp3)],
        consent_confirmed=True,
    )

    assert voice_profile_owned_audio_paths(profile, audio_dir) == [recorded_wav.resolve()]


def test_delete_voice_profile_audio_files_removes_only_owned_wavs(tmp_path: Path) -> None:
    audio_dir = tmp_path / "voice_profiles"
    recorded_wav = audio_dir / "reference_clone" / "reference" / "recorded.wav"
    recorded_wav.parent.mkdir(parents=True)
    write_audio_marker(recorded_wav)
    external_wav = tmp_path / "external.wav"
    write_audio_marker(external_wav)
    profile = build_voice_profile(
        name="Reference",
        language_code="it",
        profile_type=VOICE_PROFILE_REFERENCE,
        reference_paths=[str(recorded_wav), str(external_wav)],
        consent_confirmed=True,
    )

    deleted_paths, failed_paths = delete_voice_profile_audio_files(profile, audio_dir)

    assert deleted_paths == [recorded_wav.resolve()]
    assert failed_paths == []
    assert not recorded_wav.exists()
    assert external_wav.exists()


def test_delete_modeling_profile_removes_empty_linked_dataset(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = build_voice_profile(
        name="Anayah - IT",
        language_code="it",
        profile_type=VOICE_PROFILE_MODELING,
        reference_paths=[],
        consent_confirmed=True,
    )
    dataset = build_modeling_dataset_for_profile(profile)
    saved_profiles: list[list[VoiceProfile]] = []
    saved_datasets: list[list[ModelingDataset]] = []

    monkeypatch.setattr(
        "voicebridge.pages.voice_profiles.save_voice_profiles",
        saved_profiles.append,
    )
    monkeypatch.setattr(
        "voicebridge.pages.voice_profiles.save_modeling_datasets",
        saved_datasets.append,
    )
    monkeypatch.setattr(
        "voicebridge.pages.voice_profiles.delete_voice_profile_audio_files",
        lambda _profile: ([], []),
    )

    window = DummyVoiceProfilesWindow([profile], [dataset])

    window.delete_selected_voice_profile()

    assert window.voice_profiles == []
    assert window.modeling_datasets == []
    assert saved_profiles == [[]]
    assert saved_datasets == [[]]
    assert window.errors == []
    assert window.synced_modeling_datasets is True
    assert window.new_profile_started is True
    assert window.voice_profiles_list_refreshed is True
    assert window.local_voice_profile_combo_refreshed is True
    assert window.local_voice_tabs_updated is True
    assert window.profile_status_label.text == "Deleted profile and linked empty modeling dataset."


def test_delete_modeling_profile_blocks_linked_dataset_with_user_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = build_voice_profile(
        name="Anayah - IT",
        language_code="it",
        profile_type=VOICE_PROFILE_MODELING,
        reference_paths=[],
        consent_confirmed=True,
    )
    dataset = build_modeling_dataset_for_profile(profile)
    dataset["guided_prompt_history"].append("Read this line.")
    saved_profiles: list[list[VoiceProfile]] = []
    saved_datasets: list[list[ModelingDataset]] = []

    monkeypatch.setattr(
        "voicebridge.pages.voice_profiles.save_voice_profiles",
        saved_profiles.append,
    )
    monkeypatch.setattr(
        "voicebridge.pages.voice_profiles.save_modeling_datasets",
        saved_datasets.append,
    )
    monkeypatch.setattr(
        "voicebridge.pages.voice_profiles.delete_voice_profile_audio_files",
        lambda _profile: ([], []),
    )

    window = DummyVoiceProfilesWindow([profile], [dataset])

    window.delete_selected_voice_profile()

    assert window.voice_profiles == [profile]
    assert window.modeling_datasets == [dataset]
    assert saved_profiles == []
    assert saved_datasets == []
    assert window.synced_modeling_datasets is False
    assert window.new_profile_started is False
    assert window.profile_status_label.text == "Delete blocked: linked modeling dataset has recorded data."
    assert window.errors == [
        (
            "Voice Profiles",
            (
                "Cannot delete 'Anayah - IT' while its modeling dataset contains clips "
                "or guided prompt history.\n\n"
                "Export or manually clear the dataset data first."
            ),
        )
    ]
