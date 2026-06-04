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
from PySide6.QtCore import Qt, QTimer
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

from voicebridge.app_paths import (
    external_base_dir,
    local_tts_model_cache_dir,
    local_tts_model_dir,
    local_tts_model_ready,
    local_tts_worker_path,
    ml_python_path,
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
from voicebridge.file_checks import ensure_free_space, partial_download_files, validate_output_path
from voicebridge.languages import language_name
from voicebridge.local_tts_presets import (
    DEFAULT_LOCAL_TTS_PRESET_KEY,
    LOCAL_TTS_PRESETS,
    local_tts_preset_description,
    normalize_local_tts_preset_key,
)
from voicebridge.local_voice_sources import (
    LocalVoiceSource,
    grouped_local_voice_sources,
    local_voice_display_label,
    local_voice_from_reference_profile,
    local_voice_model_args,
    local_voice_requires_base_xtts,
    local_voice_status_text,
    ready_local_voice_sources,
)
from voicebridge.media_tools import audio_duration_seconds, concatenate_mp3_files, convert_audio_to_mp3
from voicebridge.models import TtsSegment
from voicebridge.process_jobs import WorkerProcessOutput, run_worker_process_job
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
from voicebridge.runtime_errors import is_cuda_runtime_failure
from voicebridge.tts_engine import TtsCancelled, ensure_mp3_suffix, generate_audio, suggested_output_path
from voicebridge.tts_text import split_tts_text_for_tts
from voicebridge.tts_timeline import load_local_tts_chunk_timeline, remove_tts_timeline, write_tts_timeline
from voicebridge.ui.helpers import open_path, qt_file_filter
from voicebridge.ui.widgets import Card, FilePicker
from voicebridge.voice_profiles import VoiceProfile
from voicebridge.voices import (
    FALLBACK_VOICES,
    build_voice_options,
    filter_voices_by_language,
    filter_voices_by_query,
    find_voice_label,
    save_preferred_voice_short_names,
)

LOCAL_TTS_MODEL_MIN_FREE_BYTES = 3 * 1024 * 1024 * 1024
TTS_OUTPUT_MIN_FREE_BYTES = 128 * 1024 * 1024


# noinspection PyAttributeOutsideInit,PyUnresolvedReferences,PyTypeChecker,PyMethodMayBeStatic
class TtsWorkflowMixin:
    def tts_text(self, text: str, **kwargs) -> str:
        if kwargs and hasattr(self, "format_static_ui_text"):
            return self.format_static_ui_text(text, **kwargs)
        if kwargs:
            return text.format(**kwargs)
        return self.static_ui_text(text) if hasattr(self, "static_ui_text") else text

    def populate_tts_engine_combo(self) -> None:
        selected_engine = self.tts_engine_key() if self.tts_engine_combo.count() else "edge"
        self.tts_engine_combo.blockSignals(True)
        try:
            self.tts_engine_combo.clear()
            for label in TTS_ENGINE_LABELS:
                self.tts_engine_combo.addItem(self.tts_text(label), TTS_ENGINE_BY_LABEL[label])
            self.set_tts_engine_key(selected_engine)
        finally:
            self.tts_engine_combo.blockSignals(False)

    def populate_tts_local_device_combo(self) -> None:
        selected_device = self.tts_local_device_key() if self.tts_local_device_combo.count() else "auto"
        self.tts_local_device_combo.blockSignals(True)
        try:
            self.tts_local_device_combo.clear()
            for label in STT_DEVICE_LABELS:
                self.tts_local_device_combo.addItem(self.tts_text(label), STT_DEVICE_BY_LABEL[label])
            self.set_tts_local_device_key(selected_device)
        finally:
            self.tts_local_device_combo.blockSignals(False)

    def populate_tts_split_combo(self) -> None:
        selected_split = (
            self.combo_current_data(self.tts_split_combo)
            if self.tts_split_combo.count()
            else TTS_SPLIT_PARAGRAPHS
        )
        self.tts_split_combo.blockSignals(True)
        try:
            self.tts_split_combo.clear()
            for split_mode in (TTS_SPLIT_PARAGRAPHS, TTS_SPLIT_LINES):
                self.tts_split_combo.addItem(self.tts_text(split_mode), split_mode)
            self.set_combo_data(self.tts_split_combo, selected_split, [TTS_SPLIT_PARAGRAPHS, TTS_SPLIT_LINES])
        finally:
            self.tts_split_combo.blockSignals(False)

    def retranslate_tts_page(self) -> None:
        if not hasattr(self, "tts_engine_combo"):
            return
        self.populate_tts_engine_combo()
        self.populate_tts_local_device_combo()
        if hasattr(self, "tts_split_combo"):
            self.populate_tts_split_combo()
        self.update_tts_local_device_options()
        self.update_tts_local_preset_tooltip()
        self.update_tts_mode_note()
        self.update_block_settings_controls()

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

    def tts_local_preset_key(self):
        if not hasattr(self, "tts_local_preset_combo"):
            return DEFAULT_LOCAL_TTS_PRESET_KEY
        preset = self.tts_local_preset_combo.currentData()
        return normalize_local_tts_preset_key(preset if isinstance(preset, str) else None)

    def set_tts_local_preset_key(self, preset):
        preset = normalize_local_tts_preset_key(preset if isinstance(preset, str) else None)
        for index in range(self.tts_local_preset_combo.count()):
            if self.tts_local_preset_combo.itemData(index) == preset:
                self.tts_local_preset_combo.setCurrentIndex(index)
                self.update_tts_local_preset_tooltip()
                return

    def tts_local_preset_changed(self):
        self.update_tts_local_preset_tooltip()
        self.save_user_settings()

    def update_tts_local_preset_tooltip(self):
        if not hasattr(self, "tts_local_preset_combo"):
            return
        self.tts_local_preset_combo.setToolTip(self.tts_text(local_tts_preset_description(self.tts_local_preset_key())))

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
                    tooltip = self.tts_text("Uses CUDA when available; otherwise falls back to CPU.")
                elif device == "cpu":
                    tooltip = self.tts_text("Forces CPU execution.")
                elif enabled:
                    tooltip = self.tts_text("Uses the detected CUDA GPU.")
                else:
                    tooltip = self.tts_text("CUDA is not available in the current ML runtime on this machine.")
                self.tts_local_device_combo.setItemData(index, tooltip, Qt.ItemDataRole.ToolTipRole)
            self.set_tts_local_device_key(selected_device)
        finally:
            self.tts_local_device_combo.blockSignals(False)

    def selected_tts_voice_profile(self) -> LocalVoiceSource | None:
        profile_id = self.local_voice_profile_combo.currentData()
        if not isinstance(profile_id, str) or not profile_id:
            return None
        return next((voice for voice in self.ready_tts_voice_profiles() if voice["id"] == profile_id), None)

    def ready_tts_voice_profiles(self) -> list[LocalVoiceSource]:
        return ready_local_voice_sources(self.voice_profiles)

    def local_multi_voice_available(self) -> bool:
        return len(self.ready_tts_voice_profiles()) > 1

    def populate_local_voice_combo(
        self,
        combo: QComboBox,
        voices: list[LocalVoiceSource],
        target_voice_id: str | None,
    ) -> None:
        first_voice_index = -1
        selected_index = -1
        for group_label, group_voices in grouped_local_voice_sources(voices):
            combo.addItem(group_label, "")
            header_index = combo.count() - 1
            header_item = combo.model().item(header_index)
            if header_item is not None:
                header_item.setEnabled(False)
            combo.setItemData(header_index, group_label, Qt.ItemDataRole.ToolTipRole)
            for voice in group_voices:
                combo.addItem(local_voice_display_label(voice), voice["id"])
                voice_index = combo.count() - 1
                combo.setItemData(voice_index, local_voice_status_text(voice), Qt.ItemDataRole.ToolTipRole)
                if first_voice_index < 0:
                    first_voice_index = voice_index
                if target_voice_id and voice["id"] == target_voice_id:
                    selected_index = voice_index
        if selected_index >= 0:
            combo.setCurrentIndex(selected_index)
        elif first_voice_index >= 0:
            combo.setCurrentIndex(first_voice_index)

    def update_tts_multi_mode_availability(self) -> None:
        if not hasattr(self, "tts_multi_mode_button"):
            return
        local = self.tts_engine_key() == "local"
        available = not local or self.local_multi_voice_available()
        self.tts_multi_mode_button.setEnabled(available)
        if local and not available:
            self.tts_multi_mode_button.setToolTip(
                self.tts_text("Local multi-voice requires at least two ready local voices.")
            )
            if self.tts_mode_index() == 1:
                self.set_tts_mode(0)
        else:
            self.tts_multi_mode_button.setToolTip("")

    def refresh_local_voice_profile_combo(self, preferred_profile_id=None):
        if not hasattr(self, "local_voice_profile_combo"):
            return
        previous_profile_id = self.local_voice_profile_combo.currentData()
        target_profile_id = preferred_profile_id or previous_profile_id or self.saved_tts_voice_profile_id
        profiles = self.ready_tts_voice_profiles()

        self.local_voice_profile_combo.blockSignals(True)
        try:
            self.local_voice_profile_combo.clear()
            if not profiles:
                self.local_voice_profile_combo.addItem(self.tts_text("No ready local voices"), "")
                self.local_voice_profile_combo.setEnabled(False)
            else:
                self.populate_local_voice_combo(self.local_voice_profile_combo, profiles, target_profile_id)
                self.local_voice_profile_combo.setEnabled(True)
        finally:
            self.local_voice_profile_combo.blockSignals(False)
        self.update_local_voice_profile_status()
        self.update_tts_multi_mode_availability()
        if self.tts_engine_key() == "local":
            self.refresh_local_block_voice_combo(target_profile_id)

    def local_voice_profile_changed(self):
        profile = self.selected_tts_voice_profile()
        self.saved_tts_voice_profile_id = profile["id"] if profile else ""
        self.update_local_voice_profile_status()
        self.update_tts_multi_mode_availability()
        if self.tts_engine_key() == "local":
            self.refresh_local_block_voice_combo(profile["id"] if profile else None)
        self.save_user_settings()

    def update_local_voice_profile_status(self):
        if not hasattr(self, "local_voice_profile_status"):
            return
        profile = self.selected_tts_voice_profile()
        if profile:
            self.local_voice_profile_status.setText(local_voice_status_text(profile))
        else:
            self.local_voice_profile_status.setText(
                self.tts_text("Create a ready reference profile or complete a voice training job.")
            )
        self.update_tts_button_state()

    def update_local_tts_model_status(self):
        if not hasattr(self, "local_tts_model_status"):
            return
        selected_voice = self.selected_tts_voice_profile()
        model_ready = local_tts_model_ready()
        partials = partial_download_files(local_tts_model_cache_dir())
        if selected_voice and not local_voice_requires_base_xtts(selected_voice) and not model_ready:
            self.local_tts_model_status.setText(
                self.tts_text("Trained model selected. Download XTTS-v2 is only required for reference clone voices.")
            )
        elif model_ready:
            self.local_tts_model_status.setText(self.tts_text("XTTS-v2 model ready."))
        elif partials:
            self.local_tts_model_status.setText(
                self.tts_text("XTTS-v2 model download is incomplete. Download again to repair it.")
            )
        else:
            self.local_tts_model_status.setText(
                self.tts_text("XTTS-v2 model not downloaded. Required once for all languages.")
            )
        if hasattr(self, "local_tts_model_status_box"):
            self.local_tts_model_status_box.setVisible(
                model_ready or bool(selected_voice and not local_voice_requires_base_xtts(selected_voice))
            )
        if hasattr(self, "tts_download_model_button"):
            self.tts_download_model_button.setVisible(not model_ready)
        self.update_tts_button_state()

    def update_tts_engine_ui(self):
        if not hasattr(self, "tts_engine_combo"):
            return
        local = self.tts_engine_key() == "local"
        self.edge_voice_panel.setVisible(not local)
        self.local_voice_panel.setVisible(local)
        if local:
            self.refresh_local_voice_profile_combo()
            self.update_tts_local_device_options()
            self.update_local_tts_model_status()
            self.refresh_stt_preflight_async()
            selected_voice = self.selected_tts_voice_profile()
            if local_tts_model_ready() or (
                selected_voice and not local_voice_requires_base_xtts(selected_voice)
            ):
                self.tts_status.setText(self.tts_text("Local TTS ready."))
            else:
                self.tts_status.setText(self.tts_text("Download XTTS-v2 before Local TTS generation."))
        elif hasattr(self, "tts_status"):
            self.tts_status.setText(self.tts_text("Ready."))
        self.update_tts_multi_mode_availability()
        self.update_block_settings_controls()
        self.refresh_block_voice_combo_for_engine()
        self.update_tts_mode_note()
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
        self.current_voice_labels = values
        self.voice_combo.blockSignals(True)
        self.voice_combo.clear()
        self.voice_combo.addItems(values)
        target_short_name = preferred_short_name or previous_short_name
        selected_label = find_voice_label(self.current_voice_map, target_short_name)
        if not selected_label and self.current_voice_map:
            selected_label = next(iter(self.current_voice_map))
        self.voice_combo.setCurrentText(selected_label)
        self.voice_combo.blockSignals(False)
        if self.tts_engine_key() != "local":
            self.refresh_edge_block_voice_combo(preferred_short_name=target_short_name)
        self.last_valid_voice_label = selected_label
        self.voice_combo.setEnabled(
            bool(self.current_voice_map)
            and not self.is_loading_voices
            and not self.is_detecting_language
        )
        self.sync_voice_preferred_state()
        self.update_tts_button_state()

    def refresh_block_voice_combo_for_engine(self) -> None:
        if not hasattr(self, "block_voice_combo"):
            return
        if self.tts_engine_key() == "local":
            profile = self.selected_tts_voice_profile()
            self.refresh_local_block_voice_combo(profile["id"] if profile else None)
        else:
            self.refresh_edge_block_voice_combo()

    def refresh_edge_block_voice_combo(self, preferred_short_name=None) -> None:
        if not hasattr(self, "block_voice_combo"):
            return
        previous_short_name = self.current_voice_map.get(self.block_voice_combo.currentText())
        target_short_name = preferred_short_name or previous_short_name or self.saved_tts_voice_short_name
        selected_label = find_voice_label(self.current_voice_map, target_short_name)
        if not selected_label and self.current_voice_map:
            selected_label = next(iter(self.current_voice_map))
        self.block_voice_combo.blockSignals(True)
        try:
            self.block_voice_combo.clear()
            self.block_voice_combo.addItems(getattr(self, "current_voice_labels", list(self.current_voice_map)))
            self.block_voice_combo.setEnabled(bool(self.current_voice_map))
            self.block_voice_combo.setCurrentText(selected_label)
        finally:
            self.block_voice_combo.blockSignals(False)

    def refresh_local_block_voice_combo(self, preferred_profile_id=None) -> None:
        if not hasattr(self, "block_voice_combo"):
            return
        profiles = self.ready_tts_voice_profiles()
        previous_profile_id = self.block_voice_combo.currentData()
        target_profile_id = preferred_profile_id or previous_profile_id
        self.block_voice_combo.blockSignals(True)
        try:
            self.block_voice_combo.clear()
            if not profiles:
                self.block_voice_combo.addItem(self.tts_text("No ready local voices"), "")
                self.block_voice_combo.setEnabled(False)
            else:
                self.populate_local_voice_combo(self.block_voice_combo, profiles, target_profile_id)
                self.block_voice_combo.setEnabled(True)
        finally:
            self.block_voice_combo.blockSignals(False)

    def update_block_settings_controls(self) -> None:
        if not hasattr(self, "block_voice_label"):
            return
        local = self.tts_engine_key() == "local"
        self.block_voice_label.setText(self.tts_text("Block local voice") if local else self.tts_text("Block voice"))
        self.block_rate_label.setVisible(not local)
        self.block_rate_combo.setVisible(not local)
        self.apply_current_block_button.setText(
            self.tts_text("Use current profile") if local else self.tts_text("Use current voice")
        )
        self.apply_all_blocks_button.setText(
            self.tts_text("Use current profile for all") if local else self.tts_text("Use current voice for all")
        )

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
            self.tts_text("Select input file"),
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
        path, _ = QFileDialog.getSaveFileName(self, self.tts_text("Save audio as"), initial, "MP3 files (*.mp3)")
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
        self.voice_status.setText(self.tts_text("Detecting file language..."))
        self.hide_input_warning()
        self.tts_status.setText(self.tts_text("Reading file text..."))
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
            and not self.is_audio_cleanup_running
            and not self.is_cleanup_running
            and not self.input_file_error_message
        )
        if self.tts_engine_key() == "local":
            selected_voice = self.selected_tts_voice_profile()
            ready = (
                common_ready
                and bool(selected_voice)
                and (not local_voice_requires_base_xtts(selected_voice) or local_tts_model_ready())
            )
        else:
            ready = common_ready and not self.is_loading_voices and bool(self.current_voice_map)
        self.tts_generate_button.setEnabled(ready)
        if hasattr(self, "tts_download_model_button"):
            self.tts_download_model_button.setEnabled(
                common_ready
                and self.tts_engine_key() == "local"
                and not local_tts_model_ready()
            )
        self.tts_cancel_button.setEnabled(self.is_converting and not self.tts_cancel_requested)
        output_ready = bool(self.tts_last_output_path and Path(self.tts_last_output_path).is_file())
        self.tts_open_output_button.setEnabled(output_ready)
        self.tts_open_folder_button.setEnabled(output_ready)
        if hasattr(self, "tts_audio_cleanup_button"):
            self.tts_audio_cleanup_button.setEnabled(output_ready and not self.is_converting)
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

    @staticmethod
    def local_tts_segment_voice_fields(profile: LocalVoiceSource | VoiceProfile) -> dict[str, str]:
        if "kind" not in profile:
            profile = local_voice_from_reference_profile(profile)
        return {
            "voice_label": local_voice_display_label(profile),
            "voice_profile_id": profile["id"],
            "language_code": profile["language_code"],
            "voice_short_name": "",
            "rate": DEFAULT_RATE,
        }

    def selected_block_voice_profile(self) -> LocalVoiceSource | None:
        profile_id = self.block_voice_combo.currentData()
        if not isinstance(profile_id, str) or not profile_id:
            return None
        return next((profile for profile in self.ready_tts_voice_profiles() if profile["id"] == profile_id), None)

    def split_tts_text_blocks(self, text):
        if self.combo_current_data(self.tts_split_combo) == TTS_SPLIT_LINES:
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
            if self.tts_engine_key() == "local":
                profile = self.selected_tts_voice_profile()
                if not profile:
                    raise ValueError("Please create and select a ready local voice.")
                voice_fields = self.local_tts_segment_voice_fields(profile)
            else:
                voice_label, voice_short_name = self.selected_voice_assignment()
                voice_fields = {
                    "voice_label": voice_label,
                    "voice_short_name": voice_short_name,
                    "rate": self.rate_combo.currentText(),
                }
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
                    **voice_fields,
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
        if segment.get("voice_profile_id"):
            language = language_name(segment.get("language_code") or "")
            return f"{index + 1:02d}. {voice} | {language} | {len(segment.get('text', ''))} chars"
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
        if self.tts_engine_key() == "local":
            self.refresh_local_block_voice_combo(segment.get("voice_profile_id"))
        else:
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
            "voice_profile_id": first_segment.get("voice_profile_id", ""),
            "language_code": first_segment.get("language_code", ""),
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
        if self.tts_engine_key() == "local":
            profile = self.selected_block_voice_profile()
            if not profile:
                self.show_error("Error", "Please select a valid block local voice.")
                return
            self.tts_segments[index].update(self.local_tts_segment_voice_fields(profile))
            self.refresh_tts_blocks_list()
            self.tts_blocks_list.setCurrentRow(index)
            self.tts_status.setText(f"Updated block {index + 1}.")
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
        if self.tts_engine_key() == "local":
            profile = self.selected_tts_voice_profile()
            if not profile:
                self.show_error("Error", "Please create and select a ready local voice.")
                return
            self.tts_segments[index].update(self.local_tts_segment_voice_fields(profile))
            self.refresh_tts_blocks_list()
            self.tts_blocks_list.setCurrentRow(index)
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
        if self.tts_engine_key() == "local":
            profile = self.selected_tts_voice_profile()
            if not profile:
                self.show_error("Error", "Please create and select a ready local voice.")
                return
            voice_fields = self.local_tts_segment_voice_fields(profile)
            for segment in self.tts_segments:
                segment.update(voice_fields)
            self.refresh_tts_blocks_list()
            if self.selected_tts_segment_index is not None:
                self.tts_blocks_list.setCurrentRow(self.selected_tts_segment_index)
            self.tts_status.setText(f"Applied current local voice to {len(self.tts_segments)} block(s).")
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
        validate_output_path(save_path, source_path=input_path, expected_suffixes={".mp3"})
        ensure_free_space(save_path, TTS_OUTPUT_MIN_FREE_BYTES, "TTS output")
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
        validate_output_path(save_path, source_path=input_path, expected_suffixes={".mp3"})
        ensure_free_space(save_path, TTS_OUTPUT_MIN_FREE_BYTES, "Local TTS output")
        if self.is_detecting_language:
            raise ValueError("Language detection is still running. Please wait a moment.")
        if self.input_file_error_message:
            raise ValueError(self.input_file_error_message)
        if not profile:
            raise ValueError("Please create and select a ready local voice.")
        if local_voice_requires_base_xtts(profile) and not local_tts_model_ready():
            raise ValueError("XTTS-v2 model is not downloaded yet. Use Download XTTS-v2 first.")
        if self.tts_local_device_key() == "cuda" and not self.stt_cuda_available:
            raise ValueError("CUDA is not available in the current ML runtime on this machine.")
        self.tts_output_picker.set_text(save_path)
        self.save_user_settings()
        return input_path, save_path, profile, self.tts_local_device_key(), self.tts_local_preset_key()

    def collect_multi_tts_options(self):
        source_path = self.tts_input_picker.text()
        save_path = self.tts_output_picker.text()
        if not save_path:
            raise ValueError("Please choose where to save the MP3.")
        save_path = ensure_mp3_suffix(save_path)
        validate_output_path(save_path, source_path=source_path or None, expected_suffixes={".mp3"})
        ensure_free_space(save_path, TTS_OUTPUT_MIN_FREE_BYTES, "multi-voice TTS output")
        if not self.tts_segments:
            self.split_tts_document_into_blocks()
        segments = []
        for index, segment in enumerate(self.tts_segments, start=1):
            text = segment.get("text", "").strip()
            voice_label = segment.get("voice_label", "").strip()
            voice_short_name = segment.get("voice_short_name", "").strip()
            rate = segment.get("rate", DEFAULT_RATE)
            if not text:
                continue
            if not voice_short_name:
                raise ValueError(f"Block {index} has no voice selected.")
            if rate not in RATE_CHOICES:
                raise ValueError(f"Block {index} has an invalid speed.")
            segments.append({
                "text": text,
                "voice_label": voice_label,
                "voice_short_name": voice_short_name,
                "rate": rate,
                "source_block_index": index,
            })
        if not segments:
            raise ValueError("No text blocks are ready for generation.")
        self.tts_output_picker.set_text(save_path)
        self.save_user_settings()
        return source_path, save_path, segments

    def collect_local_multi_tts_options(self):
        source_path = self.tts_input_picker.text()
        save_path = self.tts_output_picker.text()
        if not save_path:
            raise ValueError("Please choose where to save the MP3.")
        save_path = ensure_mp3_suffix(save_path)
        validate_output_path(save_path, source_path=source_path or None, expected_suffixes={".mp3"})
        ensure_free_space(save_path, TTS_OUTPUT_MIN_FREE_BYTES, "local multi-voice TTS output")
        if self.is_detecting_language:
            raise ValueError("Language detection is still running. Please wait a moment.")
        if self.input_file_error_message:
            raise ValueError(self.input_file_error_message)
        profiles = self.ready_tts_voice_profiles()
        if len(profiles) < 2:
            raise ValueError("Local multi-voice requires at least two ready local voices.")
        if self.tts_local_device_key() == "cuda" and not self.stt_cuda_available:
            raise ValueError("CUDA is not available in the current ML runtime on this machine.")
        if not self.tts_segments:
            self.split_tts_document_into_blocks()
        profiles_by_id = {profile["id"]: profile for profile in profiles}
        segments = []
        for index, segment in enumerate(self.tts_segments, start=1):
            text = (segment.get("text") or "").strip()
            profile_id = (segment.get("voice_profile_id") or "").strip()
            if not text:
                continue
            if not profile_id:
                raise ValueError(f"Block {index} has no local voice selected.")
            profile = profiles_by_id.get(profile_id)
            if not profile:
                raise ValueError(f"Block {index} uses a local voice that is no longer ready.")
            segments.append({"text": text, "profile": profile, "source_block_index": index})
        if not segments:
            raise ValueError("No text blocks are ready for generation.")
        reference_voice_selected = any(local_voice_requires_base_xtts(segment["profile"]) for segment in segments)
        if reference_voice_selected and not local_tts_model_ready():
            raise ValueError("XTTS-v2 model is required for reference clone voices. Use Download XTTS-v2 first.")
        self.tts_output_picker.set_text(save_path)
        self.save_user_settings()
        return source_path, save_path, segments, self.tts_local_device_key(), self.tts_local_preset_key()

    @staticmethod
    def expand_multi_voice_segments(segments):
        expanded_segments = []
        for source_index, segment in enumerate(segments, start=1):
            chunks = split_tts_text_for_tts(segment["text"])
            if not chunks:
                continue
            for chunk_index, chunk in enumerate(chunks, start=1):
                expanded_segments.append({
                    "text": chunk,
                    "voice_label": segment.get("voice_label", ""),
                    "voice_short_name": segment["voice_short_name"],
                    "rate": segment["rate"],
                    "source_block_index": segment.get("source_block_index", source_index),
                    "chunk_index": chunk_index,
                })
        return expanded_segments

    @staticmethod
    def tts_timeline_block(
        *,
        index,
        source_block_index,
        chunk_index,
        start_seconds,
        duration_seconds,
        text,
        voice_label="",
        voice_short_name="",
        voice_profile_id="",
        language_code="",
        rate="",
    ):
        end_seconds = start_seconds + max(0.0, duration_seconds)
        block = {
            "id": f"block-{source_block_index:04d}-chunk-{chunk_index:04d}",
            "index": index,
            "source_block_index": source_block_index,
            "chunk_index": chunk_index,
            "start_seconds": start_seconds,
            "end_seconds": end_seconds,
            "duration_seconds": duration_seconds,
            "text": text,
        }
        for key, value in (
            ("voice_label", voice_label),
            ("voice_short_name", voice_short_name),
            ("voice_profile_id", voice_profile_id),
            ("language_code", language_code),
            ("rate", rate),
        ):
            if value:
                block[key] = value
        return block

    @classmethod
    def local_tts_timeline_blocks(cls, chunks, profile, source_block_index=1, offset_seconds=0.0, start_index=1):
        blocks = []
        voice_label = local_voice_display_label(profile)
        for position, chunk in enumerate(chunks, start=start_index):
            start_seconds = offset_seconds + float(chunk["start_seconds"])
            duration_seconds = float(chunk["end_seconds"]) - float(chunk["start_seconds"])
            blocks.append(
                cls.tts_timeline_block(
                    index=position,
                    source_block_index=source_block_index,
                    chunk_index=int(chunk.get("chunk_index") or position),
                    start_seconds=start_seconds,
                    duration_seconds=duration_seconds,
                    text=chunk.get("text", ""),
                    voice_label=voice_label,
                    voice_profile_id=profile["id"],
                    language_code=profile["language_code"],
                )
            )
        return blocks

    def start_tts_conversion(self):
        if self.tts_engine_key() == "local":
            if self.tts_mode_index() == 1:
                self.start_local_multi_tts_conversion()
            else:
                self.start_local_tts_conversion()
            return
        if self.tts_mode_index() == 1:
            self.start_multi_voice_conversion()
            return
        try:
            input_path, save_path, voice, rate = self.collect_single_tts_options()
        except ValueError as exc:
            self.tts_status.setText(self.tts_text("Error."))
            self.show_error(self.tts_text("Error"), str(exc))
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
            source_path, save_path, segments = self.collect_multi_tts_options()
        except ValueError as exc:
            self.tts_status.setText(self.tts_text("Error."))
            self.show_error(self.tts_text("Error"), str(exc))
            return
        self.start_tts_busy(self.tts_text("Generating multi-voice audio..."), percent=True)
        threading.Thread(
            target=self.multi_voice_conversion_worker,
            args=(source_path, save_path, segments),
            daemon=True,
        ).start()

    def start_local_multi_tts_conversion(self):
        try:
            source_path, save_path, segments, device, preset = self.collect_local_multi_tts_options()
        except ValueError as exc:
            self.tts_status.setText(self.tts_text("Error."))
            self.show_error("Local TTS", str(exc))
            return
        python_path = ml_python_path()
        worker_path = local_tts_worker_path()
        if not python_path.is_file():
            self.tts_status.setText(self.tts_text("Local TTS environment missing."))
            self.show_error(
                self.tts_text("Local TTS environment missing"),
                self.tts_text("Could not find the ML Python runtime:\n{path}", path=python_path),
            )
            return
        if not worker_path.is_file():
            self.tts_status.setText(self.tts_text("Local TTS worker missing."))
            self.show_error(
                self.tts_text("Local TTS worker missing"),
                self.tts_text("Could not find:\n{path}", path=worker_path),
            )
            return
        self.start_tts_busy(self.tts_text("Starting local multi-voice TTS..."), percent=True)
        threading.Thread(
            target=self.local_multi_tts_conversion_worker,
            args=(python_path, worker_path, source_path, save_path, segments, device, preset),
            daemon=True,
        ).start()

    def confirm_xtts_model_license(self):
        return self.ask_question(
            self.tts_text("Download XTTS-v2"),
            self.tts_text(
                "XTTS-v2 is a single multilingual model of about 1.8-2.3 GB.\n\n"
                "The model uses the Coqui Public Model License and is limited to non-commercial use, "
                "including generated output.\n\n"
                "Download the model now?"
            ),
        )

    def start_local_tts_model_download(self):
        if local_tts_model_ready():
            self.update_local_tts_model_status()
            self.show_info("Local TTS", self.tts_text("XTTS-v2 model is already downloaded."))
            return
        python_path = ml_python_path()
        worker_path = local_tts_worker_path()
        if not python_path.is_file():
            self.tts_status.setText(self.tts_text("Local TTS environment missing."))
            self.show_error(
                self.tts_text("Local TTS environment missing"),
                self.tts_text("Could not find the ML Python runtime:\n{path}", path=python_path),
            )
            return
        if not worker_path.is_file():
            self.tts_status.setText(self.tts_text("Local TTS worker missing."))
            self.show_error(
                self.tts_text("Local TTS worker missing"),
                self.tts_text("Could not find:\n{path}", path=worker_path),
            )
            return
        try:
            ensure_free_space(local_tts_model_dir(), LOCAL_TTS_MODEL_MIN_FREE_BYTES, "XTTS-v2 model download")
        except ValueError as exc:
            self.tts_status.setText(self.tts_text("Not enough disk space."))
            self.show_error("Local TTS", str(exc))
            return
        if not self.confirm_xtts_model_license():
            self.tts_status.setText(self.tts_text("XTTS-v2 download cancelled."))
            return
        self.start_tts_busy(self.tts_text("Downloading XTTS-v2 model..."), percent=True)
        threading.Thread(
            target=self.local_tts_model_download_worker,
            args=(python_path, worker_path),
            daemon=True,
        ).start()

    def local_tts_model_download_worker(self, python_path, worker_path):
        command = [
            str(python_path),
            "-u",
            str(worker_path),
            "--download-model",
            "--accept-license",
            "--model-dir",
            str(local_tts_model_dir()),
        ]

        def handle_worker_output(output: WorkerProcessOutput) -> None:
            if output.is_progress:
                if output.progress_percent is not None:
                    self.post(self.update_tts_progress_percent, output.progress_percent)
                return
            if output.is_status:
                self.post(self.tts_status.setText, self.tts_text(output.status or ""))

        try:
            result = run_worker_process_job(
                command,
                cwd=str(external_base_dir()),
                on_process_start=lambda process: setattr(self, "tts_process", process),
                on_output=handle_worker_output,
                should_cancel=lambda: self.tts_cancel_requested,
                recent_output_limit=12,
            )
            if result.cancelled:
                self.post(self.conversion_cancelled)
                return
            if result.return_code != 0:
                raise RuntimeError(
                    "\n".join(result.recent_output[-8:])
                    or f"XTTS-v2 download exited with code {result.return_code}."
                )
            self.post(self.local_tts_model_download_succeeded)
        except (OSError, RuntimeError, TimeoutError, AssertionError) as exc:
            self.post(self.conversion_failed, str(exc))
        finally:
            self.tts_process = None
            self.post(self.finish_tts_conversion)

    def local_tts_model_download_succeeded(self):
        self.tts_status.setText(self.tts_text("XTTS-v2 model ready."))
        self.update_local_tts_model_status()
        self.refresh_home_diagnostics()
        self.show_info(
            "Local TTS",
            self.tts_text("XTTS-v2 model downloaded:\n{path}", path=local_tts_model_cache_dir()),
        )

    def start_local_tts_conversion(self):
        try:
            input_path, save_path, profile, device, preset = self.collect_local_tts_options()
        except ValueError as exc:
            self.tts_status.setText(self.tts_text("Error."))
            self.show_error("Local TTS", str(exc))
            return
        python_path = ml_python_path()
        worker_path = local_tts_worker_path()
        if not python_path.is_file():
            self.tts_status.setText(self.tts_text("Local TTS environment missing."))
            self.show_error(
                self.tts_text("Local TTS environment missing"),
                self.tts_text("Could not find the ML Python runtime:\n{path}", path=python_path),
            )
            return
        if not worker_path.is_file():
            self.tts_status.setText(self.tts_text("Local TTS worker missing."))
            self.show_error(
                self.tts_text("Local TTS worker missing"),
                self.tts_text("Could not find:\n{path}", path=worker_path),
            )
            return
        signature = file_signature(input_path)
        cached_text = self.cached_input_text if signature == self.cached_input_signature else None
        self.start_tts_busy("Starting local TTS...", percent=True)
        threading.Thread(
            target=self.local_tts_conversion_worker,
            args=(python_path, worker_path, input_path, save_path, profile, device, preset, cached_text),
            daemon=True,
        ).start()

    def local_tts_worker_command(
        self,
        python_path,
        worker_path,
        text_path,
        output_path,
        profile,
        device,
        preset,
        timeline_path=None,
    ):
        command = [
            str(python_path),
            "-u",
            str(worker_path),
            "--text-file",
            str(text_path),
            "--output",
            str(output_path),
            "--language",
            profile["language_code"],
            "--device",
            device,
            "--preset",
            preset,
            "--model-dir",
            str(local_tts_model_dir()),
        ]
        if timeline_path is not None:
            command.extend(["--timeline-json", str(timeline_path)])
        for reference_path in profile["reference_paths"]:
            command.extend(["--speaker-wav", reference_path])
        command.extend(local_voice_model_args(profile))
        return command

    def run_local_tts_worker_command(self, command, progress_start=0.0, progress_end=100.0):
        def handle_worker_output(output: WorkerProcessOutput) -> None:
            if output.is_progress:
                if output.progress_percent is not None:
                    mapped_progress = progress_start + (
                        (progress_end - progress_start) * (output.progress_percent / 100)
                    )
                    self.post(self.update_tts_progress_percent, mapped_progress)
                return
            if output.is_status:
                self.post(self.tts_status.setText, output.status or "")

        try:
            result = run_worker_process_job(
                command,
                cwd=str(external_base_dir()),
                on_process_start=lambda process: setattr(self, "tts_process", process),
                on_output=handle_worker_output,
                should_cancel=lambda: self.tts_cancel_requested,
                recent_output_limit=12,
            )
            if result.cancelled:
                raise TtsCancelled()
            if result.return_code != 0:
                raise RuntimeError(
                    "\n".join(result.recent_output[-8:]) or f"Local TTS exited with code {result.return_code}."
                )
        finally:
            self.tts_process = None

    def local_tts_conversion_worker(
        self,
        python_path,
        worker_path,
        input_path,
        save_path,
        profile,
        device,
        preset,
        cached_text,
    ):
        try:
            remove_tts_timeline(save_path)
            text = cached_text if cached_text is not None else read_input_file(input_path)
            if self.tts_cancel_requested:
                raise TtsCancelled()
            if not text.strip():
                raise ValueError("The selected file appears to contain no readable text.")
            with tempfile.TemporaryDirectory(
                prefix="voicebridge-local-tts-",
                dir=Path(save_path).resolve().parent,
            ) as temp_dir_name:
                temp_dir = Path(temp_dir_name)
                text_path = temp_dir / "input.txt"
                wav_path = temp_dir / "local-tts.wav"
                worker_timeline_path = temp_dir / "local-tts.voicebridge-chunks.json"
                temp_mp3_path = temp_dir / Path(save_path).name
                text_path.write_text(text.strip(), encoding="utf-8")
                command = self.local_tts_worker_command(
                    python_path,
                    worker_path,
                    text_path,
                    wav_path,
                    profile,
                    device,
                    preset,
                    worker_timeline_path,
                )
                self.run_local_tts_worker_command(command, progress_start=0, progress_end=95)
                self.post(self.tts_status.setText, "Converting local TTS audio to MP3...")
                self.post(self.update_tts_progress_percent, 96)
                convert_audio_to_mp3(wav_path, temp_mp3_path)
                if self.tts_cancel_requested:
                    raise TtsCancelled()
                chunks = load_local_tts_chunk_timeline(worker_timeline_path)
                if chunks:
                    timeline_blocks = self.local_tts_timeline_blocks(chunks, profile)
                else:
                    duration = audio_duration_seconds(temp_mp3_path)
                    timeline_blocks = [
                        self.tts_timeline_block(
                            index=1,
                            source_block_index=1,
                            chunk_index=1,
                            start_seconds=0.0,
                            duration_seconds=duration,
                            text=text.strip(),
                            voice_label=local_voice_display_label(profile),
                            voice_profile_id=profile["id"],
                            language_code=profile["language_code"],
                        )
                    ]
                os.replace(temp_mp3_path, save_path)
                write_tts_timeline(
                    save_path,
                    engine="local",
                    mode="single",
                    source_path=input_path,
                    blocks=timeline_blocks,
                    total_duration_seconds=audio_duration_seconds(save_path),
                )
                self.post(self.update_tts_progress_percent, 100)
            self.post(self.conversion_succeeded, save_path)
        except TtsCancelled:
            self.post(self.conversion_cancelled)
        except (OSError, RuntimeError, TimeoutError, ValueError, AssertionError) as exc:
            self.post(self.conversion_failed, str(exc))
        finally:
            self.tts_process = None
            self.post(self.finish_tts_conversion)

    def local_multi_tts_conversion_worker(
        self,
        python_path,
        worker_path,
        source_path,
        save_path,
        segments,
        device,
        preset,
    ):
        try:
            remove_tts_timeline(save_path)
            with tempfile.TemporaryDirectory(
                prefix="voicebridge-local-multi-tts-",
                dir=Path(save_path).resolve().parent,
            ) as temp_dir_name:
                temp_dir = Path(temp_dir_name)
                part_paths = []
                timeline_blocks = []
                timeline_cursor = 0.0
                total = max(1, len(segments))
                for index, segment in enumerate(segments, start=1):
                    if self.tts_cancel_requested:
                        raise TtsCancelled()
                    text = segment["text"].strip()
                    if not text:
                        continue
                    text_path = temp_dir / f"block-{index:04d}.txt"
                    wav_path = temp_dir / f"block-{index:04d}.wav"
                    mp3_path = temp_dir / f"block-{index:04d}.mp3"
                    worker_timeline_path = temp_dir / f"block-{index:04d}.voicebridge-chunks.json"
                    text_path.write_text(text, encoding="utf-8")
                    self.post(self.tts_status.setText, f"Generating local block {index}/{len(segments)}...")
                    command = self.local_tts_worker_command(
                        python_path,
                        worker_path,
                        text_path,
                        wav_path,
                        segment["profile"],
                        device,
                        preset,
                        worker_timeline_path,
                    )
                    progress_start = ((index - 1) / total) * 88
                    progress_end = (index / total) * 88
                    self.run_local_tts_worker_command(command, progress_start=progress_start, progress_end=progress_end)
                    if self.tts_cancel_requested:
                        raise TtsCancelled()
                    self.post(self.tts_status.setText, f"Converting local block {index}/{len(segments)} to MP3...")
                    convert_audio_to_mp3(wav_path, mp3_path)
                    part_paths.append(mp3_path)
                    part_duration = audio_duration_seconds(mp3_path)
                    chunks = load_local_tts_chunk_timeline(worker_timeline_path)
                    if chunks:
                        timeline_blocks.extend(
                            self.local_tts_timeline_blocks(
                                chunks,
                                segment["profile"],
                                source_block_index=segment["source_block_index"],
                                offset_seconds=timeline_cursor,
                                start_index=len(timeline_blocks) + 1,
                            )
                        )
                    else:
                        timeline_blocks.append(
                            self.tts_timeline_block(
                                index=len(timeline_blocks) + 1,
                                source_block_index=segment["source_block_index"],
                                chunk_index=1,
                                start_seconds=timeline_cursor,
                                duration_seconds=part_duration,
                                text=text,
                                voice_label=local_voice_display_label(segment["profile"]),
                                voice_profile_id=segment["profile"]["id"],
                                language_code=segment["profile"]["language_code"],
                            )
                        )
                    timeline_cursor += part_duration
                    self.post(self.update_tts_progress_percent, progress_end)
                if not part_paths:
                    raise ValueError("No text blocks are ready for generation.")
                self.post(self.tts_status.setText, "Merging local voice blocks...")
                self.post(self.update_tts_progress_percent, 94)
                temp_output = temp_dir / Path(save_path).name
                if len(part_paths) == 1:
                    shutil.copy2(part_paths[0], temp_output)
                else:
                    concatenate_mp3_files(part_paths, temp_output)
                if self.tts_cancel_requested:
                    raise TtsCancelled()
                os.replace(temp_output, save_path)
                write_tts_timeline(
                    save_path,
                    engine="local",
                    mode="multi",
                    source_path=source_path,
                    blocks=timeline_blocks,
                    total_duration_seconds=audio_duration_seconds(save_path),
                )
                self.post(self.update_tts_progress_percent, 100)
            self.post(self.conversion_succeeded, save_path)
        except TtsCancelled:
            self.post(self.conversion_cancelled)
        except (OSError, RuntimeError, TimeoutError, ValueError, AssertionError) as exc:
            self.post(self.conversion_failed, str(exc))
        finally:
            self.tts_process = None
            self.post(self.finish_tts_conversion)

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
        self.update_audio_cleanup_button_state()
        self.update_video_cleanup_button_state()

    def conversion_worker(self, input_path, save_path, voice, rate, cached_text):
        try:
            remove_tts_timeline(save_path)
            text = cached_text if cached_text is not None else read_input_file(input_path)
            if self.tts_cancel_requested:
                raise TtsCancelled()
            if not text.strip():
                raise ValueError("The selected file appears to contain no readable text.")
            self.post(self.tts_status.setText, "Generating audio... please wait.")
            with tempfile.TemporaryDirectory(
                prefix="voicebridge-tts-",
                dir=Path(save_path).resolve().parent,
            ) as temp_dir:
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

    def multi_voice_conversion_worker(self, source_path, save_path, segments):
        try:
            remove_tts_timeline(save_path)
            with tempfile.TemporaryDirectory(
                prefix="voicebridge-tts-",
                dir=Path(save_path).resolve().parent,
            ) as temp_dir_name:
                temp_dir = Path(temp_dir_name)
                part_paths = []
                timeline_blocks = []
                timeline_cursor = 0.0
                generation_segments = self.expand_multi_voice_segments(segments)
                if not generation_segments:
                    raise ValueError("No text blocks are ready for generation after cleanup.")
                total = max(1, len(generation_segments))
                for index, segment in enumerate(generation_segments, start=1):
                    if self.tts_cancel_requested:
                        raise TtsCancelled()
                    part_path = temp_dir / f"part-{index:04d}.mp3"
                    self.post(self.tts_status.setText, f"Generating chunk {index}/{len(generation_segments)}...")
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
                    part_duration = audio_duration_seconds(part_path)
                    timeline_blocks.append(
                        self.tts_timeline_block(
                            index=len(timeline_blocks) + 1,
                            source_block_index=segment["source_block_index"],
                            chunk_index=segment["chunk_index"],
                            start_seconds=timeline_cursor,
                            duration_seconds=part_duration,
                            text=segment["text"],
                            voice_label=segment.get("voice_label", ""),
                            voice_short_name=segment["voice_short_name"],
                            rate=segment["rate"],
                        )
                    )
                    timeline_cursor += part_duration
                    self.post(self.update_tts_progress_percent, (index / total) * 90)
                self.post(self.tts_status.setText, self.tts_text("Merging audio blocks..."))
                self.post(self.update_tts_progress_percent, 95)
                temp_output = temp_dir / Path(save_path).name
                if len(part_paths) == 1:
                    shutil.copy2(part_paths[0], temp_output)
                else:
                    concatenate_mp3_files(part_paths, temp_output)
                if self.tts_cancel_requested:
                    raise TtsCancelled()
                os.replace(temp_output, save_path)
                write_tts_timeline(
                    save_path,
                    engine="edge",
                    mode="multi",
                    source_path=source_path,
                    blocks=timeline_blocks,
                    total_duration_seconds=audio_duration_seconds(save_path),
                )
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
        self.tts_status.setText(self.tts_text("Done."))
        self.record_job("TTS", "MP3 generated", self.tts_input_picker.text(), save_path)
        self.show_info(self.tts_text("Success"), self.tts_text("Audio saved:\n{path}", path=save_path))

    def conversion_failed(self, message):
        self.tts_status.setText(self.tts_text("Error."))
        if (
            self.tts_engine_key() == "local"
            and self.tts_local_device_key() != "cpu"
            and is_cuda_runtime_failure(message)
            and self.ask_question(
                self.tts_text("Local TTS CUDA failed"),
                self.tts_text("Local TTS failed in the CUDA runtime.\n\nRetry the same job on CPU now?"),
                default_yes=True,
            )
        ):
            self.set_tts_local_device_key("cpu")
            self.tts_status.setText(self.tts_text("Retrying Local TTS on CPU..."))
            QTimer.singleShot(250, self.start_tts_conversion)
            return
        self.show_error(self.tts_text("Error"), message)

    def conversion_cancelled(self):
        self.tts_status.setText(self.tts_text("Cancelled."))

    def finish_tts_conversion(self):
        self.is_converting = False
        self.tts_progress.hide()
        self.update_local_tts_model_status()
        self.refresh_home_diagnostics()
        self.update_tts_button_state()
        self.update_stt_button_state()
        self.update_video_subtitle_button_state()
        self.update_audio_cleanup_button_state()
        self.update_video_cleanup_button_state()

    def cancel_tts_conversion(self):
        if not self.is_converting:
            return
        self.tts_cancel_requested = True
        process = getattr(self, "tts_process", None)
        if process is not None and process.poll() is None:
            process.terminate()
        self.tts_status.setText(self.tts_text("Cancelling TTS job..."))
        self.update_tts_button_state()

    def open_tts_output(self):
        open_path(self.tts_last_output_path)

    def open_tts_output_folder(self):
        if self.tts_last_output_path and Path(self.tts_last_output_path).is_file():
            open_path(Path(self.tts_last_output_path).parent)

    def open_tts_output_in_audio_cleanup(self):
        if not self.tts_last_output_path or not Path(self.tts_last_output_path).is_file():
            return
        try:
            self.load_audio_cleanup_source(self.tts_last_output_path)
        except ValueError as exc:
            self.show_error(self.tts_text("Audio Cleanup"), str(exc))
            return
        self.show_page(5)

    def build_tts_page(self):
        page, layout = self.page_container()
        self.page_header(
            layout,
            "Text to Speech",
            "Generate MP3 with online Edge voices or prepared local voice profiles.",
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
        self.populate_tts_engine_combo()
        self.tts_engine_combo.currentIndexChanged.connect(lambda _index: self.tts_engine_changed())
        voice_card.content_layout.addWidget(QLabel("Engine"))
        voice_card.content_layout.addWidget(self.tts_engine_combo)

        self.edge_voice_panel = QWidget()
        self.edge_voice_panel.setObjectName("InlinePanel")
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
        self.local_voice_panel.setObjectName("InlinePanel")
        local_voice_layout = QVBoxLayout(self.local_voice_panel)
        local_voice_layout.setContentsMargins(0, 0, 0, 0)
        local_voice_layout.setSpacing(10)
        self.local_voice_profile_combo = QComboBox()
        self.local_voice_profile_combo.currentTextChanged.connect(lambda _text: self.local_voice_profile_changed())
        manage_profiles_button = QPushButton("Manage profiles")
        manage_profiles_button.clicked.connect(lambda _checked=False: self.show_local_voices_tab(0))
        profile_row = QHBoxLayout()
        profile_row.setContentsMargins(0, 0, 0, 0)
        profile_row.addWidget(self.local_voice_profile_combo, 1)
        profile_row.addWidget(manage_profiles_button)
        self.local_voice_profile_status = QLabel("Create a ready reference profile in Local Voices > Profiles.")
        self.local_voice_profile_status.setObjectName("Muted")
        self.local_voice_profile_status.setWordWrap(True)
        self.tts_local_device_combo = QComboBox()
        self.populate_tts_local_device_combo()
        self.tts_local_device_combo.currentIndexChanged.connect(lambda _index: self.tts_local_device_changed())
        self.tts_local_preset_combo = QComboBox()
        for preset_key, preset in LOCAL_TTS_PRESETS.items():
            self.tts_local_preset_combo.addItem(preset["label"], preset_key)
            self.tts_local_preset_combo.setItemData(
                self.tts_local_preset_combo.count() - 1,
                local_tts_preset_description(preset_key),
                Qt.ItemDataRole.ToolTipRole,
            )
        self.tts_local_preset_combo.currentTextChanged.connect(lambda _text: self.tts_local_preset_changed())
        local_device_row = QHBoxLayout()
        local_device_row.setContentsMargins(0, 0, 0, 0)
        local_device_row.addWidget(QLabel("Preset"))
        local_device_row.addWidget(self.tts_local_preset_combo)
        local_device_row.addSpacing(10)
        local_device_row.addWidget(QLabel("Device"))
        local_device_row.addWidget(self.tts_local_device_combo)
        local_device_row.addStretch(1)
        self.local_tts_model_status = QLabel("XTTS-v2 model ready.")
        self.local_tts_model_status.setWordWrap(True)
        self.local_tts_model_status_box = QFrame()
        self.local_tts_model_status_box.setObjectName("GoodBox")
        local_model_status_layout = QVBoxLayout(self.local_tts_model_status_box)
        local_model_status_layout.setContentsMargins(12, 10, 12, 10)
        local_model_status_layout.addWidget(self.local_tts_model_status)
        self.tts_download_model_button = QPushButton("Download XTTS-v2")
        self.tts_download_model_button.clicked.connect(self.start_local_tts_model_download)
        local_voice_layout.addWidget(QLabel("Voice profile"))
        local_voice_layout.addLayout(profile_row)
        local_voice_layout.addWidget(self.local_voice_profile_status)
        local_voice_layout.addLayout(local_device_row)
        local_voice_layout.addWidget(self.local_tts_model_status_box)
        local_voice_layout.addWidget(self.tts_download_model_button)

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
        self.tts_audio_cleanup_button = QPushButton("Open in Audio Cleanup")
        self.tts_generate_button.clicked.connect(self.start_tts_conversion)
        self.tts_cancel_button.clicked.connect(self.cancel_tts_conversion)
        self.tts_open_output_button.clicked.connect(self.open_tts_output)
        self.tts_open_folder_button.clicked.connect(self.open_tts_output_folder)
        self.tts_audio_cleanup_button.clicked.connect(self.open_tts_output_in_audio_cleanup)
        action_layout.addWidget(self.tts_generate_button)
        action_layout.addWidget(self.tts_cancel_button)
        action_layout.addStretch(1)
        action_layout.addWidget(self.tts_audio_cleanup_button)
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
        self.update_tts_local_preset_tooltip()
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
        if index == 1 and self.tts_engine_key() == "local" and not self.local_multi_voice_available():
            index = 0
        self.tts_mode_stack.setCurrentIndex(index)
        self.tts_mode_stack.setVisible(index == 1)
        self.tts_single_mode_button.setChecked(index == 0)
        self.tts_multi_mode_button.setChecked(index == 1)
        self.update_tts_mode_note()
        self.update_block_settings_controls()
        self.refresh_block_voice_combo_for_engine()
        self.tts_mode_stack.updateGeometry()
        self.update_tts_button_state()
        self.save_user_settings()

    def update_tts_mode_note(self):
        if not hasattr(self, "tts_mode_note"):
            return
        index = self.tts_mode_index()
        local = self.tts_engine_key() == "local"
        if index == 0:
            text = "Uses the selected voice and speed for the whole document."
            if local:
                text = "Uses the selected voice profile for the whole document."
        elif local:
            text = (
                "Split the document into blocks and assign voice profiles per block. "
                "Long local blocks keep the same profile when XTTS splits them internally."
            )
        else:
            text = "Split the document into blocks and assign voice or speed per block."
        self.tts_mode_note.setText(self.tts_text(text))

    def build_multi_tts_tab(self):
        tab = QWidget()
        layout = QGridLayout(tab)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(16)

        left = Card("Blocks")
        split_row = QHBoxLayout()
        self.tts_split_combo = QComboBox()
        self.populate_tts_split_combo()
        self.tts_split_combo.currentIndexChanged.connect(lambda _index: self.save_user_settings())
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
        self.block_voice_label = QLabel("Block voice")
        right.content_layout.addWidget(self.block_voice_label)
        right.content_layout.addWidget(self.block_voice_combo)
        rate_row = QHBoxLayout()
        self.block_rate_label = QLabel("Block speed")
        rate_row.addWidget(self.block_rate_label)
        rate_row.addWidget(self.block_rate_combo)
        rate_row.addStretch(1)
        right.content_layout.addLayout(rate_row)
        settings_row = QHBoxLayout()
        apply_selected = QPushButton("Apply to block")
        self.apply_current_block_button = QPushButton("Use current voice")
        self.apply_all_blocks_button = QPushButton("Use current voice for all")
        apply_selected.clicked.connect(self.apply_block_settings_to_selected)
        self.apply_current_block_button.clicked.connect(self.apply_current_voice_to_selected_block)
        self.apply_all_blocks_button.clicked.connect(self.apply_current_voice_to_all_blocks)
        settings_row.addWidget(apply_selected)
        settings_row.addWidget(self.apply_current_block_button)
        settings_row.addWidget(self.apply_all_blocks_button)
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
