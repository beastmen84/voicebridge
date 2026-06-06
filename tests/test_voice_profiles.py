import json
from pathlib import Path

import pytest

from voicebridge.json_schemas import (
    VOICE_MODELING_JOB_CONFIG_JSON_KIND,
    VOICE_PROFILES_JSON_KIND,
    current_schema_version,
    with_schema_metadata,
)
from voicebridge.modeling_datasets import (
    MODELING_CLIP_FREE_RECORDING,
    ModelingDataset,
    build_modeling_clip,
    build_modeling_dataset_for_profile,
    export_modeling_dataset,
    modeling_clip_audio_path,
    modeling_clip_transcript_path,
    modeling_dataset_dir,
    modeling_dataset_exports_root,
)
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


class FakeButton:
    def __init__(self) -> None:
        self.enabled = None

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = enabled


class FakeLineEdit:
    def __init__(self, text: str = "") -> None:
        self._text = text
        self.enabled = None

    def text(self) -> str:
        return self._text

    def setText(self, text: str) -> None:
        self._text = text

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = enabled


class FakePlainTextEdit:
    def __init__(self, text: str = "") -> None:
        self._text = text

    def toPlainText(self) -> str:
        return self._text

    def setPlainText(self, text: str) -> None:
        self._text = text


class FakePicker:
    def __init__(self, text: str = "") -> None:
        self._text = text
        self.enabled = None

    def text(self) -> str:
        return self._text

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = enabled


class FakeCombo:
    def __init__(self, data: object = None) -> None:
        self.data = data
        self.enabled = None

    def currentData(self, _role: object = None) -> object:
        return self.data

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = enabled


class FakeList:
    def __init__(self) -> None:
        self.enabled = None

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = enabled


class DummyVoiceProfilesWindow(VoiceProfilesWorkflowMixin):
    def __init__(
        self,
        profiles: list[VoiceProfile],
        datasets: list[ModelingDataset],
        *,
        confirm_delete: bool = True,
    ) -> None:
        self.voice_profiles = profiles
        self.modeling_datasets = datasets
        self.selected_voice_profile_id = profiles[0]["id"] if profiles else ""
        self.profile_status_label = FakeStatusLabel()
        self.errors: list[tuple[str, str]] = []
        self.confirm_delete = confirm_delete
        self.questions: list[tuple[str, str, bool]] = []
        self.synced_modeling_datasets = False
        self.new_profile_started = False
        self.voice_profiles_list_refreshed = False
        self.local_voice_profile_combo_refreshed = False
        self.local_voice_tabs_updated = False

    def voice_profile_is_recording(self) -> bool:
        return False

    def show_error(self, title: str, message: str) -> None:
        self.errors.append((title, message))

    def ask_question(self, title: str, message: str, default_yes: bool = False) -> bool:
        self.questions.append((title, message, default_yes))
        return self.confirm_delete

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


class DummyVoiceProfileButtonWindow(VoiceProfilesWorkflowMixin):
    def __init__(self, profile: VoiceProfile) -> None:
        self.voice_profiles = [profile]
        self.selected_voice_profile_id = profile["id"]
        self.voice_profiles_list = FakeList()
        self.profile_name_edit = FakeLineEdit(profile["name"])
        self.profile_language_combo = FakeCombo(profile["language_code"])
        self.profile_type_combo = FakeCombo(profile["profile_type"])
        self.profile_reference_picker = FakePicker(profile["reference_paths"][0] if profile["reference_paths"] else "")
        self.profile_notes_edit = FakePlainTextEdit(profile["notes"])
        self.profile_new_button = FakeButton()
        self.profile_delete_button = FakeButton()
        self.profile_save_button = FakeButton()
        self.profile_open_dataset_button = FakeButton()
        self.profile_open_reference_button = FakeButton()
        self.profile_open_folder_button = FakeButton()
        self.opened_dataset_profile_id = ""
        self.synced_modeling_datasets = False
        self.modeling_datasets: list[ModelingDataset] = []

    def voice_profile_is_recording(self) -> bool:
        return False

    def sync_modeling_datasets_with_profiles(self, *, save: bool = True) -> None:
        self.synced_modeling_datasets = True

    def open_modeling_dataset_for_profile(self, profile_id: str) -> None:
        self.opened_dataset_profile_id = profile_id


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


