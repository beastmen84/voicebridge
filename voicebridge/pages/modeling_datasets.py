import os
import subprocess
import tempfile
import threading
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import Qt, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QComboBox,
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
    QVBoxLayout,
)

from voicebridge.app_paths import (
    external_base_dir,
    stt_model_dir,
    stt_python_path,
    stt_whisper_model_ready,
    stt_worker_path,
)
from voicebridge.audio_recorder import AudioRecorderError, list_input_devices
from voicebridge.constants import STT_MODEL
from voicebridge.modeling_clip_recording_dialog import ModelingClipRecordingDialog
from voicebridge.modeling_datasets import (
    MODELING_CLIP_FREE_RECORDING,
    MODELING_CLIP_TEXT_GUIDED,
    MODELING_TARGET_READY_SECONDS,
    MODELING_VERIFICATION_ERROR,
    MODELING_VERIFICATION_MATCH_OK,
    MODELING_VERIFICATION_NEEDS_REVIEW,
    MODELING_VERIFICATION_PENDING,
    ModelingClip,
    ModelingDataset,
    ModelingDatasetSummary,
    add_modeling_dataset_guided_prompt_history,
    build_modeling_clip,
    delete_modeling_clip_files,
    ensure_modeling_datasets_for_profiles,
    export_modeling_dataset,
    format_modeling_dataset_duration,
    load_modeling_datasets,
    modeling_clip_audio_path,
    modeling_clip_can_verify_transcript,
    modeling_clip_export_block_reason,
    modeling_clip_status_label,
    modeling_clip_verification_label,
    modeling_clip_verification_status,
    modeling_dataset_dir,
    modeling_dataset_export_disabled_reason_from_summary,
    modeling_dataset_guided_prompt_texts,
    modeling_dataset_guided_prompt_usage,
    modeling_dataset_summary,
    modeling_dataset_summary_text,
    modeling_dataset_tier_label,
    recover_interrupted_modeling_verifications,
    reset_modeling_dataset_guided_prompt_history,
    save_modeling_datasets,
    toggle_modeling_clip_export_exclusion,
    update_modeling_clip_recording,
    update_modeling_clip_transcript,
    update_modeling_clip_verification,
    write_modeling_clip_transcript,
)
from voicebridge.modeling_prompt_generator import (
    MODELING_PROMPT_SOURCE_GENERATED,
    MODELING_PROMPT_SOURCE_PROVIDED,
    NoUnusedModelingPromptError,
    generate_modeling_prompt,
    generated_prompt_source,
    normalize_prompt_text,
)
from voicebridge.modeling_verification import compare_transcript_to_expected, read_whisper_markdown_text
from voicebridge.ui.helpers import open_path
from voicebridge.ui.widgets import Card
from voicebridge.voice_modeling import current_voice_modeling_export_for_dataset
from voicebridge.voice_profiles import VOICE_PROFILE_MODELING

MODELING_GUIDED_TEXT_MAX_CHARS = 200
MODELING_RECORD_MAX_SECONDS = 60


