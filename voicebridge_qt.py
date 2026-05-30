import queue
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
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

from app_paths import resource_path
from app_settings import load_app_settings, save_app_settings
from languages import LANGUAGE_NAMES
from media_tools import (
    BlackFrame,
)
from voicebridge.constants import (
    APP_ATTRIBUTION,
    APP_ICON,
    APP_ICON_PNG,
    APP_NAME,
    BURN_QUALITY_LABELS,
    RATE_CHOICES,
    STT_ALIGNMENT_READY_LANGUAGES,
    STT_LANGUAGE_AUTO_LABEL,
    STT_LANGUAGE_CODES,
    STT_LANGUAGE_LEGACY_LABELS,
    STT_MODE_LABELS,
    TTS_SPLIT_LINES,
    TTS_SPLIT_PARAGRAPHS,
    UI_QUEUE_POLL_MS,
    VIDEO_CLEANUP_METHOD_LABELS,
    VIDEO_CLEANUP_QUALITY_LABELS,
    VIDEO_SUBTITLE_POSITION_LABELS,
)
from voicebridge.models import JobHistoryEntry, TtsSegment
from voicebridge.pages.builders import PageBuilderMixin
from voicebridge.pages.cleanup import VideoCleanupWorkflowMixin
from voicebridge.pages.stt import SttWorkflowMixin
from voicebridge.pages.subtitles import SubtitlesWorkflowMixin
from voicebridge.pages.tts import TtsWorkflowMixin
from voicebridge.ui.styles import apply_app_style
from voicebridge.ui.widgets import FilePicker
from voices import (
    load_preferred_voice_short_names,
)


class VoiceBridgeQt(
    VideoCleanupWorkflowMixin,
    SubtitlesWorkflowMixin,
    SttWorkflowMixin,
    TtsWorkflowMixin,
    PageBuilderMixin,
    QMainWindow,
):
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
