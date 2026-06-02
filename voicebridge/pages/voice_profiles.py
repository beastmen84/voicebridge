from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
)

from voicebridge.audio_recorder import (
    AudioRecorderError,
    list_input_devices,
)
from voicebridge.languages import language_name
from voicebridge.ui.helpers import open_path
from voicebridge.ui.widgets import Card, FilePicker
from voicebridge.voice_profile_recording_dialog import VoiceProfileRecordingDialog
from voicebridge.voice_profiles import (
    VOICE_PROFILE_AUDIO_SUFFIXES,
    VOICE_PROFILE_LANGUAGES,
    VOICE_PROFILE_MODELING,
    VOICE_PROFILE_REFERENCE,
    VOICE_PROFILE_TYPES,
    VoiceProfile,
    build_voice_profile,
    delete_voice_profile_audio_files,
    load_voice_profiles,
    save_voice_profiles,
    validate_voice_profile,
    voice_profile_status,
)


# noinspection PyAttributeOutsideInit,PyUnresolvedReferences,PyTypeChecker
# noinspection PyMethodMayBeStatic,PyStringConversionWithoutDunderMethod
class VoiceProfilesWorkflowMixin:
    def load_voice_profile_store(self) -> None:
        self.voice_profiles = load_voice_profiles()
        self.selected_voice_profile_id = ""

    def selected_voice_profile(self) -> VoiceProfile | None:
        profile_id = getattr(self, "selected_voice_profile_id", "")
        return next((profile for profile in self.voice_profiles if profile["id"] == profile_id), None)

    def voice_profile_language_code(self) -> str:
        language_code = self.profile_language_combo.currentData(Qt.ItemDataRole.UserRole)
        return language_code if isinstance(language_code, str) else "it"

    def set_voice_profile_language_code(self, language_code: str) -> None:
        for index in range(self.profile_language_combo.count()):
            if self.profile_language_combo.itemData(index, Qt.ItemDataRole.UserRole) == language_code:
                self.profile_language_combo.setCurrentIndex(index)
                return
        self.profile_language_combo.setCurrentIndex(0)

    def voice_profile_type(self) -> str:
        profile_type = self.profile_type_combo.currentData(Qt.ItemDataRole.UserRole)
        return profile_type if isinstance(profile_type, str) else VOICE_PROFILE_REFERENCE

    def set_voice_profile_type(self, profile_type: str) -> None:
        for index in range(self.profile_type_combo.count()):
            if self.profile_type_combo.itemData(index, Qt.ItemDataRole.UserRole) == profile_type:
                self.profile_type_combo.setCurrentIndex(index)
                return
        self.profile_type_combo.setCurrentIndex(0)

    def refresh_voice_profiles_list(self) -> None:
        if not hasattr(self, "voice_profiles_list"):
            return
        self.voice_profiles_list.clear()
        if not self.voice_profiles:
            self.voice_profiles_list.addItem("No voice profiles yet.")
            self.update_voice_profile_buttons()
            return
        for profile in sorted(self.voice_profiles, key=lambda profile_item: profile_item["name"].casefold()):
            status = voice_profile_status(profile)
            label = f"{profile['name']} | {language_name(profile['language_code'])} | {status}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, profile["id"])
            self.voice_profiles_list.addItem(item)
            if profile["id"] == self.selected_voice_profile_id:
                self.voice_profiles_list.setCurrentItem(item)
        self.update_voice_profile_buttons()

    def voice_profile_selection_changed(self) -> None:
        item = self.voice_profiles_list.currentItem()
        profile_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not isinstance(profile_id, str):
            self.update_voice_profile_buttons()
            return
        profile = next((entry for entry in self.voice_profiles if entry["id"] == profile_id), None)
        if not profile:
            self.update_voice_profile_buttons()
            return
        self.selected_voice_profile_id = profile["id"]
        self.profile_name_edit.setText(profile["name"])
        self.set_voice_profile_language_code(profile["language_code"])
        self.set_voice_profile_type(profile["profile_type"])
        self.profile_reference_picker.set_text(profile["reference_paths"][0] if profile["reference_paths"] else "")
        self.profile_consent_check.setChecked(profile["consent_confirmed"])
        self.profile_notes_edit.setPlainText(profile["notes"])
        self.profile_status_label.setText(voice_profile_status(profile))
        self.update_voice_profile_buttons()

    def new_voice_profile(self) -> None:
        if self.voice_profile_is_recording():
            return
        self.selected_voice_profile_id = ""
        self.voice_profiles_list.clearSelection()
        self.profile_name_edit.clear()
        self.set_voice_profile_language_code("it")
        self.set_voice_profile_type(VOICE_PROFILE_REFERENCE)
        self.profile_reference_picker.set_text("")
        self.profile_consent_check.setChecked(False)
        self.profile_notes_edit.clear()
        self.profile_status_label.setText("New profile.")
        self.profile_record_status_label.setText("Record a guided 30s voice sample for the selected profile.")
        self.update_voice_profile_buttons()

    def voice_profile_type_changed(self) -> None:
        if self.voice_profile_type() == VOICE_PROFILE_MODELING:
            self.profile_record_status_label.setText("Use Local Voices > Datasets to collect clips for this voice.")
        else:
            self.profile_record_status_label.setText("Record a guided 30s voice sample for the selected profile.")
        self.update_voice_profile_buttons()

    def select_voice_profile_reference(self) -> None:
        suffixes = " ".join(f"*{suffix}" for suffix in sorted(VOICE_PROFILE_AUDIO_SUFFIXES))
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select reference audio",
            self.profile_reference_picker.text() or str(Path.home()),
            f"Audio files ({suffixes});;All files (*.*)",
        )
        if path:
            self.profile_reference_picker.set_text(path)
            self.update_voice_profile_buttons()

    def refresh_voice_profile_microphones(self) -> None:
        if not hasattr(self, "profile_microphone_combo"):
            return
        current_device_index = self.profile_microphone_combo.currentData(Qt.ItemDataRole.UserRole)
        self.profile_microphone_combo.blockSignals(True)
        try:
            self.profile_microphone_combo.clear()
            try:
                devices = list_input_devices()
            except AudioRecorderError as exc:
                self.profile_record_status_label.setText(str(exc))
                devices = []
            for device in devices:
                default_suffix = " | default" if device.is_default else ""
                label = f"{device.name} | {device.host_api}{default_suffix}"
                self.profile_microphone_combo.addItem(label, device.index)
                if device.index == current_device_index:
                    self.profile_microphone_combo.setCurrentIndex(self.profile_microphone_combo.count() - 1)
            if not devices:
                self.profile_record_status_label.setText("No microphone input was detected by sounddevice.")
        finally:
            self.profile_microphone_combo.blockSignals(False)
        self.update_voice_profile_buttons()

    def selected_voice_profile_audio_device(self) -> int | None:
        device_index = self.profile_microphone_combo.currentData(Qt.ItemDataRole.UserRole)
        return device_index if isinstance(device_index, int) else None

    def start_voice_profile_recording(self) -> None:
        if self.voice_profile_is_recording():
            return
        if not self.profile_name_edit.text().strip():
            self.show_error("Voice Profiles", "Enter a profile name before recording.")
            return
        device = self.selected_voice_profile_audio_device()
        if device is None:
            self.show_error("Voice Profiles", "No microphone input was detected.")
            return

        dialog = VoiceProfileRecordingDialog(
            profile_name=self.profile_name_edit.text().strip(),
            language_code=self.voice_profile_language_code(),
            device_index=device,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.recording_path is None:
            self.profile_record_status_label.setText("Recording cancelled.")
            self.update_voice_profile_buttons()
            return

        self.profile_reference_picker.set_text(str(dialog.recording_path))
        self.profile_record_status_label.setText(dialog.status_message)
        self.update_voice_profile_buttons()

    def voice_profile_is_recording(self) -> bool:
        return False

    def play_voice_profile_reference(self) -> None:
        path = self.profile_reference_picker.text()
        if not path or not Path(path).is_file():
            return
        if self.profile_media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.profile_media_player.stop()
            return
        self.profile_media_player.setSource(QUrl.fromLocalFile(str(Path(path).resolve())))
        self.profile_media_player.play()

    def collect_voice_profile_form(self) -> VoiceProfile:
        existing = self.selected_voice_profile()
        profile = build_voice_profile(
            name=self.profile_name_edit.text(),
            language_code=self.voice_profile_language_code(),
            profile_type=existing["profile_type"] if existing else self.voice_profile_type(),
            reference_paths=[self.profile_reference_picker.text()],
            consent_confirmed=self.profile_consent_check.isChecked(),
            notes=self.profile_notes_edit.toPlainText(),
            profile_id=existing["id"] if existing else None,
            created_at=existing["created_at"] if existing else None,
        )
        validate_voice_profile(profile)
        return profile

    def save_voice_profile_from_form(self) -> None:
        try:
            profile = self.collect_voice_profile_form()
        except ValueError as exc:
            self.profile_status_label.setText("Error.")
            self.show_error("Voice Profiles", str(exc))
            return

        updated = False
        for index, existing in enumerate(self.voice_profiles):
            if existing["id"] == profile["id"]:
                self.voice_profiles[index] = profile
                updated = True
                break
        if not updated:
            self.voice_profiles.append(profile)
        save_voice_profiles(self.voice_profiles)
        self.sync_modeling_datasets_with_profiles()
        self.selected_voice_profile_id = profile["id"]
        self.profile_status_label.setText(voice_profile_status(profile))
        self.refresh_voice_profiles_list()
        self.refresh_local_voice_profile_combo(profile["id"])
        self.profile_status_label.setText(f"Saved: {profile['name']} | {voice_profile_status(profile)}")
        self.update_local_voice_tabs()

    def delete_selected_voice_profile(self) -> None:
        if self.voice_profile_is_recording():
            return
        profile = self.selected_voice_profile()
        if not profile:
            return
        self.voice_profiles = [entry for entry in self.voice_profiles if entry["id"] != profile["id"]]
        save_voice_profiles(self.voice_profiles)
        self.sync_modeling_datasets_with_profiles()
        deleted_paths, failed_paths = delete_voice_profile_audio_files(profile)
        self.new_voice_profile()
        self.refresh_voice_profiles_list()
        self.refresh_local_voice_profile_combo()
        self.update_local_voice_tabs()
        if failed_paths:
            self.profile_status_label.setText(
                f"Deleted profile. Could not delete {len(failed_paths)} linked audio file(s)."
            )
        elif deleted_paths:
            self.profile_status_label.setText(f"Deleted profile and {len(deleted_paths)} linked audio file(s).")
        else:
            self.profile_status_label.setText("Deleted profile.")

    def open_voice_profile_reference(self) -> None:
        path = self.profile_reference_picker.text()
        open_path(path)

    def open_voice_profile_reference_folder(self) -> None:
        path = self.profile_reference_picker.text()
        if path and Path(path).is_file():
            open_path(Path(path).parent)

    def update_voice_profile_buttons(self) -> None:
        if not hasattr(self, "profile_save_button"):
            return
        reference_path = self.profile_reference_picker.text()
        has_reference = bool(reference_path and Path(reference_path).is_file())
        has_selection = bool(self.selected_voice_profile())
        is_recording = self.voice_profile_is_recording()
        is_modeling_profile = self.voice_profile_type() == VOICE_PROFILE_MODELING
        self.voice_profiles_list.setEnabled(not is_recording)
        self.profile_type_combo.setEnabled(not has_selection and not is_recording)
        self.profile_new_button.setEnabled(not is_recording)
        self.profile_delete_button.setEnabled(has_selection and not is_recording)
        self.profile_save_button.setEnabled(not is_recording)
        self.profile_reference_picker.setEnabled(not is_recording and not is_modeling_profile)
        self.profile_open_reference_button.setEnabled(has_reference and not is_recording and not is_modeling_profile)
        self.profile_open_folder_button.setEnabled(has_reference and not is_recording and not is_modeling_profile)
        if hasattr(self, "profile_record_button"):
            self.profile_microphone_combo.setEnabled(not is_recording and not is_modeling_profile)
            self.profile_record_button.setEnabled(
                not is_recording and not is_modeling_profile and self.profile_microphone_combo.count() > 0
            )
            self.profile_play_button.setEnabled(has_reference and not is_recording and not is_modeling_profile)

    def build_voice_profiles_page(self, include_header: bool = True):
        page, layout = self.page_container()
        if not include_header:
            layout.setContentsMargins(0, 26, 0, 24)
        if include_header:
            self.page_header(
                layout,
                "Voice Profiles",
                "Manage local reference voices for future Local TTS generation.",
            )

        grid = QGridLayout()
        grid.setSpacing(16)
        layout.addLayout(grid)

        profiles_card = Card("Profiles")
        profiles_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.voice_profiles_list = QListWidget()
        self.voice_profiles_list.setMinimumHeight(360)
        self.voice_profiles_list.currentRowChanged.connect(lambda _row: self.voice_profile_selection_changed())
        profile_list_actions = QHBoxLayout()
        profile_list_actions.setContentsMargins(0, 0, 0, 0)
        self.profile_new_button = QPushButton("New")
        self.profile_delete_button = QPushButton("Delete")
        self.profile_new_button.clicked.connect(self.new_voice_profile)
        self.profile_delete_button.clicked.connect(self.delete_selected_voice_profile)
        profile_list_actions.addWidget(self.profile_new_button)
        profile_list_actions.addWidget(self.profile_delete_button)
        profile_list_actions.addStretch(1)
        profiles_card.content_layout.addWidget(self.voice_profiles_list)
        profiles_card.content_layout.addLayout(profile_list_actions)

        editor_card = Card("Profile editor")
        editor_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.profile_name_edit = QLineEdit()
        self.profile_name_edit.setMinimumHeight(34)
        self.profile_type_combo = QComboBox()
        for label, profile_type in VOICE_PROFILE_TYPES.items():
            self.profile_type_combo.addItem(label, profile_type)
        self.profile_type_combo.currentIndexChanged.connect(lambda _index: self.voice_profile_type_changed())
        self.profile_language_combo = QComboBox()
        for language_code in VOICE_PROFILE_LANGUAGES:
            self.profile_language_combo.addItem(language_name(language_code), language_code)
        self.profile_reference_picker = FilePicker("Reference audio")
        self.profile_reference_picker.button.clicked.connect(self.select_voice_profile_reference)
        self.profile_reference_picker.edit.textChanged.connect(lambda _text: self.update_voice_profile_buttons())
        self.profile_microphone_combo = QComboBox()
        self.profile_record_button = QPushButton("Record")
        self.profile_play_button = QPushButton("Play")
        self.profile_record_button.clicked.connect(self.start_voice_profile_recording)
        self.profile_play_button.clicked.connect(self.play_voice_profile_reference)
        self.profile_record_status_label = QLabel("Record a guided 30s voice sample for the selected profile.")
        self.profile_record_status_label.setObjectName("Muted")
        self.profile_record_status_label.setWordWrap(True)
        self.profile_audio_output = QAudioOutput(self)
        self.profile_media_player = QMediaPlayer(self)
        self.profile_media_player.setAudioOutput(self.profile_audio_output)
        self.profile_consent_check = QCheckBox("Voice owner consent confirmed")
        self.profile_notes_edit = QPlainTextEdit()
        self.profile_notes_edit.setMinimumHeight(90)
        self.profile_notes_edit.setPlaceholderText("Notes")
        self.profile_status_label = QLabel("New profile.")
        self.profile_status_label.setObjectName("StatusText")

        editor_card.content_layout.addWidget(QLabel("Name"))
        editor_card.content_layout.addWidget(self.profile_name_edit)
        editor_row = QHBoxLayout()
        editor_row.setContentsMargins(0, 0, 0, 0)
        editor_row.addWidget(QLabel("Type"))
        editor_row.addWidget(self.profile_type_combo)
        editor_row.addWidget(QLabel("Language"))
        editor_row.addWidget(self.profile_language_combo, 1)
        editor_card.content_layout.addLayout(editor_row)
        editor_card.content_layout.addWidget(self.profile_reference_picker)
        recorder_row = QHBoxLayout()
        recorder_row.setContentsMargins(0, 0, 0, 0)
        recorder_row.addWidget(QLabel("Microphone"))
        recorder_row.addWidget(self.profile_microphone_combo, 1)
        recorder_row.addWidget(self.profile_record_button)
        recorder_row.addWidget(self.profile_play_button)
        editor_card.content_layout.addLayout(recorder_row)
        editor_card.content_layout.addWidget(self.profile_record_status_label)
        editor_card.content_layout.addWidget(self.profile_consent_check)
        editor_card.content_layout.addWidget(self.profile_notes_edit)

        editor_actions = QHBoxLayout()
        editor_actions.setContentsMargins(0, 0, 0, 0)
        self.profile_save_button = QPushButton("Save profile")
        self.profile_save_button.setObjectName("PrimaryButton")
        self.profile_open_reference_button = QPushButton("Open audio")
        self.profile_open_folder_button = QPushButton("Open folder")
        self.profile_save_button.clicked.connect(self.save_voice_profile_from_form)
        self.profile_open_reference_button.clicked.connect(self.open_voice_profile_reference)
        self.profile_open_folder_button.clicked.connect(self.open_voice_profile_reference_folder)
        editor_actions.addWidget(self.profile_save_button)
        editor_actions.addStretch(1)
        editor_actions.addWidget(self.profile_open_reference_button)
        editor_actions.addWidget(self.profile_open_folder_button)
        editor_card.content_layout.addLayout(editor_actions)
        editor_card.content_layout.addWidget(self.profile_status_label)

        grid.addWidget(profiles_card, 0, 0)
        grid.addWidget(editor_card, 0, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 2)
        layout.addStretch(1)

        self.new_voice_profile()
        self.refresh_voice_profiles_list()
        self.refresh_voice_profile_microphones()
        return page
