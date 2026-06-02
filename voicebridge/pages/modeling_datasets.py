from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import Qt, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
)

from voicebridge.audio_recorder import AudioRecorderError, list_input_devices
from voicebridge.modeling_clip_recording_dialog import ModelingClipRecordingDialog
from voicebridge.modeling_datasets import (
    MODELING_CLIP_FREE_RECORDING,
    MODELING_CLIP_TEXT_GUIDED,
    ModelingClip,
    ModelingDataset,
    build_modeling_clip,
    delete_modeling_clip_files,
    ensure_modeling_datasets_for_profiles,
    export_modeling_dataset,
    load_modeling_datasets,
    modeling_clip_audio_path,
    modeling_clip_status_label,
    modeling_dataset_dir,
    modeling_dataset_exportable,
    modeling_dataset_summary_text,
    save_modeling_datasets,
    update_modeling_clip_transcript,
    write_modeling_clip_transcript,
)
from voicebridge.ui.helpers import open_path
from voicebridge.ui.widgets import Card
from voicebridge.voice_profiles import VOICE_PROFILE_MODELING

MODELING_GUIDED_TEXT_MAX_CHARS = 450
MODELING_RECORD_MAX_SECONDS = 60


# noinspection PyAttributeOutsideInit,PyUnresolvedReferences,PyTypeChecker,PyShadowingNames
class ModelingDatasetsWorkflowMixin:
    def load_modeling_dataset_store(self) -> None:
        self.modeling_datasets = load_modeling_datasets()
        self.selected_modeling_dataset_id = ""
        self.selected_modeling_clip_id = ""
        self.sync_modeling_datasets_with_profiles(save=False)

    def sync_modeling_datasets_with_profiles(self, *, save: bool = True) -> None:
        datasets, changed = ensure_modeling_datasets_for_profiles(self.modeling_datasets, self.voice_profiles)
        self.modeling_datasets = datasets
        if changed and save:
            save_modeling_datasets(self.modeling_datasets)
        if hasattr(self, "modeling_datasets_list"):
            self.refresh_modeling_datasets_page()
        self.update_local_voice_tabs()

    def selected_modeling_dataset(self) -> ModelingDataset | None:
        dataset_id = getattr(self, "selected_modeling_dataset_id", "")
        return next((dataset for dataset in self.modeling_datasets if dataset["id"] == dataset_id), None)

    def selected_modeling_clip(self) -> ModelingClip | None:
        dataset = self.selected_modeling_dataset()
        if not dataset:
            return None
        clip_id = getattr(self, "selected_modeling_clip_id", "")
        return next((clip for clip in dataset["clips"] if clip["id"] == clip_id), None)

    def refresh_modeling_datasets_page(self) -> None:
        self.refresh_modeling_datasets_list()
        self.update_modeling_dataset_summary()
        self.refresh_modeling_clips_list()
        self.update_modeling_dataset_buttons()

    def refresh_modeling_datasets_list(self) -> None:
        if not hasattr(self, "modeling_datasets_list"):
            return
        self.modeling_datasets_list.blockSignals(True)
        try:
            self.modeling_datasets_list.clear()
            modeling_profile_ids = {
                profile["id"] for profile in self.voice_profiles
                if profile.get("profile_type") == VOICE_PROFILE_MODELING
            }
            visible_datasets = [
                dataset for dataset in self.modeling_datasets
                if dataset["profile_id"] in modeling_profile_ids
            ]
            if not visible_datasets:
                self.modeling_datasets_list.addItem("No modeling datasets yet.")
                self.selected_modeling_dataset_id = ""
                return
            if not any(dataset["id"] == self.selected_modeling_dataset_id for dataset in visible_datasets):
                self.selected_modeling_dataset_id = visible_datasets[0]["id"]
            for dataset in sorted(visible_datasets, key=lambda dataset_item: dataset_item["name"].casefold()):
                ready_count = sum(1 for clip in dataset["clips"] if clip["status"] == "ready")
                item = QListWidgetItem(f"{dataset['name']} | {len(dataset['clips'])} clip(s), {ready_count} ready")
                item.setData(Qt.ItemDataRole.UserRole, dataset["id"])
                self.modeling_datasets_list.addItem(item)
                if dataset["id"] == self.selected_modeling_dataset_id:
                    self.modeling_datasets_list.setCurrentItem(item)
        finally:
            self.modeling_datasets_list.blockSignals(False)

    def modeling_dataset_selection_changed(self) -> None:
        item = self.modeling_datasets_list.currentItem()
        dataset_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        self.selected_modeling_dataset_id = dataset_id if isinstance(dataset_id, str) else ""
        self.selected_modeling_clip_id = ""
        self.update_modeling_dataset_summary()
        self.refresh_modeling_clips_list()
        self.update_modeling_dataset_buttons()

    def update_modeling_dataset_summary(self) -> None:
        if not hasattr(self, "modeling_dataset_summary_box"):
            return
        dataset = self.selected_modeling_dataset()
        if not dataset:
            self.modeling_dataset_summary_box.setPlainText("Create or select a modeling dataset.")
            return
        self.modeling_dataset_summary_box.setPlainText(modeling_dataset_summary_text(dataset))

    def refresh_modeling_clips_list(self) -> None:
        if not hasattr(self, "modeling_clips_list"):
            return
        dataset = self.selected_modeling_dataset()
        self.modeling_clips_list.blockSignals(True)
        try:
            self.modeling_clips_list.clear()
            if not dataset:
                self.modeling_clips_list.addItem("Select a modeling dataset.")
                self.modeling_clip_text_edit.clear()
                self.modeling_clip_details.setPlainText("")
                return
            if not dataset["clips"]:
                self.modeling_clips_list.addItem("No clips yet.")
                self.selected_modeling_clip_id = ""
                self.modeling_clip_text_edit.clear()
                self.modeling_clip_details.setPlainText("")
                return
            if not any(clip["id"] == self.selected_modeling_clip_id for clip in dataset["clips"]):
                self.selected_modeling_clip_id = dataset["clips"][0]["id"]
            for index, clip in enumerate(dataset["clips"], start=1):
                mode = "Text" if clip["mode"] == MODELING_CLIP_TEXT_GUIDED else "Free"
                label = (
                    f"C. {index} | {modeling_clip_status_label(clip['status'])} | "
                    f"{clip['duration_seconds']:.1f}s | {mode}"
                )
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, clip["id"])
                self.modeling_clips_list.addItem(item)
                if clip["id"] == self.selected_modeling_clip_id:
                    self.modeling_clips_list.setCurrentItem(item)
        finally:
            self.modeling_clips_list.blockSignals(False)
        self.populate_modeling_clip_editor()

    def modeling_clip_selection_changed(self) -> None:
        item = self.modeling_clips_list.currentItem()
        clip_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        self.selected_modeling_clip_id = clip_id if isinstance(clip_id, str) else ""
        self.populate_modeling_clip_editor()
        self.update_modeling_dataset_buttons()

    def populate_modeling_clip_editor(self) -> None:
        if not hasattr(self, "modeling_clip_text_edit"):
            return
        dataset = self.selected_modeling_dataset()
        clip = self.selected_modeling_clip()
        if not dataset:
            self.modeling_dataset_status.setText("Create a Voice Profile with type Modeling dataset first.")
            self.modeling_clip_text_edit.clear()
            self.modeling_clip_details.setPlainText("")
            return
        if not clip:
            self.modeling_dataset_status.setText(f"Dataset: {dataset['name']} | {len(dataset['clips'])} clip(s).")
            self.modeling_clip_text_edit.clear()
            self.modeling_clip_details.setPlainText("")
            return
        self.modeling_dataset_status.setText(
            f"Selected {dataset['name']} | {modeling_clip_status_label(clip['status'])}."
        )
        self.modeling_clip_text_edit.setPlainText(clip.get("transcript_text", ""))
        self.modeling_clip_details.setPlainText(clip.get("quality_details", ""))
        self.update_modeling_text_counter()

    def selected_modeling_audio_device(self) -> int | None:
        try:
            devices = list_input_devices()
        except AudioRecorderError as exc:
            self.show_error("Modeling Datasets", str(exc))
            return None
        if not devices:
            self.show_error("Modeling Datasets", "No microphone input was detected.")
            return None
        default_device = next((device for device in devices if device.is_default), devices[0])
        return default_device.index

    def load_modeling_clip_text_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select clip text",
            str(Path.home()),
            "Text files (*.txt *.md);;All files (*.*)",
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8").strip()
        except OSError as exc:
            self.show_error("Modeling Datasets", str(exc))
            return
        if len(text) > MODELING_GUIDED_TEXT_MAX_CHARS:
            self.show_error(
                "Modeling Datasets",
                (
                    f"The selected text is {len(text)} characters. "
                    f"Use up to {MODELING_GUIDED_TEXT_MAX_CHARS} characters for one guided clip."
                ),
            )
            return
        self.modeling_clip_text_edit.setPlainText(text)
        self.modeling_dataset_status.setText(f"Loaded text: {Path(path).name}")

    def record_modeling_clip_from_text(self) -> None:
        dataset = self.selected_modeling_dataset()
        if not dataset:
            self.show_error("Modeling Datasets", "Select a modeling dataset first.")
            return
        text = self.modeling_clip_text_edit.toPlainText().strip()
        if not text:
            self.show_error("Modeling Datasets", "Load or paste the text to read before recording.")
            return
        if len(text) > MODELING_GUIDED_TEXT_MAX_CHARS:
            self.show_error(
                "Modeling Datasets",
                f"Guided clips support up to {MODELING_GUIDED_TEXT_MAX_CHARS} characters. Split this text first.",
            )
            return
        self.record_modeling_clip(dataset, mode=MODELING_CLIP_TEXT_GUIDED, transcript_text=text)

    def record_free_modeling_clip(self) -> None:
        dataset = self.selected_modeling_dataset()
        if not dataset:
            self.show_error("Modeling Datasets", "Select a modeling dataset first.")
            return
        self.record_modeling_clip(dataset, mode=MODELING_CLIP_FREE_RECORDING, transcript_text="")

    def record_modeling_clip(self, dataset: ModelingDataset, *, mode: str, transcript_text: str) -> None:
        device_index = self.selected_modeling_audio_device()
        if device_index is None:
            return
        clip_id = uuid4().hex
        audio_path = modeling_clip_audio_path(dataset, clip_id)
        title = "Record from text" if mode == MODELING_CLIP_TEXT_GUIDED else "Free recording"
        dialog = ModelingClipRecordingDialog(
            title=title,
            output_path=audio_path,
            device_index=device_index,
            prompt_text=transcript_text if mode == MODELING_CLIP_TEXT_GUIDED else "",
            max_seconds=MODELING_RECORD_MAX_SECONDS,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.recording_path is None:
            self.modeling_dataset_status.setText("Recording cancelled.")
            return
        clip = build_modeling_clip(
            dataset,
            mode=mode,
            audio_path=dialog.recording_path,
            transcript_text=transcript_text,
            transcript_source="provided_text" if transcript_text else "",
            duration_seconds=dialog.duration_seconds,
            quality_details=dialog.quality_details,
            clip_id=clip_id,
        )
        write_modeling_clip_transcript(clip)
        dataset["clips"].append(clip)
        dataset["updated_at"] = clip["updated_at"]
        save_modeling_datasets(self.modeling_datasets)
        self.selected_modeling_clip_id = clip["id"]
        self.refresh_modeling_datasets_page()
        self.modeling_dataset_status.setText(f"Saved clip: {modeling_clip_status_label(clip['status'])}.")

    def save_modeling_clip_transcript_from_editor(self) -> None:
        dataset = self.selected_modeling_dataset()
        clip = self.selected_modeling_clip()
        if not dataset or not clip:
            return
        updated_clip = update_modeling_clip_transcript(clip, self.modeling_clip_text_edit.toPlainText())
        for index, existing in enumerate(dataset["clips"]):
            if existing["id"] == clip["id"]:
                dataset["clips"][index] = updated_clip
                break
        dataset["updated_at"] = updated_clip["updated_at"]
        write_modeling_clip_transcript(updated_clip)
        save_modeling_datasets(self.modeling_datasets)
        self.selected_modeling_clip_id = updated_clip["id"]
        self.refresh_modeling_datasets_page()
        self.modeling_dataset_status.setText("Transcript saved.")

    def update_modeling_text_counter(self) -> None:
        if not hasattr(self, "modeling_clip_text_counter"):
            return
        character_count = len(self.modeling_clip_text_edit.toPlainText().strip())
        remaining = MODELING_GUIDED_TEXT_MAX_CHARS - character_count
        if remaining < 0:
            self.modeling_clip_text_counter.setText(
                f"{character_count}/{MODELING_GUIDED_TEXT_MAX_CHARS} characters | split into more clips"
            )
            self.modeling_clip_text_counter.setStyleSheet("color: #b42318;")
        else:
            self.modeling_clip_text_counter.setText(
                f"{character_count}/{MODELING_GUIDED_TEXT_MAX_CHARS} characters for guided recording"
            )
            self.modeling_clip_text_counter.setStyleSheet("color: #617083;")
        self.update_modeling_dataset_buttons()

    def delete_selected_modeling_clip(self) -> None:
        dataset = self.selected_modeling_dataset()
        clip = self.selected_modeling_clip()
        if not dataset or not clip:
            return
        dataset["clips"] = [entry for entry in dataset["clips"] if entry["id"] != clip["id"]]
        delete_modeling_clip_files(clip)
        save_modeling_datasets(self.modeling_datasets)
        self.selected_modeling_clip_id = ""
        self.refresh_modeling_datasets_page()
        self.modeling_dataset_status.setText("Clip deleted.")

    def play_selected_modeling_clip(self) -> None:
        clip = self.selected_modeling_clip()
        if not clip or not Path(clip["audio_path"]).is_file():
            return
        if self.modeling_clip_media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.modeling_clip_media_player.stop()
            return
        self.modeling_clip_media_player.setSource(QUrl.fromLocalFile(str(Path(clip["audio_path"]).resolve())))
        self.modeling_clip_media_player.play()

    def open_selected_modeling_clip(self) -> None:
        clip = self.selected_modeling_clip()
        if clip and Path(clip["audio_path"]).is_file():
            open_path(clip["audio_path"])

    def open_selected_modeling_dataset_folder(self) -> None:
        dataset = self.selected_modeling_dataset()
        if dataset:
            modeling_dataset_dir(dataset).mkdir(parents=True, exist_ok=True)
            open_path(modeling_dataset_dir(dataset))

    def export_selected_modeling_dataset(self) -> None:
        dataset = self.selected_modeling_dataset()
        if not dataset:
            self.show_error("Modeling Datasets", "Select a modeling dataset first.")
            return
        try:
            result = export_modeling_dataset(dataset)
        except (OSError, ValueError) as exc:
            self.show_error("Modeling Datasets", str(exc))
            return
        export_dir = result["export_dir"]
        self.modeling_dataset_status.setText(
            f"Exported {result['exported_clips']} ready clip(s) to {export_dir}."
        )
        self.refresh_voice_modeling_exports(export_dir)
        self.update_local_voice_tabs()
        self.show_info("Modeling Datasets", f"Dataset exported:\n{export_dir}")
        open_path(export_dir)

    def send_modeling_clip_to_transcription(self) -> None:
        clip = self.selected_modeling_clip()
        if not clip or not Path(clip["audio_path"]).is_file():
            return
        self.stt_media_picker.set_text(clip["audio_path"])
        output_path = str(Path(clip["audio_path"]).with_suffix(".md"))
        self.stt_output_picker.set_text(output_path)
        self.show_page(3)

    def update_modeling_dataset_buttons(self) -> None:
        if not hasattr(self, "modeling_record_text_button"):
            return
        dataset = self.selected_modeling_dataset()
        clip = self.selected_modeling_clip()
        has_dataset = dataset is not None
        has_clip_audio = bool(clip and Path(clip["audio_path"]).is_file())
        has_exportable_clips = bool(dataset and modeling_dataset_exportable(dataset))
        text_length = len(self.modeling_clip_text_edit.toPlainText().strip())
        can_record_from_text = has_dataset and 0 < text_length <= MODELING_GUIDED_TEXT_MAX_CHARS
        self.modeling_record_text_button.setEnabled(can_record_from_text)
        self.modeling_record_free_button.setEnabled(has_dataset)
        self.modeling_load_text_button.setEnabled(has_dataset)
        self.modeling_save_text_button.setEnabled(clip is not None)
        self.modeling_delete_clip_button.setEnabled(clip is not None)
        self.modeling_play_clip_button.setEnabled(has_clip_audio)
        self.modeling_open_clip_button.setEnabled(has_clip_audio)
        self.modeling_transcribe_clip_button.setEnabled(has_clip_audio)
        self.modeling_open_dataset_folder_button.setEnabled(has_dataset)
        self.modeling_export_dataset_button.setEnabled(has_exportable_clips)

    def build_modeling_datasets_page(self, include_header: bool = True):
        page, layout = self.page_container()
        if not include_header:
            layout.setContentsMargins(0, 26, 0, 24)
        if include_header:
            self.page_header(
                layout,
                "Modeling Datasets",
                "Collect authorized audio clips and exact text pairs before future voice model training.",
            )

        grid = QGridLayout()
        grid.setSpacing(16)
        layout.addLayout(grid)

        datasets_card = Card("Datasets")
        datasets_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.modeling_datasets_list = QListWidget()
        self.modeling_datasets_list.setMinimumHeight(220)
        self.modeling_datasets_list.currentRowChanged.connect(lambda _row: self.modeling_dataset_selection_changed())
        self.modeling_dataset_summary_box = QPlainTextEdit()
        self.modeling_dataset_summary_box.setObjectName("LogBox")
        self.modeling_dataset_summary_box.setReadOnly(True)
        self.modeling_dataset_summary_box.setMinimumHeight(150)
        self.modeling_dataset_summary_box.setPlaceholderText("Dataset readiness summary appears here.")
        dataset_actions = QHBoxLayout()
        dataset_actions.setContentsMargins(0, 0, 0, 0)
        self.modeling_refresh_button = QPushButton("Refresh")
        self.modeling_export_dataset_button = QPushButton("Export dataset")
        self.modeling_open_dataset_folder_button = QPushButton("Open folder")
        self.modeling_refresh_button.clicked.connect(self.sync_modeling_datasets_with_profiles)
        self.modeling_export_dataset_button.clicked.connect(self.export_selected_modeling_dataset)
        self.modeling_open_dataset_folder_button.clicked.connect(self.open_selected_modeling_dataset_folder)
        dataset_actions.addWidget(self.modeling_refresh_button)
        dataset_actions.addWidget(self.modeling_export_dataset_button)
        dataset_actions.addWidget(self.modeling_open_dataset_folder_button)
        datasets_card.content_layout.addWidget(self.modeling_datasets_list)
        datasets_card.content_layout.addWidget(self.modeling_dataset_summary_box)
        datasets_card.content_layout.addLayout(dataset_actions)

        clips_card = Card("Clips")
        clips_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.modeling_clips_list = QListWidget()
        self.modeling_clips_list.setMinimumHeight(220)
        self.modeling_clips_list.currentRowChanged.connect(lambda _row: self.modeling_clip_selection_changed())
        clip_actions = QHBoxLayout()
        clip_actions.setContentsMargins(0, 0, 0, 0)
        self.modeling_play_clip_button = QPushButton("Play")
        self.modeling_open_clip_button = QPushButton("Open audio")
        self.modeling_delete_clip_button = QPushButton("Delete clip")
        self.modeling_transcribe_clip_button = QPushButton("Open in Transcription")
        self.modeling_play_clip_button.clicked.connect(self.play_selected_modeling_clip)
        self.modeling_open_clip_button.clicked.connect(self.open_selected_modeling_clip)
        self.modeling_delete_clip_button.clicked.connect(self.delete_selected_modeling_clip)
        self.modeling_transcribe_clip_button.clicked.connect(self.send_modeling_clip_to_transcription)
        clip_actions.addWidget(self.modeling_play_clip_button)
        clip_actions.addWidget(self.modeling_open_clip_button)
        clip_actions.addWidget(self.modeling_transcribe_clip_button)
        clip_actions.addStretch(1)
        clip_actions.addWidget(self.modeling_delete_clip_button)
        clips_card.content_layout.addWidget(self.modeling_clips_list)
        clips_card.content_layout.addLayout(clip_actions)

        editor_card = Card("Clip text")
        editor_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.modeling_clip_text_edit = QPlainTextEdit()
        self.modeling_clip_text_edit.setMinimumHeight(220)
        self.modeling_clip_text_edit.setPlaceholderText(
            f"Paste or load the exact text read in this clip. Max {MODELING_GUIDED_TEXT_MAX_CHARS} characters."
        )
        self.modeling_clip_text_edit.textChanged.connect(self.update_modeling_text_counter)
        self.modeling_clip_text_counter = QLabel(
            f"0/{MODELING_GUIDED_TEXT_MAX_CHARS} characters for guided recording"
        )
        self.modeling_clip_text_counter.setObjectName("Muted")
        self.modeling_clip_details = QPlainTextEdit()
        self.modeling_clip_details.setObjectName("LogBox")
        self.modeling_clip_details.setReadOnly(True)
        self.modeling_clip_details.setMinimumHeight(120)
        self.modeling_clip_details.setPlaceholderText("Recording quality details appear here after a clip is saved.")
        text_actions = QHBoxLayout()
        text_actions.setContentsMargins(0, 0, 0, 0)
        self.modeling_load_text_button = QPushButton("Load text")
        self.modeling_record_text_button = QPushButton("Record from text")
        self.modeling_record_text_button.setObjectName("PrimaryButton")
        self.modeling_record_free_button = QPushButton("Free record")
        self.modeling_save_text_button = QPushButton("Save transcript")
        self.modeling_load_text_button.clicked.connect(self.load_modeling_clip_text_file)
        self.modeling_record_text_button.clicked.connect(self.record_modeling_clip_from_text)
        self.modeling_record_free_button.clicked.connect(self.record_free_modeling_clip)
        self.modeling_save_text_button.clicked.connect(self.save_modeling_clip_transcript_from_editor)
        text_actions.addWidget(self.modeling_load_text_button)
        text_actions.addWidget(self.modeling_record_text_button)
        text_actions.addWidget(self.modeling_record_free_button)
        text_actions.addStretch(1)
        text_actions.addWidget(self.modeling_save_text_button)
        self.modeling_dataset_status = QLabel("Ready.")
        self.modeling_dataset_status.setObjectName("StatusText")
        editor_card.content_layout.addWidget(self.modeling_clip_text_edit)
        editor_card.content_layout.addWidget(self.modeling_clip_text_counter)
        editor_card.content_layout.addLayout(text_actions)
        editor_card.content_layout.addWidget(self.modeling_clip_details)
        editor_card.content_layout.addWidget(self.modeling_dataset_status)

        grid.addWidget(datasets_card, 0, 0)
        grid.addWidget(clips_card, 1, 0)
        grid.addWidget(editor_card, 0, 1, 2, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 2)

        self.modeling_clip_audio_output = QAudioOutput(self)
        self.modeling_clip_media_player = QMediaPlayer(self)
        self.modeling_clip_media_player.setAudioOutput(self.modeling_clip_audio_output)
        self.refresh_modeling_datasets_page()
        layout.addStretch(1)
        return page