def test_profile_validation_treats_missing_consent_as_legacy_non_blocking(tmp_path: Path) -> None:
    reference = tmp_path / "voice.wav"
    write_audio_marker(reference)
    profile = build_voice_profile(
        name="Marco",
        language_code="it",
        profile_type=VOICE_PROFILE_REFERENCE,
        reference_paths=[str(reference)],
        consent_confirmed=False,
    )

    assert profile["consent_confirmed"] is True
    assert voice_profile_status(profile) == "Ready"
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


def test_saved_voice_profile_save_button_requires_changes(tmp_path: Path) -> None:
    reference = tmp_path / "voice.wav"
    write_audio_marker(reference)
    profile = build_voice_profile(
        name="Reference Voice",
        language_code="it",
        profile_type=VOICE_PROFILE_REFERENCE,
        reference_paths=[str(reference)],
        consent_confirmed=True,
        notes="Original notes",
    )
    window = DummyVoiceProfileButtonWindow(profile)

    window.update_voice_profile_buttons()

    assert window.profile_save_button.enabled is False
    assert window.profile_name_edit.enabled is False
    assert window.profile_type_combo.enabled is False
    assert window.profile_language_combo.enabled is False
    assert window.profile_open_dataset_button.enabled is False

    window.profile_notes_edit.setPlainText("Updated notes")
    window.update_voice_profile_buttons()

    assert window.profile_save_button.enabled is True


def test_saved_modeling_profile_opens_linked_dataset() -> None:
    profile = build_voice_profile(
        name="Dataset Voice",
        language_code="it",
        profile_type=VOICE_PROFILE_MODELING,
        reference_paths=[],
        consent_confirmed=True,
    )
    window = DummyVoiceProfileButtonWindow(profile)

    window.update_voice_profile_buttons()
    window.open_selected_voice_profile_dataset()

    assert window.profile_save_button.enabled is False
    assert window.profile_open_dataset_button.enabled is True
    assert window.profile_reference_picker.enabled is False
    assert window.synced_modeling_datasets is True
    assert window.opened_dataset_profile_id == profile["id"]


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


def test_delete_profile_without_linked_modeling_work_does_not_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = build_voice_profile(
        name="Reference",
        language_code="it",
        profile_type=VOICE_PROFILE_REFERENCE,
        reference_paths=[],
        consent_confirmed=True,
    )
    saved_profiles: list[list[VoiceProfile]] = []
    saved_datasets: list[list[ModelingDataset]] = []
    monkeypatch.setattr("voicebridge.pages.voice_profiles.save_voice_profiles", saved_profiles.append)
    monkeypatch.setattr("voicebridge.pages.voice_profiles.save_modeling_datasets", saved_datasets.append)
    window = DummyVoiceProfilesWindow([profile], [])

    window.delete_selected_voice_profile()

    assert window.questions == []
    assert window.voice_profiles == []
    assert window.modeling_datasets == []
    assert saved_profiles == [[]]
    assert saved_datasets == []
    assert window.profile_status_label.text == "Deleted profile."


def test_cancel_destructive_modeling_profile_delete_keeps_everything(monkeypatch: pytest.MonkeyPatch) -> None:
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

    window = DummyVoiceProfilesWindow([profile], [dataset], confirm_delete=False)

    window.delete_selected_voice_profile()

    assert window.voice_profiles == [profile]
    assert window.modeling_datasets == [dataset]
    assert saved_profiles == []
    assert saved_datasets == []
    assert window.errors == []
    assert window.questions
    assert "guided prompt history" in window.questions[0][1]
    assert window.synced_modeling_datasets is False
    assert window.new_profile_started is False
    assert window.profile_status_label.text == "Delete cancelled."


