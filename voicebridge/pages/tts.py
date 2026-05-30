import asyncio
import os
import re
import shutil
import tempfile
import threading
import webbrowser
from collections.abc import Callable
from pathlib import Path

import aiohttp
import edge_tts
from edge_tts.exceptions import EdgeTTSException
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from voicebridge.constants import (
    DEFAULT_RATE,
    DEFAULT_VOICE_SHORT_NAME,
    RATE_CHOICES,
    STT_DEVICE_BY_LABEL,
    STT_DEVICE_LABEL_BY_KEY,
    STT_DEVICE_LABELS,
    TTS_ENGINE_BY_LABEL,
    TTS_ENGINE_LABEL_BY_KEY,
    TTS_ENGINE_LABELS,
    TTS_SPLIT_LINES,
    TTS_SPLIT_PARAGRAPHS,
)
from voicebridge.languages import language_name
from voicebridge.media_tools import concatenate_mp3_files
from voicebridge.models import TtsSegment
from voicebridge.readers import (
    SUPPORTED_FILETYPES,
    TESSERACT_NOT_INSTALLED_TEXT,
    TESSERACT_WINDOWS_INSTALL_URL,
    WORD_REQUIRED_TEXT,
    detect_text_language,
    file_signature,
    read_input_file,
    read_txt,
)
from voicebridge.tts_engine import TtsCancelled, ensure_mp3_suffix, generate_audio, suggested_output_path
from voicebridge.ui.helpers import open_path, qt_file_filter
from voicebridge.ui.widgets import Card, FilePicker
from voicebridge.voice_profiles import (
    VoiceProfile,
    ready_voice_profiles,
    voice_profile_display_label,
    voice_profile_status,
)
from voicebridge.voices import (
    FALLBACK_VOICES,
    build_voice_options,
    filter_voices_by_language,
    filter_voices_by_query,
    find_voice_label,
    save_preferred_voice_short_names,
)