# noinspection PyAttributeOutsideInit,PyUnresolvedReferences,PyTypeChecker,PyShadowingNames
class ModelingDatasetsWorkflowMixin:
    def modeling_text(self, text: str, **kwargs) -> str:
        if kwargs and hasattr(self, "format_static_ui_text"):
            return self.format_static_ui_text(text, **kwargs)
        if kwargs:
            return text.format(**kwargs)
        return self.static_ui_text(text) if hasattr(self, "static_ui_text") else text

    def load_modeling_dataset_store(self) -> None:
        self.modeling_datasets = load_modeling_datasets()
        recovered_interrupted_verifications = recover_interrupted_modeling_verifications(self.modeling_datasets)
        self.selected_modeling_dataset_id = ""
        self.selected_modeling_clip_id = ""
        self.modeling_verification_queue = []
        self.modeling_verification_running = False
        self.modeling_verification_queued_clip_ids = set()
        self.sync_modeling_datasets_with_profiles(save=False)
        if recovered_interrupted_verifications:
            save_modeling_datasets(self.modeling_datasets)

    def sync_modeling_datasets_with_profiles(self, *, save: bool = True) -> None:
        datasets, changed = ensure_modeling_datasets_for_profiles(self.modeling_datasets, self.voice_profiles)
        self.modeling_datasets = datasets
        if changed and save:
            save_modeling_datasets(self.modeling_datasets)
        if hasattr(self, "modeling_dataset_summary_box"):
            self.refresh_modeling_datasets_page()
        self.update_local_voice_tabs()

    def modeling_voice_profiles(self) -> list[dict]:
        return [
            profile for profile in self.voice_profiles
            if profile.get("profile_type") == VOICE_PROFILE_MODELING
        ]

    def active_modeling_profile_id(self) -> str:
        modeling_profiles = self.modeling_voice_profiles()
        modeling_profile_ids = {profile["id"] for profile in modeling_profiles}
        selected_profile_id = getattr(self, "selected_modeling_profile_id", "")
        if selected_profile_id in modeling_profile_ids:
            return selected_profile_id
        selected_voice_profile_id = getattr(self, "selected_voice_profile_id", "")
        if selected_voice_profile_id in modeling_profile_ids:
            return selected_voice_profile_id
        return modeling_profiles[0]["id"] if modeling_profiles else ""

    def ensure_selected_modeling_dataset(self) -> ModelingDataset | None:
        profile_id = self.active_modeling_profile_id()
        if not profile_id:
            self.selected_modeling_profile_id = ""
            self.selected_modeling_dataset_id = ""
            return None
        self.selected_modeling_profile_id = profile_id
        dataset = next((entry for entry in self.modeling_datasets if entry["profile_id"] == profile_id), None)
        self.selected_modeling_dataset_id = dataset["id"] if dataset else ""
        return dataset

    def selected_modeling_dataset(self) -> ModelingDataset | None:
        dataset_id = getattr(self, "selected_modeling_dataset_id", "")
        dataset = next((dataset for dataset in self.modeling_datasets if dataset["id"] == dataset_id), None)
        return dataset or self.ensure_selected_modeling_dataset()

    def open_modeling_dataset_for_profile(self, profile_id: str) -> None:
        if not any(profile["id"] == profile_id for profile in self.modeling_voice_profiles()):
            return
        self.selected_modeling_profile_id = profile_id
        self.sync_modeling_datasets_with_profiles()
        self.ensure_selected_modeling_dataset()
        self.selected_modeling_clip_id = ""
        self.refresh_modeling_datasets_page()
        if hasattr(self, "show_local_voices_tab"):
            if hasattr(self, "open_local_voice_workflow_tab"):
                self.open_local_voice_workflow_tab(1)
            else:
                self.local_voice_dataset_tab_open_allowed = True
                self.show_local_voices_tab(1)

    def selected_modeling_clip(self) -> ModelingClip | None:
        dataset = self.selected_modeling_dataset()
        if not dataset:
            return None
        clip_id = getattr(self, "selected_modeling_clip_id", "")
        return next((clip for clip in dataset["clips"] if clip["id"] == clip_id), None)

    @staticmethod
    def replace_modeling_clip(dataset: ModelingDataset, updated_clip: ModelingClip) -> bool:
        for index, existing in enumerate(dataset["clips"]):
            if existing["id"] == updated_clip["id"]:
                dataset["clips"][index] = updated_clip
                dataset["updated_at"] = updated_clip["updated_at"]
                return True
        return False

    def refresh_modeling_datasets_page(self) -> None:
        self.refresh_modeling_datasets_list()
        summary = self.update_modeling_dataset_summary()
        self.refresh_modeling_clips_list()
        self.update_modeling_dataset_buttons(summary)

    def refresh_modeling_clip_after_metadata_change(
        self,
        clip: ModelingClip,
        *,
        refresh_dataset_list: bool = False,
    ) -> None:
        if refresh_dataset_list:
            self.refresh_modeling_datasets_list()
        summary = self.update_modeling_dataset_summary()
        self.update_modeling_clip_list_item(clip)
        if clip["id"] == getattr(self, "selected_modeling_clip_id", ""):
            self.populate_modeling_clip_editor()
        self.update_modeling_dataset_buttons(summary)

    def refresh_modeling_datasets_list(self) -> None:
        if not hasattr(self, "modeling_datasets_list"):
            self.ensure_selected_modeling_dataset()
            return
        self.modeling_datasets_list.blockSignals(True)
        self.modeling_datasets_list.setUpdatesEnabled(False)
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
                self.modeling_datasets_list.addItem(self.modeling_text("No modeling datasets yet."))
                self.selected_modeling_dataset_id = ""
                return
            if not any(dataset["id"] == self.selected_modeling_dataset_id for dataset in visible_datasets):
                self.selected_modeling_dataset_id = visible_datasets[0]["id"]
            for dataset in sorted(visible_datasets, key=lambda dataset_item: dataset_item["name"].casefold()):
                ready_count = sum(1 for clip in dataset["clips"] if clip["status"] == "ready")
                item = QListWidgetItem(
                    self.modeling_text(
                        "{name} | {clip_count} clip(s), {ready_count} ready",
                        name=dataset["name"],
                        clip_count=len(dataset["clips"]),
                        ready_count=ready_count,
                    )
                )
                item.setData(Qt.ItemDataRole.UserRole, dataset["id"])
                self.modeling_datasets_list.addItem(item)
                if dataset["id"] == self.selected_modeling_dataset_id:
                    self.modeling_datasets_list.setCurrentItem(item)
        finally:
            self.modeling_datasets_list.setUpdatesEnabled(True)
            self.modeling_datasets_list.blockSignals(False)

    def modeling_dataset_selection_changed(self) -> None:
        item = self.modeling_datasets_list.currentItem()
        dataset_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        self.selected_modeling_dataset_id = dataset_id if isinstance(dataset_id, str) else ""
        self.selected_modeling_clip_id = ""
        summary = self.update_modeling_dataset_summary()
        self.refresh_modeling_clips_list()
        self.update_modeling_dataset_buttons(summary)

    def update_modeling_dataset_summary(self) -> ModelingDatasetSummary | None:
        if not hasattr(self, "modeling_dataset_summary_box"):
            return None
        dataset = self.selected_modeling_dataset()
        if not dataset:
            self.modeling_dataset_summary_box.setPlainText(self.modeling_text("Create or select a modeling dataset."))
            self.update_modeling_dataset_metric_tiles(None)
            self.update_modeling_prompt_usage_label()
            return None
        summary = modeling_dataset_summary(dataset)
        self.update_modeling_dataset_metric_tiles(summary)
        self.modeling_dataset_summary_box.setPlainText(modeling_dataset_summary_text(dataset, summary))
        self.update_modeling_prompt_usage_label()
        return summary

    def update_modeling_dataset_metric_tiles(self, summary: ModelingDatasetSummary | None) -> None:
        if not hasattr(self, "modeling_ready_clips_tile"):
            return
        dataset = self.selected_modeling_dataset()
        if not dataset or summary is None:
            self.modeling_dataset_profile_label.setText(self.modeling_text("No modeling profile selected."))
            self.set_modeling_dataset_tile(
                self.modeling_ready_clips_tile,
                "info",
                self.modeling_text("Ready clips\n--"),
                "",
            )
            self.set_modeling_dataset_tile(
                self.modeling_ready_duration_tile,
                "info",
                self.modeling_text("Ready duration\n--"),
                "",
            )
            self.set_modeling_dataset_tile(
                self.modeling_average_clip_tile,
                "info",
                self.modeling_text("Avg clip\n--"),
                "",
            )
            self.set_modeling_dataset_tile(
                self.modeling_target_duration_tile,
                "info",
                self.modeling_text("Target duration\n--"),
                "",
            )
            self.set_modeling_dataset_tile(self.modeling_tier_tile, "info", self.modeling_text("Tier\n--"), "")
            self.set_modeling_dataset_tile(
                self.modeling_exportable_tile,
                "info",
                self.modeling_text("Exportable\n--"),
                "",
            )
            return
        export_disabled_reason = modeling_dataset_export_disabled_reason_from_summary(summary)
        self.modeling_dataset_profile_label.setText(
            self.modeling_text(
                "Dataset for: {name} | {language}",
                name=dataset["name"],
                language=dataset["language_code"],
            )
        )
        self.set_modeling_dataset_tile(
            self.modeling_ready_clips_tile,
            "ok" if summary["ready_clips"] else "warn",
            self.modeling_text("Ready clips\n{count}", count=summary["ready_clips"]),
            self.modeling_text(
                "{count} of {total} clip(s) are ready.",
                count=summary["ready_clips"],
                total=summary["total_clips"],
            ),
        )
        self.set_modeling_dataset_tile(
            self.modeling_ready_duration_tile,
            "ok" if summary["ready_duration_seconds"] else "warn",
            self.modeling_text(
                "Ready duration\n{duration}",
                duration=format_modeling_dataset_duration(summary["ready_duration_seconds"]),
            ),
            self.modeling_text("Total duration of ready clips."),
        )
        self.set_modeling_dataset_tile(
            self.modeling_average_clip_tile,
            "info" if summary["average_ready_duration_seconds"] else "warn",
            self.modeling_text(
                "Avg clip\n{duration:.1f}s",
                duration=summary["average_ready_duration_seconds"],
            ),
            self.modeling_text("Average duration of ready clips."),
        )
        target_duration_percent = summary["target_duration_percent"]
        self.set_modeling_dataset_tile(
            self.modeling_target_duration_tile,
            "ok" if target_duration_percent >= 100 else "info",
            self.modeling_text("Target duration\n{percent}%", percent=target_duration_percent),
            self.modeling_text(
                "{ready} of {target} target ready audio.",
                ready=format_modeling_dataset_duration(summary["ready_duration_seconds"]),
                target=format_modeling_dataset_duration(MODELING_TARGET_READY_SECONDS),
            ),
        )
        self.set_modeling_dataset_tile(
            self.modeling_tier_tile,
            "ok" if summary["dataset_tier"] not in {"not_ready", "technical_test"} else "info",
            self.modeling_text("Tier\n{tier}", tier=modeling_dataset_tier_label(summary["dataset_tier"])),
            self.modeling_text("Dataset duration tier."),
        )
        self.set_modeling_dataset_tile(
            self.modeling_exportable_tile,
            "ok" if not export_disabled_reason else "warn",
            self.modeling_text(
                "Exportable\n{value}",
                value=self.modeling_text("Yes") if not export_disabled_reason else self.modeling_text("No"),
            ),
            export_disabled_reason or self.modeling_text("Dataset can be exported."),
        )

    @staticmethod
    def set_modeling_dataset_tile(tile: QLabel, state: str, text: str, tooltip: str) -> None:
        tile.setText(text)
        tile.setToolTip(tooltip)
        tile.setProperty("state", state)
        tile.style().unpolish(tile)
        tile.style().polish(tile)

    def refresh_modeling_clips_list(self) -> None:
        if not hasattr(self, "modeling_clips_list"):
            return
        dataset = self.selected_modeling_dataset()
        self.modeling_clips_list.blockSignals(True)
        self.modeling_clips_list.setUpdatesEnabled(False)
        try:
            self.modeling_clips_list.clear()
            if not dataset:
                self.modeling_clips_list.addItem(self.modeling_text("Select a modeling dataset."))
                self.modeling_clip_text_edit.clear()
                self.modeling_clip_details.setPlainText("")
                self.modeling_generated_prompt_text = ""
                return
            if not dataset["clips"]:
                self.modeling_clips_list.addItem(self.modeling_text("No clips yet."))
                self.selected_modeling_clip_id = ""
                self.modeling_clip_text_edit.clear()
                self.modeling_clip_details.setPlainText("")
                self.modeling_generated_prompt_text = ""
                return
            if not any(clip["id"] == self.selected_modeling_clip_id for clip in dataset["clips"]):
                self.selected_modeling_clip_id = dataset["clips"][0]["id"]
            for index, clip in enumerate(dataset["clips"], start=1):
                item = QListWidgetItem(self.modeling_clip_list_label(index, clip))
                item.setData(Qt.ItemDataRole.UserRole, clip["id"])
                self.modeling_clips_list.addItem(item)
                if clip["id"] == self.selected_modeling_clip_id:
                    self.modeling_clips_list.setCurrentItem(item)
        finally:
            self.modeling_clips_list.setUpdatesEnabled(True)
            self.modeling_clips_list.blockSignals(False)
        self.populate_modeling_clip_editor()

    @staticmethod
    def modeling_clip_list_label(index: int, clip: ModelingClip) -> str:
        if generated_prompt_source(clip.get("transcript_source", "")):
            mode = "Guided"
        elif clip["mode"] == MODELING_CLIP_TEXT_GUIDED:
            mode = "Text"
        else:
            mode = "Free"
        verification_label = modeling_clip_verification_label(modeling_clip_verification_status(clip))
        export_label = " | Excluded" if clip.get("excluded_from_export", False) else ""
        return (
            f"C. {index} | {modeling_clip_status_label(clip['status'])} | "
            f"{clip['duration_seconds']:.1f}s | {mode} | {verification_label}{export_label}"
        )

    def update_modeling_clip_list_item(self, clip: ModelingClip) -> None:
        if not hasattr(self, "modeling_clips_list"):
            return
        for row in range(self.modeling_clips_list.count()):
            item = self.modeling_clips_list.item(row)
            if item and item.data(Qt.ItemDataRole.UserRole) == clip["id"]:
                item.setText(self.modeling_clip_list_label(row + 1, clip))
                return

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
            self.modeling_dataset_status.setText(
                self.modeling_text("Create a Voice Profile with type Modeling dataset first.")
            )
            self.modeling_clip_text_edit.clear()
            self.modeling_clip_details.setPlainText("")
            self.modeling_generated_prompt_text = ""
            return
        if not clip:
            self.modeling_dataset_status.setText(
                self.modeling_text(
                    "Dataset: {name} | {clip_count} clip(s).",
                    name=dataset["name"],
                    clip_count=len(dataset["clips"]),
                )
            )
            self.modeling_clip_text_edit.clear()
            self.modeling_clip_details.setPlainText("")
            self.modeling_generated_prompt_text = ""
            return
        verification_status = modeling_clip_verification_status(clip)
        self.modeling_dataset_status.setText(
            f"Selected {dataset['name']} | {modeling_clip_status_label(clip['status'])} | "
            f"{modeling_clip_verification_label(verification_status)}."
        )
        self.modeling_clip_text_edit.blockSignals(True)
        try:
            self.modeling_clip_text_edit.setPlainText(clip.get("transcript_text", ""))
        finally:
            self.modeling_clip_text_edit.blockSignals(False)
        self.modeling_clip_details.setPlainText(self.modeling_clip_details_text(clip))
        self.modeling_generated_prompt_text = ""
        self.update_modeling_text_counter(refresh_buttons=False)

    @staticmethod
    def modeling_clip_details_text(clip: ModelingClip) -> str:
        sections = []
        quality_details = clip.get("quality_details", "").strip()
        if quality_details:
            sections.append("Audio quality\n" + quality_details)
        verification_status = modeling_clip_verification_status(clip)
        verification_lines = [f"Status: {modeling_clip_verification_label(verification_status)}"]
        score = float(clip.get("verification_score", 0.0) or 0.0)
        if score:
            verification_lines.append(f"Score: {score:.1f}%")
        checked_at = clip.get("verification_checked_at", "").strip()
        if checked_at:
            verification_lines.append(f"Checked at: {checked_at}")
        details = clip.get("verification_details", "").strip()
        if details:
            verification_lines.extend(["", details])
        sections.append("Text verification\n" + "\n".join(verification_lines))
        export_reason = modeling_clip_export_block_reason(clip)
        if export_reason:
            sections.append("Export\nNot exportable: " + export_reason)
        else:
            sections.append("Export\nExportable.")
        return "\n\n".join(sections)

    def refresh_modeling_microphones(self) -> None:
        if not hasattr(self, "modeling_microphone_combo"):
            return
        current_device_index = self.current_modeling_audio_device_index()
        self.modeling_microphone_combo.blockSignals(True)
        try:
            self.modeling_microphone_combo.clear()
            try:
                devices = list_input_devices()
            except AudioRecorderError as exc:
                self.modeling_microphone_combo.addItem(self.modeling_text("Microphone unavailable"), None)
                self.modeling_microphone_combo.setEnabled(False)
                if hasattr(self, "modeling_dataset_status"):
                    self.modeling_dataset_status.setText(str(exc))
                return
            if not devices:
                self.modeling_microphone_combo.addItem(self.modeling_text("No microphone input was detected."), None)
                self.modeling_microphone_combo.setEnabled(False)
                if hasattr(self, "modeling_dataset_status"):
                    self.modeling_dataset_status.setText(self.modeling_text("No microphone input was detected."))
                return
            selected_row = 0
            default_row = 0
            for row, device in enumerate(devices):
                label = f"{device.name} | {device.host_api}"
                if device.is_default:
                    label += " | default"
                    default_row = row
                self.modeling_microphone_combo.addItem(label, device.index)
                if device.index == current_device_index:
                    selected_row = row
            if current_device_index is None:
                selected_row = default_row
            self.modeling_microphone_combo.setCurrentIndex(selected_row)
            self.modeling_microphone_combo.setEnabled(True)
        finally:
            self.modeling_microphone_combo.blockSignals(False)
            self.update_modeling_dataset_buttons()

    def current_modeling_audio_device_index(self) -> int | None:
        if not hasattr(self, "modeling_microphone_combo"):
            return None
        device_index = self.modeling_microphone_combo.currentData(Qt.ItemDataRole.UserRole)
        return device_index if isinstance(device_index, int) else None

    def selected_modeling_audio_device(self) -> int | None:
        device_index = self.current_modeling_audio_device_index()
        if device_index is None:
            self.show_error("Modeling Datasets", "Select a microphone input first.")
            return None
        return device_index

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
        self.modeling_generated_prompt_text = ""
        self.modeling_dataset_status.setText(f"Loaded text: {Path(path).name}")

    def generate_modeling_clip_text(self) -> None:
        dataset = self.selected_modeling_dataset()
        if not dataset:
            self.show_error("Modeling Datasets", "Select a modeling dataset first.")
            return
        used_prompts = modeling_dataset_guided_prompt_texts(dataset)
        try:
            prompt = generate_modeling_prompt(
                dataset["language_code"],
                used_texts=used_prompts,
                max_chars=MODELING_GUIDED_TEXT_MAX_CHARS,
            )
        except NoUnusedModelingPromptError as exc:
            self.show_error("Modeling Datasets", str(exc))
            self.modeling_dataset_status.setText("Guided prompt pool exhausted.")
            return
        if add_modeling_dataset_guided_prompt_history(dataset, prompt.text):
            save_modeling_datasets(self.modeling_datasets)
        self.modeling_clip_text_edit.setPlainText(prompt.text)
        self.modeling_generated_prompt_text = prompt.text
        self.update_modeling_prompt_usage_label()
        self.modeling_dataset_status.setText(
            f"Generated guided text ({prompt.language_code}, corpus {prompt.corpus_version})."
        )

    def reset_guided_prompt_history(self) -> None:
        dataset = self.selected_modeling_dataset()
        if not dataset:
            return
        if not self.ask_question(
            "Reset guided prompt history",
            (
                "Reset generated prompt history for this dataset?\n\n"
                "Existing saved clips will still prevent duplicate guided text."
            ),
        ):
            return
        if reset_modeling_dataset_guided_prompt_history(dataset):
            save_modeling_datasets(self.modeling_datasets)
        self.update_modeling_dataset_summary()
        self.update_modeling_dataset_buttons()
        self.modeling_dataset_status.setText("Guided prompt history reset.")

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
        generated_text = getattr(self, "modeling_generated_prompt_text", "")
        transcript_source = (
            MODELING_PROMPT_SOURCE_GENERATED
            if normalize_prompt_text(text) == normalize_prompt_text(generated_text)
            else MODELING_PROMPT_SOURCE_PROVIDED
        )
        self.record_modeling_clip(
            dataset,
            mode=MODELING_CLIP_TEXT_GUIDED,
            transcript_text=text,
            transcript_source=transcript_source,
        )

    def record_free_modeling_clip(self) -> None:
        dataset = self.selected_modeling_dataset()
        if not dataset:
            self.show_error("Modeling Datasets", "Select a modeling dataset first.")
            return
        self.record_modeling_clip(dataset, mode=MODELING_CLIP_FREE_RECORDING, transcript_text="", transcript_source="")

    def record_modeling_clip(
        self,
        dataset: ModelingDataset,
        *,
        mode: str,
        transcript_text: str,
        transcript_source: str,
    ) -> None:
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
            transcript_source=transcript_source if transcript_text else "",
            duration_seconds=dialog.duration_seconds,
            quality_details=dialog.quality_details,
            clip_id=clip_id,
        )
        write_modeling_clip_transcript(clip)
        dataset["clips"].append(clip)
        dataset["updated_at"] = clip["updated_at"]
        save_modeling_datasets(self.modeling_datasets)
        self.selected_modeling_clip_id = clip["id"]
        self.modeling_generated_prompt_text = ""
        self.refresh_modeling_datasets_page()
        self.modeling_dataset_status.setText(f"Saved clip: {modeling_clip_status_label(clip['status'])}.")
        if modeling_clip_can_verify_transcript(clip):
            self.queue_modeling_clip_verification(dataset, clip)

    def save_modeling_clip_transcript_from_editor(self) -> None:
        dataset = self.selected_modeling_dataset()
        clip = self.selected_modeling_clip()
        if not dataset or not clip:
            return
        updated_clip = update_modeling_clip_transcript(clip, self.modeling_clip_text_edit.toPlainText())
        self.replace_modeling_clip(dataset, updated_clip)
        write_modeling_clip_transcript(updated_clip)
        save_modeling_datasets(self.modeling_datasets)
        self.selected_modeling_clip_id = updated_clip["id"]
        self.refresh_modeling_clip_after_metadata_change(updated_clip, refresh_dataset_list=True)
        self.modeling_dataset_status.setText("Transcript saved.")
        if modeling_clip_can_verify_transcript(updated_clip):
            self.queue_modeling_clip_verification(dataset, updated_clip)

    def update_modeling_text_counter(self, *, refresh_buttons: bool = True) -> None:
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
        if refresh_buttons:
            self.update_modeling_dataset_buttons()

    def update_modeling_prompt_usage_label(self) -> None:
        if not hasattr(self, "modeling_prompt_usage_label"):
            return
        dataset = self.selected_modeling_dataset()
        if not dataset:
            self.modeling_prompt_usage_label.setText(self.modeling_text("Guided prompts used: --"))
            self.modeling_prompt_usage_label.setToolTip("")
            return
        used_count, available_count = modeling_dataset_guided_prompt_usage(dataset)
        percent = (used_count / available_count * 100.0) if available_count else 0.0
        percent_text = f"{percent:.4f}" if 0 < percent < 0.01 else f"{percent:.1f}"
        self.modeling_prompt_usage_label.setText(
            self.modeling_text("Guided prompts used: {percent}%", percent=percent_text)
        )
        self.modeling_prompt_usage_label.setToolTip(
            self.modeling_text(
                "{used:,} of {available:,} generated prompt combinations used.",
                used=used_count,
                available=available_count,
            )
        )

    def set_modeling_export_dataset_button_primary(self, is_primary: bool) -> None:
        button = self.modeling_export_dataset_button
        object_name = "FlowButton" if is_primary else ""
        if button.objectName() == object_name:
            return
        button.setObjectName(object_name)
        button.style().unpolish(button)
        button.style().polish(button)

    def current_selected_modeling_dataset_export(self):
        dataset = self.selected_modeling_dataset()
        if not dataset:
            return None
        dataset_id = dataset.get("id", "")
        profile_id = dataset.get("profile_id", "")
        if not dataset_id and not profile_id:
            return None
        return current_voice_modeling_export_for_dataset(
            dataset_id=dataset_id,
            profile_id=profile_id,
            source_updated_at=dataset.get("updated_at", ""),
        )

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

    def retry_selected_modeling_clip_recording(self) -> None:
        dataset = self.selected_modeling_dataset()
        clip = self.selected_modeling_clip()
        if not dataset or not clip:
            return
        if clip.get("mode") != MODELING_CLIP_TEXT_GUIDED or not clip.get("transcript_text", "").strip():
            self.show_error("Modeling Datasets", "Retry recording is available for guided clips with text.")
            return
        device_index = self.selected_modeling_audio_device()
        if device_index is None:
            return
        retry_audio_path = modeling_clip_audio_path(dataset, f"{clip['id']}-retry-{uuid4().hex[:8]}")
        dialog = ModelingClipRecordingDialog(
            title="Retry guided recording",
            output_path=retry_audio_path,
            device_index=device_index,
            prompt_text=clip["transcript_text"],
            max_seconds=MODELING_RECORD_MAX_SECONDS,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.recording_path is None:
            self.modeling_dataset_status.setText("Retry cancelled.")
            return
        old_audio_path = Path(clip["audio_path"])
        updated_clip = update_modeling_clip_recording(
            clip,
            audio_path=dialog.recording_path,
            duration_seconds=dialog.duration_seconds,
            quality_details=dialog.quality_details,
        )
        if old_audio_path != Path(updated_clip["audio_path"]):
            with suppress(OSError):
                old_audio_path.unlink(missing_ok=True)
        self.replace_modeling_clip(dataset, updated_clip)
        save_modeling_datasets(self.modeling_datasets)
        self.selected_modeling_clip_id = updated_clip["id"]
        self.refresh_modeling_clip_after_metadata_change(updated_clip)
        self.modeling_dataset_status.setText("Recording replaced; text verification queued.")
        self.queue_modeling_clip_verification(dataset, updated_clip)

    def toggle_selected_modeling_clip_export_exclusion(self) -> None:
        dataset = self.selected_modeling_dataset()
        clip = self.selected_modeling_clip()
        if not dataset or not clip:
            return
        updated_clip = toggle_modeling_clip_export_exclusion(clip)
        self.replace_modeling_clip(dataset, updated_clip)
        save_modeling_datasets(self.modeling_datasets)
        self.selected_modeling_clip_id = updated_clip["id"]
        self.refresh_modeling_clip_after_metadata_change(updated_clip)
        if updated_clip.get("excluded_from_export", False):
            self.modeling_dataset_status.setText("Clip excluded from export.")
        else:
            self.modeling_dataset_status.setText("Clip included in export.")

    def verify_selected_modeling_clip_text(self) -> None:
        dataset = self.selected_modeling_dataset()
        clip = self.selected_modeling_clip()
        if not dataset or not clip:
            return
        if not modeling_clip_can_verify_transcript(clip):
            self.show_error("Modeling Datasets", "Select a guided clip with audio and text.")
            return
        self.queue_modeling_clip_verification(dataset, clip)

    def queue_modeling_clip_verification(
        self,
        dataset: ModelingDataset,
        clip: ModelingClip,
    ) -> None:
        if not modeling_clip_can_verify_transcript(clip):
            return
        queue_key = f"{dataset['id']}:{clip['id']}"
        if queue_key in self.modeling_verification_queued_clip_ids:
            self.modeling_dataset_status.setText("Text verification is already queued.")
            return
        python_path = stt_python_path()
        worker_path = stt_worker_path()
        preflight_error = ""
        if not python_path.is_file():
            preflight_error = f"STT Python runtime missing: {python_path}"
        elif not worker_path.is_file():
            preflight_error = f"STT worker missing: {worker_path}"
        elif not stt_whisper_model_ready():
            preflight_error = f"Whisper large-v3 model not downloaded: {stt_model_dir()}"
        if preflight_error:
            updated_clip = update_modeling_clip_verification(
                clip,
                status=MODELING_VERIFICATION_ERROR,
                details=preflight_error,
            )
            self.replace_modeling_clip(dataset, updated_clip)
            save_modeling_datasets(self.modeling_datasets)
            self.refresh_modeling_clip_after_metadata_change(updated_clip)
            self.modeling_dataset_status.setText("Text verification unavailable; guided clip is not exportable.")
            return

        pending_clip = update_modeling_clip_verification(
            clip,
            status=MODELING_VERIFICATION_PENDING,
            details="Waiting for Whisper transcript verification.",
        )
        self.replace_modeling_clip(dataset, pending_clip)
        save_modeling_datasets(self.modeling_datasets)
        self.selected_modeling_clip_id = pending_clip["id"]
        self.refresh_modeling_clip_after_metadata_change(pending_clip)
        self.modeling_verification_queue.append(
            {
                "dataset_id": dataset["id"],
                "clip_id": pending_clip["id"],
                "audio_path": pending_clip["audio_path"],
                "expected_text": pending_clip["transcript_text"],
                "language_code": pending_clip.get("language_code", dataset["language_code"]),
            }
        )
        self.modeling_verification_queued_clip_ids.add(queue_key)
        self.modeling_dataset_status.setText("Text verification queued; guided clip is not exportable until Match OK.")
        self.start_next_modeling_clip_verification()

    def start_next_modeling_clip_verification(self) -> None:
        if self.modeling_verification_running or not self.modeling_verification_queue:
            return
        job = self.modeling_verification_queue.pop(0)
        self.modeling_verification_running = True
        threading.Thread(target=self.modeling_clip_verification_worker, args=(job,), daemon=True).start()

    def modeling_clip_verification_worker(self, job: dict[str, str]) -> None:
        dataset_id = job["dataset_id"]
        clip_id = job["clip_id"]
        audio_path = job["audio_path"]
        expected_text = job["expected_text"]
        language_code = (job.get("language_code") or "auto").strip().lower() or "auto"
        device = getattr(self, "preferred_stt_device_key", "auto")
        if device == "cuda" and not getattr(self, "stt_cuda_available", False):
            device = "auto"
        result = {
            "status": MODELING_VERIFICATION_ERROR,
            "score": 0.0,
            "detected_text": "",
            "details": "Text verification failed before Whisper could run.",
        }
        try:
            with tempfile.TemporaryDirectory(prefix="voicebridge-modeling-verify-") as temp_dir:
                output_path = Path(temp_dir) / "transcript.md"
                command = [
                    str(stt_python_path()),
                    str(stt_worker_path()),
                    "--media",
                    audio_path,
                    "--output",
                    str(output_path),
                    "--mode",
                    "transcript",
                    "--model",
                    STT_MODEL,
                    "--model-dir",
                    str(stt_model_dir()),
                    "--language",
                    language_code,
                    "--device",
                    device,
                    "--batch-size",
                    "1",
                    "--offline",
                ]
                recent_output: list[str] = []
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                process = subprocess.Popen(
                    command,
                    cwd=str(external_base_dir()),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=creationflags,
                    env=os.environ.copy(),
                )
                assert process.stdout is not None
                for raw_line in process.stdout:
                    line = raw_line.strip()
                    if not line:
                        continue
                    recent_output.append(line)
                    recent_output = recent_output[-10:]
                return_code = process.wait()
                if return_code != 0:
                    details = "\n".join(recent_output) or f"Whisper verification exited with code {return_code}."
                    raise RuntimeError(details)
                detected_text = read_whisper_markdown_text(output_path)
                result = compare_transcript_to_expected(expected_text, detected_text)
        except (OSError, RuntimeError, AssertionError, ValueError) as exc:
            result = {
                "status": MODELING_VERIFICATION_ERROR,
                "score": 0.0,
                "detected_text": "",
                "details": str(exc),
            }
        self.post(
            self.finish_modeling_clip_verification,
            dataset_id,
            clip_id,
            audio_path,
            expected_text,
            result,
        )

    def finish_modeling_clip_verification(
        self,
        dataset_id: str,
        clip_id: str,
        audio_path: str,
        expected_text: str,
        result: dict[str, object],
    ) -> None:
        queue_key = f"{dataset_id}:{clip_id}"
        self.modeling_verification_queued_clip_ids.discard(queue_key)
        self.modeling_verification_running = False
        dataset = next((entry for entry in self.modeling_datasets if entry["id"] == dataset_id), None)
        clip = None
        if dataset:
            clip = next((entry for entry in dataset["clips"] if entry["id"] == clip_id), None)
        if dataset and clip:
            if clip.get("audio_path") == audio_path and clip.get("transcript_text") == expected_text:
                updated_clip = update_modeling_clip_verification(
                    clip,
                    status=str(result.get("status", MODELING_VERIFICATION_ERROR)),
                    score=float(result.get("score", 0.0) or 0.0),
                    detected_text=str(result.get("detected_text", "")),
                    details=str(result.get("details", "")),
                )
                self.replace_modeling_clip(dataset, updated_clip)
                save_modeling_datasets(self.modeling_datasets)
                self.selected_modeling_clip_id = updated_clip["id"]
                self.refresh_modeling_clip_after_metadata_change(updated_clip)
                if updated_clip["verification_status"] == MODELING_VERIFICATION_MATCH_OK:
                    self.modeling_dataset_status.setText("Text verification Match OK; clip is exportable if included.")
                elif updated_clip["verification_status"] == MODELING_VERIFICATION_NEEDS_REVIEW:
                    self.modeling_dataset_status.setText("Text verification needs review; clip is not exportable.")
                else:
                    self.modeling_dataset_status.setText("Text verification failed; clip is not exportable.")
            else:
                self.modeling_dataset_status.setText("Skipped stale text verification result.")
        self.start_next_modeling_clip_verification()

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
        current_export = self.current_selected_modeling_dataset_export()
        if current_export:
            self.modeling_dataset_status.setText(
                self.modeling_text("Dataset export is current. Opening setup.")
            )
            self.open_voice_modeling_setup_for_export(current_export["dataset_dir"])
            return
        try:
            result = export_modeling_dataset(dataset)
        except (OSError, ValueError) as exc:
            self.show_error("Modeling Datasets", str(exc))
            return
        export_dir = result["export_dir"]
        skipped_clips = result["skipped_clips"]
        self.modeling_dataset_status.setText(
            f"Exported {result['exported_clips']} exportable clip(s); "
            f"skipped {skipped_clips} non-exportable clip(s). Opening setup."
        )
        self.update_local_voice_tabs()
        self.open_voice_modeling_setup_for_export(export_dir)

    def send_modeling_clip_to_transcription(self) -> None:
        clip = self.selected_modeling_clip()
        if not clip or not Path(clip["audio_path"]).is_file():
            return
        self.stt_media_picker.set_text(clip["audio_path"])
        output_path = str(Path(clip["audio_path"]).with_suffix(".md"))
        self.stt_output_picker.set_text(output_path)
        self.show_page(3)

    def update_modeling_dataset_buttons(self, dataset_summary: ModelingDatasetSummary | None = None) -> None:
        if not hasattr(self, "modeling_record_text_button"):
            return
        dataset = self.selected_modeling_dataset()
        clip = self.selected_modeling_clip()
        has_dataset = dataset is not None
        has_microphone = self.current_modeling_audio_device_index() is not None
        has_clip_audio = bool(clip and Path(clip["audio_path"]).is_file())
        dataset_summary = dataset_summary if dataset else None
        if dataset and dataset_summary is None:
            dataset_summary = modeling_dataset_summary(dataset)
        export_disabled_reason = (
            modeling_dataset_export_disabled_reason_from_summary(dataset_summary)
            if dataset_summary
            else "Select a modeling dataset first."
        )
        self.update_modeling_dataset_metric_tiles(dataset_summary)
        has_exportable_clips = bool(dataset_summary and not export_disabled_reason)
        current_export = self.current_selected_modeling_dataset_export() if has_exportable_clips else None
        can_verify_clip = bool(clip and modeling_clip_can_verify_transcript(clip))
        can_retry_clip = bool(
            clip
            and clip.get("mode") == MODELING_CLIP_TEXT_GUIDED
            and clip.get("transcript_text", "").strip()
            and has_microphone
        )
        text_length = len(self.modeling_clip_text_edit.toPlainText().strip())
        can_record_from_text = has_dataset and has_microphone and 0 < text_length <= MODELING_GUIDED_TEXT_MAX_CHARS
        self.modeling_record_text_button.setEnabled(can_record_from_text)
        if can_record_from_text:
            self.modeling_record_text_button.setToolTip("Record the text currently shown in the clip text box.")
        elif has_dataset and not has_microphone:
            self.modeling_record_text_button.setToolTip("Select a microphone input first.")
        elif has_dataset:
            self.modeling_record_text_button.setToolTip(
                f"Paste, load or generate text up to {MODELING_GUIDED_TEXT_MAX_CHARS} characters."
            )
        else:
            self.modeling_record_text_button.setToolTip("Select a modeling dataset first.")
        self.modeling_record_free_button.setEnabled(has_dataset and has_microphone)
        self.modeling_record_free_button.setToolTip(
            "Record up to 60 seconds without prepared text."
            if has_dataset and has_microphone
            else "Select a microphone input first."
            if has_dataset
            else "Select a modeling dataset first."
        )
        self.modeling_load_text_button.setEnabled(has_dataset)
        self.modeling_load_text_button.setToolTip(
            "Load custom text for a guided clip." if has_dataset else "Select a modeling dataset first."
        )
        self.modeling_generate_text_button.setEnabled(has_dataset)
        self.modeling_generate_text_button.setToolTip(
            "Generate an unused guided prompt for this dataset language."
            if has_dataset
            else "Select a modeling dataset first."
        )
        self.modeling_reset_prompt_history_button.setEnabled(
            bool(dataset and dataset.get("guided_prompt_history"))
        )
        self.modeling_reset_prompt_history_button.setToolTip(
            "Reset generated prompt history. Saved clip texts still prevent duplicates."
            if dataset and dataset.get("guided_prompt_history")
            else "No generated prompt history to reset."
        )
        self.modeling_save_text_button.setEnabled(clip is not None)
        self.modeling_save_text_button.setToolTip(
            "Save transcript text. Guided clips must be verified again before export."
            if clip
            else "Select a clip first."
        )
        self.modeling_delete_clip_button.setEnabled(clip is not None)
        self.modeling_delete_clip_button.setToolTip(
            "Delete this clip and its sidecar files. Guided prompt history is not freed automatically."
            if clip
            else "Select a clip first."
        )
        self.modeling_play_clip_button.setEnabled(has_clip_audio)
        self.modeling_play_clip_button.setToolTip(
            "Play the selected clip audio." if has_clip_audio else "Select a clip with an existing WAV file."
        )
        self.modeling_open_clip_button.setEnabled(has_clip_audio)
        self.modeling_open_clip_button.setToolTip(
            "Open the selected clip audio file." if has_clip_audio else "Select a clip with an existing WAV file."
        )
        self.modeling_transcribe_clip_button.setEnabled(has_clip_audio)
        self.modeling_transcribe_clip_button.setToolTip(
            "Send this clip to the Transcription page." if has_clip_audio else "Select a clip with audio first."
        )
        self.modeling_retry_clip_button.setEnabled(can_retry_clip)
        self.modeling_retry_clip_button.setToolTip(
            "Record this guided clip again with the same text."
            if can_retry_clip
            else "Select a microphone input first."
            if clip and not has_microphone
            else "Retry recording is available for guided clips with transcript text."
        )
        self.modeling_verify_clip_button.setEnabled(can_verify_clip)
        self.modeling_verify_clip_button.setToolTip(
            "Run Whisper verification against the expected text."
            if can_verify_clip
            else "Verify text requires a guided clip with audio and transcript text."
        )
        self.modeling_toggle_export_clip_button.setEnabled(clip is not None)
        if clip and clip.get("excluded_from_export", False):
            self.modeling_toggle_export_clip_button.setText("Include export")
            self.modeling_toggle_export_clip_button.setToolTip(
                "Allow this clip to be exported if it also meets transcript and verification requirements."
            )
        else:
            self.modeling_toggle_export_clip_button.setText("Exclude export")
            self.modeling_toggle_export_clip_button.setToolTip(
                "Keep this clip in the dataset but skip it during dataset export."
                if clip
                else "Select a clip first."
            )
        self.modeling_open_dataset_folder_button.setEnabled(has_dataset)
        self.modeling_open_dataset_folder_button.setToolTip(
            "Open the dataset folder." if has_dataset else "Select a modeling dataset first."
        )
        self.modeling_export_dataset_button.setEnabled(has_exportable_clips)
        self.modeling_export_dataset_button.setText(
            self.modeling_text("Open Setup") if current_export else self.modeling_text("Setup Dataset")
        )
        self.set_modeling_export_dataset_button_primary(has_exportable_clips)
        if dataset_summary:
            exportable_count = dataset_summary["exportable_clips"]
            self.modeling_export_dataset_button.setToolTip(
                export_disabled_reason
                or (
                    self.modeling_text("Open Setup using the current dataset export.")
                    if current_export
                    else self.modeling_text(
                        "Export {count} clip(s) and open Setup.",
                        count=exportable_count,
                    )
                )
            )
        else:
            self.modeling_export_dataset_button.setToolTip("Select a modeling dataset first.")

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

        datasets_card = Card("Dataset")
        datasets_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.modeling_dataset_profile_label = QLabel("No modeling profile selected.")
        self.modeling_dataset_profile_label.setObjectName("Muted")
        self.modeling_ready_clips_tile = QLabel("Ready clips\n--")
        self.modeling_ready_duration_tile = QLabel("Ready duration\n--")
        self.modeling_average_clip_tile = QLabel("Avg clip\n--")
        self.modeling_target_duration_tile = QLabel("Target duration\n--")
        self.modeling_tier_tile = QLabel("Tier\n--")
        self.modeling_exportable_tile = QLabel("Exportable\n--")
        dataset_metric_grid = QGridLayout()
        dataset_metric_grid.setContentsMargins(0, 0, 0, 0)
        dataset_metric_grid.setSpacing(6)
        for index, tile in enumerate(
            (
                self.modeling_ready_clips_tile,
                self.modeling_ready_duration_tile,
                self.modeling_average_clip_tile,
                self.modeling_target_duration_tile,
                self.modeling_tier_tile,
                self.modeling_exportable_tile,
            )
        ):
            tile.setObjectName("StatusTile")
            tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tile.setProperty("state", "info")
            dataset_metric_grid.addWidget(tile, index // 3, index % 3)
        self.modeling_dataset_summary_box = QPlainTextEdit()
        self.modeling_dataset_summary_box.setObjectName("LogBox")
        self.modeling_dataset_summary_box.setReadOnly(True)
        self.modeling_dataset_summary_box.setMinimumHeight(240)
        self.modeling_dataset_summary_box.setPlaceholderText("Dataset readiness summary appears here.")
        dataset_actions = QHBoxLayout()
        dataset_actions.setContentsMargins(0, 0, 0, 0)
        self.modeling_refresh_button = QPushButton("Refresh")
        self.modeling_export_dataset_button = QPushButton("Setup Dataset")
        self.modeling_open_dataset_folder_button = QPushButton("Open folder")
        self.modeling_refresh_button.clicked.connect(self.sync_modeling_datasets_with_profiles)
        self.modeling_export_dataset_button.clicked.connect(self.export_selected_modeling_dataset)
        self.modeling_open_dataset_folder_button.clicked.connect(self.open_selected_modeling_dataset_folder)
        dataset_actions.addWidget(self.modeling_refresh_button)
        dataset_actions.addWidget(self.modeling_export_dataset_button)
        dataset_actions.addWidget(self.modeling_open_dataset_folder_button)
        datasets_card.content_layout.addWidget(self.modeling_dataset_profile_label)
        datasets_card.content_layout.addLayout(dataset_metric_grid)
        datasets_card.content_layout.addWidget(self.modeling_dataset_summary_box)
        datasets_card.content_layout.addLayout(dataset_actions)

        clips_card = Card("Clips")
        clips_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.modeling_clips_list = QListWidget()
        self.modeling_clips_list.setMinimumHeight(220)
        self.modeling_clips_list.currentRowChanged.connect(lambda _row: self.modeling_clip_selection_changed())
        clip_actions = QVBoxLayout()
        clip_actions.setContentsMargins(0, 0, 0, 0)
        clip_actions.setSpacing(8)
        clip_actions_primary = QHBoxLayout()
        clip_actions_primary.setContentsMargins(0, 0, 0, 0)
        clip_actions_secondary = QHBoxLayout()
        clip_actions_secondary.setContentsMargins(0, 0, 0, 0)
        self.modeling_play_clip_button = QPushButton("Play")
        self.modeling_open_clip_button = QPushButton("Open audio")
        self.modeling_retry_clip_button = QPushButton("Retry recording")
        self.modeling_verify_clip_button = QPushButton("Verify text")
        self.modeling_toggle_export_clip_button = QPushButton("Exclude export")
        self.modeling_delete_clip_button = QPushButton("Delete clip")
        self.modeling_transcribe_clip_button = QPushButton("Open in Transcription")
        self.modeling_play_clip_button.clicked.connect(self.play_selected_modeling_clip)
        self.modeling_open_clip_button.clicked.connect(self.open_selected_modeling_clip)
        self.modeling_retry_clip_button.clicked.connect(self.retry_selected_modeling_clip_recording)
        self.modeling_verify_clip_button.clicked.connect(self.verify_selected_modeling_clip_text)
        self.modeling_toggle_export_clip_button.clicked.connect(self.toggle_selected_modeling_clip_export_exclusion)
        self.modeling_delete_clip_button.clicked.connect(self.delete_selected_modeling_clip)
        self.modeling_transcribe_clip_button.clicked.connect(self.send_modeling_clip_to_transcription)
        clip_actions_primary.addWidget(self.modeling_play_clip_button)
        clip_actions_primary.addWidget(self.modeling_open_clip_button)
        clip_actions_primary.addWidget(self.modeling_transcribe_clip_button)
        clip_actions_primary.addStretch(1)
        clip_actions_secondary.addWidget(self.modeling_retry_clip_button)
        clip_actions_secondary.addWidget(self.modeling_verify_clip_button)
        clip_actions_secondary.addWidget(self.modeling_toggle_export_clip_button)
        clip_actions_secondary.addStretch(1)
        clip_actions_secondary.addWidget(self.modeling_delete_clip_button)
        clip_actions.addLayout(clip_actions_primary)
        clip_actions.addLayout(clip_actions_secondary)
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
        self.modeling_recording_guidance_label = QLabel(
            self.modeling_text(
                "Read naturally and clearly, like an audiobook for one person. "
                "Do not slow down artificially, act, or over-enunciate. "
                "Keep volume, microphone distance, and rhythm steady."
            )
        )
        self.modeling_recording_guidance_label.setObjectName("Muted")
        self.modeling_recording_guidance_label.setWordWrap(True)
        self.modeling_prompt_usage_label = QLabel("Guided prompts used: --")
        self.modeling_prompt_usage_label.setObjectName("Muted")
        self.modeling_clip_details = QPlainTextEdit()
        self.modeling_clip_details.setObjectName("LogBox")
        self.modeling_clip_details.setReadOnly(True)
        self.modeling_clip_details.setMinimumHeight(120)
        self.modeling_clip_details.setPlaceholderText("Recording quality details appear here after a clip is saved.")
        microphone_row = QHBoxLayout()
        microphone_row.setContentsMargins(0, 0, 0, 0)
        self.modeling_microphone_label = QLabel("Microphone")
        self.modeling_microphone_combo = QComboBox()
        self.modeling_microphone_combo.currentIndexChanged.connect(
            lambda _index: self.update_modeling_dataset_buttons()
        )
        self.modeling_refresh_microphones_button = QPushButton("Refresh")
        self.modeling_refresh_microphones_button.clicked.connect(self.refresh_modeling_microphones)
        microphone_row.addWidget(self.modeling_microphone_label)
        microphone_row.addWidget(self.modeling_microphone_combo, 1)
        microphone_row.addWidget(self.modeling_refresh_microphones_button)
        text_actions = QHBoxLayout()
        text_actions.setContentsMargins(0, 0, 0, 0)
        self.modeling_generate_text_button = QPushButton("Generate guided text")
        self.modeling_load_text_button = QPushButton("Load text")
        self.modeling_reset_prompt_history_button = QPushButton("Reset guided history")
        self.modeling_record_text_button = QPushButton("Record from text")
        self.modeling_record_text_button.setObjectName("PrimaryButton")
        self.modeling_record_free_button = QPushButton("Free record")
        self.modeling_save_text_button = QPushButton("Save transcript")
        self.modeling_generate_text_button.clicked.connect(self.generate_modeling_clip_text)
        self.modeling_load_text_button.clicked.connect(self.load_modeling_clip_text_file)
        self.modeling_reset_prompt_history_button.clicked.connect(self.reset_guided_prompt_history)
        self.modeling_record_text_button.clicked.connect(self.record_modeling_clip_from_text)
        self.modeling_record_free_button.clicked.connect(self.record_free_modeling_clip)
        self.modeling_save_text_button.clicked.connect(self.save_modeling_clip_transcript_from_editor)
        text_actions.addWidget(self.modeling_generate_text_button)
        text_actions.addWidget(self.modeling_load_text_button)
        text_actions.addWidget(self.modeling_reset_prompt_history_button)
        text_actions.addWidget(self.modeling_record_text_button)
        text_actions.addWidget(self.modeling_record_free_button)
        text_actions.addStretch(1)
        text_actions.addWidget(self.modeling_save_text_button)
        self.modeling_dataset_status = QLabel("Ready.")
        self.modeling_dataset_status.setObjectName("StatusText")
        editor_card.content_layout.addWidget(self.modeling_clip_text_edit)
        editor_card.content_layout.addWidget(self.modeling_clip_text_counter)
        editor_card.content_layout.addWidget(self.modeling_recording_guidance_label)
        editor_card.content_layout.addWidget(self.modeling_prompt_usage_label)
        editor_card.content_layout.addLayout(microphone_row)
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
        self.refresh_modeling_microphones()
        self.refresh_modeling_datasets_page()
        layout.addStretch(1)
        return page
