import os
import re
import subprocess
import tempfile
import threading
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSlider,
    QToolButton,
    QWidget,
)

from voicebridge.constants import (
    AUDIO_CLEANUP_ACTION_BY_LABEL,
    AUDIO_CLEANUP_FADE_LABEL,
    AUDIO_CLEANUP_REMOVE_LABEL,
    AUDIO_CLEANUP_SILENCE_LABEL,
)
from voicebridge.media_tools import (
    SUPPORTED_AUDIO_SUFFIXES,
    audio_cleanup_command,
    audio_waveform_peaks,
    find_ffmpeg_exe,
    probe_audio_info,
    suggest_audio_cleanup_output_path,
)
from voicebridge.tts_timeline import (
    load_tts_timeline_for_audio,
    write_audio_cleanup_timeline_for_changes,
)
from voicebridge.ui.helpers import open_path
from voicebridge.ui.waveform import AudioWaveformWidget
from voicebridge.ui.widgets import Card, FilePicker

AUDIO_CLEANUP_WAVEFORM_SCROLL_MAX = 10_000
AUDIO_CLEANUP_WAVEFORM_ZOOM_LEVELS = (
    ("Fit", 1.0),
    ("2x", 2.0),
    ("4x", 4.0),
    ("8x", 8.0),
    ("16x", 16.0),
)


