import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
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
    SoundDevicePcmRecorder,
    list_input_devices,
    select_input_settings,
)
from voicebridge.languages import language_name
from voicebridge.ui.helpers import open_path
from voicebridge.ui.widgets import Card, FilePicker
from voicebridge.voice_profiles import (
    VOICE_PROFILE_AUDIO_SUFFIXES,
    VOICE_PROFILE_LANGUAGES,
    VOICE_PROFILE_REFERENCE,
    VOICE_PROFILE_TYPES,
    VoiceProfile,
    build_voice_profile,
    load_voice_profiles,
    save_voice_profiles,
    validate_voice_profile,
    voice_profile_recording_path,
    voice_profile_status,
)
from voicebridge.wav_writer import prepare_voice_reference_pcm, trim_pcm16_to_frames, write_pcm16_wav

VOICE_PROFILE_RECORD_SAMPLE_RATE = 24_000
VOICE_PROFILE_RECORD_CHANNELS = 1
VOICE_PROFILE_RECORD_MIN_SECONDS = 6
VOICE_PROFILE_RECORD_TARGET_SECONDS = 10
VOICE_PROFILE_RECORD_MAX_SECONDS = 30


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
        for profile in sorted(self.voice_profiles, key=lambda item: item["name"].casefold()):
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
        self.profile_record_status_label.setText("Record 10-30s of clean speech for the selected profile.")
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
        try:
            settings = select_input_settings(
                device,
                preferred_sample_rate=VOICE_PROFILE_RECORD_SAMPLE_RATE,
                channel_count=VOICE_PROFILE_RECORD_CHANNELS,
            )
            recorder = SoundDevicePcmRecorder(device, settings)
            recorder.start()
        except AudioRecorderError as exc:
            self.show_error("Voice Profiles", str(exc))
            return

        self.profile_record_format = settings
        self.profile_record_path = voice_profile_recording_path(self.profile_name_edit.text())
        self.profile_record_started_at = time.monotonic()
        self.profile_record_source = recorder
        self.profile_record_timer.start(200)
        self.profile_record_status_label.setText("Recording... 00:00 / 00:30")
        self.update_voice_profile_buttons()

    def voice_profile_is_recording(self) -> bool:
        return getattr(self, "profile_record_source", None) is not None

    def voice_profile_recording_seconds(self) -> float:
        if not self.voice_profile_is_recording():
            return 0.0
        return max(0.0, time.monotonic() - getattr(self, "profile_record_started_at", time.monotonic()))

    @staticmethod
    def voice_profile_duration_label(seconds: float) -> str:
        seconds = max(0, int(seconds))
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def update_voice_profile_recording_timer(self) -> None:
        elapsed = self.voice_profile_recording_seconds()
        self.profile_record_status_label.setText(
            f"Recording... {self.voice_profile_duration_label(elapsed)} / 00:30"
        )
        if elapsed >= VOICE_PROFILE_RECORD_MAX_SECONDS:
            self.stop_voice_profile_recording(auto_stopped=True)

    def stop_voice_profile_recording(self, auto_stopped: bool = False) -> None:
        if not self.voice_profile_is_recording():
            return
        recorder = self.profile_record_source
        self.profile_record_timer.stop()
        self.profile_record_source = None
        try:
            recorder.stop()
        except AudioRecorderError as exc:
            self.profile_record_status_label.setText("Recording failed.")
            self.show_error("Voice Profiles", str(exc))
            self.update_voice_profile_buttons()
            return

        settings = self.profile_record_format
        sample_rate = settings.sample_rate
        channel_count = settings.channel_count
        pcm_data = trim_pcm16_to_frames(recorder.read_pcm(), channel_count)
        recording = prepare_voice_reference_pcm(pcm_data, sample_rate, channel_count)
        duration = recording.duration_seconds
        try:
            if duration < 1:
                reason = " ".join(recording.messages) or "Recording is too short."
                raise ValueError(reason)
            write_pcm16_wav(self.profile_record_path, recording.pcm_data, sample_rate, channel_count)
        except (OSError, ValueError) as exc:
            self.profile_record_status_label.setText("Recording failed.")
            self.show_error("Voice Profiles", str(exc))
            self.update_voice_profile_buttons()
            return

        self.profile_reference_picker.set_text(str(self.profile_record_path))
        recorder_messages = recorder.status_messages
        cleanup_messages = (*recording.messages, *recorder_messages)
        cleanup_message = f" {' '.join(cleanup_messages)}" if cleanup_messages else ""
        if duration < VOICE_PROFILE_RECORD_MIN_SECONDS:
            message = f"Recorded {duration:.1f}s. Use at least 10s for better cloning.{cleanup_message}"
        elif duration < VOICE_PROFILE_RECORD_TARGET_SECONDS:
            message = f"Recorded {duration:.1f}s. 10-30s is recommended.{cleanup_message}"
        elif auto_stopped:
            message = f"Recorded {duration:.1f}s. Maximum reference length reached.{cleanup_message}"
        else:
            message = f"Recorded {duration:.1f}s.{cleanup_message}"
        self.profile_record_status_label.setText(message)
        self.update_voice_profile_buttons()

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
            profile_type=self.voice_profile_type(),
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
        self.selected_voice_profile_id = profile["id"]
        self.profile_status_label.setText(voice_profile_status(profile))
        self.refresh_voice_profiles_list()
        self.refresh_local_voice_profile_combo(profile["id"])
        self.profile_status_label.setText(f"Saved: {profile['name']} | {voice_profile_status(profile)}")

    def delete_selected_voice_profile(self) -> None:
        if self.voice_profile_is_recording():
            return
        profile = self.selected_voice_profile()
        if not profile:
            return
        self.voice_profiles = [entry for entry in self.voice_profiles if entry["id"] != profile["id"]]
        save_voice_profiles(self.voice_profiles)
        self.new_voice_profile()
        self.refresh_voice_profiles_list()
        self.refresh_local_voice_profile_combo()

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
        self.voice_profiles_list.setEnabled(not is_recording)
        self.profile_new_button.setEnabled(not is_recording)
        self.profile_delete_button.setEnabled(has_selection and not is_recording)
        self.profile_save_button.setEnabled(not is_recording)
        self.profile_open_reference_button.setEnabled(has_reference and not is_recording)
        self.profile_open_folder_button.setEnabled(has_reference and not is_recording)
        if hasattr(self, "profile_record_button"):
            self.profile_record_button.setEnabled(not is_recording and self.profile_microphone_combo.count() > 0)
            self.profile_stop_record_button.setEnabled(is_recording)
            self.profile_play_button.setEnabled(has_reference and not is_recording)

    def build_voice_profiles_page(self):
        page, layout = self.page_container()
        self.page_header(
            layout,
            "PROFILES",
            "Voice Profiles",
            "Manage local reference voices for future Local TTS generation.",
            "BadgeGreen",
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
        self.profile_language_combo = QComboBox()
        for language_code in VOICE_PROFILE_LANGUAGES:
            self.profile_language_combo.addItem(language_name(language_code), language_code)
        self.profile_reference_picker = FilePicker("Reference audio")
        self.profile_reference_picker.button.clicked.connect(self.select_voice_profile_reference)
        self.profile_reference_picker.edit.textChanged.connect(lambda _text: self.update_voice_profile_buttons())
        self.profile_microphone_combo = QComboBox()
        self.profile_record_button = QPushButton("Record")
        self.profile_stop_record_button = QPushButton("Stop")
        self.profile_play_button = QPushButton("Play")
        self.profile_record_button.clicked.connect(self.start_voice_profile_recording)
        self.profile_stop_record_button.clicked.connect(lambda _checked=False: self.stop_voice_profile_recording())
        self.profile_play_button.clicked.connect(self.play_voice_profile_reference)
        self.profile_record_status_label = QLabel("Record 10-30s of clean speech for the selected profile.")
        self.profile_record_status_label.setObjectName("Muted")
        self.profile_record_status_label.setWordWrap(True)
        self.profile_record_timer = QTimer(self)
        self.profile_record_timer.timeout.connect(self.update_voice_profile_recording_timer)
        self.profile_record_source = None
        self.profile_record_format = None
        self.profile_record_path = None
        self.profile_record_started_at = 0.0
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
        recorder_row.addWidget(self.profile_stop_record_button)
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
