import os
import queue
import re
import subprocess
import tempfile
import threading
from collections.abc import Callable
from contextlib import suppress
from functools import partial
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app_paths import external_base_dir, resource_path, stt_python_path, stt_worker_path
from app_settings import load_app_settings, save_app_settings
from languages import LANGUAGE_NAMES, language_name
from media_tools import (
    STT_VIDEO_SUFFIXES,
    BlackFrame,
    SubtitleStyle,
    auto_burn_quality,
    black_frame_detect_command,
    can_create_video_subtitles,
    find_ffmpeg_exe,
    first_srt_timestamp_seconds,
    isolated_black_frame_numbers,
    parse_blackframe_line,
    probe_video_info,
    suggest_video_cleanup_output_path,
    suggest_video_subtitle_output_path,
    video_cleanup_repair_commands,
    video_frame_preview_command,
    video_subtitle_commands,
    video_subtitle_preview_command,
)
from readers import (
    read_input_file,
)
from stt_preflight import check_stt_preflight
from voicebridge.constants import (
    APP_ATTRIBUTION,
    APP_ICON,
    APP_ICON_PNG,
    APP_NAME,
    BURN_QUALITY_AUTO,
    BURN_QUALITY_BY_LABEL,
    BURN_QUALITY_CRF_VALUES,
    BURN_QUALITY_DESCRIPTIONS,
    BURN_QUALITY_LABELS,
    BURN_QUALITY_ORIGINAL_BITRATE,
    BURN_QUALITY_STANDARD,
    MISSING_ALIGNMENT_PREFIX,
    RATE_CHOICES,
    STT_ALIGNMENT_READY_LANGUAGES,
    STT_LANGUAGE_AUTO_LABEL,
    STT_LANGUAGE_CODES,
    STT_LANGUAGE_LEGACY_LABELS,
    STT_MODE_LABELS,
    STT_MODEL,
    STT_SRT_MODES,
    TTS_SPLIT_LINES,
    TTS_SPLIT_PARAGRAPHS,
    UI_QUEUE_POLL_MS,
    VIDEO_CLEANUP_METHOD_BY_LABEL,
    VIDEO_CLEANUP_METHOD_DESCRIPTIONS,
    VIDEO_CLEANUP_METHOD_FREEZE,
    VIDEO_CLEANUP_METHOD_LABELS,
    VIDEO_CLEANUP_METHOD_REMOVE,
    VIDEO_CLEANUP_QUALITY_BY_LABEL,
    VIDEO_CLEANUP_QUALITY_DESCRIPTIONS,
    VIDEO_CLEANUP_QUALITY_LABELS,
    VIDEO_SUBTITLE_BURN_LABEL,
    VIDEO_SUBTITLE_EMBED_LABEL,
    VIDEO_SUBTITLE_MODE_BY_LABEL,
    VIDEO_SUBTITLE_MODE_DESCRIPTIONS,
    VIDEO_SUBTITLE_POSITION_LABELS,
)
from voicebridge.models import JobHistoryEntry, TtsSegment
from voicebridge.pages.builders import PageBuilderMixin
from voicebridge.pages.tts import TtsWorkflowMixin
from voicebridge.ui.helpers import (
    normalize_video_subtitle_output_path,
    open_path,
    validate_video_subtitle_inputs,
)
from voicebridge.ui.styles import apply_app_style
from voicebridge.ui.widgets import FilePicker
from voices import (
    load_preferred_voice_short_names,
)