class AudioCleanupWorkflowMixin:
    def audio_cleanup_input_changed(self):
        self.stop_audio_cleanup_playback()
        self.reset_audio_cleanup_changes()
        self.audio_cleanup_last_output_path = ""
        self.update_audio_cleanup_output(force=False)
        self.refresh_audio_cleanup_input_info()
        self.update_audio_cleanup_button_state()
        self.save_user_settings()

    def reset_audio_cleanup_waveform(self, status="No waveform loaded."):
        if not hasattr(self, "audio_cleanup_waveform"):
            return
        self.audio_cleanup_waveform_generation += 1
        self.audio_cleanup_waveform.clear_waveform()
        self.audio_cleanup_waveform.set_markers([])
        self.audio_cleanup_waveform.set_playhead(None)
        self.audio_cleanup_waveform_status.setText(status)
        if hasattr(self, "audio_cleanup_waveform_zoom_combo"):
            self.audio_cleanup_waveform_zoom_combo.blockSignals(True)
            self.audio_cleanup_waveform_zoom_combo.setCurrentIndex(0)
            self.audio_cleanup_waveform_zoom_combo.blockSignals(False)
            self.audio_cleanup_waveform_scroll.setValue(0)
            self.audio_cleanup_waveform_zoom_combo.setEnabled(False)
            self.audio_cleanup_waveform_scroll.setEnabled(False)

    def start_audio_cleanup_waveform_load(self, ffmpeg, audio_path, duration):
        if not hasattr(self, "audio_cleanup_waveform"):
            return
        self.audio_cleanup_waveform_generation += 1
        generation = self.audio_cleanup_waveform_generation
        self.audio_cleanup_waveform.clear_waveform()
        self.audio_cleanup_waveform.set_playhead(None)
        self.audio_cleanup_waveform_status.setText("Loading waveform...")
        self.audio_cleanup_waveform_zoom_combo.blockSignals(True)
        self.audio_cleanup_waveform_zoom_combo.setCurrentIndex(0)
        self.audio_cleanup_waveform_zoom_combo.blockSignals(False)
        self.audio_cleanup_waveform_scroll.setValue(0)
        self.audio_cleanup_waveform_zoom_combo.setEnabled(False)
        self.audio_cleanup_waveform_scroll.setEnabled(False)
        threading.Thread(
            target=self.audio_cleanup_waveform_worker,
            args=(generation, str(ffmpeg), str(audio_path), float(duration)),
            daemon=True,
        ).start()

    def audio_cleanup_waveform_worker(self, generation, ffmpeg, audio_path, duration):
        try:
            peaks = audio_waveform_peaks(ffmpeg, audio_path)
            self.post(self.audio_cleanup_waveform_loaded, generation, peaks, duration, None)
        except (OSError, RuntimeError, ValueError) as exc:
            self.post(self.audio_cleanup_waveform_loaded, generation, [], duration, str(exc))

    def audio_cleanup_waveform_loaded(self, generation, peaks, duration, error_message):
        if generation != self.audio_cleanup_waveform_generation:
            return
        if error_message or not peaks:
            self.audio_cleanup_waveform.clear_waveform()
            self.audio_cleanup_waveform_status.setText("Waveform unavailable.")
            return
        self.audio_cleanup_waveform.set_waveform(peaks, duration)
        self.audio_cleanup_waveform.set_playhead(None)
        self.audio_cleanup_waveform.set_selection(
            self.audio_cleanup_start_spin.value(),
            self.audio_cleanup_end_spin.value(),
        )
        self.refresh_audio_cleanup_waveform_markers()
        self.audio_cleanup_waveform_zoom_combo.setEnabled(True)
        self.audio_cleanup_waveform_view_changed(*self.audio_cleanup_waveform.visible_window())
        self.update_audio_cleanup_button_state()

    def audio_cleanup_waveform_zoom_changed(self):
        if not hasattr(self, "audio_cleanup_waveform"):
            return
        zoom_factor = self.audio_cleanup_waveform_zoom_combo.currentData()
        try:
            zoom_factor = float(zoom_factor)
        except (TypeError, ValueError):
            zoom_factor = 1.0
        self.audio_cleanup_waveform.set_zoom_factor(zoom_factor)
        self.update_audio_cleanup_button_state()

    def audio_cleanup_waveform_scroll_changed(self, value):
        if (
            not hasattr(self, "audio_cleanup_waveform")
            or self.audio_cleanup_waveform_view_syncing
            or not self.audio_cleanup_waveform.has_waveform()
        ):
            return
        ratio = value / AUDIO_CLEANUP_WAVEFORM_SCROLL_MAX
        self.audio_cleanup_waveform.set_view_position_ratio(ratio)

    def audio_cleanup_waveform_view_changed(self, start, end):
        if not hasattr(self, "audio_cleanup_waveform_scroll"):
            return
        if not self.audio_cleanup_waveform.has_waveform():
            self.audio_cleanup_waveform_scroll.setEnabled(False)
            return
        self.audio_cleanup_waveform_view_syncing = True
        try:
            ratio = self.audio_cleanup_waveform.view_position_ratio()
            self.audio_cleanup_waveform_scroll.setValue(round(ratio * AUDIO_CLEANUP_WAVEFORM_SCROLL_MAX))
        finally:
            self.audio_cleanup_waveform_view_syncing = False
        zoomed = self.audio_cleanup_waveform.zoom_factor() > 1.0
        self.audio_cleanup_waveform_scroll.setEnabled(zoomed and not self.is_audio_cleanup_running)
        self.audio_cleanup_waveform_status.setText(
            f"Waveform ready. View: {self.format_audio_cleanup_time(start)} - "
            f"{self.format_audio_cleanup_time(end)}"
        )

    def reset_audio_cleanup_tts_timeline(self, status="No TTS block JSON found."):
        if not hasattr(self, "audio_cleanup_tts_blocks_list"):
            return
        self.audio_cleanup_tts_timeline = None
        self.audio_cleanup_tts_blocks_list.blockSignals(True)
        try:
            self.audio_cleanup_tts_blocks_list.clear()
            self.audio_cleanup_tts_blocks_list.setEnabled(False)
        finally:
            self.audio_cleanup_tts_blocks_list.blockSignals(False)
        self.audio_cleanup_tts_block_preview.clear()
        self.audio_cleanup_tts_block_preview.setEnabled(False)
        self.audio_cleanup_tts_block_status.setText(status)
        self.audio_cleanup_tts_blocks_card.hide()

    def load_audio_cleanup_tts_timeline(self, audio_path, duration_seconds):
        if not hasattr(self, "audio_cleanup_tts_blocks_list"):
            return
        timeline = load_tts_timeline_for_audio(audio_path)
        if not timeline:
            self.reset_audio_cleanup_tts_timeline()
            return
        duration = max(0.0, float(duration_seconds))
        blocks = [
            block
            for block in timeline["blocks"]
            if block["start_seconds"] < duration and block["end_seconds"] <= duration + 0.5
        ]
        if not blocks:
            self.reset_audio_cleanup_tts_timeline("TTS block JSON found, but no usable ranges were detected.")
            return
        self.audio_cleanup_tts_timeline = {**timeline, "blocks": blocks}
        self.audio_cleanup_tts_blocks_list.blockSignals(True)
        try:
            self.audio_cleanup_tts_blocks_list.clear()
            for block in blocks:
                self.audio_cleanup_tts_blocks_list.addItem(self.audio_cleanup_tts_block_label(block))
                item = self.audio_cleanup_tts_blocks_list.item(self.audio_cleanup_tts_blocks_list.count() - 1)
                item.setData(Qt.ItemDataRole.UserRole, block)
            self.audio_cleanup_tts_blocks_list.setEnabled(not self.is_audio_cleanup_running)
        finally:
            self.audio_cleanup_tts_blocks_list.blockSignals(False)
        self.audio_cleanup_tts_block_preview.clear()
        self.audio_cleanup_tts_block_preview.setEnabled(True)
        self.audio_cleanup_tts_blocks_card.show()
        engine = str(timeline.get("engine") or "TTS").title()
        self.audio_cleanup_tts_block_status.setText(f"{engine} block map loaded: {len(blocks)} range(s).")

    def audio_cleanup_tts_block_label(self, block):
        source_index = int(block.get("source_block_index") or block.get("index") or 1)
        chunk_index = int(block.get("chunk_index") or 1)
        block_ref = f"B. {source_index}" if chunk_index <= 1 else f"B. {source_index}.{chunk_index}"
        return (
            f"{block_ref} - {self.format_audio_cleanup_time(block['start_seconds'])} - "
            f"{self.format_audio_cleanup_time(block['end_seconds'])}"
        )

    def audio_cleanup_tts_block_changed(self):
        item = self.audio_cleanup_tts_blocks_list.currentItem()
        block = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if not isinstance(block, dict):
            self.audio_cleanup_tts_block_preview.clear()
            return
        self.stop_audio_cleanup_playback()
        start = max(0.0, min(self.audio_cleanup_duration_seconds, float(block["start_seconds"])))
        end = max(start, min(self.audio_cleanup_duration_seconds, float(block["end_seconds"])))
        if end <= start:
            return
        self.audio_cleanup_start_spin.blockSignals(True)
        self.audio_cleanup_end_spin.blockSignals(True)
        try:
            self.audio_cleanup_start_spin.setValue(start)
            self.audio_cleanup_end_spin.setValue(end)
        finally:
            self.audio_cleanup_start_spin.blockSignals(False)
            self.audio_cleanup_end_spin.blockSignals(False)
        self.update_audio_cleanup_selection_note()
        if hasattr(self, "audio_cleanup_waveform"):
            self.audio_cleanup_waveform.set_selection(start, end)
            self.audio_cleanup_waveform.center_on(start + ((end - start) / 2))
        self.audio_cleanup_tts_block_preview.setPlainText(str(block.get("text", "")).strip())
        voice = (block.get("voice_label") or block.get("voice_short_name") or "TTS").split(" - ", 1)[0].strip()
        self.audio_cleanup_tts_block_status.setText(
            f"Selected {self.audio_cleanup_tts_block_label(block)} | {voice}"
        )
        self.update_audio_cleanup_button_state()

    def update_audio_cleanup_output(self, force=False):
        if not hasattr(self, "audio_cleanup_output_picker"):
            return
        input_path = self.audio_cleanup_input_picker.text()
        if not input_path:
            return
        suggested = suggest_audio_cleanup_output_path(input_path)
        current = self.audio_cleanup_output_picker.text()
        if force or not current or current == self.audio_cleanup_last_auto_output_path:
            self.audio_cleanup_output_picker.set_text(suggested)
            self.audio_cleanup_last_auto_output_path = suggested

    def load_audio_cleanup_source(self, input_path):
        audio_path = Path(input_path)
        if not audio_path.is_file():
            raise ValueError("The selected audio file does not exist.")
        self.stop_audio_cleanup_playback()
        self.reset_audio_cleanup_changes()
        self.audio_cleanup_input_picker.edit.blockSignals(True)
        try:
            self.audio_cleanup_input_picker.set_text(str(audio_path))
        finally:
            self.audio_cleanup_input_picker.edit.blockSignals(False)
        self.audio_cleanup_last_output_path = ""
        self.update_audio_cleanup_output(force=True)
        self.refresh_audio_cleanup_input_info()
        self.update_audio_cleanup_button_state()
        self.save_user_settings()

    def select_audio_cleanup_input_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select audio file",
            self.audio_cleanup_input_picker.text() or str(Path.home()),
            "Audio files (*.mp3 *.wav *.m4a *.aac *.flac *.ogg);;All files (*.*)",
        )
        if path:
            self.audio_cleanup_input_picker.set_text(path)
            self.update_audio_cleanup_output(force=False)
            self.save_user_settings()

    def select_audio_cleanup_output_file(self):
        input_path = self.audio_cleanup_input_picker.text()
        suggested = self.audio_cleanup_output_picker.text() or (
            suggest_audio_cleanup_output_path(input_path) if input_path else str(Path.home() / "audio_cleaned.mp3")
        )
        filter_text = (
            "MP3 audio (*.mp3);;WAV audio (*.wav);;M4A audio (*.m4a);;"
            "AAC audio (*.aac);;FLAC audio (*.flac);;OGG audio (*.ogg);;All files (*.*)"
        )
        path, selected_filter = QFileDialog.getSaveFileName(self, "Save cleaned audio as", suggested, filter_text)
        if path:
            default_suffix = self.audio_cleanup_output_suffix_from_filter(selected_filter)
            self.audio_cleanup_output_picker.set_text(
                self.normalize_audio_cleanup_output_path(path, input_path, default_suffix)
            )
            self.audio_cleanup_last_auto_output_path = ""
            self.save_user_settings()

    @staticmethod
    def audio_cleanup_output_suffix_from_filter(selected_filter):
        for label, suffix in (
            ("WAV", ".wav"),
            ("M4A", ".m4a"),
            ("AAC", ".aac"),
            ("FLAC", ".flac"),
            ("OGG", ".ogg"),
        ):
            if label in selected_filter:
                return suffix
        return ".mp3"

    @staticmethod
    def normalize_audio_cleanup_output_path(output_path, input_path="", default_suffix=".mp3"):
        path = Path(output_path)
        if path.suffix:
            return str(path)
        input_suffix = Path(input_path).suffix.lower() if input_path else ""
        suffix = input_suffix if input_suffix in SUPPORTED_AUDIO_SUFFIXES else default_suffix
        return str(path.with_suffix(suffix))

    def refresh_audio_cleanup_input_info(self):
        if not hasattr(self, "audio_cleanup_duration_label"):
            return
        self.audio_cleanup_duration_seconds = 0.0
        input_path = self.audio_cleanup_input_picker.text()
        if not input_path:
            self.audio_cleanup_duration_label.setText("No audio selected.")
            self.reset_audio_cleanup_waveform("No audio selected.")
            self.reset_audio_cleanup_tts_timeline("No audio selected.")
            self.update_audio_cleanup_time_limits(0.0)
            return
        audio_path = Path(input_path)
        if not audio_path.is_file():
            self.audio_cleanup_duration_label.setText("Selected audio file does not exist.")
            self.reset_audio_cleanup_waveform("No waveform loaded.")
            self.reset_audio_cleanup_tts_timeline("No TTS block JSON found.")
            self.update_audio_cleanup_time_limits(0.0)
            return
        ffmpeg = find_ffmpeg_exe()
        if not ffmpeg:
            self.audio_cleanup_duration_label.setText("ffmpeg missing.")
            self.reset_audio_cleanup_waveform("ffmpeg missing.")
            self.reset_audio_cleanup_tts_timeline("ffmpeg missing.")
            self.update_audio_cleanup_time_limits(0.0)
            return
        try:
            info = probe_audio_info(ffmpeg, audio_path)
        except (OSError, RuntimeError, ValueError) as exc:
            self.audio_cleanup_duration_label.setText(f"Could not inspect audio: {exc}")
            self.reset_audio_cleanup_waveform("Waveform unavailable.")
            self.reset_audio_cleanup_tts_timeline("No TTS block JSON loaded.")
            self.update_audio_cleanup_time_limits(0.0)
            return
        duration = float(info.get("duration_seconds") or 0.0)
        if not info.get("has_audio") or duration <= 0:
            self.audio_cleanup_duration_label.setText("Could not detect an audio stream.")
            self.reset_audio_cleanup_waveform("Waveform unavailable.")
            self.reset_audio_cleanup_tts_timeline("No TTS block JSON loaded.")
            self.update_audio_cleanup_time_limits(0.0)
            return
        self.audio_cleanup_duration_seconds = duration
        self.audio_cleanup_duration_label.setText(f"Duration: {self.format_audio_cleanup_time(duration)}")
        self.update_audio_cleanup_time_limits(duration)
        self.load_audio_cleanup_tts_timeline(audio_path, duration)
        self.start_audio_cleanup_waveform_load(ffmpeg, audio_path, duration)

    def update_audio_cleanup_time_limits(self, duration):
        duration = max(0.0, float(duration))
        for spin in (self.audio_cleanup_start_spin, self.audio_cleanup_end_spin):
            spin.blockSignals(True)
            spin.setMaximum(max(0.001, duration))
            spin.blockSignals(False)
        if duration <= 0:
            self.audio_cleanup_start_spin.setValue(0.0)
            self.audio_cleanup_end_spin.setValue(0.0)
            self.update_audio_cleanup_selection_note()
            return
        self.audio_cleanup_start_spin.blockSignals(True)
        self.audio_cleanup_end_spin.blockSignals(True)
        self.audio_cleanup_start_spin.setValue(0.0)
        self.audio_cleanup_end_spin.setValue(min(duration, 1.0))
        self.audio_cleanup_start_spin.blockSignals(False)
        self.audio_cleanup_end_spin.blockSignals(False)
        self.update_audio_cleanup_selection_note()

    def audio_cleanup_time_changed(self):
        self.update_audio_cleanup_selection_note()
        if hasattr(self, "audio_cleanup_waveform") and not self.audio_cleanup_waveform_syncing:
            self.audio_cleanup_waveform.set_selection(
                self.audio_cleanup_start_spin.value(),
                self.audio_cleanup_end_spin.value(),
            )
        self.update_audio_cleanup_button_state()

    def audio_cleanup_waveform_selection_changed(self, start, end):
        self.audio_cleanup_waveform_syncing = True
        try:
            self.audio_cleanup_start_spin.blockSignals(True)
            self.audio_cleanup_end_spin.blockSignals(True)
            self.audio_cleanup_start_spin.setValue(start)
            self.audio_cleanup_end_spin.setValue(end)
        finally:
            self.audio_cleanup_start_spin.blockSignals(False)
            self.audio_cleanup_end_spin.blockSignals(False)
            self.audio_cleanup_waveform_syncing = False
        self.update_audio_cleanup_selection_note()
        self.update_audio_cleanup_button_state()

    def update_audio_cleanup_selection_note(self):
        if not hasattr(self, "audio_cleanup_selection_note"):
            return
        start = self.audio_cleanup_start_spin.value()
        end = self.audio_cleanup_end_spin.value()
        duration = max(0.0, end - start)
        if duration <= 0:
            self.audio_cleanup_selection_note.setText("Selection: none")
            return
        self.audio_cleanup_selection_note.setText(
            f"Selection: {self.format_audio_cleanup_time(start)} - "
            f"{self.format_audio_cleanup_time(end)} ({duration:.3f}s)"
        )

    def has_audio_cleanup_selection(self):
        return self.audio_cleanup_end_spin.value() > self.audio_cleanup_start_spin.value()

    @staticmethod
    def audio_cleanup_action_label_for_key(action):
        for label, key in AUDIO_CLEANUP_ACTION_BY_LABEL.items():
            if key == action:
                return label
        return str(action)

    def audio_cleanup_action_key(self):
        return AUDIO_CLEANUP_ACTION_BY_LABEL[AUDIO_CLEANUP_REMOVE_LABEL]

    def reset_audio_cleanup_changes(self):
        self.audio_cleanup_changes = []
        if hasattr(self, "audio_cleanup_changes_list"):
            self.refresh_audio_cleanup_changes_list()
        self.refresh_audio_cleanup_waveform_markers()

    def refresh_audio_cleanup_waveform_markers(self):
        if not hasattr(self, "audio_cleanup_waveform"):
            return
        self.audio_cleanup_waveform.set_markers([
            {
                "action": change["action"],
                "start_seconds": change["source_start_seconds"],
                "end_seconds": change["source_end_seconds"],
            }
            for change in self.audio_cleanup_changes
        ])

    def adjusted_audio_cleanup_range_for_changes(self, start, end, changes):
        adjusted_start = float(start)
        adjusted_end = float(end)
        for change in changes:
            if change["action"] != "remove":
                continue
            cut_start = change["source_start_seconds"]
            cut_end = change["source_end_seconds"]
            cut_duration = cut_end - cut_start
            if end <= cut_start:
                continue
            if start >= cut_end:
                adjusted_start -= cut_duration
                adjusted_end -= cut_duration
                continue
            raise ValueError("The selected range overlaps a cut already queued.")
        return max(0.0, adjusted_start), max(0.0, adjusted_end)

    def adjusted_audio_cleanup_range(self, start, end):
        return self.adjusted_audio_cleanup_range_for_changes(start, end, self.audio_cleanup_changes)

    def recompute_audio_cleanup_changes(self):
        recomputed = []
        for change in self.audio_cleanup_changes:
            adjusted_start, adjusted_end = self.adjusted_audio_cleanup_range_for_changes(
                change["source_start_seconds"],
                change["source_end_seconds"],
                recomputed,
            )
            recomputed.append({
                **change,
                "start_seconds": adjusted_start,
                "end_seconds": adjusted_end,
            })
        self.audio_cleanup_changes = recomputed

    def audio_cleanup_change_label(self, index, change):
        return (
            f"C. {index} - {self.format_audio_cleanup_time(change['start_seconds'])} - "
            f"{self.format_audio_cleanup_time(change['end_seconds'])} | "
            f"{self.audio_cleanup_action_label_for_key(change['action'])}"
        )

    def audio_cleanup_change_row_widget(self, index, change):
        row = QWidget()
        row.setObjectName("InlinePanel")
        row_index = index - 1

        def select_change(_event):
            self.audio_cleanup_changes_list.setCurrentRow(row_index)

        row.mousePressEvent = select_change
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)
        label = QLabel(self.audio_cleanup_change_label(index, change))
        label.setObjectName("Muted")
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        remove_button = QToolButton()
        remove_button.setObjectName("InlineDangerButton")
        remove_button.setText("X")
        remove_button.setToolTip("Remove this change")
        remove_button.setAutoRaise(True)
        remove_button.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_button.clicked.connect(lambda _checked=False: self.remove_audio_cleanup_change_at_index(row_index))
        row_layout.addWidget(label, 1)
        row_layout.addWidget(remove_button)
        return row

    def refresh_audio_cleanup_changes_list(self):
        if not hasattr(self, "audio_cleanup_changes_list"):
            return
        self.audio_cleanup_changes_list.blockSignals(True)
        try:
            self.audio_cleanup_changes_list.clear()
            if not self.audio_cleanup_changes:
                self.audio_cleanup_changes_list.addItem("No applied changes.")
            else:
                for index, change in enumerate(self.audio_cleanup_changes, start=1):
                    item = QListWidgetItem()
                    item.setData(Qt.ItemDataRole.UserRole, index - 1)
                    row = self.audio_cleanup_change_row_widget(index, change)
                    item.setSizeHint(row.sizeHint())
                    self.audio_cleanup_changes_list.addItem(item)
                    self.audio_cleanup_changes_list.setItemWidget(item, row)
        finally:
            self.audio_cleanup_changes_list.blockSignals(False)
        self.refresh_audio_cleanup_waveform_markers()
        self.audio_cleanup_changes_status.setText(
            f"{len(self.audio_cleanup_changes)} change(s) queued."
            if self.audio_cleanup_changes else
            "Apply one or more ranges before cleaning audio."
        )
        self.update_audio_cleanup_button_state()

    def audio_cleanup_change_selection_changed(self):
        item = self.audio_cleanup_changes_list.currentItem()
        if item is None:
            self.update_audio_cleanup_button_state()
            return
        index = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(index, int) or not (0 <= index < len(self.audio_cleanup_changes)):
            self.update_audio_cleanup_button_state()
            return
        change = self.audio_cleanup_changes[index]
        start = change["source_start_seconds"]
        end = change["source_end_seconds"]
        if hasattr(self, "audio_cleanup_waveform"):
            self.audio_cleanup_waveform.center_on((start + end) / 2)
            self.audio_cleanup_waveform.set_selection(start, end)
        self.audio_cleanup_start_spin.blockSignals(True)
        self.audio_cleanup_end_spin.blockSignals(True)
        try:
            self.audio_cleanup_start_spin.setValue(start)
            self.audio_cleanup_end_spin.setValue(end)
        finally:
            self.audio_cleanup_start_spin.blockSignals(False)
            self.audio_cleanup_end_spin.blockSignals(False)
        self.update_audio_cleanup_selection_note()
        self.update_audio_cleanup_button_state()

    def apply_audio_cleanup_change(self, action=None):
        if not self.has_audio_cleanup_selection():
            self.show_error("Audio Cleanup", "Select a range before applying a cleanup change.")
            return
        start = self.audio_cleanup_start_spin.value()
        end = self.audio_cleanup_end_spin.value()
        try:
            adjusted_start, adjusted_end = self.adjusted_audio_cleanup_range(start, end)
        except ValueError as exc:
            self.show_error("Audio Cleanup", str(exc))
            return
        if adjusted_end <= adjusted_start:
            self.show_error("Audio Cleanup", "The selected range is no longer valid after queued cuts.")
            return
        self.audio_cleanup_changes.append({
            "action": action or self.audio_cleanup_action_key(),
            "source_start_seconds": start,
            "source_end_seconds": end,
            "start_seconds": adjusted_start,
            "end_seconds": adjusted_end,
        })
        self.refresh_audio_cleanup_changes_list()
        self.audio_cleanup_changes_list.setCurrentRow(len(self.audio_cleanup_changes) - 1)
        self.audio_cleanup_status.setText(f"Queued cleanup change {len(self.audio_cleanup_changes)}.")

    def remove_selected_audio_cleanup_change(self):
        item = self.audio_cleanup_changes_list.currentItem()
        if item is None:
            return
        index = item.data(Qt.ItemDataRole.UserRole)
        self.remove_audio_cleanup_change_at_index(index)

    def remove_audio_cleanup_change_at_index(self, index):
        if not isinstance(index, int) or not (0 <= index < len(self.audio_cleanup_changes)):
            return
        del self.audio_cleanup_changes[index]
        self.recompute_audio_cleanup_changes()
        self.refresh_audio_cleanup_changes_list()
        if self.audio_cleanup_changes:
            self.audio_cleanup_changes_list.setCurrentRow(min(index, len(self.audio_cleanup_changes) - 1))
        self.audio_cleanup_status.setText("Removed queued cleanup change.")

    def collect_audio_cleanup_options(self):
        input_path = self.audio_cleanup_input_picker.text()
        if not input_path:
            raise ValueError("Please select an audio file.")
        input_file = Path(input_path)
        if not input_file.is_file():
            raise ValueError("The selected audio file does not exist.")
        if input_file.suffix.lower() not in SUPPORTED_AUDIO_SUFFIXES:
            raise ValueError("The selected file must be .mp3, .wav, .m4a, .aac, .flac or .ogg.")
        if self.audio_cleanup_duration_seconds <= 0:
            raise ValueError("Could not detect the selected audio duration.")
        if not self.audio_cleanup_changes:
            raise ValueError("Apply at least one cleanup range before cleaning audio.")

        output_path = self.audio_cleanup_output_picker.text()
        if not output_path:
            output_path = suggest_audio_cleanup_output_path(input_path)
        output_path = self.normalize_audio_cleanup_output_path(output_path, input_path)
        output_file = Path(output_path)
        if output_file.suffix.lower() not in SUPPORTED_AUDIO_SUFFIXES:
            raise ValueError("Cleaned audio output must be .mp3, .wav, .m4a, .aac, .flac or .ogg.")
        if not output_file.parent.is_dir():
            raise ValueError("The output folder does not exist.")
        try:
            if output_file.resolve() == input_file.resolve():
                raise ValueError("Choose an output path different from the source audio.")
        except OSError:
            pass
        self.audio_cleanup_output_picker.set_text(output_path)
        self.save_user_settings()
        return input_path, output_path, list(self.audio_cleanup_changes), self.audio_cleanup_duration_seconds

    def start_audio_cleanup_job(self):
        try:
            input_path, output_path, changes, duration = self.collect_audio_cleanup_options()
        except ValueError as exc:
            self.audio_cleanup_status.setText("Error.")
            self.show_error("Audio Cleanup", str(exc))
            return
        ffmpeg = find_ffmpeg_exe()
        if not ffmpeg:
            self.audio_cleanup_status.setText("ffmpeg missing.")
            self.show_error("ffmpeg missing", "Could not find ffmpeg. Use the full VoiceBridge bundle.")
            return

        self.stop_audio_cleanup_playback()
        self.audio_cleanup_cancel_requested = False
        self.audio_cleanup_process = None
        self.audio_cleanup_last_output_path = ""
        self.reset_audio_cleanup_log()
        self.is_audio_cleanup_running = True
        self.update_audio_cleanup_progress_percent(0)
        self.audio_cleanup_status.setText(f"Cleaning {len(changes)} queued range(s)...")
        self.append_audio_cleanup_log(f"Input: {input_path}")
        for index, change in enumerate(changes, start=1):
            self.append_audio_cleanup_log(
                f"C. {index}: {change['start_seconds']:.3f}s - {change['end_seconds']:.3f}s "
                f"| {self.audio_cleanup_action_label_for_key(change['action'])}"
            )
        self.update_audio_cleanup_button_state()
        self.update_tts_button_state()
        self.update_stt_button_state()
        self.update_video_subtitle_button_state()
        self.update_video_cleanup_button_state()
        threading.Thread(
            target=self.audio_cleanup_worker,
            args=(str(ffmpeg), input_path, output_path, changes, duration),
            daemon=True,
        ).start()

    def audio_cleanup_worker(self, ffmpeg, input_path, output_path, changes, duration):
        try:
            output_file = Path(output_path)
            current_input = Path(input_path)
            current_duration = float(duration)
            change_count = max(1, len(changes))
            with tempfile.TemporaryDirectory(
                prefix="voicebridge-audio-cleanup-",
                dir=str(output_file.resolve().parent),
            ) as temp_dir_name:
                temp_dir = Path(temp_dir_name)
                final_temp_output = temp_dir / output_file.name
                for index, change in enumerate(changes, start=1):
                    if self.audio_cleanup_cancel_requested:
                        self.post(self.audio_cleanup_job_cancelled)
                        return

                    action = change["action"]
                    start = float(change["start_seconds"])
                    end = float(change["end_seconds"])
                    output_duration = (
                        max(0.001, current_duration - (end - start)) if action == "remove" else current_duration
                    )
                    stage_output = final_temp_output if index == change_count else temp_dir / f"stage-{index:04d}.wav"
                    command = audio_cleanup_command(
                        ffmpeg,
                        current_input,
                        stage_output,
                        action,
                        start,
                        end,
                        current_duration,
                    )
                    progress_start = ((index - 1) / change_count) * 99
                    progress_end = (index / change_count) * 99
                    return_code, recent_output = self.run_audio_cleanup_ffmpeg_process(
                        command,
                        output_duration,
                        progress_start=progress_start,
                        progress_end=progress_end,
                    )
                    if self.audio_cleanup_cancel_requested:
                        self.post(self.audio_cleanup_job_cancelled)
                        return
                    if return_code != 0 or not stage_output.is_file():
                        message = "\n".join(recent_output[-8:]) or f"Audio cleanup exited with code {return_code}."
                        self.post(self.audio_cleanup_job_failed, message)
                        return

                    current_input = stage_output
                    current_duration = output_duration

                os.replace(final_temp_output, output_file)
                timeline_path = write_audio_cleanup_timeline_for_changes(
                    input_path,
                    output_path,
                    changes=changes,
                    total_duration_seconds=current_duration,
                )
                self.post(self.audio_cleanup_job_succeeded, output_path, len(changes), str(timeline_path or ""))
        except (OSError, RuntimeError, ValueError, AssertionError) as exc:
            self.post(self.audio_cleanup_job_failed, str(exc))
        finally:
            self.post(self.finish_audio_cleanup_job)

    @staticmethod
    def parse_audio_cleanup_ffmpeg_time_seconds(value):
        value = value.strip()
        time_match = re.match(r"(\d+):(\d+):(\d+(?:\.\d+)?)", value)
        if time_match:
            return int(time_match.group(1)) * 3600 + int(time_match.group(2)) * 60 + float(time_match.group(3))
        try:
            return float(value) / 1_000_000
        except ValueError:
            return None

    def audio_cleanup_progress_percent(self, line, duration_seconds):
        if not duration_seconds:
            return None
        if line.startswith("out_time=") or line.startswith(("out_time_us=", "out_time_ms=")):
            seconds = self.parse_audio_cleanup_ffmpeg_time_seconds(line.split("=", 1)[1])
        else:
            return None
        if seconds is None:
            return None
        return min(99, max(0, round((seconds / duration_seconds) * 100)))

    @staticmethod
    def is_audio_cleanup_ffmpeg_progress_line(line):
        key = line.split("=", 1)[0]
        return key in {
            "bitrate",
            "drop_frames",
            "dup_frames",
            "fps",
            "frame",
            "out_time",
            "out_time_ms",
            "out_time_us",
            "progress",
            "speed",
            "stream_0_0_q",
            "total_size",
        }

    def run_audio_cleanup_ffmpeg_process(
        self,
        command,
        duration_seconds=None,
        *,
        progress_start=0.0,
        progress_end=99.0,
    ):
        recent_output = []
        last_progress_percent = -1.0
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )
        self.audio_cleanup_process = process
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.strip()
            if not line:
                continue
            progress_percent = self.audio_cleanup_progress_percent(line, duration_seconds)
            if progress_percent is not None:
                mapped_percent = progress_start + ((progress_end - progress_start) * (progress_percent / 100))
                if mapped_percent > last_progress_percent:
                    last_progress_percent = mapped_percent
                    self.post(self.update_audio_cleanup_progress_percent, round(mapped_percent))
                continue
            if self.is_audio_cleanup_ffmpeg_progress_line(line):
                continue
            recent_output.append(line)
            recent_output = recent_output[-12:]
            self.post(self.append_audio_cleanup_log, line)
            if self.audio_cleanup_cancel_requested and process.poll() is None:
                process.terminate()
        return process.wait(), recent_output

    def cancel_audio_cleanup_job(self):
        if not self.is_audio_cleanup_running:
            return
        self.audio_cleanup_cancel_requested = True
        self.audio_cleanup_status.setText("Cancelling...")
        self.append_audio_cleanup_log("Cancellation requested.")
        self.update_audio_cleanup_button_state()
        process = self.audio_cleanup_process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError as exc:
                self.append_audio_cleanup_log(f"Could not terminate process cleanly: {exc}")

    def audio_cleanup_job_succeeded(self, output_path, change_count, timeline_path=""):
        self.audio_cleanup_last_output_path = output_path
        self.audio_cleanup_status.setText("Cleaned audio saved.")
        self.append_audio_cleanup_log(f"Output saved: {output_path}")
        if timeline_path:
            self.append_audio_cleanup_log(f"TTS timeline saved: {timeline_path}")
        self.update_audio_cleanup_progress_percent(100)
        self.record_job(
            "AUDIO",
            "Audio cleanup",
            self.audio_cleanup_input_picker.text(),
            output_path,
            f"{change_count} change(s)",
        )
        self.load_audio_cleanup_source(output_path)
        self.audio_cleanup_last_output_path = output_path
        self.update_audio_cleanup_button_state()
        self.show_info("Audio Cleanup", f"Audio saved and loaded for the next cleanup pass:\n{output_path}")

    def audio_cleanup_job_failed(self, message):
        self.audio_cleanup_status.setText("Error.")
        self.append_audio_cleanup_log(f"ERROR: {message}")
        self.show_error("Audio Cleanup", message)

    def audio_cleanup_job_cancelled(self):
        self.audio_cleanup_status.setText("Cancelled.")
        self.append_audio_cleanup_log("Job cancelled.")

    def finish_audio_cleanup_job(self):
        self.is_audio_cleanup_running = False
        self.audio_cleanup_progress.hide()
        self.audio_cleanup_process = None
        self.update_audio_cleanup_button_state()
        self.update_tts_button_state()
        self.update_stt_button_state()
        self.update_video_subtitle_button_state()
        self.update_video_cleanup_button_state()

    def update_audio_cleanup_button_state(self):
        if not hasattr(self, "audio_cleanup_start_button"):
            return
        busy_elsewhere = self.is_converting or self.is_stt_running or self.is_video_running or self.is_cleanup_running
        has_input = bool(self.audio_cleanup_input_picker.text() and self.audio_cleanup_duration_seconds > 0)
        has_range = self.has_audio_cleanup_selection()
        has_changes = bool(self.audio_cleanup_changes)
        self.audio_cleanup_start_button.setEnabled(
            has_input and has_changes and not self.is_audio_cleanup_running and not busy_elsewhere
        )
        action_buttons_enabled = has_input and has_range and not self.is_audio_cleanup_running and not busy_elsewhere
        for button_name in (
            "audio_cleanup_cut_button",
            "audio_cleanup_silence_button",
            "audio_cleanup_fade_button",
        ):
            if hasattr(self, button_name):
                getattr(self, button_name).setEnabled(action_buttons_enabled)
        if hasattr(self, "audio_cleanup_changes_list"):
            self.audio_cleanup_changes_list.setEnabled(has_changes and not self.is_audio_cleanup_running)
            if not has_changes:
                self.audio_cleanup_changes_list.clearSelection()
        self.audio_cleanup_cancel_button.setEnabled(
            self.is_audio_cleanup_running and not self.audio_cleanup_cancel_requested
        )
        self.audio_cleanup_play_selection_button.setText("Play selection" if has_range else "Play all")
        self.audio_cleanup_play_selection_button.setEnabled(has_input and not self.is_audio_cleanup_running)
        output_ready = bool(
            self.audio_cleanup_last_output_path and Path(self.audio_cleanup_last_output_path).is_file()
        )
        self.audio_cleanup_play_output_button.setEnabled(output_ready and not self.is_audio_cleanup_running)
        self.audio_cleanup_open_output_button.setEnabled(output_ready)
        self.audio_cleanup_open_folder_button.setEnabled(output_ready)
        for widget in (
            self.audio_cleanup_input_picker,
            self.audio_cleanup_output_picker,
            self.audio_cleanup_start_spin,
            self.audio_cleanup_end_spin,
        ):
            widget.setEnabled(not self.is_audio_cleanup_running)
        self.audio_cleanup_tts_blocks_list.setEnabled(
            bool(self.audio_cleanup_tts_timeline) and not self.is_audio_cleanup_running
        )
        self.audio_cleanup_tts_block_preview.setEnabled(bool(self.audio_cleanup_tts_timeline))
        if hasattr(self, "audio_cleanup_waveform"):
            has_waveform = self.audio_cleanup_waveform.has_waveform()
            self.audio_cleanup_waveform.setEnabled(
                has_waveform and not self.is_audio_cleanup_running
            )
            self.audio_cleanup_waveform_zoom_combo.setEnabled(has_waveform and not self.is_audio_cleanup_running)
            self.audio_cleanup_waveform_scroll.setEnabled(
                has_waveform
                and self.audio_cleanup_waveform.zoom_factor() > 1.0
                and not self.is_audio_cleanup_running
            )
        self.update_navigation_state()

    def play_audio_cleanup_selection(self):
        if self.audio_cleanup_media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.stop_audio_cleanup_playback()
            return
        input_path = self.audio_cleanup_input_picker.text()
        if not input_path or not Path(input_path).is_file():
            return
        start = self.audio_cleanup_start_spin.value()
        end = self.audio_cleanup_end_spin.value()
        if end <= start:
            self.play_audio_cleanup_path(input_path)
            return
        self.play_audio_cleanup_path(input_path, start_seconds=start, stop_after_seconds=end - start)

    def play_audio_cleanup_output(self):
        if self.audio_cleanup_media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.stop_audio_cleanup_playback()
            return
        if not self.audio_cleanup_last_output_path or not Path(self.audio_cleanup_last_output_path).is_file():
            return
        self.play_audio_cleanup_path(self.audio_cleanup_last_output_path)

    def play_audio_cleanup_path(self, path, start_seconds=0.0, stop_after_seconds=None):
        self.audio_cleanup_preview_timer.stop()
        self.audio_cleanup_preview_end_ms = None
        self.audio_cleanup_media_player.stop()
        self.refresh_audio_cleanup_playback_device()
        start_ms = max(0, round(start_seconds * 1000))
        resolved_path = Path(path).resolve()
        tracks_waveform = self.audio_cleanup_path_matches_waveform_source(resolved_path)
        self.audio_cleanup_preview_pending_start_ms = start_ms
        self.audio_cleanup_preview_pending_timer_ms = (
            max(10_000, round(stop_after_seconds * 1000) + 5000) if stop_after_seconds else None
        )
        self.audio_cleanup_preview_tracks_waveform = tracks_waveform
        if tracks_waveform and hasattr(self, "audio_cleanup_waveform"):
            self.audio_cleanup_waveform.center_on(start_ms / 1000)
            self.audio_cleanup_waveform.set_playhead(start_ms / 1000)
        elif hasattr(self, "audio_cleanup_waveform"):
            self.audio_cleanup_waveform.set_playhead(None)
        self.audio_cleanup_media_player.setSource(QUrl.fromLocalFile(str(resolved_path)))
        if stop_after_seconds:
            self.audio_cleanup_preview_end_ms = start_ms + max(1, round(stop_after_seconds * 1000))
        self.audio_cleanup_start_pending_preview_if_ready(self.audio_cleanup_media_player.mediaStatus())

    def audio_cleanup_start_pending_preview_if_ready(self, status):
        if self.audio_cleanup_preview_pending_start_ms is None:
            return
        if status not in {
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferingMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        }:
            return
        start_ms = self.audio_cleanup_preview_pending_start_ms
        timer_ms = self.audio_cleanup_preview_pending_timer_ms
        self.audio_cleanup_preview_pending_start_ms = None
        self.audio_cleanup_preview_pending_timer_ms = None
        self.audio_cleanup_media_player.setPosition(start_ms)
        if getattr(self, "audio_cleanup_preview_tracks_waveform", False) and hasattr(self, "audio_cleanup_waveform"):
            self.audio_cleanup_waveform.set_playhead(start_ms / 1000)
        self.audio_cleanup_media_player.play()
        if timer_ms is not None:
            self.audio_cleanup_preview_timer.start(timer_ms)

    def audio_cleanup_path_matches_waveform_source(self, path):
        input_path = self.audio_cleanup_input_picker.text()
        if not input_path:
            return False
        try:
            return Path(path).resolve() == Path(input_path).resolve()
        except OSError:
            return False

    def audio_cleanup_playback_position_changed(self, position_ms):
        if self.audio_cleanup_preview_pending_start_ms is not None:
            return
        if getattr(self, "audio_cleanup_preview_tracks_waveform", False) and hasattr(self, "audio_cleanup_waveform"):
            self.audio_cleanup_waveform.set_playhead(position_ms / 1000)
        target_ms = self.audio_cleanup_preview_end_ms
        if target_ms is not None and position_ms >= target_ms:
            self.stop_audio_cleanup_playback()

    def audio_cleanup_media_status_changed(self, status):
        self.audio_cleanup_start_pending_preview_if_ready(status)
        if status in {
            QMediaPlayer.MediaStatus.NoMedia,
            QMediaPlayer.MediaStatus.InvalidMedia,
        }:
            self.audio_cleanup_preview_pending_start_ms = None
            self.audio_cleanup_preview_pending_timer_ms = None

    def audio_cleanup_playback_state_changed(self, state):
        if state == QMediaPlayer.PlaybackState.PlayingState:
            return
        if self.audio_cleanup_preview_pending_start_ms is not None:
            return
        self.audio_cleanup_preview_tracks_waveform = False
        if hasattr(self, "audio_cleanup_waveform"):
            self.audio_cleanup_waveform.set_playhead(None)

    def refresh_audio_cleanup_playback_device(self):
        if not hasattr(self, "audio_cleanup_audio_output"):
            return
        try:
            self.audio_cleanup_audio_output.setDevice(QMediaDevices.defaultAudioOutput())
        except RuntimeError:
            return

    def stop_audio_cleanup_playback(self):
        if not hasattr(self, "audio_cleanup_media_player"):
            return
        self.audio_cleanup_preview_end_ms = None
        self.audio_cleanup_preview_pending_start_ms = None
        self.audio_cleanup_preview_pending_timer_ms = None
        self.audio_cleanup_preview_tracks_waveform = False
        self.audio_cleanup_preview_timer.stop()
        self.audio_cleanup_media_player.stop()
        if hasattr(self, "audio_cleanup_waveform"):
            self.audio_cleanup_waveform.set_playhead(None)

    def open_audio_cleanup_output(self):
        open_path(self.audio_cleanup_last_output_path)

    def open_audio_cleanup_output_folder(self):
        if self.audio_cleanup_last_output_path and Path(self.audio_cleanup_last_output_path).is_file():
            open_path(Path(self.audio_cleanup_last_output_path).parent)

    def append_audio_cleanup_log(self, line):
        self.audio_cleanup_log_lines.append(line)
        self.audio_cleanup_log_lines = self.audio_cleanup_log_lines[-300:]
        self.audio_cleanup_log.appendPlainText(line)
        scrollbar = self.audio_cleanup_log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def reset_audio_cleanup_log(self):
        self.audio_cleanup_log_lines = []
        self.audio_cleanup_log.clear()

    def toggle_audio_cleanup_details(self):
        if self.audio_cleanup_log.isVisible():
            self.audio_cleanup_log.hide()
            self.audio_cleanup_details_button.setText("Show details")
            return
        self.audio_cleanup_log.show()
        self.audio_cleanup_details_button.setText("Hide details")

    @staticmethod
    def format_audio_cleanup_time(seconds):
        seconds = max(0.0, float(seconds))
        minutes, remainder = divmod(seconds, 60)
        hours, minutes = divmod(int(minutes), 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{remainder:06.3f}"
        return f"{minutes:02d}:{remainder:06.3f}"

    def build_audio_cleanup_page(self):
        page, layout = self.page_container()
        self.page_header(
            layout,
            "Audio Cleanup",
            "Remove, silence or fade short AI TTS artifacts and hallucinated fragments, not full audio edits.",
        )

        grid = QGridLayout()
        grid.setSpacing(16)
        layout.addLayout(grid)

        cleanup_top_card_min_height = 180
        files_card = Card("Files")
        files_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        files_card.setMinimumHeight(cleanup_top_card_min_height)
        self.audio_cleanup_input_picker = FilePicker("Audio file")
        self.audio_cleanup_output_picker = FilePicker("Save cleaned audio as", "Save as...")
        self.audio_cleanup_input_picker.button.clicked.connect(self.select_audio_cleanup_input_file)
        self.audio_cleanup_output_picker.button.clicked.connect(self.select_audio_cleanup_output_file)
        self.audio_cleanup_input_picker.edit.textChanged.connect(self.audio_cleanup_input_changed)
        self.audio_cleanup_output_picker.edit.textChanged.connect(lambda _text: self.save_user_settings())
        self.audio_cleanup_duration_label = QLabel("No audio selected.")
        self.audio_cleanup_duration_label.setObjectName("Muted")
        files_card.content_layout.addWidget(self.audio_cleanup_input_picker)
        files_card.content_layout.addWidget(self.audio_cleanup_output_picker)
        files_card.content_layout.addWidget(self.audio_cleanup_duration_label)

        self.audio_cleanup_tts_timeline = None
        self.audio_cleanup_changes_card = Card("Applied changes")
        self.audio_cleanup_changes_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.audio_cleanup_changes_card.setMinimumHeight(cleanup_top_card_min_height)
        self.audio_cleanup_changes_list = QListWidget()
        self.audio_cleanup_changes_list.setMinimumHeight(88)
        self.audio_cleanup_changes_list.currentItemChanged.connect(
            lambda _current, _previous: self.audio_cleanup_change_selection_changed()
        )
        self.audio_cleanup_changes_status = QLabel("Apply one or more ranges before cleaning audio.")
        self.audio_cleanup_changes_status.setObjectName("Muted")
        self.audio_cleanup_changes_status.setWordWrap(True)
        self.audio_cleanup_changes_card.content_layout.addWidget(self.audio_cleanup_changes_list)
        self.audio_cleanup_changes_card.content_layout.addWidget(self.audio_cleanup_changes_status)

        self.audio_cleanup_start_spin = QDoubleSpinBox()
        self.audio_cleanup_end_spin = QDoubleSpinBox()
        for spin in (self.audio_cleanup_start_spin, self.audio_cleanup_end_spin):
            spin.setDecimals(3)
            spin.setRange(0.0, 0.001)
            spin.setSingleStep(0.01)
            spin.setSuffix(" s")
            spin.valueChanged.connect(lambda _value: self.audio_cleanup_time_changed())
        self.audio_cleanup_selection_note = QLabel("Selection: none")
        self.audio_cleanup_selection_note.setObjectName("Muted")

        grid.addWidget(files_card, 0, 0)
        grid.addWidget(self.audio_cleanup_changes_card, 0, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        waveform_card = Card("Waveform")
        waveform_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.audio_cleanup_waveform_generation = 0
        self.audio_cleanup_waveform_syncing = False
        self.audio_cleanup_waveform_view_syncing = False
        self.audio_cleanup_waveform = AudioWaveformWidget()
        self.audio_cleanup_waveform.selectionChanged.connect(self.audio_cleanup_waveform_selection_changed)
        self.audio_cleanup_waveform.viewChanged.connect(self.audio_cleanup_waveform_view_changed)
        waveform_controls = QHBoxLayout()
        waveform_controls.setContentsMargins(0, 0, 0, 0)
        self.audio_cleanup_waveform_zoom_combo = QComboBox()
        for label, zoom_factor in AUDIO_CLEANUP_WAVEFORM_ZOOM_LEVELS:
            self.audio_cleanup_waveform_zoom_combo.addItem(label, zoom_factor)
        self.audio_cleanup_waveform_zoom_combo.setEnabled(False)
        self.audio_cleanup_waveform_zoom_combo.currentTextChanged.connect(
            lambda _text: self.audio_cleanup_waveform_zoom_changed()
        )
        self.audio_cleanup_waveform_scroll = QSlider(Qt.Orientation.Horizontal)
        self.audio_cleanup_waveform_scroll.setRange(0, AUDIO_CLEANUP_WAVEFORM_SCROLL_MAX)
        self.audio_cleanup_waveform_scroll.setEnabled(False)
        self.audio_cleanup_waveform_scroll.valueChanged.connect(self.audio_cleanup_waveform_scroll_changed)
        waveform_controls.addWidget(QLabel("Zoom"))
        waveform_controls.addWidget(self.audio_cleanup_waveform_zoom_combo)
        waveform_controls.addWidget(QLabel("Position"))
        waveform_controls.addWidget(self.audio_cleanup_waveform_scroll, 1)
        waveform_action_controls = QHBoxLayout()
        waveform_action_controls.setContentsMargins(0, 0, 0, 0)
        waveform_action_controls.setSpacing(8)
        self.audio_cleanup_play_selection_button = QPushButton("Play selection")
        self.audio_cleanup_cut_button = QPushButton("Cut")
        self.audio_cleanup_cut_button.setObjectName("DangerButton")
        self.audio_cleanup_silence_button = QPushButton("Silence")
        self.audio_cleanup_fade_button = QPushButton("Fade")
        self.audio_cleanup_play_selection_button.clicked.connect(self.play_audio_cleanup_selection)
        self.audio_cleanup_cut_button.clicked.connect(
            lambda _checked=False: self.apply_audio_cleanup_change(
                AUDIO_CLEANUP_ACTION_BY_LABEL[AUDIO_CLEANUP_REMOVE_LABEL]
            )
        )
        self.audio_cleanup_silence_button.clicked.connect(
            lambda _checked=False: self.apply_audio_cleanup_change(
                AUDIO_CLEANUP_ACTION_BY_LABEL[AUDIO_CLEANUP_SILENCE_LABEL]
            )
        )
        self.audio_cleanup_fade_button.clicked.connect(
            lambda _checked=False: self.apply_audio_cleanup_change(
                AUDIO_CLEANUP_ACTION_BY_LABEL[AUDIO_CLEANUP_FADE_LABEL]
            )
        )
        waveform_action_controls.addWidget(QLabel("Start"))
        waveform_action_controls.addWidget(self.audio_cleanup_start_spin)
        waveform_action_controls.addWidget(QLabel("End"))
        waveform_action_controls.addWidget(self.audio_cleanup_end_spin)
        waveform_action_controls.addStretch(1)
        waveform_action_controls.addWidget(self.audio_cleanup_play_selection_button)
        waveform_action_separator = QFrame()
        waveform_action_separator.setFrameShape(QFrame.Shape.VLine)
        waveform_action_separator.setFrameShadow(QFrame.Shadow.Plain)
        waveform_action_separator.setObjectName("VerticalSeparator")
        waveform_action_controls.addWidget(waveform_action_separator)
        waveform_action_controls.addWidget(self.audio_cleanup_cut_button)
        waveform_action_controls.addWidget(self.audio_cleanup_silence_button)
        waveform_action_controls.addWidget(self.audio_cleanup_fade_button)
        self.audio_cleanup_waveform_status = QLabel("No audio selected.")
        self.audio_cleanup_waveform_status.setObjectName("Muted")
        self.audio_cleanup_selection_note.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        waveform_status_row = QHBoxLayout()
        waveform_status_row.setContentsMargins(0, 0, 0, 0)
        waveform_status_row.setSpacing(8)
        waveform_status_row.addWidget(self.audio_cleanup_waveform_status)
        waveform_status_row.addStretch(1)
        waveform_status_row.addWidget(self.audio_cleanup_selection_note)
        waveform_card.content_layout.addWidget(self.audio_cleanup_waveform)
        waveform_card.content_layout.addLayout(waveform_controls)
        waveform_card.content_layout.addLayout(waveform_action_controls)
        waveform_card.content_layout.addLayout(waveform_status_row)
        layout.addWidget(waveform_card)

        self.audio_cleanup_tts_blocks_card = Card("TTS blocks")
        self.audio_cleanup_tts_blocks_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.audio_cleanup_tts_blocks_list = QListWidget()
        self.audio_cleanup_tts_blocks_list.setMinimumHeight(160)
        self.audio_cleanup_tts_blocks_list.currentItemChanged.connect(
            lambda _current, _previous: self.audio_cleanup_tts_block_changed()
        )
        self.audio_cleanup_tts_block_preview = QPlainTextEdit()
        self.audio_cleanup_tts_block_preview.setObjectName("LogBox")
        self.audio_cleanup_tts_block_preview.setReadOnly(True)
        self.audio_cleanup_tts_block_preview.setMinimumHeight(160)
        self.audio_cleanup_tts_block_preview.setPlaceholderText("Select a TTS block to preview its text.")
        self.audio_cleanup_tts_block_status = QLabel("No TTS block JSON found.")
        self.audio_cleanup_tts_block_status.setObjectName("Muted")
        self.audio_cleanup_tts_block_status.setWordWrap(True)
        tts_blocks_layout = QHBoxLayout()
        tts_blocks_layout.setContentsMargins(0, 0, 0, 0)
        tts_blocks_layout.setSpacing(12)
        tts_blocks_layout.addWidget(self.audio_cleanup_tts_blocks_list, 1)
        tts_blocks_layout.addWidget(self.audio_cleanup_tts_block_preview, 2)
        self.audio_cleanup_tts_blocks_card.content_layout.addLayout(tts_blocks_layout)
        self.audio_cleanup_tts_blocks_card.content_layout.addWidget(self.audio_cleanup_tts_block_status)
        self.audio_cleanup_tts_blocks_card.hide()
        layout.addWidget(self.audio_cleanup_tts_blocks_card)

        action_card = Card()
        action_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        self.audio_cleanup_start_button = QPushButton("Clean audio")
        self.audio_cleanup_start_button.setObjectName("PrimaryButton")
        self.audio_cleanup_cancel_button = QPushButton("Cancel")
        self.audio_cleanup_play_output_button = QPushButton("Play output")
        self.audio_cleanup_open_output_button = QPushButton("Open output")
        self.audio_cleanup_open_folder_button = QPushButton("Open folder")
        self.audio_cleanup_details_button = QPushButton("Show details")
        self.audio_cleanup_start_button.clicked.connect(self.start_audio_cleanup_job)
        self.audio_cleanup_cancel_button.clicked.connect(self.cancel_audio_cleanup_job)
        self.audio_cleanup_play_output_button.clicked.connect(self.play_audio_cleanup_output)
        self.audio_cleanup_open_output_button.clicked.connect(self.open_audio_cleanup_output)
        self.audio_cleanup_open_folder_button.clicked.connect(self.open_audio_cleanup_output_folder)
        self.audio_cleanup_details_button.clicked.connect(self.toggle_audio_cleanup_details)
        actions.addWidget(self.audio_cleanup_start_button)
        actions.addWidget(self.audio_cleanup_cancel_button)
        actions.addStretch(1)
        actions.addWidget(self.audio_cleanup_play_output_button)
        actions.addWidget(self.audio_cleanup_open_output_button)
        actions.addWidget(self.audio_cleanup_open_folder_button)
        actions.addWidget(self.audio_cleanup_details_button)
        action_card.content_layout.addLayout(actions)
        self.audio_cleanup_progress = QProgressBar()
        self.audio_cleanup_progress.setRange(0, 0)
        self.audio_cleanup_progress.hide()
        self.audio_cleanup_status = QLabel("Ready.")
        self.audio_cleanup_status.setObjectName("StatusText")
        self.audio_cleanup_log = QPlainTextEdit()
        self.audio_cleanup_log.setObjectName("LogBox")
        self.audio_cleanup_log.setReadOnly(True)
        self.audio_cleanup_log.setMinimumHeight(160)
        self.audio_cleanup_log.hide()
        action_card.content_layout.addWidget(self.audio_cleanup_progress)
        action_card.content_layout.addWidget(self.audio_cleanup_status)
        action_card.content_layout.addWidget(self.audio_cleanup_log)
        layout.addWidget(action_card)
        layout.addStretch(1)

        self.audio_cleanup_audio_output = QAudioOutput(self)
        self.refresh_audio_cleanup_playback_device()
        self.audio_cleanup_media_devices = QMediaDevices(self)
        self.audio_cleanup_media_devices.audioOutputsChanged.connect(self.refresh_audio_cleanup_playback_device)
        self.audio_cleanup_media_player = QMediaPlayer(self)
        self.audio_cleanup_media_player.setAudioOutput(self.audio_cleanup_audio_output)
        self.audio_cleanup_preview_end_ms = None
        self.audio_cleanup_preview_pending_start_ms = None
        self.audio_cleanup_preview_pending_timer_ms = None
        self.audio_cleanup_preview_tracks_waveform = False
        self.audio_cleanup_media_player.positionChanged.connect(self.audio_cleanup_playback_position_changed)
        self.audio_cleanup_media_player.mediaStatusChanged.connect(self.audio_cleanup_media_status_changed)
        self.audio_cleanup_media_player.playbackStateChanged.connect(self.audio_cleanup_playback_state_changed)
        self.audio_cleanup_preview_timer = QTimer(self)
        self.audio_cleanup_preview_timer.setSingleShot(True)
        self.audio_cleanup_preview_timer.timeout.connect(self.stop_audio_cleanup_playback)
        self.refresh_audio_cleanup_changes_list()
        self.update_audio_cleanup_button_state()
        return page