class TtsWorkflowMixin:
    def tts_engine_key(self):
        engine = self.tts_engine_combo.currentData()
        return engine if isinstance(engine, str) and engine in TTS_ENGINE_LABEL_BY_KEY else "edge"

    def set_tts_engine_key(self, engine):
        engine = engine if isinstance(engine, str) and engine in TTS_ENGINE_LABEL_BY_KEY else "edge"
        for index in range(self.tts_engine_combo.count()):
            if self.tts_engine_combo.itemData(index) == engine:
                self.tts_engine_combo.setCurrentIndex(index)
                return

    def tts_engine_changed(self):
        self.update_tts_engine_ui()
        self.save_user_settings()

    def tts_local_device_key(self):
        device = self.tts_local_device_combo.currentData()
        return device if isinstance(device, str) and device in STT_DEVICE_LABEL_BY_KEY else "auto"

    def set_tts_local_device_key(self, device):
        device = device if isinstance(device, str) and device in STT_DEVICE_LABEL_BY_KEY else "auto"
        for index in range(self.tts_local_device_combo.count()):
            if self.tts_local_device_combo.itemData(index) == device:
                self.tts_local_device_combo.setCurrentIndex(index)
                return

    def tts_local_device_changed(self):
        if self.tts_local_device_key() == "cuda" and not self.stt_cuda_available:
            self.set_tts_local_device_key("auto")
        self.save_user_settings()

    def update_tts_local_device_options(self):
        if not hasattr(self, "tts_local_device_combo"):
            return
        selected_device = self.tts_local_device_key()
        if selected_device == "cuda" and not self.stt_cuda_available:
            selected_device = "auto"
        self.tts_local_device_combo.blockSignals(True)
        try:
            for index in range(self.tts_local_device_combo.count()):
                device = self.tts_local_device_combo.itemData(index)
                item = self.tts_local_device_combo.model().item(index)
                enabled = device != "cuda" or self.stt_cuda_available
                if item is not None:
                    item.setEnabled(enabled)
                if device == "auto":
                    tooltip = "Uses CUDA when available; otherwise falls back to CPU."
                elif device == "cpu":
                    tooltip = "Forces CPU execution."
                elif enabled:
                    tooltip = "Uses the detected CUDA GPU."
                else:
                    tooltip = "CUDA is not available in the current ML runtime on this machine."
                self.tts_local_device_combo.setItemData(index, tooltip)
            self.set_tts_local_device_key(selected_device)
        finally:
            self.tts_local_device_combo.blockSignals(False)

    def selected_tts_voice_profile(self) -> VoiceProfile | None:
        profile_id = self.local_voice_profile_combo.currentData()
        if not isinstance(profile_id, str) or not profile_id:
            return None
        return next((profile for profile in self.voice_profiles if profile["id"] == profile_id), None)

    def refresh_local_voice_profile_combo(self, preferred_profile_id=None):
        if not hasattr(self, "local_voice_profile_combo"):
            return
        previous_profile_id = self.local_voice_profile_combo.currentData()
        target_profile_id = preferred_profile_id or previous_profile_id or self.saved_tts_voice_profile_id
        profiles = ready_voice_profiles(self.voice_profiles)

        self.local_voice_profile_combo.blockSignals(True)
        try:
            self.local_voice_profile_combo.clear()
            if not profiles:
                self.local_voice_profile_combo.addItem("No ready voice profiles", "")
                self.local_voice_profile_combo.setEnabled(False)
            else:
                for profile in profiles:
                    self.local_voice_profile_combo.addItem(voice_profile_display_label(profile), profile["id"])
                self.local_voice_profile_combo.setEnabled(True)
                if target_profile_id:
                    for index in range(self.local_voice_profile_combo.count()):
                        if self.local_voice_profile_combo.itemData(index) == target_profile_id:
                            self.local_voice_profile_combo.setCurrentIndex(index)
                            break
        finally:
            self.local_voice_profile_combo.blockSignals(False)
        self.update_local_voice_profile_status()

    def local_voice_profile_changed(self):
        profile = self.selected_tts_voice_profile()
        self.saved_tts_voice_profile_id = profile["id"] if profile else ""
        self.update_local_voice_profile_status()
        self.save_user_settings()

    def update_local_voice_profile_status(self):
        if not hasattr(self, "local_voice_profile_status"):
            return
        profile = self.selected_tts_voice_profile()
        if profile:
            self.local_voice_profile_status.setText(
                f"{voice_profile_status(profile)} | {Path(profile['reference_paths'][0]).name}"
            )
        else:
            self.local_voice_profile_status.setText("Create a ready reference profile in Voice Profiles.")
        self.update_tts_button_state()

    def update_tts_engine_ui(self):
        if not hasattr(self, "tts_engine_combo"):
            return
        local = self.tts_engine_key() == "local"
        self.edge_voice_panel.setVisible(not local)
        self.local_voice_panel.setVisible(local)
        if hasattr(self, "tts_multi_mode_button"):
            self.tts_multi_mode_button.setEnabled(not local)
            if local and self.tts_mode_index() == 1:
                self.set_tts_mode(0)
        if local:
            self.refresh_local_voice_profile_combo()
            self.update_tts_local_device_options()
            self.refresh_stt_preflight_async()
            self.tts_status.setText("Local TTS profile selection ready; generation worker not installed yet.")
        elif hasattr(self, "tts_status"):
            self.tts_status.setText("Ready.")
        self.update_tts_button_state()

    def start_voice_loading(self):
        self.is_loading_voices = True
        self.voice_combo.setEnabled(False)
        self.update_tts_button_state()
        threading.Thread(target=self.load_voices_worker, daemon=True).start()

    def load_voices_worker(self):
        try:
            voices = asyncio.run(edge_tts.list_voices())
            error_message = None
        except (aiohttp.ClientError, EdgeTTSException, OSError, RuntimeError, TimeoutError, ValueError) as exc:
            voices = FALLBACK_VOICES
            error_message = str(exc)
        self.post(self.voices_loaded, voices, error_message)

    def voices_loaded(self, voices, error_message):
        self.all_voices = voices
        self.voice_load_error_message = error_message or ""
        self.is_loading_voices = False
        if self.detected_language_code:
            self.apply_language_voice_filter(self.detected_language_code, self.detected_language_confidence)
        else:
            self.populate_voice_combo(
                self.all_voices,
                preferred_short_name=self.saved_tts_voice_short_name or DEFAULT_VOICE_SHORT_NAME,
            )
            self.voice_status.setText(f"Loaded {len(self.all_voices)} voices. Select a file to filter by language.")
        if error_message:
            self.voice_status.setText("Could not load the complete Edge TTS voice list. Showing fallback voices.")
        self.update_tts_button_state()
        self.refresh_home_diagnostics()

    def populate_voice_combo(self, voices, preferred_short_name=None):
        previous_short_name = self.current_voice_map.get(self.voice_combo.currentText())
        self.current_voice_candidates = list(voices)
        filtered_voices = filter_voices_by_query(self.current_voice_candidates, self.voice_search.text().strip())
        values, self.current_voice_map = build_voice_options(
            filtered_voices,
            preferred_short_names=self.preferred_voice_short_names,
        )
        self.voice_combo.blockSignals(True)
        self.voice_combo.clear()
        self.voice_combo.addItems(values)
        self.block_voice_combo.clear()
        self.block_voice_combo.addItems(values)
        target_short_name = preferred_short_name or previous_short_name
        selected_label = find_voice_label(self.current_voice_map, target_short_name)
        if not selected_label and self.current_voice_map:
            selected_label = next(iter(self.current_voice_map))
        self.voice_combo.setCurrentText(selected_label)
        self.block_voice_combo.setCurrentText(selected_label)
        self.voice_combo.blockSignals(False)
        self.last_valid_voice_label = selected_label
        self.voice_combo.setEnabled(
            bool(self.current_voice_map)
            and not self.is_loading_voices
            and not self.is_detecting_language
        )
        self.sync_voice_preferred_state()
        self.update_tts_button_state()

    def voice_selected(self, label):
        if label in self.current_voice_map:
            self.last_valid_voice_label = label
            self.saved_tts_voice_short_name = self.current_voice_map[label]
            self.sync_voice_preferred_state()
            self.save_user_settings()
            return
        if self.last_valid_voice_label:
            self.voice_combo.setCurrentText(self.last_valid_voice_label)

    def voice_search_changed(self):
        self.populate_voice_combo(self.current_voice_candidates or self.all_voices)
        if self.detected_language_code:
            self.voice_status.setText(
                f"Detected {language_name(self.detected_language_code)} "
                f"({self.detected_language_confidence:.0%}). Search filters matching voices."
            )

    def sync_voice_preferred_state(self):
        short_name = self.current_voice_map.get(self.voice_combo.currentText())
        self.voice_preferred.blockSignals(True)
        self.voice_preferred.setChecked(bool(short_name and short_name in self.preferred_voice_short_names))
        self.voice_preferred.setEnabled(bool(short_name))
        self.voice_preferred.blockSignals(False)

    def toggle_preferred_voice(self):
        short_name = self.current_voice_map.get(self.voice_combo.currentText())
        if not short_name:
            return
        if self.voice_preferred.isChecked():
            self.preferred_voice_short_names.add(short_name)
        else:
            self.preferred_voice_short_names.discard(short_name)
        save_preferred_voice_short_names(self.preferred_voice_short_names)
        self.save_user_settings()
        self.populate_voice_combo(self.current_voice_candidates or self.all_voices, preferred_short_name=short_name)

    def select_input_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select input file",
            self.tts_input_picker.text() or str(Path.home()),
            qt_file_filter(SUPPORTED_FILETYPES),
        )
        if not path:
            return
        previous = self.tts_input_picker.text()
        self.update_tts_output_path_for_input_change(previous, path)
        self.tts_input_picker.set_text(path)
        self.save_user_settings()
        self.start_language_detection(path)

    def select_save_path(self):
        initial = self.tts_output_picker.text()
        if not initial and self.tts_input_picker.text():
            initial = suggested_output_path(self.tts_input_picker.text())
        if not initial:
            initial = str(Path.home() / "audio.mp3")
        path, _ = QFileDialog.getSaveFileName(self, "Save audio as", initial, "MP3 files (*.mp3)")
        if path:
            self.tts_output_picker.set_text(ensure_mp3_suffix(path))
            self.last_auto_save_path = ""
            self.save_user_settings()

    def update_tts_output_path_for_input_change(self, previous_input_path, new_input_path):
        current = self.tts_output_picker.text()
        previous_suggestion = suggested_output_path(previous_input_path) if previous_input_path else ""
        new_suggestion = suggested_output_path(new_input_path)
        if not current or current == previous_suggestion or current == self.last_auto_save_path:
            self.tts_output_picker.set_text(new_suggestion)
            self.last_auto_save_path = new_suggestion

    def start_language_detection(self, path):
        self.detected_language_code = None
        self.detected_language_confidence = 0.0
        self.input_file_error_message = ""
        self.is_detecting_language = True
        self.voice_combo.setEnabled(False)
        self.voice_status.setText("Detecting file language...")
        self.hide_input_warning()
        self.tts_status.setText("Reading file text...")
        self.update_tts_button_state()
        threading.Thread(target=self.detect_language_worker, args=(path, file_signature(path)), daemon=True).start()

    def detect_language_worker(self, path, signature):
        try:
            text = read_input_file(path)
            if not text:
                raise ValueError("The selected file contains no readable text.")
            language_code, confidence = detect_text_language(text)
            self.post(self.language_detection_finished, path, signature, text, language_code, confidence, None)
        except (OSError, RuntimeError, ValueError) as exc:
            self.post(self.language_detection_finished, path, signature, "", None, 0.0, str(exc))

    def language_detection_finished(self, path, signature, text, language_code, confidence, error_message):
        if self.tts_input_picker.text() != path:
            return
        self.is_detecting_language = False
        self.cached_input_signature = signature
        self.cached_input_text = text
        if error_message:
            self.input_file_error_message = error_message
            self.tts_status.setText("Error.")
            self.voice_status.setText(error_message)
            self.show_input_warning_for_file(path, error_message)
        else:
            self.input_file_error_message = ""
            self.detected_language_code = language_code
            self.detected_language_confidence = confidence
            self.apply_language_voice_filter(language_code, confidence)
            self.show_input_warning_for_file(path, "")
            self.tts_status.setText("Ready.")
        self.update_tts_button_state()

    def apply_language_voice_filter(self, language_code, confidence):
        if not self.all_voices:
            return
        if language_code:
            matching = filter_voices_by_language(self.all_voices, language_code)
            self.populate_voice_combo(matching or self.all_voices)
            self.voice_status.setText(
                f"Detected {language_name(language_code)} ({confidence:.0%}). "
                f"Showing {len(matching) or len(self.all_voices)} matching voice(s)."
            )
        else:
            self.populate_voice_combo(self.all_voices, preferred_short_name=DEFAULT_VOICE_SHORT_NAME)
            self.voice_status.setText("Could not reliably detect language. Showing all voices.")

    def show_input_warning_for_file(self, path, error_message):
        suffix = Path(path).suffix.lower()
        if TESSERACT_NOT_INSTALLED_TEXT in error_message:
            self.show_input_warning(
                "OCR optional package required",
                "This PDF appears to need OCR. Install Tesseract and OCR Python packages to read scanned PDFs.",
                "Open installer page",
                self.open_tesseract_installer_page,
            )
        elif suffix == ".doc" and WORD_REQUIRED_TEXT in error_message:
            self.show_input_warning(
                "Microsoft Word required for .doc",
                "Old .doc files require Microsoft Word installed. .docx files do not require Word.",
            )
        else:
            self.hide_input_warning()

    @staticmethod
    def open_tesseract_installer_page() -> None:
        webbrowser.open(TESSERACT_WINDOWS_INSTALL_URL)

    @staticmethod
    def no_warning_action() -> None:
        return

    def show_input_warning(
        self,
        title: str,
        message: str,
        button_text: str | None = None,
        callback: Callable[[], None] | None = None,
    ) -> None:
        self.warning_title.setText(title)
        self.warning_message.setText(message)
        self.warning_callback = callback or self.no_warning_action
        self.warning_action.setVisible(bool(button_text and callback))
        self.warning_action.setText(button_text or "")
        self.warning_box.show()

    def hide_input_warning(self):
        self.warning_callback = self.no_warning_action
        self.warning_box.hide()

    def run_warning_action(self):
        self.warning_callback()

    def update_tts_button_state(self):
        common_ready = (
            not self.is_detecting_language
            and not self.is_converting
            and not self.is_stt_running
            and not self.is_video_running
            and not self.is_cleanup_running
            and not self.input_file_error_message
        )
        if self.tts_engine_key() == "local":
            ready = common_ready and bool(self.selected_tts_voice_profile())
        else:
            ready = common_ready and not self.is_loading_voices and bool(self.current_voice_map)
        self.tts_generate_button.setEnabled(ready)
        self.tts_cancel_button.setEnabled(self.is_converting and not self.tts_cancel_requested)
        output_ready = bool(self.tts_last_output_path and Path(self.tts_last_output_path).is_file())
        self.tts_open_output_button.setEnabled(output_ready)
        self.tts_open_folder_button.setEnabled(output_ready)
        self.update_navigation_state()

    def current_tts_input_text(self, preserve_text_layout=False):
        input_path = self.tts_input_picker.text()
        if not input_path:
            raise ValueError("Please select an input file.")
        if not os.path.isfile(input_path):
            raise ValueError("The selected input file does not exist.")
        if self.input_file_error_message:
            raise ValueError(self.input_file_error_message)
        if preserve_text_layout and Path(input_path).suffix.lower() in {".txt", ".md"}:
            return read_txt(input_path).replace("\r\n", "\n").replace("\r", "\n").strip()
        signature = file_signature(input_path)
        if signature == self.cached_input_signature and self.cached_input_text:
            return self.cached_input_text
        return read_input_file(input_path)

    def selected_voice_assignment(self) -> tuple[str, str]:
        voice_label = self.voice_combo.currentText()
        voice_short_name = self.current_voice_map.get(voice_label, "")
        if not voice_short_name:
            raise ValueError("Please select a valid voice.")
        return voice_label, voice_short_name

    def split_tts_text_blocks(self, text):
        if self.tts_split_combo.currentText() == TTS_SPLIT_LINES:
            blocks = [line.strip() for line in text.splitlines() if line.strip()]
        else:
            blocks = [
                self.normalize_tts_block_text(block)
                for block in re.split(r"\n\s*\n+", text)
                if self.normalize_tts_block_text(block)
            ]
        return blocks or ([text.strip()] if text.strip() else [])

    @staticmethod
    def normalize_tts_block_text(text):
        lines = [
            re.sub(r"[ \t]+", " ", line.strip())
            for line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
        ]
        return "\n".join(line for line in lines if line).strip()

    def split_tts_document_into_blocks(self):
        try:
            text = self.current_tts_input_text(preserve_text_layout=True)
            voice_label, voice_short_name = self.selected_voice_assignment()
        except (OSError, RuntimeError, ValueError) as exc:
            self.tts_status.setText("Error.")
            self.show_error("Error", str(exc))
            return
        blocks = self.split_tts_text_blocks(text)
        if not blocks:
            self.show_error("Error", "The selected file contains no readable text.")
            return
        segments: list[TtsSegment] = []
        for block in blocks:
            segments.append(
                {
                    "text": block,
                    "voice_label": voice_label,
                    "voice_short_name": voice_short_name,
                    "rate": self.rate_combo.currentText(),
                }
            )
        self.tts_segments = segments
        self.selected_tts_segment_index = 0
        self.refresh_tts_blocks_list()
        self.tts_blocks_list.setCurrentRow(0)
        self.tts_status.setText(f"Prepared {len(self.tts_segments)} text block(s).")

    @staticmethod
    def tts_segment_summary(index: int, segment: TtsSegment) -> str:
        voice = segment.get("voice_label") or segment.get("voice_short_name") or "No voice"
        voice = voice.split(" - ", 1)[0].strip()
        return f"{index + 1:02d}. {voice} | {segment.get('rate', DEFAULT_RATE)} | {len(segment.get('text', ''))} chars"

    def refresh_tts_blocks_list(self):
        self.tts_blocks_list.clear()
        for index, segment in enumerate(self.tts_segments):
            self.tts_blocks_list.addItem(self.tts_segment_summary(index, segment))

    def tts_segment_at(self, index: int) -> TtsSegment:
        return self.tts_segments[index]

    def load_tts_block_editor(self, index: int) -> None:
        if not (0 <= index < len(self.tts_segments)):
            self.selected_tts_segment_index = None
            self.tts_block_preview.clear()
            return
        self.selected_tts_segment_index = index
        segment = self.tts_segment_at(index)
        self.block_voice_combo.setCurrentText(segment.get("voice_label", ""))
        self.block_rate_combo.setCurrentText(segment.get("rate", DEFAULT_RATE))
        self.tts_block_preview.setPlainText(segment.get("text", ""))

    def selected_block_rows(self) -> list[int]:
        return sorted(index.row() for index in self.tts_blocks_list.selectedIndexes())

    def merge_selected_tts_blocks(self):
        selection = self.selected_block_rows()
        if len(selection) < 2:
            self.show_info("Merge selected", "Select at least two adjacent blocks to merge.")
            return
        if selection != list(range(selection[0], selection[-1] + 1)):
            self.show_error("Merge selected", "Only adjacent blocks can be merged.")
            return
        first = selection[0]
        first_segment = self.tts_segment_at(first)
        merged_text = "\n\n".join(self.tts_segments[index]["text"].strip() for index in selection)
        merged_segment: TtsSegment = {
            "text": merged_text,
            "voice_label": first_segment.get("voice_label", ""),
            "voice_short_name": first_segment.get("voice_short_name", ""),
            "rate": first_segment.get("rate", DEFAULT_RATE),
        }
        updated_segments: list[TtsSegment] = []
        last = selection[-1]
        for index, segment in enumerate(self.tts_segments):
            if index < first or index > last:
                updated_segments.append(segment)
            elif index == first:
                updated_segments.append(merged_segment)
        self.tts_segments = updated_segments
        self.refresh_tts_blocks_list()
        self.tts_blocks_list.setCurrentRow(first)
        self.tts_status.setText(f"Merged {len(selection)} block(s).")

    def apply_block_settings_to_selected(self):
        index = self.selected_tts_segment_index
        if index is None or not (0 <= index < len(self.tts_segments)):
            return
        voice_label = self.block_voice_combo.currentText()
        voice_short_name = self.current_voice_map.get(voice_label, "")
        rate = self.block_rate_combo.currentText()
        if not voice_short_name or rate not in RATE_CHOICES:
            self.show_error("Error", "Please select a valid block voice and speed.")
            return
        self.tts_segments[index].update({
            "voice_label": voice_label,
            "voice_short_name": voice_short_name,
            "rate": rate,
        })
        self.refresh_tts_blocks_list()
        self.tts_blocks_list.setCurrentRow(index)
        self.tts_status.setText(f"Updated block {index + 1}.")

    def apply_current_voice_to_selected_block(self):
        index = self.selected_tts_segment_index
        if index is None or not (0 <= index < len(self.tts_segments)):
            return
        try:
            voice_label, voice_short_name = self.selected_voice_assignment()
        except ValueError as exc:
            self.show_error("Error", str(exc))
            return
        self.tts_segments[index].update({
            "voice_label": voice_label,
            "voice_short_name": voice_short_name,
            "rate": self.rate_combo.currentText(),
        })
        self.refresh_tts_blocks_list()
        self.tts_blocks_list.setCurrentRow(index)

    def apply_current_voice_to_all_blocks(self):
        if not self.tts_segments:
            return
        try:
            voice_label, voice_short_name = self.selected_voice_assignment()
        except ValueError as exc:
            self.show_error("Error", str(exc))
            return
        for segment in self.tts_segments:
            segment["voice_label"] = voice_label
            segment["voice_short_name"] = voice_short_name
            segment["rate"] = self.rate_combo.currentText()
        self.refresh_tts_blocks_list()
        if self.selected_tts_segment_index is not None:
            self.tts_blocks_list.setCurrentRow(self.selected_tts_segment_index)
        self.tts_status.setText(f"Applied current voice to {len(self.tts_segments)} block(s).")

    def collect_single_tts_options(self):
        input_path = self.tts_input_picker.text()
        save_path = self.tts_output_picker.text()
        if not input_path:
            raise ValueError("Please select an input file.")
        if not os.path.isfile(input_path):
            raise ValueError("The selected input file does not exist.")
        if not save_path:
            raise ValueError("Please choose where to save the MP3.")
        save_path = ensure_mp3_suffix(save_path)
        save_dir = os.path.dirname(os.path.abspath(save_path))
        if not os.path.isdir(save_dir):
            raise ValueError("The output folder does not exist.")
        if self.is_loading_voices:
            raise ValueError("The voice list is still loading. Please wait a moment.")
        if self.is_detecting_language:
            raise ValueError("Language detection is still running. Please wait a moment.")
        if self.input_file_error_message:
            raise ValueError(self.input_file_error_message)
        voice_label, voice = self.selected_voice_assignment()
        rate = self.rate_combo.currentText()
        if rate not in RATE_CHOICES:
            raise ValueError("Please select a valid speed.")
        self.tts_output_picker.set_text(save_path)
        self.save_user_settings()
        return input_path, save_path, voice, rate

    def collect_local_tts_options(self):
        input_path = self.tts_input_picker.text()
        save_path = self.tts_output_picker.text()
        profile = self.selected_tts_voice_profile()
        if not input_path:
            raise ValueError("Please select an input file.")
        if not os.path.isfile(input_path):
            raise ValueError("The selected input file does not exist.")
        if not save_path:
            raise ValueError("Please choose where to save the MP3.")
        save_path = ensure_mp3_suffix(save_path)
        if not os.path.isdir(os.path.dirname(os.path.abspath(save_path))):
            raise ValueError("The output folder does not exist.")
        if self.is_detecting_language:
            raise ValueError("Language detection is still running. Please wait a moment.")
        if self.input_file_error_message:
            raise ValueError(self.input_file_error_message)
        if not profile:
            raise ValueError("Please create and select a ready voice profile.")
        if self.tts_local_device_key() == "cuda" and not self.stt_cuda_available:
            raise ValueError("CUDA is not available in the current ML runtime on this machine.")
        self.tts_output_picker.set_text(save_path)
        self.save_user_settings()
        return input_path, save_path, profile, self.tts_local_device_key()

    def collect_multi_tts_options(self):
        save_path = self.tts_output_picker.text()
        if not save_path:
            raise ValueError("Please choose where to save the MP3.")
        save_path = ensure_mp3_suffix(save_path)
        if not os.path.isdir(os.path.dirname(os.path.abspath(save_path))):
            raise ValueError("The output folder does not exist.")
        if not self.tts_segments:
            self.split_tts_document_into_blocks()
        segments = []
        for index, segment in enumerate(self.tts_segments, start=1):
            text = segment.get("text", "").strip()
            voice_short_name = segment.get("voice_short_name", "").strip()
            rate = segment.get("rate", DEFAULT_RATE)
            if not text:
                continue
            if not voice_short_name:
                raise ValueError(f"Block {index} has no voice selected.")
            if rate not in RATE_CHOICES:
                raise ValueError(f"Block {index} has an invalid speed.")
            segments.append({"text": text, "voice_short_name": voice_short_name, "rate": rate})
        if not segments:
            raise ValueError("No text blocks are ready for generation.")
        self.tts_output_picker.set_text(save_path)
        self.save_user_settings()
        return save_path, segments

    def start_tts_conversion(self):
        if self.tts_engine_key() == "local":
            self.start_local_tts_conversion()
            return
        if self.tts_mode_index() == 1:
            self.start_multi_voice_conversion()
            return
        try:
            input_path, save_path, voice, rate = self.collect_single_tts_options()
        except ValueError as exc:
            self.tts_status.setText("Error.")
            self.show_error("Error", str(exc))
            return
        signature = file_signature(input_path)
        cached_text = self.cached_input_text if signature == self.cached_input_signature else None
        self.start_tts_busy("Reading file...")
        threading.Thread(
            target=self.conversion_worker,
            args=(input_path, save_path, voice, rate, cached_text),
            daemon=True,
        ).start()

    def start_multi_voice_conversion(self):
        try:
            save_path, segments = self.collect_multi_tts_options()
        except ValueError as exc:
            self.tts_status.setText("Error.")
            self.show_error("Error", str(exc))
            return
        self.start_tts_busy("Generating multi-voice audio...", percent=True)
        threading.Thread(target=self.multi_voice_conversion_worker, args=(save_path, segments), daemon=True).start()

    def start_local_tts_conversion(self):
        try:
            self.collect_local_tts_options()
        except ValueError as exc:
            self.tts_status.setText("Error.")
            self.show_error("Local TTS", str(exc))
            return
        self.tts_status.setText("Local TTS engine not installed.")
        self.show_info(
            "Local TTS",
            "Voice profile selection is ready. The next step will add the local XTTS worker.",
        )

    def start_tts_busy(self, status, percent=False):
        self.is_converting = True
        self.tts_cancel_requested = False
        self.tts_last_output_path = ""
        if percent:
            self.show_percent_progress(self.tts_progress, 0)
        else:
            self.show_indeterminate_progress(self.tts_progress)
        self.tts_status.setText(status)
        self.update_tts_button_state()
        self.update_stt_button_state()
        self.update_video_subtitle_button_state()
        self.update_video_cleanup_button_state()

    def conversion_worker(self, input_path, save_path, voice, rate, cached_text):
        try:
            text = cached_text if cached_text is not None else read_input_file(input_path)
            if self.tts_cancel_requested:
                raise TtsCancelled()
            if not text.strip():
                raise ValueError("The selected file appears to contain no readable text.")
            self.post(self.tts_status.setText, "Generating audio... please wait.")
            with tempfile.TemporaryDirectory(prefix="voicebridge-tts-") as temp_dir:
                temp_output = Path(temp_dir) / Path(save_path).name
                asyncio.run(
                    generate_audio(
                        text,
                        voice,
                        str(temp_output),
                        rate,
                        should_cancel=lambda: self.tts_cancel_requested,
                    )
                )
                if self.tts_cancel_requested:
                    raise TtsCancelled()
                os.replace(temp_output, save_path)
            self.post(self.conversion_succeeded, save_path)
        except TtsCancelled:
            self.post(self.conversion_cancelled)
        except (aiohttp.ClientError, EdgeTTSException, OSError, RuntimeError, TimeoutError, ValueError) as exc:
            self.post(self.conversion_failed, str(exc))
        finally:
            self.post(self.finish_tts_conversion)

    def multi_voice_conversion_worker(self, save_path, segments):
        try:
            with tempfile.TemporaryDirectory(prefix="voicebridge-tts-") as temp_dir_name:
                temp_dir = Path(temp_dir_name)
                part_paths = []
                total = max(1, len(segments))
                for index, segment in enumerate(segments, start=1):
                    if self.tts_cancel_requested:
                        raise TtsCancelled()
                    part_path = temp_dir / f"part-{index:04d}.mp3"
                    self.post(self.tts_status.setText, f"Generating block {index}/{len(segments)}...")
                    self.post(self.update_tts_progress_percent, ((index - 1) / total) * 90)
                    asyncio.run(
                        generate_audio(
                            segment["text"],
                            segment["voice_short_name"],
                            str(part_path),
                            segment["rate"],
                            should_cancel=lambda: self.tts_cancel_requested,
                        )
                    )
                    if self.tts_cancel_requested:
                        raise TtsCancelled()
                    part_paths.append(part_path)
                    self.post(self.update_tts_progress_percent, (index / total) * 90)
                self.post(self.tts_status.setText, "Merging audio blocks...")
                self.post(self.update_tts_progress_percent, 95)
                temp_output = temp_dir / Path(save_path).name
                if len(part_paths) == 1:
                    shutil.copy2(part_paths[0], temp_output)
                else:
                    concatenate_mp3_files(part_paths, temp_output)
                if self.tts_cancel_requested:
                    raise TtsCancelled()
                os.replace(temp_output, save_path)
                self.post(self.update_tts_progress_percent, 100)
            self.post(self.conversion_succeeded, save_path)
        except TtsCancelled:
            self.post(self.conversion_cancelled)
        except (aiohttp.ClientError, EdgeTTSException, OSError, RuntimeError, TimeoutError, ValueError) as exc:
            self.post(self.conversion_failed, str(exc))
        finally:
            self.post(self.finish_tts_conversion)

    def conversion_succeeded(self, save_path):
        self.tts_last_output_path = save_path
        self.tts_status.setText("Done.")
        self.record_job("TTS", "MP3 generated", self.tts_input_picker.text(), save_path)
        self.show_info("Success", f"Audio saved:\n{save_path}")

    def conversion_failed(self, message):
        self.tts_status.setText("Error.")
        self.show_error("Error", message)

    def conversion_cancelled(self):
        self.tts_status.setText("Cancelled.")

    def finish_tts_conversion(self):
        self.is_converting = False
        self.tts_progress.hide()
        self.update_tts_button_state()
        self.update_stt_button_state()
        self.update_video_subtitle_button_state()
        self.update_video_cleanup_button_state()

    def cancel_tts_conversion(self):
        if not self.is_converting:
            return
        self.tts_cancel_requested = True
        self.tts_status.setText("Cancelling TTS job...")
        self.update_tts_button_state()

    def open_tts_output(self):
        open_path(self.tts_last_output_path)

    def open_tts_output_folder(self):
        if self.tts_last_output_path and Path(self.tts_last_output_path).is_file():
            open_path(Path(self.tts_last_output_path).parent)

    def build_tts_page(self):
        page, layout = self.page_container()
        self.page_header(
            layout,
            "TTS",
            "Text to Speech",
            "Generate MP3 with online Edge voices or prepared local voice profiles.",
            "BadgeBlue",
        )

        main_grid = QGridLayout()
        main_grid.setSpacing(16)
        layout.addLayout(main_grid)

        files_card = Card("Files and mode")
        files_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.tts_input_picker = FilePicker("Input file")
        self.tts_output_picker = FilePicker("Save MP3 as", "Save as...")
        self.tts_input_picker.button.clicked.connect(self.select_input_file)
        self.tts_output_picker.button.clicked.connect(self.select_save_path)
        files_card.content_layout.addWidget(self.tts_input_picker)
        files_card.content_layout.addWidget(self.tts_output_picker)
        mode_label = QLabel("Voice mode")
        mode_label.setObjectName("FieldLabel")
        self.tts_single_mode_button = QPushButton("Single voice")
        self.tts_multi_mode_button = QPushButton("Multi-voice blocks")
        for button in (self.tts_single_mode_button, self.tts_multi_mode_button):
            button.setObjectName("SegmentButton")
            button.setCheckable(True)
            button.setMinimumHeight(36)
        self.tts_single_mode_button.clicked.connect(lambda _checked=False: self.set_tts_mode(0))
        self.tts_multi_mode_button.clicked.connect(lambda _checked=False: self.set_tts_mode(1))
        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_row.setSpacing(8)
        mode_row.addWidget(self.tts_single_mode_button)
        mode_row.addWidget(self.tts_multi_mode_button)
        mode_row.addStretch(1)
        self.tts_mode_note = QLabel()
        self.tts_mode_note.setObjectName("Muted")
        self.tts_mode_note.setWordWrap(True)
        files_card.content_layout.addSpacing(4)
        files_card.content_layout.addWidget(mode_label)
        files_card.content_layout.addLayout(mode_row)
        files_card.content_layout.addWidget(self.tts_mode_note)

        self.warning_box = QFrame()
        self.warning_box.setObjectName("WarningBox")
        warning_layout = QVBoxLayout(self.warning_box)
        warning_layout.setContentsMargins(12, 10, 12, 10)
        self.warning_title = QLabel()
        self.warning_title.setObjectName("FieldLabel")
        self.warning_message = QLabel()
        self.warning_message.setWordWrap(True)
        self.warning_message.setObjectName("Muted")
        self.warning_action = QPushButton()
        self.warning_action.setObjectName("SecondaryButton")
        self.warning_action.clicked.connect(self.run_warning_action)
        warning_layout.addWidget(self.warning_title)
        warning_layout.addWidget(self.warning_message)
        warning_layout.addWidget(self.warning_action)
        self.warning_box.hide()
        files_card.content_layout.addWidget(self.warning_box)

        voice_card = Card("Voice")
        voice_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.tts_engine_combo = QComboBox()
        for label in TTS_ENGINE_LABELS:
            self.tts_engine_combo.addItem(label, TTS_ENGINE_BY_LABEL[label])
        self.tts_engine_combo.currentTextChanged.connect(lambda _text: self.tts_engine_changed())
        voice_card.content_layout.addWidget(QLabel("Engine"))
        voice_card.content_layout.addWidget(self.tts_engine_combo)

        self.edge_voice_panel = QWidget()
        edge_voice_layout = QVBoxLayout(self.edge_voice_panel)
        edge_voice_layout.setContentsMargins(0, 0, 0, 0)
        edge_voice_layout.setSpacing(10)
        self.voice_status = QLabel("Loading complete voice list...")
        self.voice_status.setObjectName("Muted")
        self.voice_combo = QComboBox()
        self.voice_combo.setEditable(False)
        self.voice_combo.currentTextChanged.connect(self.voice_selected)
        self.voice_search = QLineEdit()
        self.voice_search.setPlaceholderText("Search voice, locale or style")
        self.voice_search.textChanged.connect(self.voice_search_changed)
        self.voice_preferred = QCheckBox("Preferred voice")
        self.voice_preferred.stateChanged.connect(self.toggle_preferred_voice)
        self.rate_combo = QComboBox()
        self.rate_combo.addItems(RATE_CHOICES)
        self.rate_combo.setCurrentText(DEFAULT_RATE)
        self.rate_combo.currentTextChanged.connect(lambda _text: self.save_user_settings())
        edge_voice_layout.addWidget(self.voice_status)
        edge_voice_layout.addWidget(QLabel("Voice"))
        edge_voice_layout.addWidget(self.voice_combo)
        edge_voice_layout.addWidget(QLabel("Search"))
        edge_voice_layout.addWidget(self.voice_search)
        voice_row = QHBoxLayout()
        voice_row.addWidget(self.voice_preferred)
        voice_row.addStretch(1)
        voice_row.addWidget(QLabel("Speed"))
        voice_row.addWidget(self.rate_combo)
        edge_voice_layout.addLayout(voice_row)

        self.local_voice_panel = QWidget()
        local_voice_layout = QVBoxLayout(self.local_voice_panel)
        local_voice_layout.setContentsMargins(0, 0, 0, 0)
        local_voice_layout.setSpacing(10)
        self.local_voice_profile_combo = QComboBox()
        self.local_voice_profile_combo.currentTextChanged.connect(lambda _text: self.local_voice_profile_changed())
        manage_profiles_button = QPushButton("Manage profiles")
        manage_profiles_button.clicked.connect(lambda _checked=False: self.show_page(2))
        profile_row = QHBoxLayout()
        profile_row.setContentsMargins(0, 0, 0, 0)
        profile_row.addWidget(self.local_voice_profile_combo, 1)
        profile_row.addWidget(manage_profiles_button)
        self.local_voice_profile_status = QLabel("Create a ready reference profile in Voice Profiles.")
        self.local_voice_profile_status.setObjectName("Muted")
        self.local_voice_profile_status.setWordWrap(True)
        self.tts_local_device_combo = QComboBox()
        for label in STT_DEVICE_LABELS:
            self.tts_local_device_combo.addItem(label, STT_DEVICE_BY_LABEL[label])
        self.tts_local_device_combo.currentTextChanged.connect(lambda _text: self.tts_local_device_changed())
        local_device_row = QHBoxLayout()
        local_device_row.setContentsMargins(0, 0, 0, 0)
        local_device_row.addWidget(QLabel("Device"))
        local_device_row.addWidget(self.tts_local_device_combo)
        local_device_row.addStretch(1)
        local_voice_layout.addWidget(QLabel("Voice profile"))
        local_voice_layout.addLayout(profile_row)
        local_voice_layout.addWidget(self.local_voice_profile_status)
        local_voice_layout.addLayout(local_device_row)

        voice_card.content_layout.addWidget(self.edge_voice_panel)
        voice_card.content_layout.addWidget(self.local_voice_panel)

        main_grid.addWidget(files_card, 0, 0)
        main_grid.addWidget(voice_card, 0, 1)
        main_grid.setColumnStretch(0, 1)
        main_grid.setColumnStretch(1, 1)

        self.tts_mode_stack = QStackedWidget()
        self.single_tts_page = self.build_single_tts_page()
        self.multi_tts_tab = self.build_multi_tts_tab()
        self.tts_mode_stack.addWidget(self.single_tts_page)
        self.tts_mode_stack.addWidget(self.multi_tts_tab)
        self.tts_mode_stack.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.tts_mode_stack, 1)

        action_bar = Card()
        action_bar.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        action_layout = QHBoxLayout()
        action_layout.setContentsMargins(0, 0, 0, 0)
        self.tts_generate_button = QPushButton("Generate MP3")
        self.tts_generate_button.setObjectName("PrimaryButton")
        self.tts_cancel_button = QPushButton("Cancel")
        self.tts_open_output_button = QPushButton("Open output")
        self.tts_open_folder_button = QPushButton("Open folder")
        self.tts_generate_button.clicked.connect(self.start_tts_conversion)
        self.tts_cancel_button.clicked.connect(self.cancel_tts_conversion)
        self.tts_open_output_button.clicked.connect(self.open_tts_output)
        self.tts_open_folder_button.clicked.connect(self.open_tts_output_folder)
        action_layout.addWidget(self.tts_generate_button)
        action_layout.addWidget(self.tts_cancel_button)
        action_layout.addStretch(1)
        action_layout.addWidget(self.tts_open_output_button)
        action_layout.addWidget(self.tts_open_folder_button)
        action_bar.content_layout.addLayout(action_layout)
        self.tts_progress = QProgressBar()
        self.tts_progress.setRange(0, 0)
        self.tts_progress.hide()
        self.tts_status = QLabel("Ready.")
        self.tts_status.setObjectName("StatusText")
        action_bar.content_layout.addWidget(self.tts_progress)
        action_bar.content_layout.addWidget(self.tts_status)
        layout.addWidget(action_bar)
        layout.addStretch(1)

        self.set_tts_mode(0)
        self.refresh_local_voice_profile_combo()
        self.update_tts_local_device_options()
        self.set_tts_engine_key("edge")
        self.update_tts_engine_ui()
        return page

    @staticmethod
    def build_single_tts_page():
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        return tab

    def tts_mode_index(self):
        if not hasattr(self, "tts_mode_stack"):
            return 0
        return self.tts_mode_stack.currentIndex()

    def set_tts_mode(self, index):
        index = 1 if index == 1 else 0
        if not hasattr(self, "tts_mode_stack"):
            return
        self.tts_mode_stack.setCurrentIndex(index)
        self.tts_mode_stack.setVisible(index == 1)
        self.tts_single_mode_button.setChecked(index == 0)
        self.tts_multi_mode_button.setChecked(index == 1)
        self.tts_mode_note.setText(
            "Uses the selected voice and speed for the whole document."
            if index == 0
            else "Split the document into blocks and assign voice or speed per block."
        )
        self.tts_mode_stack.updateGeometry()
        self.update_tts_button_state()
        self.save_user_settings()

    def build_multi_tts_tab(self):
        tab = QWidget()
        layout = QGridLayout(tab)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(16)

        left = Card("Blocks")
        split_row = QHBoxLayout()
        self.tts_split_combo = QComboBox()
        self.tts_split_combo.addItems([TTS_SPLIT_PARAGRAPHS, TTS_SPLIT_LINES])
        self.tts_split_combo.currentTextChanged.connect(lambda _text: self.save_user_settings())
        split_button = QPushButton("Split document")
        merge_button = QPushButton("Merge selected")
        split_button.clicked.connect(self.split_tts_document_into_blocks)
        merge_button.clicked.connect(self.merge_selected_tts_blocks)
        split_row.addWidget(self.tts_split_combo)
        split_row.addWidget(split_button)
        split_row.addWidget(merge_button)
        left.content_layout.addLayout(split_row)
        self.tts_blocks_list = QListWidget()
        self.tts_blocks_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tts_blocks_list.currentRowChanged.connect(self.load_tts_block_editor)
        self.tts_blocks_list.setMinimumHeight(220)
        left.content_layout.addWidget(self.tts_blocks_list, 1)

        right = Card("Block settings")
        self.block_voice_combo = QComboBox()
        self.block_rate_combo = QComboBox()
        self.block_rate_combo.addItems(RATE_CHOICES)
        self.block_rate_combo.setCurrentText(DEFAULT_RATE)
        right.content_layout.addWidget(QLabel("Block voice"))
        right.content_layout.addWidget(self.block_voice_combo)
        rate_row = QHBoxLayout()
        rate_row.addWidget(QLabel("Block speed"))
        rate_row.addWidget(self.block_rate_combo)
        rate_row.addStretch(1)
        right.content_layout.addLayout(rate_row)
        settings_row = QHBoxLayout()
        apply_selected = QPushButton("Apply to block")
        apply_current = QPushButton("Use current voice")
        apply_all = QPushButton("Use current voice for all")
        apply_selected.clicked.connect(self.apply_block_settings_to_selected)
        apply_current.clicked.connect(self.apply_current_voice_to_selected_block)
        apply_all.clicked.connect(self.apply_current_voice_to_all_blocks)
        settings_row.addWidget(apply_selected)
        settings_row.addWidget(apply_current)
        settings_row.addWidget(apply_all)
        right.content_layout.addLayout(settings_row)
        self.tts_block_preview = QPlainTextEdit()
        self.tts_block_preview.setReadOnly(True)
        self.tts_block_preview.setPlaceholderText("Select a block to preview the text.")
        self.tts_block_preview.setMinimumHeight(220)
        right.content_layout.addWidget(self.tts_block_preview, 1)

        layout.addWidget(left, 0, 0)
        layout.addWidget(right, 0, 1)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 2)
        return tab