def test_confirm_destructive_modeling_profile_delete_removes_empty_linked_dataset(
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

    window = DummyVoiceProfilesWindow([profile], [dataset])

    window.delete_selected_voice_profile()

    assert window.voice_profiles == []
    assert window.modeling_datasets == []
    assert saved_profiles == [[]]
    assert saved_datasets == [[]]
    assert window.errors == []
    assert window.questions
    assert "modeling dataset entry" in window.questions[0][1]
    assert window.synced_modeling_datasets is True
    assert window.new_profile_started is True
    assert window.voice_profiles_list_refreshed is True
    assert window.local_voice_profile_combo_refreshed is True
    assert window.local_voice_tabs_updated is True
    assert window.profile_status_label.text == "Deleted profile and linked modeling work."


def test_confirm_destructive_modeling_profile_delete_removes_user_content(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("voicebridge.voice_profiles.external_base_dir", lambda: tmp_path)
    monkeypatch.setattr("voicebridge.modeling_datasets.external_base_dir", lambda: tmp_path)
    monkeypatch.setattr("voicebridge.voice_modeling.external_base_dir", lambda: tmp_path)
    profile = build_voice_profile(
        name="Anayah - IT",
        language_code="it",
        profile_type=VOICE_PROFILE_MODELING,
        reference_paths=[],
        consent_confirmed=True,
    )
    dataset = build_modeling_dataset_for_profile(profile)
    dataset["guided_prompt_history"].append("Read this line.")
    for index in range(5):
        clip_id = f"ready-{index}"
        audio_path = modeling_clip_audio_path(dataset, clip_id)
        transcript_path = modeling_clip_transcript_path(dataset, clip_id)
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        write_audio_marker(audio_path)
        transcript_path.write_text(f"Ready transcript {index}", encoding="utf-8")
        dataset["clips"].append(
            build_modeling_clip(
                dataset,
                mode=MODELING_CLIP_FREE_RECORDING,
                audio_path=audio_path,
                transcript_text=f"Ready transcript {index}",
                duration_seconds=12.0,
                clip_id=clip_id,
            )
        )
    generated_artifact = modeling_dataset_dir(dataset) / "generated" / "notes.txt"
    generated_artifact.parent.mkdir(parents=True, exist_ok=True)
    generated_artifact.write_text("managed artifact", encoding="utf-8")
    export_result = export_modeling_dataset(
        dataset,
        export_root=modeling_dataset_exports_root(),
        timestamp="20260601-120000",
    )
    export_dir = Path(export_result["export_dir"])
    training_output_dir = tmp_path / "voice_models" / "anayah-it-20260601"
    training_output_dir.mkdir(parents=True)
    (training_output_dir / "job_config.json").write_text(
        json.dumps(
            with_schema_metadata(
                {
                    "id": "job-1",
                    "status": "completed",
                    "training_backend": "xtts_v2",
                    "dataset_dir": str(export_dir),
                    "output_dir": str(training_output_dir),
                    "dataset": {
                        "dataset_dir": str(export_dir),
                        "name": dataset["name"],
                        "language_code": dataset["language_code"],
                        "readiness": "usable",
                        "ready_clips": 5,
                        "ready_duration_seconds": 60.0,
                        "metadata_path": str(export_dir / "metadata.csv"),
                        "dataset_json_path": str(export_dir / "dataset.json"),
                        "wavs_dir": str(export_dir / "wavs"),
                        "metadata_rows": 5,
                    },
                    "created_at": "",
                    "updated_at": "",
                },
                VOICE_MODELING_JOB_CONFIG_JSON_KIND,
            ),
            indent=2,
        ),
        encoding="utf-8",
    )
    archived_log_dir = tmp_path / "logs" / "voice_modeling" / "anayah-it-20260605-failed"
    archived_log_dir.mkdir(parents=True)
    (archived_log_dir / "summary.json").write_text(
        json.dumps(
            {
                "reason": "failed",
                "dataset": {
                    "dataset_id": dataset["id"],
                    "profile_id": profile["id"],
                    "name": dataset["name"],
                    "language_code": dataset["language_code"],
                },
            }
        ),
        encoding="utf-8",
    )
    saved_profiles: list[list[VoiceProfile]] = []
    saved_datasets: list[list[ModelingDataset]] = []
    monkeypatch.setattr("voicebridge.pages.voice_profiles.save_voice_profiles", saved_profiles.append)
    monkeypatch.setattr("voicebridge.pages.voice_profiles.save_modeling_datasets", saved_datasets.append)

    window = DummyVoiceProfilesWindow([profile], [dataset])

    window.delete_selected_voice_profile()

    assert window.voice_profiles == []
    assert window.modeling_datasets == []
    assert saved_profiles == [[]]
    assert saved_datasets == [[]]
    assert not modeling_dataset_dir(dataset).exists()
    assert not export_dir.exists()
    assert not training_output_dir.exists()
    assert not archived_log_dir.exists()
    confirmation = window.questions[0][1]
    assert "recorded clips" in confirmation
    assert "guided prompt history entry" in confirmation
    assert "exported dataset folder" in confirmation
    assert "trained model / training output folder" in confirmation
    assert "archived training log folder" in confirmation
    assert "other generated artifacts" in confirmation
    assert window.profile_status_label.text == "Deleted profile and linked modeling work."


def test_destructive_modeling_profile_delete_removes_linked_empty_training_dirs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("voicebridge.voice_profiles.external_base_dir", lambda: tmp_path)
    monkeypatch.setattr("voicebridge.modeling_datasets.external_base_dir", lambda: tmp_path)
    monkeypatch.setattr("voicebridge.voice_modeling.external_base_dir", lambda: tmp_path)
    profile = build_voice_profile(
        name="Anayah",
        language_code="it",
        profile_type=VOICE_PROFILE_MODELING,
        reference_paths=[],
        consent_confirmed=True,
    )
    dataset = build_modeling_dataset_for_profile(profile)
    linked_empty_dir = tmp_path / "voice_models" / "anayah-20260605-180944"
    unrelated_empty_dir = tmp_path / "voice_models" / "other-20260605-180944"
    linked_empty_dir.mkdir(parents=True)
    unrelated_empty_dir.mkdir(parents=True)
    saved_profiles: list[list[VoiceProfile]] = []
    saved_datasets: list[list[ModelingDataset]] = []
    monkeypatch.setattr("voicebridge.pages.voice_profiles.save_voice_profiles", saved_profiles.append)
    monkeypatch.setattr("voicebridge.pages.voice_profiles.save_modeling_datasets", saved_datasets.append)

    window = DummyVoiceProfilesWindow([profile], [dataset])

    window.delete_selected_voice_profile()

    assert not linked_empty_dir.exists()
    assert unrelated_empty_dir.exists()
    assert "empty training output folder" in window.questions[0][1]


def test_destructive_modeling_profile_delete_preserves_unmanaged_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("voicebridge.voice_profiles.external_base_dir", lambda: tmp_path / "managed")
    monkeypatch.setattr("voicebridge.modeling_datasets.external_base_dir", lambda: tmp_path / "managed")
    monkeypatch.setattr("voicebridge.voice_modeling.external_base_dir", lambda: tmp_path / "managed")
    profile = build_voice_profile(
        name="Anayah - IT",
        language_code="it",
        profile_type=VOICE_PROFILE_MODELING,
        reference_paths=[],
        consent_confirmed=True,
    )
    dataset = build_modeling_dataset_for_profile(profile)
    external_audio = tmp_path / "external.wav"
    external_transcript = tmp_path / "external.txt"
    write_audio_marker(external_audio)
    external_transcript.write_text("External transcript", encoding="utf-8")
    clip = build_modeling_clip(
        dataset,
        mode=MODELING_CLIP_FREE_RECORDING,
        audio_path=external_audio,
        transcript_text="External transcript",
        duration_seconds=12.0,
        clip_id="external",
    )
    clip["transcript_path"] = str(external_transcript)
    dataset["clips"].append(clip)
    saved_profiles: list[list[VoiceProfile]] = []
    saved_datasets: list[list[ModelingDataset]] = []
    monkeypatch.setattr("voicebridge.pages.voice_profiles.save_voice_profiles", saved_profiles.append)
    monkeypatch.setattr("voicebridge.pages.voice_profiles.save_modeling_datasets", saved_datasets.append)

    window = DummyVoiceProfilesWindow([profile], [dataset])

    window.delete_selected_voice_profile()

    assert window.voice_profiles == []
    assert window.modeling_datasets == []
    assert saved_profiles == [[]]
    assert saved_datasets == [[]]
    assert external_audio.exists()
    assert external_transcript.exists()
    confirmation = window.questions[0][1]
    assert "will NOT be deleted" in confirmation
    assert str(external_audio) in confirmation
    assert str(external_transcript) in confirmation
    assert window.profile_status_label.text == (
        "Deleted profile and linked modeling work. "
        "2 linked path(s) were left because they were not safely identifiable."
    )