class VoiceBridgeQt(TtsWorkflowMixin, PageBuilderMixin, QMainWindow):
    stack: QStackedWidget
    nav_home: QPushButton
    nav_tts: QPushButton
    nav_stt: QPushButton
    nav_video: QPushButton
    nav_cleanup: QPushButton
    status_tiles: dict[str, QLabel]
    job_history_list: QListWidget
    job_open_output_button: QPushButton
    job_open_folder_button: QPushButton
    job_clear_button: QPushButton

    tts_input_picker: FilePicker
    tts_output_picker: FilePicker
    warning_box: QFrame
    warning_title: QLabel
    warning_message: QLabel
    warning_action: QPushButton
    warning_callback: Callable[[], None]
    all_voices: list[dict[str, Any]]
    current_voice_candidates: list[dict[str, Any]]
    current_voice_map: dict[str, str]
    preferred_voice_short_names: set[str]
    voice_status: QLabel
    voice_combo: QComboBox
    voice_search: QLineEdit
    voice_preferred: QCheckBox
    rate_combo: QComboBox
    tts_generate_button: QPushButton
    tts_cancel_button: QPushButton
    tts_open_output_button: QPushButton
    tts_open_folder_button: QPushButton
    tts_progress: QProgressBar
    tts_status: QLabel
    tts_mode_stack: QStackedWidget
    tts_single_mode_button: QPushButton
    tts_multi_mode_button: QPushButton
    tts_mode_note: QLabel
    single_tts_page: QWidget
    multi_tts_tab: QWidget
    tts_split_combo: QComboBox
    tts_blocks_list: QListWidget
    block_voice_combo: QComboBox
    block_rate_combo: QComboBox
    tts_block_preview: QPlainTextEdit

    stt_media_picker: FilePicker
    stt_text_picker: FilePicker
    stt_output_picker: FilePicker
    stt_mode_combo: QComboBox
    stt_language_combo: QComboBox
    stt_preflight_box: QFrame
    stt_preflight_label: QLabel
    stt_generate_button: QPushButton
    stt_cancel_button: QPushButton
    stt_open_output_button: QPushButton
    stt_open_folder_button: QPushButton
    stt_video_button: QPushButton
    stt_details_button: QPushButton
    stt_progress: QProgressBar
    stt_status: QLabel
    stt_log: QPlainTextEdit

    video_media_picker: FilePicker
    video_srt_picker: FilePicker
    video_output_picker: FilePicker
    video_embed_mode_button: QPushButton
    video_burn_mode_button: QPushButton
    video_mode_note: QLabel
    video_quality_label: QLabel
    video_quality_combo: QComboBox
    video_crf_note: QLabel
    video_quality_description: QLabel
    video_style_panel: QWidget
    video_font_size_spin: QSpinBox
    video_outline_spin: QSpinBox
    video_margin_spin: QSpinBox
    video_position_combo: QComboBox
    video_start_button: QPushButton
    video_preview_button: QPushButton
    video_cancel_button: QPushButton
    video_open_output_button: QPushButton
    video_open_folder_button: QPushButton
    video_details_button: QPushButton
    video_progress: QProgressBar
    video_status: QLabel
    video_log: QPlainTextEdit

    cleanup_media_picker: FilePicker
    cleanup_output_picker: FilePicker
    cleanup_rule_note: QLabel
    cleanup_repair_options: QWidget
    cleanup_method_label: QLabel
    cleanup_method_combo: QComboBox
    cleanup_method_description: QLabel
    cleanup_quality_label: QLabel
    cleanup_quality_combo: QComboBox
    cleanup_quality_description: QLabel
    cleanup_results: QListWidget
    cleanup_start_button: QPushButton
    cleanup_repair_button: QPushButton
    cleanup_cancel_button: QPushButton
    cleanup_open_output_button: QPushButton
    cleanup_open_folder_button: QPushButton
    cleanup_details_button: QPushButton
    cleanup_progress: QProgressBar
    cleanup_status: QLabel
    cleanup_log: QPlainTextEdit
    tts_segments: list[TtsSegment]
    selected_tts_segment_index: int | None
    app_settings: dict[str, Any]
    is_restoring_settings: bool
    saved_tts_voice_short_name: str
    job_history: list[JobHistoryEntry]
    cleanup_detected_frames: list[BlackFrame]
    cleanup_repairable_frame_map: dict[int, BlackFrame]
    cleanup_frame_checkboxes: dict[int, QCheckBox]

    def setting_section(self, key: str) -> dict[str, Any]:
        value = self.app_settings.get(key, {})
        return value if isinstance(value, dict) else {}

    @staticmethod
    def setting_str(value: Any, default: str = "") -> str:
        return value if isinstance(value, str) else default

    @staticmethod
    def safe_int(value: Any, default: int, minimum: int, maximum: int) -> int:
        if not isinstance(value, int):
            return default
        return min(max(value, minimum), maximum)

    @staticmethod
    def validated_job_history(value: Any) -> list[JobHistoryEntry]:
        if not isinstance(value, list):
            return []
        jobs: list[JobHistoryEntry] = []
        for item in value[:30]:
            if not isinstance(item, dict):
                continue
            output_path = item.get("output_path", "")
            if not isinstance(output_path, str) or not output_path:
                continue
            jobs.append(
                {
                    "timestamp": item.get("timestamp", "") if isinstance(item.get("timestamp"), str) else "",
                    "kind": item.get("kind", "") if isinstance(item.get("kind"), str) else "",
                    "title": item.get("title", "") if isinstance(item.get("title"), str) else "",
                    "detail": item.get("detail", "") if isinstance(item.get("detail"), str) else "",
                    "input_path": item.get("input_path", "") if isinstance(item.get("input_path"), str) else "",
                    "output_path": output_path,
                }
            )
        return jobs

    @staticmethod
    def validated_language_codes(value: Any) -> set[str]:
        if not isinstance(value, list):
            return set()
        return {
            item.lower()
            for item in value
            if isinstance(item, str) and item.lower() in LANGUAGE_NAMES
        }

    def __init__(self):
        super().__init__()
        self.app_settings = load_app_settings()
        self.is_restoring_settings = True
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(1100, 680)
        window_settings = self.setting_section("window")
        window_width = self.safe_int(window_settings.get("width"), 1240, 1100, 2200)
        window_height = self.safe_int(window_settings.get("height"), 760, 680, 1400)
        self.resize(window_width, window_height)
        icon_path = resource_path(APP_ICON)
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.ui_queue = queue.Queue()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.process_ui_queue)
        self.timer.start(UI_QUEUE_POLL_MS)

        self.all_voices: list[dict[str, Any]] = []
        self.current_voice_candidates: list[dict[str, Any]] = []
        self.current_voice_map: dict[str, str] = {}
        self.voice_load_error_message = ""
        self.preferred_voice_short_names: set[str] = load_preferred_voice_short_names()
        self.saved_tts_voice_short_name = self.setting_str(self.setting_section("tts").get("voice_short_name"))
        self.last_valid_voice_label = ""
        self.cached_input_signature = None
        self.cached_input_text = ""
        self.input_file_error_message = ""
        self.detected_language_code = None
        self.detected_language_confidence = 0.0
        self.is_loading_voices = True
        self.is_detecting_language = False
        self.is_converting = False
        self.tts_cancel_requested = False
        self.tts_last_output_path = ""
        self.last_auto_save_path = ""
        self.tts_segments: list[TtsSegment] = []
        self.selected_tts_segment_index = None
        self.status_tiles: dict[str, QLabel] = {}
        self.job_history: list[JobHistoryEntry] = self.validated_job_history(
            self.app_settings.get("job_history", [])
        )
        self.downloaded_alignment_languages = self.validated_language_codes(
            self.app_settings.get("downloaded_alignment_languages", [])
        )

        self.is_stt_running = False
        self.stt_cancel_requested = False
        self.stt_process = None
        self.stt_preflight_ok = False
        self.stt_preflight_details = []
        self.stt_last_output_path = ""
        self.stt_last_srt_path = ""
        self.stt_last_media_path = ""
        self.stt_log_lines = []
        self.is_video_running = False
        self.video_cancel_requested = False
        self.video_process = None
        self.video_last_output_path = ""
        self.video_last_media_path = ""
        self.video_last_srt_path = ""
        self.video_last_auto_output_path = ""
        self.video_log_lines = []
        self.is_cleanup_running = False
        self.cleanup_cancel_requested = False
        self.cleanup_process = None
        self.cleanup_last_output_path = ""
        self.cleanup_last_auto_output_path = ""
        self.cleanup_detected_frames: list[BlackFrame] = []
        self.cleanup_detected_media_path = ""
        self.cleanup_repairable_frame_map: dict[int, BlackFrame] = {}
        self.cleanup_frame_checkboxes: dict[int, QCheckBox] = {}
        self.cleanup_log_lines = []
        self._stt_preflight_refreshing = False
        self.warning_callback: Callable[[], None] = self.no_warning_action

        self.apply_style()
        self.build_ui()
        self.start_voice_loading()
        self.refresh_stt_preflight_async()

    def apply_style(self):
        check_icon = resource_path(Path("images") / "checkbox_check.svg").as_posix()
        chevron_icon = resource_path(Path("images") / "chevron_down.svg").as_posix()
        apply_app_style(self, check_icon, chevron_icon)

    def build_ui(self):
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.setCentralWidget(root)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(230)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(18, 22, 18, 18)
        side_layout.setSpacing(10)

        title = QLabel(APP_NAME)
        title.setObjectName("AppTitle")
        subtitle = QLabel("Voice and subtitle tools")
        subtitle.setObjectName("AppSubtitle")
        side_layout.addWidget(title)
        side_layout.addWidget(subtitle)
        side_layout.addSpacing(18)

        workflow_label = QLabel("WORKFLOWS")
        workflow_label.setObjectName("SidebarSection")
        side_layout.addWidget(workflow_label)

        self.nav_home = self.nav_button("Dashboard", lambda: self.show_page(0))
        self.nav_tts = self.nav_button("Text to Speech", lambda: self.show_page(1))
        self.nav_stt = self.nav_button("Transcription", lambda: self.show_page(2))
        self.nav_video = self.nav_button("Subtitles", lambda: self.show_page(3))
        self.nav_cleanup = self.nav_button("Video Cleanup", lambda: self.show_page(4))
        side_layout.addWidget(self.nav_home)
        side_layout.addWidget(self.nav_tts)
        side_layout.addWidget(self.nav_stt)
        side_layout.addWidget(self.nav_video)
        side_layout.addWidget(self.nav_cleanup)
        side_layout.addStretch(1)

        status_label = QLabel("STATUS")
        status_label.setObjectName("SidebarSection")
        side_layout.addWidget(status_label)

        status_panel = QWidget()
        status_panel.setObjectName("SidebarStatus")
        status_layout = QGridLayout(status_panel)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(6)
        self.status_tiles = {}
        for index, key in enumerate(("TTS", "STT", "FFMPEG", "DOC", "OCR", "CPU")):
            tile = QLabel(key)
            tile.setObjectName("StatusTile")
            tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tile.setCursor(Qt.CursorShape.PointingHandCursor)
            tile.setProperty("state", "info")
            self.status_tiles[key] = tile
            status_layout.addWidget(tile, index // 2, index % 2)
        side_layout.addWidget(status_panel)

        footer = QLabel(APP_ATTRIBUTION)
        footer.setObjectName("AppSubtitle")
        side_layout.addWidget(footer)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.build_home_page())
        self.stack.addWidget(self.build_tts_page())
        self.stack.addWidget(self.build_stt_page())
        self.stack.addWidget(self.build_video_subtitle_page())
        self.stack.addWidget(self.build_video_cleanup_page())
        root_layout.addWidget(sidebar)
        root_layout.addWidget(self.stack, 1)
        self.restore_user_settings()
        self.show_page(0)
        self.refresh_home_diagnostics()

    @staticmethod
    def set_combo_text(combo: QComboBox, value: Any, allowed_values: list[str] | None = None) -> None:
        if not isinstance(value, str) or not value:
            return
        if allowed_values is not None and value not in allowed_values:
            return
        combo.setCurrentText(value)

    @staticmethod
    def stt_language_code_from_settings(stt_settings: dict[str, Any]) -> str | None:
        stored_code = stt_settings.get("language_code")
        if isinstance(stored_code, str) and stored_code in STT_LANGUAGE_CODES:
            return stored_code

        stored_label = stt_settings.get("language_label")
        if not isinstance(stored_label, str):
            return None
        return STT_LANGUAGE_LEGACY_LABELS.get(stored_label)

    def restore_stt_language_selection(self, stt_settings: dict[str, Any]) -> None:
        language_code = self.stt_language_code_from_settings(stt_settings)
        if language_code:
            self.set_stt_language_code(language_code)

    @staticmethod
    def set_picker_text(picker: FilePicker, value: Any) -> None:
        if isinstance(value, str):
            picker.set_text(value)

    def restore_user_settings(self) -> None:
        self.is_restoring_settings = True
        try:
            tts_settings = self.setting_section("tts")
            self.set_picker_text(self.tts_input_picker, tts_settings.get("input_path"))
            self.set_picker_text(self.tts_output_picker, tts_settings.get("output_path"))
            self.set_combo_text(self.rate_combo, tts_settings.get("rate"), RATE_CHOICES)
            self.set_combo_text(
                self.tts_split_combo,
                tts_settings.get("split_mode"),
                [TTS_SPLIT_PARAGRAPHS, TTS_SPLIT_LINES],
            )
            tab_index = self.safe_int(tts_settings.get("tab_index"), 0, 0, 1)
            self.set_tts_mode(tab_index)

            stt_settings = self.setting_section("stt")
            self.set_picker_text(self.stt_media_picker, stt_settings.get("media_path"))
            self.set_picker_text(self.stt_text_picker, stt_settings.get("text_path"))
            self.set_picker_text(self.stt_output_picker, stt_settings.get("output_path"))
            self.set_combo_text(self.stt_mode_combo, stt_settings.get("mode_label"), list(STT_MODE_LABELS))
            self.restore_stt_language_selection(stt_settings)

            video_settings = self.setting_section("video_subtitles")
            self.set_picker_text(self.video_media_picker, video_settings.get("media_path"))
            self.set_picker_text(self.video_srt_picker, video_settings.get("srt_path"))
            self.set_picker_text(self.video_output_picker, video_settings.get("output_path"))
            self.set_video_subtitle_mode(video_settings.get("mode_label"))
            self.set_combo_text(self.video_quality_combo, video_settings.get("quality_label"), BURN_QUALITY_LABELS)
            self.set_combo_text(
                self.video_position_combo,
                video_settings.get("position_label"),
                list(VIDEO_SUBTITLE_POSITION_LABELS),
            )
            self.video_font_size_spin.setValue(self.safe_int(video_settings.get("font_size"), 28, 14, 72))
            self.video_outline_spin.setValue(self.safe_int(video_settings.get("outline"), 2, 0, 8))
            self.video_margin_spin.setValue(self.safe_int(video_settings.get("margin_v"), 36, 0, 160))

            cleanup_settings = self.setting_section("video_cleanup")
            self.set_picker_text(self.cleanup_media_picker, cleanup_settings.get("media_path"))
            self.set_picker_text(self.cleanup_output_picker, cleanup_settings.get("output_path"))
            self.set_combo_text(
                self.cleanup_quality_combo,
                cleanup_settings.get("quality_label"),
                VIDEO_CLEANUP_QUALITY_LABELS,
            )
            self.set_combo_text(
                self.cleanup_method_combo,
                cleanup_settings.get("method_label"),
                VIDEO_CLEANUP_METHOD_LABELS,
            )
        finally:
            self.is_restoring_settings = False

        self.set_tts_mode(self.tts_mode_index())
        self.stt_mode_changed()
        self.video_subtitle_mode_changed()
        self.update_video_quality_description(self.video_quality_combo.currentText())
        self.cleanup_media_changed()
        self.update_cleanup_method_description(self.cleanup_method_combo.currentText())
        self.update_cleanup_quality_description(self.cleanup_quality_combo.currentText())
        self.refresh_job_history()

    def save_user_settings(self) -> None:
        if getattr(self, "is_restoring_settings", False):
            return

        settings = dict(self.app_settings)
        settings["preferred_voice_short_names"] = sorted(self.preferred_voice_short_names)
        settings["job_history"] = list(self.job_history[:30])
        settings["downloaded_alignment_languages"] = sorted(self.downloaded_alignment_languages)
        settings["window"] = {
            "width": self.safe_int(self.width(), 1240, 1100, 2200),
            "height": self.safe_int(self.height(), 760, 680, 1400),
        }

        if hasattr(self, "rate_combo"):
            selected_voice = self.current_voice_map.get(self.voice_combo.currentText(), self.saved_tts_voice_short_name)
            if selected_voice:
                self.saved_tts_voice_short_name = selected_voice
            settings["tts"] = {
                "input_path": self.tts_input_picker.text(),
                "output_path": self.tts_output_picker.text(),
                "voice_short_name": self.saved_tts_voice_short_name,
                "rate": self.rate_combo.currentText(),
                "tab_index": self.tts_mode_index(),
                "split_mode": self.tts_split_combo.currentText(),
            }

        if hasattr(self, "stt_mode_combo"):
            settings["stt"] = {
                "media_path": self.stt_media_picker.text(),
                "text_path": self.stt_text_picker.text(),
                "output_path": self.stt_output_picker.text(),
                "mode_label": self.stt_mode_combo.currentText(),
                "language_label": self.stt_language_combo.currentText(),
                "language_code": self.stt_language_key(),
            }

        if hasattr(self, "video_embed_mode_button"):
            settings["video_subtitles"] = {
                "media_path": self.video_media_picker.text(),
                "srt_path": self.video_srt_picker.text(),
                "output_path": self.video_output_picker.text(),
                "mode_label": self.video_subtitle_mode_label(),
                "quality_label": self.video_quality_combo.currentText(),
                "font_size": self.video_font_size_spin.value(),
                "outline": self.video_outline_spin.value(),
                "margin_v": self.video_margin_spin.value(),
                "position_label": self.video_position_combo.currentText(),
            }

        if hasattr(self, "cleanup_quality_combo"):
            settings["video_cleanup"] = {
                "media_path": self.cleanup_media_picker.text(),
                "output_path": self.cleanup_output_picker.text(),
                "quality_label": self.cleanup_quality_combo.currentText(),
                "method_label": self.cleanup_method_combo.currentText(),
            }

        self.app_settings = settings
        save_app_settings(settings)

    def closeEvent(self, event):
        self.save_user_settings()
        super().closeEvent(event)

    def post(self, callback, *args):
        self.ui_queue.put((callback, args))

    def process_ui_queue(self):
        try:
            while True:
                callback, args = self.ui_queue.get_nowait()
                callback(*args)
        except queue.Empty:
            pass

    def show_error(self, title, message):
        QMessageBox.critical(self, title, message)

    def show_info(self, title, message):
        QMessageBox.information(self, title, message)

    def stt_alignment_language_ready(self, language_code):
        return (
            language_code == "auto"
            or language_code in STT_ALIGNMENT_READY_LANGUAGES
            or language_code in self.downloaded_alignment_languages
        )

    def stt_language_label(self, language_code):
        if language_code == "auto":
            return STT_LANGUAGE_AUTO_LABEL
        suffix = "offline ready" if self.stt_alignment_language_ready(language_code) else "download for SRT"
        return f"{LANGUAGE_NAMES[language_code]} ({suffix})"

    def set_stt_language_code(self, language_code):
        for index in range(self.stt_language_combo.count()):
            if self.stt_language_combo.itemData(index, Qt.ItemDataRole.UserRole) == language_code:
                self.stt_language_combo.setCurrentIndex(index)
                return

    def populate_stt_language_combo(self):
        selected_code = self.stt_language_key() if self.stt_language_combo.count() else "auto"
        self.stt_language_combo.clear()
        for code in STT_LANGUAGE_CODES:
            label = self.stt_language_label(code)
            self.stt_language_combo.addItem(label)
            index = self.stt_language_combo.count() - 1
            self.stt_language_combo.setItemData(index, code, Qt.ItemDataRole.UserRole)
            if code == "auto":
                tooltip = "Detects the spoken language automatically."
            elif code in STT_ALIGNMENT_READY_LANGUAGES:
                tooltip = "Included in the offline package for SRT alignment."
            elif code in self.downloaded_alignment_languages:
                tooltip = "Downloaded on this computer and available offline for SRT alignment."
            else:
                tooltip = "Markdown transcripts work offline; SRT alignment downloads this language on request."
            self.stt_language_combo.setItemData(index, tooltip, Qt.ItemDataRole.ToolTipRole)
        self.set_stt_language_code(selected_code if selected_code in STT_LANGUAGE_CODES else "auto")

    @staticmethod
    def show_indeterminate_progress(progress_bar):
        progress_bar.setTextVisible(False)
        progress_bar.setRange(0, 0)
        progress_bar.show()

    @staticmethod
    def show_percent_progress(progress_bar, percent):
        percent = max(0, min(100, int(round(percent))))
        progress_bar.setTextVisible(True)
        progress_bar.setRange(0, 100)
        progress_bar.setFormat("%p%")
        progress_bar.setValue(percent)
        progress_bar.show()

    def update_tts_progress_percent(self, percent):
        self.show_percent_progress(self.tts_progress, percent)

    def update_stt_progress_percent(self, percent):
        self.show_percent_progress(self.stt_progress, percent)

    def update_video_progress_percent(self, percent):
        self.show_percent_progress(self.video_progress, percent)

    def update_cleanup_progress_percent(self, percent):
        self.show_percent_progress(self.cleanup_progress, percent)

    def set_video_progress_indeterminate(self):
        self.show_indeterminate_progress(self.video_progress)

    def set_cleanup_progress_indeterminate(self):
        self.show_indeterminate_progress(self.cleanup_progress)

    def stt_mode_key(self):
        return STT_MODE_LABELS.get(self.stt_mode_combo.currentText(), "transcript")

    def stt_language_key(self):
        language_code = self.stt_language_combo.currentData(Qt.ItemDataRole.UserRole)
        return language_code if isinstance(language_code, str) else "auto"

    def stt_mode_changed(self):
        align = self.stt_mode_key() == "align_text"
        self.stt_text_picker.setVisible(align)
        self.update_stt_output_for_mode_or_media()
        self.update_stt_button_state()
        self.save_user_settings()

    def stt_output_suffix(self):
        return ".md" if self.stt_mode_key() == "transcript" else ".srt"

    def update_stt_output_for_mode_or_media(self):
        media_path = self.stt_media_picker.text()
        current = self.stt_output_picker.text()
        suffix = self.stt_output_suffix()
        if media_path:
            suggested = str(Path(media_path).with_suffix(suffix))
            if not current or Path(current).suffix.lower() in {".md", ".srt"}:
                self.stt_output_picker.set_text(suggested)
        elif current and Path(current).suffix.lower() in {".md", ".srt"}:
            self.stt_output_picker.set_text(str(Path(current).with_suffix(suffix)))

    def select_stt_media_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select audio or video file",
            self.stt_media_picker.text() or str(Path.home()),
            "Audio/video files (*.mp3 *.wav *.m4a *.aac *.flac *.ogg *.mp4 *.mkv *.mov *.avi *.webm);;All files (*.*)",
        )
        if path:
            self.stt_media_picker.set_text(path)
            self.update_stt_output_for_mode_or_media()
            self.save_user_settings()

    def select_stt_text_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select transcript file",
            self.stt_text_picker.text() or str(Path.home()),
            "Transcript files (*.txt *.md *.docx *.doc);;All files (*.*)",
        )
        if path:
            self.stt_text_picker.set_text(path)
            self.save_user_settings()

    def select_stt_output_file(self):
        suffix = self.stt_output_suffix()
        filter_text = (
            "Markdown files (*.md);;All files (*.*)"
            if suffix == ".md"
            else "SubRip subtitles (*.srt);;All files (*.*)"
        )
        initial = self.stt_output_picker.text() or str(Path.home() / f"output{suffix}")
        path, _ = QFileDialog.getSaveFileName(self, "Save output as", initial, filter_text)
        if path:
            self.stt_output_picker.set_text(str(Path(path).with_suffix(suffix)))
            self.save_user_settings()

    def refresh_stt_preflight_async(self):
        if getattr(self, "_stt_preflight_refreshing", False):
            return
        self._stt_preflight_refreshing = True
        threading.Thread(target=self.refresh_stt_preflight_worker, daemon=True).start()

    def refresh_stt_preflight_worker(self):
        ok, summary, details = check_stt_preflight()
        self.post(self.stt_preflight_finished, ok, summary, details)

    def stt_preflight_finished(self, ok, summary, details):
        self._stt_preflight_refreshing = False
        self.stt_preflight_ok = ok
        self.stt_preflight_details = details
        self.stt_preflight_label.setText(summary)
        self.update_stt_button_state()
        self.refresh_home_diagnostics()

    def update_stt_button_state(self):
        if not hasattr(self, "stt_generate_button"):
            return
        busy_elsewhere = self.is_converting or self.is_video_running or self.is_cleanup_running
        self.stt_generate_button.setEnabled(not self.is_stt_running and not busy_elsewhere and self.stt_preflight_ok)
        self.stt_cancel_button.setEnabled(self.is_stt_running)
        output_ready = bool(self.stt_last_output_path and Path(self.stt_last_output_path).is_file())
        self.stt_open_output_button.setEnabled(output_ready)
        self.stt_open_folder_button.setEnabled(output_ready)
        self.stt_video_button.setEnabled(
            not self.is_stt_running and not self.is_video_running and not self.is_converting
        )
        self.update_navigation_state()

    def append_stt_log(self, line):
        self.stt_log_lines.append(line)
        self.stt_log_lines = self.stt_log_lines[-300:]
        self.stt_log.appendPlainText(line)
        scrollbar = self.stt_log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def reset_stt_log(self):
        self.stt_log_lines = []
        self.stt_log.clear()

    def toggle_stt_details(self):
        if self.stt_log.isVisible():
            self.stt_log.hide()
            self.stt_details_button.setText("Show details")
            return
        if not self.stt_log_lines and self.stt_preflight_details:
            for line in self.stt_preflight_details:
                self.append_stt_log(line)
        self.stt_log.show()
        self.stt_details_button.setText("Hide details")

    @staticmethod
    def prepare_stt_transcript_file(text_path):
        source_path = Path(text_path)
        if source_path.suffix.lower() in {".txt", ".md"}:
            return str(source_path), None
        temp_path = None
        success = False
        try:
            transcript_text = read_input_file(str(source_path))
            if not transcript_text.strip():
                raise ValueError("The selected transcript file contains no readable text.")
            fd, temp_path = tempfile.mkstemp(prefix="voicebridge-transcript-", suffix=".txt", text=True)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as temp_file:
                temp_file.write(transcript_text)
                temp_file.write("\n")
            success = True
            return temp_path, temp_path
        finally:
            if temp_path and not success:
                with suppress(OSError):
                    Path(temp_path).unlink(missing_ok=True)

    def collect_stt_options(self):
        media_path = self.stt_media_picker.text()
        output_path = self.stt_output_picker.text()
        text_path = self.stt_text_picker.text()
        mode = self.stt_mode_key()
        language = self.stt_language_key()
        device = "cpu"
        if not media_path:
            raise ValueError("Please select an audio or video file.")
        if not os.path.isfile(media_path):
            raise ValueError("The selected media file does not exist.")
        if not output_path:
            raise ValueError("Please choose where to save the output file.")
        if mode == "align_text" and (not text_path or not os.path.isfile(text_path)):
            raise ValueError("Please select the transcript text file to align.")
        output_path = str(Path(output_path).with_suffix(self.stt_output_suffix()))
        self.stt_output_picker.set_text(output_path)
        self.save_user_settings()
        return media_path, output_path, text_path, mode, STT_MODEL, language, device

    def start_stt_job(self):
        try:
            media_path, output_path, text_path, mode, model, language, device = self.collect_stt_options()
        except ValueError as exc:
            self.stt_status.setText("Error.")
            self.show_error("Error", str(exc))
            return
        if not self.stt_preflight_ok:
            self.stt_status.setText("STT offline package incomplete.")
            self.reset_stt_log()
            for line in self.stt_preflight_details:
                self.append_stt_log(line)
            if not self.stt_log.isVisible():
                self.toggle_stt_details()
            self.show_error("STT offline package incomplete", self.stt_preflight_label.text())
            return
        if mode in STT_SRT_MODES and language != "auto" and not self.stt_alignment_language_ready(language):
            self.handle_stt_alignment_model_missing(language, "selected")
            return
        python_path = stt_python_path()
        worker_path = stt_worker_path()
        if not python_path.is_file():
            self.show_error("STT environment missing", f"Could not find the STT Python runtime:\n{python_path}")
            return
        if not worker_path.is_file():
            self.show_error("STT worker missing", f"Could not find:\n{worker_path}")
            return
        worker_text_path = text_path
        cleanup_text_path = None
        if mode == "align_text":
            try:
                worker_text_path, cleanup_text_path = self.prepare_stt_transcript_file(text_path)
            except (OSError, RuntimeError, ValueError) as exc:
                self.stt_status.setText("Error.")
                self.show_error("Transcript file error", f"Could not read transcript file.\n\n{exc}")
                return
        self.stt_cancel_requested = False
        self.stt_process = None
        self.stt_last_output_path = ""
        self.reset_stt_log()
        self.is_stt_running = True
        self.show_percent_progress(self.stt_progress, 0)
        self.stt_status.setText("Starting offline transcription...")
        self.append_stt_log(f"Starting mode={mode}, language={language}, device={device}, model={model}")
        if cleanup_text_path:
            self.append_stt_log(f"Prepared transcript text from: {text_path}")
        self.update_stt_button_state()
        self.update_tts_button_state()
        self.update_video_subtitle_button_state()
        self.update_video_cleanup_button_state()
        threading.Thread(
            target=self.stt_worker_thread,
            args=(
                python_path,
                worker_path,
                media_path,
                output_path,
                worker_text_path,
                cleanup_text_path,
                mode,
                model,
                language,
                device,
            ),
            daemon=True,
        ).start()

    def stt_worker_thread(
        self,
        python_path,
        worker_path,
        media_path,
        output_path,
        text_path,
        cleanup_text_path,
        mode,
        model,
        language,
        device,
    ):
        command = [
            str(python_path),
            str(worker_path),
            "--media",
            media_path,
            "--output",
            output_path,
            "--mode",
            mode,
            "--model",
            model,
            "--language",
            language,
            "--device",
            device,
            "--offline",
        ]
        if mode == "align_text":
            command.extend(["--text", text_path])
        recent_output = []
        missing_alignment_language = None
        prompt_alignment_language = None
        try:
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            process = subprocess.Popen(
                command,
                cwd=str(external_base_dir()),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
            )
            self.stt_process = process
            assert process.stdout is not None
            for raw_line in process.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                if line.startswith(MISSING_ALIGNMENT_PREFIX):
                    missing_alignment_language = line.removeprefix(MISSING_ALIGNMENT_PREFIX).strip()
                    self.post(
                        self.append_stt_log,
                        f"Alignment model missing for language: {missing_alignment_language}",
                    )
                    continue
                if line.startswith("PROGRESS: "):
                    try:
                        progress_percent = float(line.removeprefix("PROGRESS: ").strip())
                    except ValueError:
                        continue
                    self.post(self.update_stt_progress_percent, progress_percent)
                    continue
                recent_output.append(line)
                recent_output = recent_output[-12:]
                self.post(self.append_stt_log, line)
                if line.startswith("STATUS: "):
                    self.post(self.stt_status.setText, line.removeprefix("STATUS: "))
                if self.stt_cancel_requested and process.poll() is None:
                    process.terminate()
            return_code = process.wait()
            if self.stt_cancel_requested:
                self.post(self.stt_job_cancelled)
                return
            if return_code != 0:
                if mode in STT_SRT_MODES and missing_alignment_language:
                    prompt_alignment_language = missing_alignment_language
                    return
                raise RuntimeError("\n".join(recent_output[-8:]) or f"STT worker exited with code {return_code}.")
            self.post(self.stt_job_succeeded, output_path, media_path)
        except (OSError, RuntimeError, AssertionError) as exc:
            self.post(self.stt_job_failed, str(exc))
        finally:
            if cleanup_text_path:
                try:
                    Path(cleanup_text_path).unlink(missing_ok=True)
                except OSError as exc:
                    self.post(self.append_stt_log, f"Could not remove temporary transcript file: {exc}")
            self.stt_process = None
            self.post(self.finish_stt_job)
            if prompt_alignment_language:
                self.post(self.handle_stt_alignment_model_missing, prompt_alignment_language)

    def handle_stt_alignment_model_missing(self, language_code, source="detected"):
        language_code = (language_code or "").strip().lower()
        if not language_code:
            self.stt_status.setText("Alignment model missing.")
            self.show_error("Alignment model missing", "The required alignment model is not included.")
            return

        language_label = f"{language_name(language_code)} ({language_code})"
        self.stt_status.setText("Alignment model required.")
        source_label = "Lingua selezionata" if source == "selected" else "Lingua rilevata"
        answer = QMessageBox.question(
            self,
            "Alignment model missing",
            (
                f"{source_label}: {language_label}.\n\n"
                "Il modello di allineamento non è incluso. Vuoi scaricarlo ora?\n\n"
                "Dopo il download questa lingua funzionerà offline su questo computer."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.start_alignment_model_download(language_code)
        else:
            self.append_stt_log(f"Alignment model download skipped for language: {language_code}")
            self.stt_status.setText("Alignment model required.")

    def start_alignment_model_download(self, language_code):
        python_path = stt_python_path()
        worker_path = stt_worker_path()
        if not python_path.is_file():
            self.show_error("STT environment missing", f"Could not find the STT Python runtime:\n{python_path}")
            return
        if not worker_path.is_file():
            self.show_error("STT worker missing", f"Could not find:\n{worker_path}")
            return

        self.stt_cancel_requested = False
        self.stt_process = None
        self.is_stt_running = True
        self.show_percent_progress(self.stt_progress, 0)
        self.stt_status.setText(f"Downloading alignment model for {language_name(language_code)}...")
        self.append_stt_log(f"Downloading alignment model for language: {language_code}")
        self.update_stt_button_state()
        self.update_tts_button_state()
        self.update_video_subtitle_button_state()
        self.update_video_cleanup_button_state()
        threading.Thread(
            target=self.alignment_model_download_thread,
            args=(python_path, worker_path, language_code),
            daemon=True,
        ).start()

    def alignment_model_download_thread(self, python_path, worker_path, language_code):
        command = [
            str(python_path),
            str(worker_path),
            "--mode",
            "download_align",
            "--language",
            language_code,
            "--device",
            "cpu",
        ]
        recent_output = []
        completion_callback = None
        completion_args = ()
        try:
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            process = subprocess.Popen(
                command,
                cwd=str(external_base_dir()),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
            )
            self.stt_process = process
            assert process.stdout is not None
            for raw_line in process.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                if line.startswith("PROGRESS: "):
                    try:
                        progress_percent = float(line.removeprefix("PROGRESS: ").strip())
                    except ValueError:
                        continue
                    self.post(self.update_stt_progress_percent, progress_percent)
                    continue
                recent_output.append(line)
                recent_output = recent_output[-12:]
                self.post(self.append_stt_log, line)
                if line.startswith("STATUS: "):
                    self.post(self.stt_status.setText, line.removeprefix("STATUS: "))
                if self.stt_cancel_requested and process.poll() is None:
                    process.terminate()
            return_code = process.wait()
            if self.stt_cancel_requested:
                completion_callback = self.stt_job_cancelled
            elif return_code != 0:
                message = "\n".join(recent_output[-8:]) or f"Alignment model download exited with code {return_code}."
                completion_callback = self.stt_job_failed
                completion_args = (message,)
            else:
                completion_callback = self.alignment_model_download_succeeded
                completion_args = (language_code,)
        except (OSError, RuntimeError, AssertionError) as exc:
            completion_callback = self.stt_job_failed
            completion_args = (str(exc),)
        finally:
            self.stt_process = None
            self.post(self.finish_stt_job)
            if completion_callback:
                self.post(completion_callback, *completion_args)

    def alignment_model_download_succeeded(self, language_code):
        self.downloaded_alignment_languages.add(language_code)
        self.populate_stt_language_combo()
        self.set_stt_language_code(language_code)
        self.save_user_settings()
        self.stt_status.setText("Alignment model downloaded. Restarting SRT job...")
        self.append_stt_log(f"Alignment model ready for language: {language_code}")
        QTimer.singleShot(250, self.start_stt_job)

    def cancel_stt_job(self):
        if not self.is_stt_running:
            return
        self.stt_cancel_requested = True
        self.stt_status.setText("Cancelling...")
        self.append_stt_log("Cancellation requested.")
        process = self.stt_process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError as exc:
                self.append_stt_log(f"Could not terminate process cleanly: {exc}")

    def stt_job_succeeded(self, output_path, media_path=None):
        self.stt_last_output_path = output_path
        if Path(output_path).suffix.lower() == ".srt" and media_path:
            self.stt_last_srt_path = output_path
            self.stt_last_media_path = media_path
            self.sync_video_subtitle_inputs_from_stt()
        self.stt_status.setText("Done.")
        self.append_stt_log(f"Output saved: {output_path}")
        self.record_job("STT", "Transcript/SRT generated", media_path or self.stt_media_picker.text(), output_path)
        self.show_info("Success", f"Output saved:\n{output_path}")

    def stt_job_cancelled(self):
        self.stt_status.setText("Cancelled.")
        self.append_stt_log("Job cancelled.")

    def stt_job_failed(self, message):
        self.stt_status.setText("Error.")
        self.append_stt_log(f"ERROR: {message}")
        self.show_error("STT Error", message)

    def finish_stt_job(self):
        self.is_stt_running = False
        self.stt_progress.hide()
        self.update_stt_button_state()
        self.update_tts_button_state()
        self.update_video_subtitle_button_state()
        self.update_video_cleanup_button_state()

    def open_stt_output(self):
        open_path(self.stt_last_output_path)

    def open_stt_output_folder(self):
        if self.stt_last_output_path and Path(self.stt_last_output_path).is_file():
            open_path(Path(self.stt_last_output_path).parent)

    def video_subtitle_mode_label(self):
        if getattr(self, "video_burn_mode_button", None) and self.video_burn_mode_button.isChecked():
            return VIDEO_SUBTITLE_BURN_LABEL
        return VIDEO_SUBTITLE_EMBED_LABEL

    def video_subtitle_mode_key(self):
        return VIDEO_SUBTITLE_MODE_BY_LABEL.get(self.video_subtitle_mode_label(), "embed")

    def set_video_subtitle_mode(self, mode_or_label):
        if not hasattr(self, "video_embed_mode_button"):
            return
        if mode_or_label in VIDEO_SUBTITLE_MODE_BY_LABEL:
            label = mode_or_label
        else:
            label = VIDEO_SUBTITLE_BURN_LABEL if mode_or_label == "burn" else VIDEO_SUBTITLE_EMBED_LABEL
        burn = label == VIDEO_SUBTITLE_BURN_LABEL
        self.video_embed_mode_button.setChecked(not burn)
        self.video_burn_mode_button.setChecked(burn)
        self.video_subtitle_mode_changed()

    def sync_video_subtitle_inputs_from_stt(self):
        if not hasattr(self, "video_media_picker"):
            return
        if can_create_video_subtitles(self.stt_last_srt_path, self.stt_last_media_path):
            if not self.video_media_picker.text():
                self.video_media_picker.set_text(self.stt_last_media_path)
            if not self.video_srt_picker.text():
                self.video_srt_picker.set_text(self.stt_last_srt_path)
            self.update_video_subtitle_output(force=False)
            self.save_user_settings()

    def video_subtitle_mode_changed(self):
        mode = self.video_subtitle_mode_key()
        burn = mode == "burn"
        self.video_mode_note.setText(
            VIDEO_SUBTITLE_MODE_DESCRIPTIONS[VIDEO_SUBTITLE_BURN_LABEL if burn else VIDEO_SUBTITLE_EMBED_LABEL]
        )
        for widget in (
            self.video_quality_label,
            self.video_quality_combo,
            self.video_crf_note,
            self.video_quality_description,
            self.video_style_panel,
        ):
            widget.setVisible(burn)
        self.video_preview_button.setVisible(burn)
        self.update_video_subtitle_output(force=False)
        self.save_user_settings()

    def update_video_quality_description(self, text):
        self.video_quality_description.setText(BURN_QUALITY_DESCRIPTIONS.get(text, ""))
        self.save_user_settings()

    def collect_video_subtitle_style(self) -> SubtitleStyle:
        return {
            "font_size": self.video_font_size_spin.value(),
            "outline": self.video_outline_spin.value(),
            "margin_v": self.video_margin_spin.value(),
            "alignment": VIDEO_SUBTITLE_POSITION_LABELS.get(self.video_position_combo.currentText(), 2),
        }

    def suggested_video_subtitle_output_path(self):
        media_path = self.video_media_picker.text()
        if not media_path:
            return ""
        try:
            return suggest_video_subtitle_output_path(media_path, self.video_subtitle_mode_key())
        except ValueError:
            return ""

    def update_video_subtitle_output(self, force=False):
        if not hasattr(self, "video_output_picker"):
            return
        current = self.video_output_picker.text()
        suggested = self.suggested_video_subtitle_output_path()
        if not suggested:
            return
        if force or not current or current == self.video_last_auto_output_path:
            self.video_output_picker.set_text(suggested)
            self.video_last_auto_output_path = suggested

    def select_video_subtitle_media_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select video file",
            self.video_media_picker.text() or str(Path.home()),
            "Video files (*.mp4 *.mkv *.mov *.avi *.webm *.m4v);;All files (*.*)",
        )
        if path:
            self.video_media_picker.set_text(path)
            self.video_last_media_path = path
            self.update_video_subtitle_output(force=False)
            self.save_user_settings()

    def select_video_subtitle_srt_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select SRT subtitle file",
            self.video_srt_picker.text() or str(Path.home()),
            "SubRip subtitles (*.srt);;All files (*.*)",
        )
        if path:
            self.video_srt_picker.set_text(path)
            self.video_last_srt_path = path
            self.save_user_settings()

    def select_video_subtitle_output_file(self):
        mode = self.video_subtitle_mode_key()
        suggested = self.video_output_picker.text() or self.suggested_video_subtitle_output_path()
        if not suggested:
            suggested = str(Path.home() / ("subtitled_video.mp4" if mode == "burn" else "subtitled_video.mkv"))
        if mode == "burn":
            filter_text = "MP4 video (*.mp4);;All files (*.*)"
        else:
            filter_text = "MP4 video (*.mp4);;Matroska video (*.mkv);;All files (*.*)"
        path, selected_filter = QFileDialog.getSaveFileName(self, "Save subtitled video as", suggested, filter_text)
        if path:
            default_suffix = ".mkv" if mode == "embed" and "Matroska" in selected_filter else ".mp4"
            self.video_output_picker.set_text(normalize_video_subtitle_output_path(path, mode, default_suffix))
            self.video_last_auto_output_path = ""
            self.save_user_settings()

    def collect_video_subtitle_options(self):
        mode = self.video_subtitle_mode_key()
        media_path = self.video_media_picker.text()
        srt_path = self.video_srt_picker.text()
        output_path = self.video_output_picker.text()
        if media_path and not output_path:
            output_path = self.suggested_video_subtitle_output_path()
            self.video_output_picker.set_text(output_path)
        output_path = normalize_video_subtitle_output_path(
            output_path,
            mode,
            Path(output_path).suffix.lower() if output_path else "",
        )
        validate_video_subtitle_inputs(mode, media_path, srt_path, output_path)
        burn_quality = BURN_QUALITY_BY_LABEL.get(self.video_quality_combo.currentText(), BURN_QUALITY_AUTO)
        subtitle_style = self.collect_video_subtitle_style() if mode == "burn" else None
        self.video_output_picker.set_text(output_path)
        self.save_user_settings()
        return mode, media_path, srt_path, output_path, burn_quality, subtitle_style

    def start_video_subtitle_from_page(self):
        try:
            (
                mode,
                media_path,
                srt_path,
                output_path,
                burn_quality,
                subtitle_style,
            ) = self.collect_video_subtitle_options()
        except ValueError as exc:
            self.video_status.setText("Error.")
            self.show_error("Subtitles", str(exc))
            return
        self.start_video_subtitle_job(mode, media_path, srt_path, output_path, burn_quality, subtitle_style)

    def preview_video_subtitle_style(self) -> None:
        if self.video_subtitle_mode_key() != "burn":
            return
        media_path = self.video_media_picker.text()
        srt_path = self.video_srt_picker.text()
        if not media_path or not Path(media_path).is_file():
            self.show_error("Preview subtitles", "Select an existing video file.")
            return
        if not srt_path or not Path(srt_path).is_file() or Path(srt_path).suffix.lower() != ".srt":
            self.show_error("Preview subtitles", "Select an existing .srt subtitle file.")
            return
        ffmpeg = find_ffmpeg_exe()
        if not ffmpeg:
            self.show_error("ffmpeg missing", "Could not find ffmpeg. Use the full VoiceBridge bundle.")
            return

        timestamp_seconds = first_srt_timestamp_seconds(srt_path)
        subtitle_style = self.collect_video_subtitle_style()
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        with tempfile.TemporaryDirectory(prefix="voicebridge-subtitle-preview-") as temp_dir:
            preview_path = str(Path(temp_dir) / "subtitle-preview.jpg")
            command = video_subtitle_preview_command(
                ffmpeg,
                media_path,
                srt_path,
                preview_path,
                subtitle_style=subtitle_style,
                timestamp_seconds=timestamp_seconds,
            )
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
                timeout=90,
                check=False,
            )
            if result.returncode != 0 or not Path(preview_path).is_file():
                self.show_error(
                    "Preview subtitles",
                    (result.stderr or result.stdout or "Could not generate subtitle preview.").strip(),
                )
                return

            dialog = QDialog(self)
            dialog.setWindowTitle("Subtitle style preview")
            dialog.setMinimumWidth(860)
            layout = QVBoxLayout(dialog)
            header = QLabel(f"Preview at {timestamp_seconds:.2f}s")
            header.setObjectName("CardTitle")
            image = QLabel()
            image.setAlignment(Qt.AlignmentFlag.AlignCenter)
            image.setStyleSheet("background: #0f172a; border-radius: 6px;")
            pixmap = QPixmap(preview_path)
            if not pixmap.isNull():
                image.setPixmap(
                    pixmap.scaled(
                        820,
                        462,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            else:
                image.setText("Preview unavailable")
            close_button = QPushButton("Close")
            close_button.clicked.connect(dialog.accept)
            footer = QHBoxLayout()
            footer.addStretch(1)
            footer.addWidget(close_button)
            layout.addWidget(header)
            layout.addWidget(image)
            layout.addLayout(footer)
            dialog.exec()

    def start_video_subtitle_job(
        self,
        mode,
        media_path,
        srt_path,
        output_path,
        burn_quality=BURN_QUALITY_AUTO,
        subtitle_style: SubtitleStyle | None = None,
    ):
        ffmpeg = find_ffmpeg_exe()
        if not ffmpeg:
            self.video_status.setText("ffmpeg missing.")
            self.show_error("ffmpeg missing", "Could not find ffmpeg. Use the full VoiceBridge bundle.")
            return
        try:
            validate_video_subtitle_inputs(mode, media_path, srt_path, output_path)
        except ValueError as exc:
            self.video_status.setText("Error.")
            self.show_error("Subtitles", str(exc))
            return
        self.video_cancel_requested = False
        self.video_process = None
        self.video_last_output_path = ""
        self.video_last_media_path = media_path
        self.video_last_srt_path = srt_path
        self.is_video_running = True
        self.show_indeterminate_progress(self.video_progress)
        self.video_status.setText(
            "Embedding subtitle track..." if mode == "embed" else "Burning subtitles into video..."
        )
        self.reset_video_log()
        log_line = f"Starting video subtitle mode={mode}, media={media_path}, srt={srt_path}, output={output_path}"
        if mode == "burn":
            log_line = f"{log_line}, quality={burn_quality}, style={subtitle_style}"
        self.append_video_log(log_line)
        self.update_video_subtitle_button_state()
        self.update_stt_button_state()
        self.update_tts_button_state()
        self.update_video_cleanup_button_state()
        threading.Thread(
            target=self.video_subtitle_worker,
            args=(mode, str(ffmpeg), media_path, srt_path, output_path, burn_quality, subtitle_style),
            daemon=True,
        ).start()

    def video_subtitle_worker(self, mode, ffmpeg, media_path, srt_path, output_path, burn_quality, subtitle_style):
        output_path = Path(output_path)
        temp_output_path = None
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(
                prefix=f".{output_path.stem}.voicebridge-",
                suffix=output_path.suffix,
                dir=str(output_path.parent),
            )
            os.close(fd)
            temp_output_path = Path(temp_name)
            temp_output_path.unlink(missing_ok=True)

            self.post(self.append_video_log, "Detecting source video details...")
            source_video_info = probe_video_info(ffmpeg, media_path)
            source_video_bitrate_kbps = source_video_info.get("bitrate_kbps")
            source_video_width = source_video_info.get("width")
            source_video_height = source_video_info.get("height")
            source_video_duration_seconds = source_video_info.get("duration_seconds")
            if source_video_duration_seconds:
                self.post(self.update_video_progress_percent, 0)
            else:
                self.post(self.set_video_progress_indeterminate)
            if mode == "burn" and burn_quality == BURN_QUALITY_AUTO:
                selected_quality = auto_burn_quality(
                    source_video_bitrate_kbps,
                    source_video_width,
                    source_video_height,
                )
                selected_crf = BURN_QUALITY_CRF_VALUES.get(
                    selected_quality,
                    BURN_QUALITY_CRF_VALUES[BURN_QUALITY_STANDARD],
                )
                source_parts = []
                if source_video_width and source_video_height:
                    source_parts.append(f"{source_video_width}x{source_video_height}")
                if source_video_bitrate_kbps:
                    source_parts.append(f"{source_video_bitrate_kbps} kb/s")
                source_note = f" ({', '.join(source_parts)})" if source_parts else ""
                self.post(self.append_video_log, f"Auto burn-in quality selected: CRF {selected_crf}{source_note}")
            if mode == "burn" and burn_quality == BURN_QUALITY_ORIGINAL_BITRATE and not source_video_bitrate_kbps:
                raise RuntimeError("Could not detect the original video bitrate. Choose a CRF option instead.")

            commands = video_subtitle_commands(
                mode,
                ffmpeg,
                media_path,
                srt_path,
                str(temp_output_path),
                burn_quality=burn_quality,
                source_video_bitrate_kbps=source_video_bitrate_kbps,
                source_video_width=source_video_width,
                source_video_height=source_video_height,
                subtitle_style=subtitle_style,
            )
            recent_output = []
            for command in commands:
                return_code, recent_output = self.run_ffmpeg_process(command, source_video_duration_seconds)
                if return_code == 0:
                    if self.video_cancel_requested:
                        self.post(self.video_subtitle_job_cancelled)
                        return
                    os.replace(temp_output_path, output_path)
                    self.post(self.update_video_progress_percent, 100)
                    self.post(self.video_subtitle_job_succeeded, str(output_path), mode)
                    return
                if self.video_cancel_requested:
                    self.post(self.video_subtitle_job_cancelled)
                    return
            raise RuntimeError("\n".join(recent_output[-8:]) or "ffmpeg could not create the subtitled video.")
        except (OSError, RuntimeError, ValueError) as exc:
            self.post(self.video_subtitle_job_failed, str(exc))
        finally:
            if temp_output_path:
                with suppress(OSError):
                    temp_output_path.unlink(missing_ok=True)
            self.video_process = None
            self.post(self.finish_video_subtitle_job)

    @staticmethod
    def parse_ffmpeg_time_seconds(value):
        value = value.strip()
        time_match = re.match(r"(\d+):(\d+):(\d+(?:\.\d+)?)", value)
        if time_match:
            return int(time_match.group(1)) * 3600 + int(time_match.group(2)) * 60 + float(time_match.group(3))
        try:
            return float(value) / 1_000_000
        except ValueError:
            return None

    def ffmpeg_progress_percent(self, line, duration_seconds):
        if not duration_seconds:
            return None
        if line.startswith("out_time=") or line.startswith(("out_time_us=", "out_time_ms=")):
            seconds = self.parse_ffmpeg_time_seconds(line.split("=", 1)[1])
        else:
            return None
        if seconds is None:
            return None
        return min(99, max(0, round((seconds / duration_seconds) * 100)))

    @staticmethod
    def is_ffmpeg_progress_line(line):
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

    def run_ffmpeg_process(self, command, duration_seconds=None):
        recent_output = []
        last_progress_percent = -1
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
        self.video_process = process
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.strip()
            if not line:
                continue
            progress_percent = self.ffmpeg_progress_percent(line, duration_seconds)
            if progress_percent is not None:
                if progress_percent > last_progress_percent:
                    last_progress_percent = progress_percent
                    self.post(self.update_video_progress_percent, progress_percent)
                continue
            if self.is_ffmpeg_progress_line(line):
                continue
            recent_output.append(line)
            recent_output = recent_output[-12:]
            self.post(self.append_video_log, line)
            if self.video_cancel_requested and process.poll() is None:
                process.terminate()
        return process.wait(), recent_output

    def cancel_video_subtitle_job(self):
        if not self.is_video_running:
            return
        self.video_cancel_requested = True
        self.video_status.setText("Cancelling...")
        self.append_video_log("Cancellation requested.")
        self.update_video_subtitle_button_state()
        process = self.video_process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError as exc:
                self.append_video_log(f"Could not terminate process cleanly: {exc}")

    def video_subtitle_job_succeeded(self, output_path, mode):
        self.video_last_output_path = output_path
        self.video_status.setText("Subtitles embedded." if mode == "embed" else "Subtitles burned into video.")
        self.append_video_log(f"Video saved: {output_path}")
        self.record_job(
            "VIDEO",
            "Subtitled video",
            self.video_media_picker.text(),
            output_path,
            "embedded" if mode == "embed" else "burned",
        )
        self.show_info("Success", f"Video saved:\n{output_path}")

    def video_subtitle_job_cancelled(self):
        self.video_status.setText("Cancelled.")
        self.append_video_log("Job cancelled.")

    def video_subtitle_job_failed(self, message):
        self.video_status.setText("Error.")
        self.append_video_log(f"ERROR: {message}")
        self.show_error("Subtitles", message)

    def finish_video_subtitle_job(self):
        self.is_video_running = False
        self.video_progress.hide()
        self.update_video_subtitle_button_state()
        self.update_stt_button_state()
        self.update_tts_button_state()
        self.update_video_cleanup_button_state()

    def open_video_subtitle_output(self):
        open_path(self.video_last_output_path)

    def open_video_subtitle_output_folder(self):
        if self.video_last_output_path and Path(self.video_last_output_path).is_file():
            open_path(Path(self.video_last_output_path).parent)

    def update_video_subtitle_button_state(self):
        if not hasattr(self, "video_start_button"):
            return
        busy_elsewhere = self.is_converting or self.is_stt_running or self.is_cleanup_running
        burn_mode = self.video_subtitle_mode_key() == "burn"
        self.video_start_button.setEnabled(not self.is_video_running and not busy_elsewhere)
        self.video_preview_button.setEnabled(not self.is_video_running and not busy_elsewhere and burn_mode)
        self.video_cancel_button.setEnabled(self.is_video_running and not self.video_cancel_requested)
        output_ready = bool(self.video_last_output_path and Path(self.video_last_output_path).is_file())
        self.video_open_output_button.setEnabled(output_ready)
        self.video_open_folder_button.setEnabled(output_ready)
        for widget in (
            self.video_media_picker,
            self.video_srt_picker,
            self.video_output_picker,
            self.video_embed_mode_button,
            self.video_burn_mode_button,
            self.video_quality_combo,
            self.video_font_size_spin,
            self.video_outline_spin,
            self.video_margin_spin,
            self.video_position_combo,
        ):
            widget.setEnabled(not self.is_video_running)
        self.update_navigation_state()

    def append_video_log(self, line):
        self.video_log_lines.append(line)
        self.video_log_lines = self.video_log_lines[-300:]
        self.video_log.appendPlainText(line)
        scrollbar = self.video_log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def reset_video_log(self):
        self.video_log_lines = []
        self.video_log.clear()

    def toggle_video_details(self):
        if self.video_log.isVisible():
            self.video_log.hide()
            self.video_details_button.setText("Show details")
            return
        self.video_log.show()
        self.video_details_button.setText("Hide details")

    def cleanup_media_changed(self):
        self.update_cleanup_output(force=False)
        if self.cleanup_detected_media_path and self.cleanup_media_picker.text() != self.cleanup_detected_media_path:
            self.clear_cleanup_detection_results("Ready.")
        self.update_video_cleanup_button_state()
        self.save_user_settings()

    def clear_cleanup_detection_results(self, status_text=None):
        self.cleanup_detected_frames = []
        self.cleanup_detected_media_path = ""
        self.cleanup_repairable_frame_map = {}
        self.cleanup_frame_checkboxes = {}
        if hasattr(self, "cleanup_results"):
            self.cleanup_results.clear()
        if hasattr(self, "cleanup_repair_options"):
            self.cleanup_repair_options.hide()
        if hasattr(self, "cleanup_repair_button"):
            self.cleanup_repair_button.hide()
        if status_text is not None and hasattr(self, "cleanup_status"):
            self.cleanup_status.setText(status_text)

    def update_cleanup_quality_description(self, text):
        self.cleanup_quality_description.setText(VIDEO_CLEANUP_QUALITY_DESCRIPTIONS.get(text, ""))
        self.save_user_settings()

    def update_cleanup_method_description(self, text):
        self.cleanup_method_description.setText(VIDEO_CLEANUP_METHOD_DESCRIPTIONS.get(text, ""))
        self.save_user_settings()

    def cleanup_method_key(self):
        return VIDEO_CLEANUP_METHOD_BY_LABEL.get(self.cleanup_method_combo.currentText(), VIDEO_CLEANUP_METHOD_FREEZE)

    def update_cleanup_output(self, force=False):
        if not hasattr(self, "cleanup_output_picker"):
            return
        media_path = self.cleanup_media_picker.text()
        if not media_path:
            return
        suggested = suggest_video_cleanup_output_path(media_path)
        current = self.cleanup_output_picker.text()
        if force or not current or current == self.cleanup_last_auto_output_path:
            self.cleanup_output_picker.set_text(suggested)
            self.cleanup_last_auto_output_path = suggested

    def select_cleanup_media_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select video file",
            self.cleanup_media_picker.text() or str(Path.home()),
            "Video files (*.mp4 *.mkv *.mov *.avi *.webm *.m4v);;All files (*.*)",
        )
        if path:
            self.cleanup_media_picker.set_text(path)
            self.update_cleanup_output(force=False)
            self.save_user_settings()

    def select_cleanup_output_file(self):
        media_path = self.cleanup_media_picker.text()
        suggested = self.cleanup_output_picker.text() or (
            suggest_video_cleanup_output_path(media_path) if media_path else str(Path.home() / "cleaned_video.mp4")
        )
        filter_text = "MP4 video (*.mp4);;Matroska video (*.mkv);;QuickTime video (*.mov);;All files (*.*)"
        path, selected_filter = QFileDialog.getSaveFileName(self, "Save repaired video as", suggested, filter_text)
        if path:
            default_suffix = (
                ".mkv"
                if "Matroska" in selected_filter
                else ".mov"
                if "QuickTime" in selected_filter
                else ".mp4"
            )
            self.cleanup_output_picker.set_text(self.normalize_cleanup_output_path(path, media_path, default_suffix))
            self.cleanup_last_auto_output_path = ""
            self.save_user_settings()

    @staticmethod
    def normalize_cleanup_output_path(output_path, media_path, default_suffix=".mp4"):
        path = Path(output_path)
        if path.suffix:
            return str(path)
        media_suffix = Path(media_path).suffix.lower() if media_path else ""
        fallback = media_suffix if media_suffix in {".mp4", ".mkv", ".mov", ".m4v"} else default_suffix
        return str(path.with_suffix(fallback))

    def collect_video_cleanup_media(self):
        media_path = self.cleanup_media_picker.text()
        if not media_path:
            raise ValueError("Please select a video file.")
        media = Path(media_path)
        if not media.is_file():
            raise ValueError("The selected video file does not exist.")
        if media.suffix.lower() not in STT_VIDEO_SUFFIXES:
            raise ValueError("The selected file must be a video.")
        return media_path

    def selected_cleanup_frame_numbers(self) -> list[int]:
        selected: list[int] = []
        for frame_number, checkbox in self.cleanup_frame_checkboxes.items():
            if frame_number in self.cleanup_repairable_frame_map and checkbox.isChecked():
                selected.append(frame_number)
        return sorted(selected)

    def selected_cleanup_frame_times(self, selected_frames: list[int]) -> list[float]:
        return [
            self.cleanup_repairable_frame_map[frame_number]["time"]
            for frame_number in selected_frames
            if frame_number in self.cleanup_repairable_frame_map
        ]

    def collect_video_cleanup_repair_options(self):
        media_path = self.collect_video_cleanup_media()
        if self.cleanup_detected_media_path != media_path:
            raise ValueError("Run detection on this video before repairing frames.")
        selected_frames = self.selected_cleanup_frame_numbers()
        if not selected_frames:
            raise ValueError("Select at least one repairable frame to repair.")

        output_path = self.cleanup_output_picker.text()
        if not output_path:
            output_path = suggest_video_cleanup_output_path(media_path)
            self.cleanup_output_picker.set_text(output_path)
        output_path = self.normalize_cleanup_output_path(output_path, media_path)
        output = Path(output_path)
        if output.suffix.lower() not in {".mp4", ".mkv", ".mov", ".m4v"}:
            raise ValueError("Repaired video output must be .mp4, .mkv, .mov or .m4v.")
        try:
            if output.resolve() == Path(media_path).resolve():
                raise ValueError("Choose an output path different from the source video.")
        except OSError:
            pass
        self.cleanup_output_picker.set_text(output_path)
        self.save_user_settings()

        cleanup_quality = VIDEO_CLEANUP_QUALITY_BY_LABEL.get(
            self.cleanup_quality_combo.currentText(),
            BURN_QUALITY_AUTO,
        )
        cleanup_method = self.cleanup_method_key()
        selected_frame_times = self.selected_cleanup_frame_times(selected_frames)
        return media_path, output_path, cleanup_quality, cleanup_method, selected_frames, selected_frame_times

    def start_video_cleanup_from_page(self):
        try:
            media_path = self.collect_video_cleanup_media()
        except ValueError as exc:
            self.cleanup_status.setText("Error.")
            self.show_error("Video Cleanup", str(exc))
            return
        ffmpeg = find_ffmpeg_exe()
        if not ffmpeg:
            self.cleanup_status.setText("ffmpeg missing.")
            self.show_error("ffmpeg missing", "Could not find ffmpeg. Use the full VoiceBridge bundle.")
            return

        self.cleanup_cancel_requested = False
        self.cleanup_process = None
        self.cleanup_last_output_path = ""
        self.clear_cleanup_detection_results()
        self.reset_cleanup_log()
        self.cleanup_results.clear()
        self.is_cleanup_running = True
        self.show_indeterminate_progress(self.cleanup_progress)
        self.cleanup_status.setText("Detecting black frames...")
        self.append_cleanup_log(f"Detecting black frames: {media_path}")
        self.update_video_cleanup_button_state()
        self.update_tts_button_state()
        self.update_stt_button_state()
        self.update_video_subtitle_button_state()
        threading.Thread(
            target=self.video_cleanup_detect_worker,
            args=(str(ffmpeg), media_path),
            daemon=True,
        ).start()

    def start_video_cleanup_repair_from_page(self):
        try:
            (
                media_path,
                output_path,
                cleanup_quality,
                cleanup_method,
                selected_frames,
                selected_frame_times,
            ) = self.collect_video_cleanup_repair_options()
        except ValueError as exc:
            self.cleanup_status.setText("Error.")
            self.show_error("Video Cleanup", str(exc))
            return
        ffmpeg = find_ffmpeg_exe()
        if not ffmpeg:
            self.cleanup_status.setText("ffmpeg missing.")
            self.show_error("ffmpeg missing", "Could not find ffmpeg. Use the full VoiceBridge bundle.")
            return

        self.cleanup_cancel_requested = False
        self.cleanup_process = None
        self.cleanup_last_output_path = ""
        self.is_cleanup_running = True
        self.update_cleanup_progress_percent(0)
        action = "Removing" if cleanup_method == VIDEO_CLEANUP_METHOD_REMOVE else "Repairing"
        self.cleanup_status.setText(f"{action} {len(selected_frames)} selected frame(s)...")
        self.append_cleanup_log("")
        self.append_cleanup_log(f"{action} selected frames: {', '.join(str(frame) for frame in selected_frames)}")
        self.update_video_cleanup_button_state()
        self.update_tts_button_state()
        self.update_stt_button_state()
        self.update_video_subtitle_button_state()
        threading.Thread(
            target=self.video_cleanup_repair_worker,
            args=(
                str(ffmpeg),
                media_path,
                output_path,
                cleanup_quality,
                cleanup_method,
                selected_frames,
                selected_frame_times,
            ),
            daemon=True,
        ).start()

    def video_cleanup_detect_worker(self, ffmpeg, media_path):
        try:
            self.post(self.append_cleanup_log, "Detecting source video details...")
            source_video_info = probe_video_info(ffmpeg, media_path)
            duration_seconds = source_video_info.get("duration_seconds")
            if duration_seconds:
                self.post(self.update_cleanup_progress_percent, 0)
            else:
                self.post(self.set_cleanup_progress_indeterminate)

            command = black_frame_detect_command(ffmpeg, media_path)
            black_frames, recent_output = self.run_blackframe_detect_process(command, duration_seconds, 0, 100)
            if self.cleanup_cancel_requested:
                self.post(self.video_cleanup_job_cancelled)
                return
            isolated_frames, longer_runs = isolated_black_frame_numbers(black_frames, max_run_length=1)
            self.post(self.cleanup_detection_finished, media_path, black_frames, isolated_frames, longer_runs)
            self.post(self.video_cleanup_detect_succeeded, black_frames, isolated_frames, longer_runs)
        except (OSError, RuntimeError, ValueError) as exc:
            self.post(self.video_cleanup_job_failed, str(exc))
        finally:
            self.cleanup_process = None
            self.post(self.finish_video_cleanup_job)

    def video_cleanup_repair_worker(
        self,
        ffmpeg,
        media_path,
        output_path,
        cleanup_quality,
        cleanup_method,
        selected_frames,
        selected_frame_times,
    ):
        temp_output_path = None
        try:
            self.post(self.append_cleanup_log, "Detecting source video details...")
            source_video_info = probe_video_info(ffmpeg, media_path)
            duration_seconds = source_video_info.get("duration_seconds")
            if duration_seconds:
                self.post(self.update_cleanup_progress_percent, 0)
            else:
                self.post(self.set_cleanup_progress_indeterminate)

            if not selected_frames:
                self.post(self.video_cleanup_no_repair_needed)
                return

            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(
                prefix=f".{output_path.stem}.voicebridge-clean-",
                suffix=output_path.suffix,
                dir=str(output_path.parent),
            )
            os.close(fd)
            temp_output_path = Path(temp_name)
            temp_output_path.unlink(missing_ok=True)

            removing_frames = cleanup_method == VIDEO_CLEANUP_METHOD_REMOVE
            action = "Removing" if removing_frames else "Repairing"
            self.post(self.cleanup_status.setText, f"{action} {len(selected_frames)} selected frame(s)...")
            self.post(self.append_cleanup_log, f"Clean method: {cleanup_method}")
            self.post(self.append_cleanup_log, f"Output quality: {cleanup_quality}")
            if removing_frames:
                source_fps = source_video_info.get("fps")
                fps_note = f"{source_fps:.3f} fps" if source_fps else "fps unavailable; assuming 25 fps"
                self.post(self.append_cleanup_log, f"Removing matching audio slices too ({fps_note}).")
            self.post(
                self.append_cleanup_log,
                f"{action} frames: {', '.join(str(frame) for frame in selected_frames[:40])}",
            )
            if len(selected_frames) > 40:
                self.post(self.append_cleanup_log, f"...and {len(selected_frames) - 40} more.")

            commands = video_cleanup_repair_commands(
                ffmpeg,
                media_path,
                str(temp_output_path),
                selected_frames,
                repair_method=cleanup_method,
                cleanup_quality=cleanup_quality,
                source_video_bitrate_kbps=source_video_info.get("bitrate_kbps"),
                source_video_width=source_video_info.get("width"),
                source_video_height=source_video_info.get("height"),
                source_video_fps=source_video_info.get("fps"),
                source_has_audio=source_video_info.get("has_audio", True),
                frame_times_seconds=selected_frame_times,
            )
            recent_output = []
            for command in commands:
                return_code, recent_output = self.run_cleanup_ffmpeg_process(command, duration_seconds, 0, 100)
                if return_code == 0:
                    if self.cleanup_cancel_requested:
                        self.post(self.video_cleanup_job_cancelled)
                        return
                    os.replace(temp_output_path, output_path)
                    self.post(self.update_cleanup_progress_percent, 100)
                    self.post(
                        self.video_cleanup_repair_succeeded,
                        str(output_path),
                        len(selected_frames),
                        cleanup_method,
                    )
                    return
                if self.cleanup_cancel_requested:
                    self.post(self.video_cleanup_job_cancelled)
                    return
            raise RuntimeError("\n".join(recent_output[-8:]) or "ffmpeg could not repair the video.")
        except (OSError, RuntimeError, ValueError) as exc:
            self.post(self.video_cleanup_job_failed, str(exc))
        finally:
            if temp_output_path:
                with suppress(OSError):
                    temp_output_path.unlink(missing_ok=True)
            self.cleanup_process = None
            self.post(self.finish_video_cleanup_job)

    def run_blackframe_detect_process(
        self,
        command: list[str],
        duration_seconds: float | None = None,
        progress_start: int = 0,
        progress_end: int = 100,
    ) -> tuple[list[BlackFrame], list[str]]:
        black_frames: list[BlackFrame] = []
        recent_output = []
        last_progress_percent = -1
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
        self.cleanup_process = process
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.strip()
            if not line:
                continue
            progress_percent = self.ffmpeg_progress_percent(line, duration_seconds)
            if progress_percent is not None:
                mapped = progress_start + ((progress_end - progress_start) * progress_percent / 100)
                if mapped > last_progress_percent:
                    last_progress_percent = mapped
                    self.post(self.update_cleanup_progress_percent, mapped)
                continue
            if self.is_ffmpeg_progress_line(line):
                continue
            black_frame = parse_blackframe_line(line)
            if black_frame:
                black_frames.append(black_frame)
                self.post(
                    self.append_cleanup_log,
                    f"Black frame candidate: frame {black_frame['frame']} at {black_frame['time']:.3f}s "
                    f"({black_frame['pblack']}% black)",
                )
                continue
            recent_output.append(line)
            recent_output = recent_output[-12:]
            if self.cleanup_cancel_requested and process.poll() is None:
                process.terminate()
        return_code = process.wait()
        if return_code != 0 and not self.cleanup_cancel_requested:
            raise RuntimeError("\n".join(recent_output[-8:]) or f"ffmpeg exited with code {return_code}.")
        return black_frames, recent_output

    def run_cleanup_ffmpeg_process(self, command, duration_seconds=None, progress_start=0, progress_end=100):
        recent_output = []
        last_progress_percent = -1
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
        self.cleanup_process = process
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.strip()
            if not line:
                continue
            progress_percent = self.ffmpeg_progress_percent(line, duration_seconds)
            if progress_percent is not None:
                mapped = progress_start + ((progress_end - progress_start) * progress_percent / 100)
                if mapped > last_progress_percent:
                    last_progress_percent = mapped
                    self.post(self.update_cleanup_progress_percent, mapped)
                continue
            if self.is_ffmpeg_progress_line(line):
                continue
            recent_output.append(line)
            recent_output = recent_output[-12:]
            self.post(self.append_cleanup_log, line)
            if self.cleanup_cancel_requested and process.poll() is None:
                process.terminate()
        return process.wait(), recent_output

    @staticmethod
    def cleanup_long_run_reason_map(longer_runs: list[list[BlackFrame]]) -> dict[int, str]:
        reasons: dict[int, str] = {}
        for run in longer_runs:
            if not run:
                continue
            frame_numbers = [frame["frame"] for frame in run]
            if len(run) == 1 and frame_numbers[0] == 0:
                reason = "Skipped: first frame / edge candidate"
            else:
                reason = "Skipped: longer black run, fade or head/tail section"
            for frame_number in frame_numbers:
                reasons[frame_number] = reason
        return reasons

    def add_cleanup_result_row(self, frame: BlackFrame, repairable: bool, reason: str) -> None:
        frame_number = frame["frame"]
        item = QListWidgetItem()
        item.setSizeHint(QSize(0, 46))
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(8, 4, 8, 4)
        row_layout.setSpacing(10)

        checkbox = QCheckBox()
        checkbox.setChecked(repairable)
        checkbox.setEnabled(repairable and not self.is_cleanup_running)
        checkbox.stateChanged.connect(lambda _state: self.update_video_cleanup_button_state())
        self.cleanup_frame_checkboxes[frame_number] = checkbox

        title = QLabel(f"Frame {frame_number} | {frame['time']:.3f}s | {frame['pblack']}% black")
        title.setWordWrap(True)
        title.setMinimumWidth(260)
        state = QLabel("Repairable" if repairable else reason)
        state.setObjectName("Muted")
        state.setWordWrap(True)
        detail_button = QPushButton("Details")
        detail_button.setEnabled(repairable)
        detail_button.clicked.connect(partial(self.show_cleanup_frame_details_from_button, frame))

        row_layout.addWidget(checkbox)
        row_layout.addWidget(title, 2)
        row_layout.addWidget(state, 2)
        row_layout.addWidget(detail_button)
        self.cleanup_results.addItem(item)
        self.cleanup_results.setItemWidget(item, row)

    def cleanup_detection_finished(
        self,
        media_path: str,
        black_frames: list[BlackFrame],
        isolated_frames: list[int],
        longer_runs: list[list[BlackFrame]],
    ) -> None:
        self.cleanup_detected_frames = black_frames
        self.cleanup_detected_media_path = media_path
        self.cleanup_repairable_frame_map = {
            frame["frame"]: frame for frame in black_frames if frame["frame"] in set(isolated_frames)
        }
        self.cleanup_frame_checkboxes = {}
        self.cleanup_results.clear()
        if not black_frames:
            self.cleanup_results.addItem("No black-frame candidates found.")
            self.update_video_cleanup_button_state()
            return
        self.cleanup_results.addItem(f"Black-frame candidates: {len(black_frames)}")
        self.cleanup_results.addItem(f"Repairable isolated frames: {len(isolated_frames)}")
        if longer_runs:
            self.cleanup_results.addItem(f"Longer black runs left untouched: {len(longer_runs)}")
        reason_by_frame = self.cleanup_long_run_reason_map(longer_runs)
        isolated_set = set(isolated_frames)
        for frame in black_frames[:120]:
            repairable = frame["frame"] in isolated_set
            reason = reason_by_frame.get(frame["frame"], "Skipped: not an isolated one-frame glitch")
            self.add_cleanup_result_row(frame, repairable, reason)
        if len(black_frames) > 120:
            self.cleanup_results.addItem(f"...and {len(black_frames) - 120} more candidates. See details.")
        self.update_video_cleanup_button_state()

    def show_cleanup_frame_details_from_button(self, frame: BlackFrame, _checked: bool = False) -> None:
        self.show_cleanup_frame_details(frame)

    def show_cleanup_frame_details(self, frame: BlackFrame) -> None:
        media_path = self.cleanup_detected_media_path or self.cleanup_media_picker.text()
        if not media_path:
            self.show_error("Frame details", "Select a video and run detection first.")
            return
        ffmpeg = find_ffmpeg_exe()
        if not ffmpeg:
            self.show_error("ffmpeg missing", "Could not find ffmpeg. Use the full VoiceBridge bundle.")
            return

        frame_number = int(frame["frame"])
        preview_specs = [
            ("Previous frame", max(0, frame_number - 1)),
            ("Problem frame", frame_number),
            ("Next frame", frame_number + 1),
        ]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        with tempfile.TemporaryDirectory(prefix="voicebridge-frame-preview-") as temp_dir:
            preview_paths = []
            for title, preview_frame in preview_specs:
                output_path = str(Path(temp_dir) / f"frame_{preview_frame}.png")
                command = video_frame_preview_command(ffmpeg, media_path, preview_frame, output_path)
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=creationflags,
                    timeout=60,
                    check=False,
                )
                preview_path = (
                    output_path
                    if result.returncode == 0 and Path(output_path).is_file()
                    else ""
                )
                preview_paths.append((title, preview_frame, preview_path))

            dialog = QDialog(self)
            dialog.setWindowTitle(f"Frame {frame_number} details")
            dialog.setMinimumWidth(980)
            layout = QVBoxLayout(dialog)
            header = QLabel(f"Frame {frame_number} at {frame['time']:.3f}s")
            header.setObjectName("CardTitle")
            layout.addWidget(header)
            row = QHBoxLayout()
            row.setSpacing(12)
            layout.addLayout(row)

            for title, preview_frame, preview_path in preview_paths:
                panel = QVBoxLayout()
                label = QLabel(f"{title}\n#{preview_frame}")
                label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                image = QLabel()
                image.setAlignment(Qt.AlignmentFlag.AlignCenter)
                image.setMinimumSize(300, 170)
                image.setStyleSheet("background: #0f172a; border-radius: 6px; color: #e5e7eb;")
                if preview_path:
                    pixmap = QPixmap(preview_path)
                    if not pixmap.isNull():
                        image.setPixmap(
                            pixmap.scaled(
                                300,
                                170,
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation,
                            )
                        )
                    else:
                        image.setText("Preview unavailable")
                else:
                    image.setText("Preview unavailable")
                panel.addWidget(label)
                panel.addWidget(image)
                row.addLayout(panel)

            close_button = QPushButton("Close")
            close_button.clicked.connect(dialog.accept)
            footer = QHBoxLayout()
            footer.addStretch(1)
            footer.addWidget(close_button)
            layout.addLayout(footer)
            dialog.exec()

    def video_cleanup_detect_succeeded(self, black_frames, isolated_frames, longer_runs):
        if black_frames:
            self.cleanup_status.setText(
                f"Detected {len(black_frames)} black-frame candidate(s); {len(isolated_frames)} repairable."
            )
        else:
            self.cleanup_status.setText("No black-frame candidates found.")
        if longer_runs:
            self.append_cleanup_log(
                f"Longer black runs were detected and left untouched: {len(longer_runs)}. "
                "These may be fades or intentional black sections."
            )

    def video_cleanup_no_repair_needed(self):
        self.cleanup_status.setText("No isolated black frames to clean.")
        self.append_cleanup_log("No one-frame black glitches were selected. No output video was created.")

    def video_cleanup_repair_succeeded(self, output_path, repaired_count, cleanup_method):
        self.cleanup_last_output_path = output_path
        removed = cleanup_method == VIDEO_CLEANUP_METHOD_REMOVE
        status_text = (
            f"Removed {repaired_count} selected frame(s)."
            if removed
            else f"Repaired {repaired_count} selected frame(s)."
        )
        self.cleanup_status.setText(status_text)
        self.append_cleanup_log(f"Video saved: {output_path}")
        self.record_job(
            "CLEAN",
            "Video cleaned",
            self.cleanup_media_picker.text(),
            output_path,
            f"{repaired_count} frame(s), {'removed' if removed else 'freeze'}",
        )
        self.show_info("Video Cleanup", f"Video saved:\n{output_path}")

    def video_cleanup_job_cancelled(self):
        self.cleanup_status.setText("Cancelled.")
        self.append_cleanup_log("Job cancelled.")

    def video_cleanup_job_failed(self, message):
        self.cleanup_status.setText("Error.")
        self.append_cleanup_log(f"ERROR: {message}")
        self.show_error("Video Cleanup", message)

    def finish_video_cleanup_job(self):
        self.is_cleanup_running = False
        self.cleanup_progress.hide()
        self.update_video_cleanup_button_state()
        self.update_tts_button_state()
        self.update_stt_button_state()
        self.update_video_subtitle_button_state()

    def cancel_video_cleanup_job(self):
        if not self.is_cleanup_running:
            return
        self.cleanup_cancel_requested = True
        self.cleanup_status.setText("Cancelling...")
        self.append_cleanup_log("Cancellation requested.")
        self.update_video_cleanup_button_state()
        process = self.cleanup_process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError as exc:
                self.append_cleanup_log(f"Could not terminate process cleanly: {exc}")

    def open_cleanup_output(self):
        open_path(self.cleanup_last_output_path)

    def open_cleanup_output_folder(self):
        if self.cleanup_last_output_path and Path(self.cleanup_last_output_path).is_file():
            open_path(Path(self.cleanup_last_output_path).parent)

    def update_video_cleanup_button_state(self):
        if not hasattr(self, "cleanup_start_button"):
            return
        busy_elsewhere = self.is_converting or self.is_stt_running or self.is_video_running
        current_media = self.cleanup_media_picker.text()
        detection_ready = bool(
            self.cleanup_detected_media_path
            and self.cleanup_detected_media_path == current_media
            and self.cleanup_repairable_frame_map
        )
        selected_frames = self.selected_cleanup_frame_numbers() if detection_ready else []
        self.cleanup_start_button.setEnabled(not self.is_cleanup_running and not busy_elsewhere)
        self.cleanup_repair_button.setVisible(detection_ready)
        self.cleanup_repair_button.setEnabled(
            detection_ready
            and bool(selected_frames)
            and not self.is_cleanup_running
            and not busy_elsewhere
        )
        self.cleanup_cancel_button.setEnabled(self.is_cleanup_running and not self.cleanup_cancel_requested)
        output_ready = bool(self.cleanup_last_output_path and Path(self.cleanup_last_output_path).is_file())
        self.cleanup_open_output_button.setEnabled(output_ready)
        self.cleanup_open_folder_button.setEnabled(output_ready)
        self.cleanup_repair_options.setVisible(detection_ready)
        for widget in (
            self.cleanup_media_picker,
            self.cleanup_output_picker,
            self.cleanup_method_combo,
            self.cleanup_quality_combo,
        ):
            widget.setEnabled(not self.is_cleanup_running)
        for frame_number, checkbox in self.cleanup_frame_checkboxes.items():
            checkbox.setEnabled(
                detection_ready
                and frame_number in self.cleanup_repairable_frame_map
                and not self.is_cleanup_running
            )
        self.update_navigation_state()

    def append_cleanup_log(self, line):
        self.cleanup_log_lines.append(line)
        self.cleanup_log_lines = self.cleanup_log_lines[-300:]
        self.cleanup_log.appendPlainText(line)
        scrollbar = self.cleanup_log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def reset_cleanup_log(self):
        self.cleanup_log_lines = []
        self.cleanup_log.clear()

    def toggle_cleanup_details(self):
        if self.cleanup_log.isVisible():
            self.cleanup_log.hide()
            self.cleanup_details_button.setText("Show details")
            return
        self.cleanup_log.show()
        self.cleanup_details_button.setText("Hide details")


def main():
    app = QApplication([])
    app.setApplicationName(APP_NAME)
    icon_path = resource_path(APP_ICON_PNG)
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = VoiceBridgeQt()
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
