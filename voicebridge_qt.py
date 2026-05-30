import asyncio
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import webbrowser
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any, TypedDict

import aiohttp
import edge_tts
from edge_tts.exceptions import EdgeTTSException
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
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
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app_paths import external_base_dir, resource_path, stt_python_path, stt_worker_path
from app_settings import load_app_settings, save_app_settings
from languages import LANGUAGE_NAMES, language_name
from media_tools import (
    BURN_QUALITY_AUTO,
    BURN_QUALITY_CRF_VALUES,
    BURN_QUALITY_HIGH,
    BURN_QUALITY_MAXIMUM,
    BURN_QUALITY_ORIGINAL_BITRATE,
    BURN_QUALITY_STANDARD,
    STT_VIDEO_SUFFIXES,
    VIDEO_CLEANUP_METHOD_FREEZE,
    VIDEO_CLEANUP_METHOD_REMOVE,
    BlackFrame,
    SubtitleStyle,
    auto_burn_quality,
    black_frame_detect_command,
    can_create_video_subtitles,
    concatenate_mp3_files,
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
    SUPPORTED_FILETYPES,
    TESSERACT_NOT_INSTALLED_TEXT,
    TESSERACT_WINDOWS_INSTALL_URL,
    WORD_REQUIRED_TEXT,
    detect_text_language,
    file_signature,
    load_ocr_dependencies,
    read_input_file,
    read_txt,
)
from stt_preflight import check_stt_preflight
from tts_engine import TtsCancelled, ensure_mp3_suffix, generate_audio, suggested_output_path
from voices import (
    FALLBACK_VOICES,
    build_voice_options,
    filter_voices_by_language,
    filter_voices_by_query,
    find_voice_label,
    load_preferred_voice_short_names,
    save_preferred_voice_short_names,
)

APP_NAME = "VoiceBridge"
APP_ATTRIBUTION = "© Davide Marchi"
APP_ICON = Path("images") / "file_to_mp3.ico"
APP_ICON_PNG = Path("images") / "file_to_mp3.png"
DEFAULT_VOICE_SHORT_NAME = "en-US-AriaNeural"
DEFAULT_RATE = "-5%"
RATE_CHOICES = ["-20%", "-15%", "-10%", "-5%", "+0%", "+5%", "+10%"]
TTS_SPLIT_PARAGRAPHS = "Paragraphs"
TTS_SPLIT_LINES = "Lines"
STT_MODEL = "large-v3"
UI_QUEUE_POLL_MS = 50

STT_MODE_LABELS = {
    "Transcript Markdown (.md)": "transcript",
    "Auto subtitles (.srt)": "auto_srt",
    "Subtitles from provided text (.srt)": "align_text",
}
STT_SRT_MODES = {"auto_srt", "align_text"}
STT_ALIGNMENT_READY_LANGUAGES = {"en", "it"}
STT_LANGUAGE_AUTO_LABEL = "Auto detect"
STT_LANGUAGE_CODES = [
    "auto",
    "en",
    "it",
    *[
        code for code in sorted(LANGUAGE_NAMES, key=lambda language_code: LANGUAGE_NAMES[language_code])
        if code not in STT_ALIGNMENT_READY_LANGUAGES
    ],
]
STT_LANGUAGE_LEGACY_LABELS = {STT_LANGUAGE_AUTO_LABEL: "auto"} | {
    LANGUAGE_NAMES[code]: code for code in LANGUAGE_NAMES
}
STT_CPU_ONLY_STATUS = "CPU-only STT runtime included."
MISSING_ALIGNMENT_PREFIX = "MISSING_ALIGNMENT_MODEL:"

BURN_QUALITY_AUTO_LABEL = "Auto (recommended)"
BURN_QUALITY_STANDARD_LABEL = "Standard (CRF 20)"
BURN_QUALITY_HIGH_LABEL = "High quality (CRF 18)"
BURN_QUALITY_MAXIMUM_LABEL = "Maximum quality (CRF 16)"
BURN_QUALITY_ORIGINAL_LABEL = "Original bitrate"
BURN_QUALITY_LABELS = [
    BURN_QUALITY_AUTO_LABEL,
    BURN_QUALITY_STANDARD_LABEL,
    BURN_QUALITY_HIGH_LABEL,
    BURN_QUALITY_MAXIMUM_LABEL,
    BURN_QUALITY_ORIGINAL_LABEL,
]
BURN_QUALITY_BY_LABEL = {
    BURN_QUALITY_AUTO_LABEL: BURN_QUALITY_AUTO,
    BURN_QUALITY_STANDARD_LABEL: BURN_QUALITY_STANDARD,
    BURN_QUALITY_HIGH_LABEL: BURN_QUALITY_HIGH,
    BURN_QUALITY_MAXIMUM_LABEL: BURN_QUALITY_MAXIMUM,
    BURN_QUALITY_ORIGINAL_LABEL: BURN_QUALITY_ORIGINAL_BITRATE,
}
BURN_QUALITY_DESCRIPTIONS = {
    BURN_QUALITY_AUTO_LABEL: (
        "Chooses CRF 20 for most 1080p videos, CRF 18 for 4K "
        "or high-bitrate 1080p sources."
    ),
    BURN_QUALITY_STANDARD_LABEL: "CRF 20: high quality for 1080p, usually smaller files.",
    BURN_QUALITY_HIGH_LABEL: "CRF 18: closer to the source, larger files.",
    BURN_QUALITY_MAXIMUM_LABEL: "CRF 16: very high quality, much larger files.",
    BURN_QUALITY_ORIGINAL_LABEL: (
        "Targets the source video bitrate; still re-encodes, so it is not lossless."
    ),
}
VIDEO_SUBTITLE_EMBED_LABEL = "Embed SRT track"
VIDEO_SUBTITLE_BURN_LABEL = "Burn in SRT"
VIDEO_SUBTITLE_MODE_LABELS = [VIDEO_SUBTITLE_EMBED_LABEL, VIDEO_SUBTITLE_BURN_LABEL]
VIDEO_SUBTITLE_MODE_BY_LABEL = {
    VIDEO_SUBTITLE_EMBED_LABEL: "embed",
    VIDEO_SUBTITLE_BURN_LABEL: "burn",
}
VIDEO_SUBTITLE_MODE_DESCRIPTIONS = {
    VIDEO_SUBTITLE_EMBED_LABEL: "Adds the SRT as a subtitle track. Video and audio streams are copied when possible.",
    VIDEO_SUBTITLE_BURN_LABEL: "Draws subtitles into the video frames. The video must be re-encoded.",
}
VIDEO_SUBTITLE_POSITION_LABELS = {
    "Bottom center": 2,
    "Middle center": 5,
    "Top center": 8,
}
VIDEO_CLEANUP_QUALITY_LABELS = [
    BURN_QUALITY_AUTO_LABEL,
    BURN_QUALITY_STANDARD_LABEL,
    BURN_QUALITY_HIGH_LABEL,
    BURN_QUALITY_MAXIMUM_LABEL,
    BURN_QUALITY_ORIGINAL_LABEL,
]
VIDEO_CLEANUP_QUALITY_BY_LABEL = {
    BURN_QUALITY_AUTO_LABEL: BURN_QUALITY_AUTO,
    BURN_QUALITY_ORIGINAL_LABEL: BURN_QUALITY_ORIGINAL_BITRATE,
    BURN_QUALITY_HIGH_LABEL: BURN_QUALITY_HIGH,
    BURN_QUALITY_MAXIMUM_LABEL: BURN_QUALITY_MAXIMUM,
    BURN_QUALITY_STANDARD_LABEL: BURN_QUALITY_STANDARD,
}
VIDEO_CLEANUP_QUALITY_DESCRIPTIONS = {
    BURN_QUALITY_AUTO_LABEL: BURN_QUALITY_DESCRIPTIONS[BURN_QUALITY_AUTO_LABEL],
    BURN_QUALITY_ORIGINAL_LABEL: "Targets the source video bitrate; still re-encodes, so it is not lossless.",
    BURN_QUALITY_HIGH_LABEL: "CRF 18: high visual quality, bitrate may differ from the source.",
    BURN_QUALITY_MAXIMUM_LABEL: "CRF 16: very high quality, larger output files.",
    BURN_QUALITY_STANDARD_LABEL: "CRF 20: good quality and smaller files, but less conservative.",
}
VIDEO_CLEANUP_FREEZE_LABEL = "Freeze previous frame"
VIDEO_CLEANUP_REMOVE_LABEL = "Remove selected frames"
VIDEO_CLEANUP_METHOD_LABELS = [
    VIDEO_CLEANUP_FREEZE_LABEL,
    VIDEO_CLEANUP_REMOVE_LABEL,
]
VIDEO_CLEANUP_METHOD_BY_LABEL = {
    VIDEO_CLEANUP_FREEZE_LABEL: VIDEO_CLEANUP_METHOD_FREEZE,
    VIDEO_CLEANUP_REMOVE_LABEL: VIDEO_CLEANUP_METHOD_REMOVE,
}
VIDEO_CLEANUP_METHOD_DESCRIPTIONS = {
    VIDEO_CLEANUP_FREEZE_LABEL: (
        "Replaces each selected black frame with the previous frame. Keeps video duration and timing unchanged."
    ),
    VIDEO_CLEANUP_REMOVE_LABEL: (
        "Deletes selected black frames and the matching audio slices. Useful before creating subtitles, "
        "but it shortens the timeline."
    ),
}


class TtsSegment(TypedDict):
    text: str
    voice_label: str
    voice_short_name: str
    rate: str


class JobHistoryEntry(TypedDict):
    timestamp: str
    kind: str
    title: str
    detail: str
    input_path: str
    output_path: str


def qt_file_filter(filetypes):
    parts = []
    for label, patterns in filetypes:
        parts.append(f"{label} ({patterns})")
    return ";;".join(parts)


def open_path(path):
    if path and Path(path).exists():
        os.startfile(str(path))


def normalize_video_subtitle_output_path(output_path, mode, default_suffix=""):
    path = Path(output_path)
    if path.suffix:
        return str(path)
    fallback = default_suffix or (".mp4" if mode == "burn" else ".mkv")
    return str(path.with_suffix(fallback))


def validate_video_subtitle_inputs(mode, media_path, srt_path, output_path):
    media = Path(media_path) if media_path else None
    srt = Path(srt_path) if srt_path else None
    output = Path(output_path) if output_path else None
    if mode not in {"embed", "burn"}:
        raise ValueError("Choose a valid video subtitle mode.")
    if not media or not media.is_file():
        raise ValueError("Select an existing video file.")
    if media.suffix.lower() not in STT_VIDEO_SUFFIXES:
        raise ValueError("The selected media file must be a video.")
    if not srt or not srt.is_file() or srt.suffix.lower() != ".srt":
        raise ValueError("Select an existing .srt subtitle file.")
    if not output:
        raise ValueError("Choose where to save the subtitled video.")
    if mode == "embed" and output.suffix.lower() not in {".mp4", ".mkv"}:
        raise ValueError("Embedded subtitles can be saved as .mp4 or .mkv.")
    if mode == "burn" and output.suffix.lower() != ".mp4":
        raise ValueError("Burned subtitles are saved as .mp4.")
    try:
        if output.resolve() == media.resolve():
            raise ValueError("Choose an output path different from the source video.")
    except OSError:
        pass


class Card(QFrame):
    def __init__(self, title=None, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.content_layout: QVBoxLayout = QVBoxLayout(self)
        self.content_layout.setContentsMargins(18, 14, 18, 14)
        self.content_layout.setSpacing(10)
        if title:
            label = QLabel(title)
            label.setObjectName("CardTitle")
            self.content_layout.addWidget(label)


class FilePicker(QWidget):
    def __init__(self, label, button_text="Browse...", parent=None):
        super().__init__(parent)
        self.setObjectName("FilePicker")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setColumnStretch(0, 1)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(5)

        self.label = QLabel(label)
        self.label.setObjectName("FieldLabel")
        self.edit = QLineEdit()
        self.button = QPushButton(button_text)
        self.button.setObjectName("SecondaryButton")
        self.edit.setMinimumHeight(34)
        self.button.setMinimumHeight(34)

        layout.addWidget(self.label, 0, 0, 1, 2)
        layout.addWidget(self.edit, 1, 0)
        layout.addWidget(self.button, 1, 1)

    def text(self):
        return self.edit.text().strip()

    def set_text(self, value):
        self.edit.setText(value or "")


class VoiceBridgeQt(QMainWindow):
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
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #f4f6f8; color: #111827; font-family: "Segoe UI"; font-size: 10pt; }
            QLabel, QCheckBox { background: transparent; }
            QScrollArea { background: #f4f6f8; border: 0; }
            QScrollArea > QWidget > QWidget { background: #f4f6f8; }
            QScrollBar:vertical {
                background: transparent;
                width: 10px;
                margin: 6px 2px 6px 0;
            }
            QScrollBar::handle:vertical {
                background: #b8c2d1;
                border-radius: 4px;
                min-height: 36px;
            }
            QScrollBar::handle:vertical:hover { background: #8f9caf; }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                background: transparent;
                border: 0;
                height: 0;
            }
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background: transparent;
            }
            QScrollBar:horizontal {
                background: transparent;
                height: 10px;
                margin: 0 6px 2px 6px;
            }
            QScrollBar::handle:horizontal {
                background: #b8c2d1;
                border-radius: 4px;
                min-width: 36px;
            }
            QScrollBar::handle:horizontal:hover { background: #8f9caf; }
            QScrollBar::add-line:horizontal,
            QScrollBar::sub-line:horizontal {
                background: transparent;
                border: 0;
                width: 0;
            }
            QScrollBar::add-page:horizontal,
            QScrollBar::sub-page:horizontal {
                background: transparent;
            }
            QCheckBox { spacing: 8px; }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border-radius: 4px;
                border: 1px solid #98a2b3;
                background: #ffffff;
            }
            QCheckBox::indicator:hover { border-color: #2f6fed; }
            QCheckBox::indicator:checked {
                background: #2f6fed;
                border: 1px solid #2f6fed;
                image: url("__CHECK_ICON__");
            }
            QCheckBox::indicator:disabled {
                background: #eef1f5;
                border-color: #cfd6e2;
            }
            #Sidebar { background: #101827; border: none; }
            #Sidebar QLabel { background: transparent; }
            #AppTitle { color: white; font-size: 18pt; font-weight: 700; }
            #AppSubtitle { color: #aab4c4; }
            #SidebarSection { color: #aab4c4; font-size: 8pt; font-weight: 800; }
            #SidebarStatus { background: transparent; }
            #StatusTile {
                border: 1px solid #445269;
                border-radius: 6px;
                padding: 5px 4px;
                min-height: 34px;
                font-size: 8pt;
                font-weight: 800;
            }
            #StatusTile[state="ok"] { background: #123a31; border-color: #21a67a; color: #d1fae5; }
            #StatusTile[state="warn"] { background: #3a2a12; border-color: #d99020; color: #fdecc8; }
            #StatusTile[state="bad"] { background: #3b1717; border-color: #d14343; color: #fee2e2; }
            #StatusTile[state="info"] { background: #1c2637; border-color: #445269; color: #d5dce8; }
            QPushButton { padding: 8px 12px; border-radius: 6px; border: 1px solid #cfd6e2; background: #ffffff; }
            QPushButton:hover { background: #f1f5fb; border-color: #aeb9c8; }
            QPushButton:disabled { color: #98a2b3; background: #eef1f5; }
            #PrimaryButton { color: white; background: #2f6fed; border-color: #2f6fed; font-weight: 600; }
            #PrimaryButton:hover { background: #265ecb; }
            #DangerButton { color: white; background: #b42318; border-color: #b42318; font-weight: 600; }
            #SecondaryButton { background: #f8fafc; }
            #SegmentButton {
                background: #f8fafc;
                border: 1px solid #cfd6e2;
                padding: 8px 12px;
                font-weight: 600;
            }
            #SegmentButton:hover { background: #edf3ff; border-color: #aeb9c8; }
            #SegmentButton:checked { background: #2f6fed; border-color: #2f6fed; color: #ffffff; }
            #NavButton { color: #d5dce8; background: transparent; border: 0; text-align: left; padding: 10px 12px; }
            #NavButton:hover { background: #1c2637; }
            #NavButton[active="true"] { background: #2f6fed; color: white; font-weight: 600; }
            #Card { background: #ffffff; border: 1px solid #d8dee8; border-radius: 8px; }
            #HomeCard { background: #ffffff; border: 1px solid #d8dee8; border-radius: 8px; }
            #Card QLabel, #HomeCard QLabel, #InlinePanel { background: transparent; }
            #FilePicker { background: transparent; }
            #CardTitle { font-size: 13pt; font-weight: 700; }
            #PageTitle { font-size: 21pt; font-weight: 750; }
            #PageSubtitle, #Muted, #StatusText { color: #617083; }
            #FieldLabel { color: #1f2937; font-weight: 650; }
            #BadgeBlue { color: #2f6fed; font-weight: 800; letter-spacing: 1px; }
            #BadgeGreen { color: #00856f; font-weight: 800; letter-spacing: 1px; }
            #WarningBox { background: #fff7e6; border: 1px solid #f1c36d; border-radius: 8px; }
            #GoodBox { background: #eef8f5; border: 1px solid #b8ddd5; border-radius: 8px; color: #1f5f54; }
            #LogBox { background: #111827; color: #e5e7eb; border-radius: 8px; border: 1px solid #111827; }
            QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QListWidget {
                background: white; border: 1px solid #cfd6e2; border-radius: 6px; padding: 6px;
            }
            QComboBox {
                padding: 6px 34px 6px 8px;
                min-height: 22px;
                selection-background-color: #eaf1ff;
                selection-color: #111827;
            }
            QSpinBox {
                padding: 6px 8px;
                min-height: 22px;
                selection-background-color: #eaf1ff;
                selection-color: #111827;
            }
            QSpinBox::up-button,
            QSpinBox::down-button {
                width: 0;
                border: 0;
            }
            QComboBox:hover { border-color: #aeb9c8; }
            QComboBox:on { border-color: #2f6fed; }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 30px;
                border-left: 1px solid #e4e8ef;
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
                background: #f8fafc;
            }
            QComboBox::drop-down:hover { background: #edf3ff; }
            QComboBox::down-arrow {
                image: url("__CHEVRON_ICON__");
                width: 14px;
                height: 14px;
            }
            QComboBox QAbstractItemView {
                background: #ffffff;
                border: 1px solid #cfd6e2;
                border-radius: 6px;
                padding: 4px;
                outline: 0;
                selection-background-color: #eaf1ff;
                selection-color: #111827;
            }
            QComboBox QAbstractItemView::item {
                min-height: 28px;
                padding: 6px 8px;
            }
            QProgressBar {
                border: 1px solid #cfd6e2;
                border-radius: 7px;
                height: 16px;
                background: #edf1f5;
                text-align: center;
                color: #1f2937;
                font-size: 8pt;
                font-weight: 650;
            }
            QProgressBar::chunk { background: #2f6fed; border-radius: 6px; }
            """
            .replace("__CHECK_ICON__", check_icon)
            .replace("__CHEVRON_ICON__", chevron_icon)
        )

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

    @staticmethod
    def nav_button(text: str, callback: Callable[[], None]) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("NavButton")
        button.clicked.connect(callback)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def show_page(self, index):
        if self.is_converting or self.is_stt_running or self.is_video_running or self.is_cleanup_running:
            return
        self.stack.setCurrentIndex(index)
        for button, active in (
            (self.nav_home, index == 0),
            (self.nav_tts, index == 1),
            (self.nav_stt, index == 2),
            (self.nav_video, index == 3),
            (self.nav_cleanup, index == 4),
        ):
            button.setProperty("active", active)
            button.style().unpolish(button)
            button.style().polish(button)
        if index == 2:
            self.refresh_stt_preflight_async()
        if index == 3:
            self.sync_video_subtitle_inputs_from_stt()

    def update_navigation_state(self):
        if not hasattr(self, "nav_home"):
            return
        enabled = not (self.is_converting or self.is_stt_running or self.is_video_running or self.is_cleanup_running)
        for button in (self.nav_home, self.nav_tts, self.nav_stt, self.nav_video, self.nav_cleanup):
            button.setEnabled(enabled)

    @staticmethod
    def page_container():
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 26, 28, 24)
        layout.setSpacing(16)
        scroll.setWidget(page)
        return scroll, layout

    @staticmethod
    def page_header(layout, badge, title, subtitle, badge_name):
        header = QVBoxLayout()
        header.setSpacing(4)
        badge_label = QLabel(badge)
        badge_label.setObjectName(badge_name)
        title_label = QLabel(title)
        title_label.setObjectName("PageTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("PageSubtitle")
        subtitle_label.setWordWrap(True)
        header.addWidget(badge_label)
        header.addWidget(title_label)
        header.addWidget(subtitle_label)
        layout.addLayout(header)

    def build_home_page(self):
        page, layout = self.page_container()
        self.page_header(
            layout,
            "VOICEBRIDGE",
            "Convert, transcribe and subtitle",
            "Online text-to-speech, offline speech-to-text and practical video subtitle tools in one workspace.",
            "BadgeBlue",
        )

        home_grid = QGridLayout()
        home_grid.setSpacing(16)
        layout.addLayout(home_grid)

        modules_layout = QVBoxLayout()
        modules_layout.setSpacing(10)
        home_grid.addLayout(modules_layout, 0, 0)

        tts_card = self.home_card(
            "TTS",
            "Text to Speech",
            "Convert DOCX, DOC, PDF and TXT into MP3 with Microsoft Edge voices.",
            "Online TTS",
            "BadgeBlue",
        )
        stt_card = self.home_card(
            "STT",
            "Transcription",
            "Create Markdown transcripts, automatic SRT files, or aligned subtitles with bundled offline models.",
            "Offline STT",
            "BadgeGreen",
        )
        video_card = self.home_card(
            "SRT",
            "Subtitles",
            "Embed an SRT track or burn subtitles into an MP4 with controlled output quality.",
            "FFmpeg tools",
            "BadgeBlue",
        )
        cleanup_card = self.home_card(
            "FIX",
            "Video Cleanup",
            "Detect isolated black-frame glitches and repair them without shortening the video.",
            "Frame repair/removal",
            "BadgeGreen",
        )
        for card in (tts_card, stt_card, video_card, cleanup_card):
            modules_layout.addWidget(card)

        note = QLabel("TTS requires internet. STT is CPU-only; SRT can add alignment languages on request.")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        modules_layout.addWidget(note)
        modules_layout.addStretch(1)

        history_card = Card("Recent jobs")
        history_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.job_history_list = QListWidget()
        self.job_history_list.setMinimumHeight(360)
        self.job_history_list.currentRowChanged.connect(lambda _row: self.update_job_history_buttons())
        self.job_history_list.itemDoubleClicked.connect(lambda _item: self.open_selected_job_output())
        history_actions = QHBoxLayout()
        history_actions.setContentsMargins(0, 0, 0, 0)
        self.job_open_output_button = QPushButton("Open output")
        self.job_open_folder_button = QPushButton("Open folder")
        self.job_clear_button = QPushButton("Clear")
        self.job_open_output_button.clicked.connect(self.open_selected_job_output)
        self.job_open_folder_button.clicked.connect(self.open_selected_job_folder)
        self.job_clear_button.clicked.connect(self.clear_job_history)
        history_actions.addWidget(self.job_open_output_button)
        history_actions.addWidget(self.job_open_folder_button)
        history_actions.addStretch(1)
        history_actions.addWidget(self.job_clear_button)
        history_card.content_layout.addWidget(self.job_history_list)
        history_card.content_layout.addLayout(history_actions)

        home_grid.addWidget(history_card, 0, 1)
        home_grid.setColumnStretch(0, 1)
        home_grid.setColumnStretch(1, 2)

        layout.addStretch(1)
        self.refresh_job_history()
        return page

    @staticmethod
    def home_card(
        badge: str,
        title: str,
        body: str,
        details: str,
        badge_name: str,
        button_text: str | None = None,
        callback: Callable[[], None] | None = None,
    ) -> QFrame:
        card = QFrame()
        card.setObjectName("HomeCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(5)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)

        title_label = QLabel(title)
        title_label.setObjectName("CardTitle")
        title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        badge_label = QLabel(badge)
        badge_label.setObjectName(badge_name)
        badge_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        title_row.addWidget(title_label)
        title_row.addWidget(badge_label)

        body_label = QLabel(body)
        body_label.setObjectName("Muted")
        body_label.setWordWrap(True)
        details_label = QLabel(details)
        details_label.setObjectName("Muted")
        layout.addLayout(title_row)
        layout.addWidget(body_label)
        layout.addWidget(details_label)
        if button_text and callback:
            button = QPushButton(button_text)
            button.setObjectName("PrimaryButton")
            button.clicked.connect(callback)
            button.setMinimumHeight(30)
            layout.addWidget(button)
        return card

    @staticmethod
    def word_diagnostic_detail() -> tuple[bool, str]:
        try:
            import win32com.client  # noqa: F401
        except ImportError:
            return False, "pywin32 missing; legacy .doc files cannot be read"
        return True, "pywin32 ready; Microsoft Word is still required for .doc files"

    @staticmethod
    def ocr_diagnostic_detail() -> tuple[bool, str]:
        try:
            load_ocr_dependencies()
        except RuntimeError as exc:
            return False, str(exc)
        return True, "Tesseract and OCR Python packages available"

    @staticmethod
    def diagnostic_state_label(state: str) -> str:
        return {
            "ok": "OK",
            "warn": "WARN",
            "bad": "BAD",
            "info": "INFO",
        }.get(state, "INFO")

    def set_status_tile(self, key: str, state: str, detail: str) -> None:
        tile = self.status_tiles.get(key)
        if tile is None:
            return
        tile.setText(f"{key}\n{self.diagnostic_state_label(state)}")
        tile.setToolTip(detail)
        tile.setProperty("state", state)
        tile.style().unpolish(tile)
        tile.style().polish(tile)

    def refresh_home_diagnostics(self) -> None:
        if not hasattr(self, "status_tiles"):
            return

        if self.is_loading_voices:
            self.set_status_tile("TTS", "info", "Checking Edge TTS voices")
        elif self.voice_load_error_message:
            self.set_status_tile("TTS", "warn", "Fallback voices loaded; internet may be unavailable")
        else:
            self.set_status_tile("TTS", "ok", f"{len(self.all_voices)} online voices loaded")

        if self.stt_preflight_ok:
            self.set_status_tile("STT", "ok", "Offline STT package complete")
        elif self.stt_preflight_details:
            self.set_status_tile("STT", "bad", self.stt_preflight_details[0])
        else:
            self.set_status_tile("STT", "info", "Checking offline STT package")

        ffmpeg = find_ffmpeg_exe()
        self.set_status_tile("FFMPEG", "ok" if ffmpeg else "bad", str(ffmpeg) if ffmpeg else "FFmpeg not found")

        word_ok, word_detail = self.word_diagnostic_detail()
        self.set_status_tile("DOC", "ok" if word_ok else "warn", word_detail)

        ocr_ok, ocr_detail = self.ocr_diagnostic_detail()
        self.set_status_tile("OCR", "ok" if ocr_ok else "warn", ocr_detail)

        self.set_status_tile("CPU", "ok", STT_CPU_ONLY_STATUS)

    def record_job(self, kind: str, title: str, input_path: str, output_path: str, detail: str = "") -> None:
        self.job_history.insert(
            0,
            {
                "timestamp": datetime.now().strftime("%H:%M"),
                "kind": kind,
                "title": title,
                "detail": detail,
                "input_path": input_path or "",
                "output_path": output_path or "",
            },
        )
        self.job_history = self.job_history[:30]
        self.refresh_job_history()
        self.save_user_settings()

    def refresh_job_history(self) -> None:
        if not hasattr(self, "job_history_list"):
            return
        self.job_history_list.clear()
        if not self.job_history:
            self.job_history_list.addItem("No jobs yet.")
            self.update_job_history_buttons()
            return
        for index, job in enumerate(self.job_history):
            output_name = Path(job["output_path"]).name if job["output_path"] else "No output"
            detail = f" - {job['detail']}" if job["detail"] else ""
            item = QListWidgetItem(f"{job['timestamp']}  {job['kind']}  {job['title']}  |  {output_name}{detail}")
            item.setData(Qt.ItemDataRole.UserRole, index)
            self.job_history_list.addItem(item)
        self.job_history_list.setCurrentRow(0)
        self.update_job_history_buttons()

    def selected_job_history_entry(self) -> JobHistoryEntry | None:
        if not hasattr(self, "job_history_list"):
            return None
        item = self.job_history_list.currentItem()
        if item is None:
            return None
        index = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(index, int) or not (0 <= index < len(self.job_history)):
            return None
        return self.job_history[index]

    def update_job_history_buttons(self) -> None:
        if not hasattr(self, "job_open_output_button"):
            return
        job = self.selected_job_history_entry()
        output_ready = bool(job and job["output_path"] and Path(job["output_path"]).is_file())
        self.job_open_output_button.setEnabled(output_ready)
        self.job_open_folder_button.setEnabled(output_ready)
        self.job_clear_button.setEnabled(bool(self.job_history))

    def open_selected_job_output(self) -> None:
        job = self.selected_job_history_entry()
        if job:
            open_path(job["output_path"])

    def open_selected_job_folder(self) -> None:
        job = self.selected_job_history_entry()
        if job and job["output_path"] and Path(job["output_path"]).is_file():
            open_path(Path(job["output_path"]).parent)

    def clear_job_history(self) -> None:
        self.job_history = []
        self.refresh_job_history()
        self.save_user_settings()

    def build_tts_page(self):
        page, layout = self.page_container()
        self.page_header(
            layout,
            "TTS",
            "Text to Speech",
            "Uses Microsoft Edge TTS voices. Internet connection is required.",
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
        voice_card.content_layout.addWidget(self.voice_status)
        voice_card.content_layout.addWidget(QLabel("Voice"))
        voice_card.content_layout.addWidget(self.voice_combo)
        voice_card.content_layout.addWidget(QLabel("Search"))
        voice_card.content_layout.addWidget(self.voice_search)
        voice_row = QHBoxLayout()
        voice_row.addWidget(self.voice_preferred)
        voice_row.addStretch(1)
        voice_row.addWidget(QLabel("Speed"))
        voice_row.addWidget(self.rate_combo)
        voice_card.content_layout.addLayout(voice_row)

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

    def build_stt_page(self):
        page, layout = self.page_container()
        self.page_header(
            layout,
            "STT",
            "Transcription",
            "Creates transcripts or SRT subtitles locally with the bundled offline STT package.",
            "BadgeGreen",
        )

        grid = QGridLayout()
        grid.setSpacing(16)
        layout.addLayout(grid)

        media_card = Card("Media and output")
        media_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.stt_media_picker = FilePicker("Media file")
        self.stt_text_picker = FilePicker("Provided transcript file")
        self.stt_output_picker = FilePicker("Save output as", "Save as...")
        self.stt_media_picker.button.clicked.connect(self.select_stt_media_file)
        self.stt_text_picker.button.clicked.connect(self.select_stt_text_file)
        self.stt_output_picker.button.clicked.connect(self.select_stt_output_file)
        media_card.content_layout.addWidget(self.stt_media_picker)
        media_card.content_layout.addWidget(self.stt_text_picker)
        media_card.content_layout.addWidget(self.stt_output_picker)

        settings_card = Card("Transcription settings")
        settings_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.stt_mode_combo = QComboBox()
        self.stt_mode_combo.addItems(list(STT_MODE_LABELS))
        self.stt_mode_combo.currentTextChanged.connect(self.stt_mode_changed)
        self.stt_language_combo = QComboBox()
        self.stt_language_combo.setMinimumWidth(260)
        self.stt_language_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.populate_stt_language_combo()
        self.stt_language_combo.currentTextChanged.connect(lambda _text: self.save_user_settings())
        settings_card.content_layout.addWidget(QLabel("Mode"))
        settings_card.content_layout.addWidget(self.stt_mode_combo)
        settings_row = QHBoxLayout()
        settings_row.addWidget(QLabel("Language"))
        settings_row.addWidget(self.stt_language_combo, 1)
        settings_row.addWidget(QLabel("Runtime"))
        runtime_label = QLabel("CPU-only")
        runtime_label.setObjectName("Muted")
        settings_row.addWidget(runtime_label)
        settings_card.content_layout.addLayout(settings_row)
        self.stt_preflight_label = QLabel("Checking STT offline package...")
        self.stt_preflight_label.setWordWrap(True)
        self.stt_preflight_box = QFrame()
        self.stt_preflight_box.setObjectName("GoodBox")
        pf_layout = QVBoxLayout(self.stt_preflight_box)
        pf_layout.setContentsMargins(12, 10, 12, 10)
        pf_layout.addWidget(self.stt_preflight_label)
        settings_card.content_layout.addWidget(self.stt_preflight_box)

        grid.addWidget(media_card, 0, 0)
        grid.addWidget(settings_card, 0, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        action_card = Card()
        action_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        self.stt_generate_button = QPushButton("Generate")
        self.stt_generate_button.setObjectName("PrimaryButton")
        self.stt_cancel_button = QPushButton("Cancel")
        self.stt_open_output_button = QPushButton("Open output")
        self.stt_open_folder_button = QPushButton("Open folder")
        self.stt_video_button = QPushButton("Open Subtitles")
        self.stt_details_button = QPushButton("Show details")
        self.stt_generate_button.clicked.connect(self.start_stt_job)
        self.stt_cancel_button.clicked.connect(self.cancel_stt_job)
        self.stt_open_output_button.clicked.connect(self.open_stt_output)
        self.stt_open_folder_button.clicked.connect(self.open_stt_output_folder)
        self.stt_details_button.clicked.connect(self.toggle_stt_details)
        self.stt_video_button.clicked.connect(lambda: self.show_page(3))
        actions.addWidget(self.stt_generate_button)
        actions.addWidget(self.stt_cancel_button)
        actions.addStretch(1)
        actions.addWidget(self.stt_open_output_button)
        actions.addWidget(self.stt_open_folder_button)
        actions.addWidget(self.stt_video_button)
        actions.addWidget(self.stt_details_button)
        action_card.content_layout.addLayout(actions)
        self.stt_progress = QProgressBar()
        self.stt_progress.setRange(0, 0)
        self.stt_progress.hide()
        self.stt_status = QLabel("Ready.")
        self.stt_status.setObjectName("StatusText")
        self.stt_log = QPlainTextEdit()
        self.stt_log.setObjectName("LogBox")
        self.stt_log.setReadOnly(True)
        self.stt_log.setMinimumHeight(160)
        self.stt_log.hide()
        action_card.content_layout.addWidget(self.stt_progress)
        action_card.content_layout.addWidget(self.stt_status)
        action_card.content_layout.addWidget(self.stt_log)
        layout.addWidget(action_card)
        layout.addStretch(1)

        self.stt_mode_changed()
        self.update_stt_button_state()
        return page

    def build_video_subtitle_page(self):
        page, layout = self.page_container()
        self.page_header(
            layout,
            "SUBTITLES",
            "Subtitles",
            "Embed an SRT track without re-encoding or burn subtitles directly into the video frames.",
            "BadgeBlue",
        )

        grid = QGridLayout()
        grid.setSpacing(16)
        layout.addLayout(grid)

        files_card = Card("Files")
        files_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.video_media_picker = FilePicker("Video file")
        self.video_srt_picker = FilePicker("SRT file")
        self.video_output_picker = FilePicker("Save video as", "Save as...")
        self.video_media_picker.button.clicked.connect(self.select_video_subtitle_media_file)
        self.video_srt_picker.button.clicked.connect(self.select_video_subtitle_srt_file)
        self.video_output_picker.button.clicked.connect(self.select_video_subtitle_output_file)
        self.video_media_picker.edit.textChanged.connect(lambda: self.update_video_subtitle_output(force=False))
        files_card.content_layout.addWidget(self.video_media_picker)
        files_card.content_layout.addWidget(self.video_srt_picker)
        files_card.content_layout.addWidget(self.video_output_picker)

        settings_card = Card("Mode and quality")
        settings_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.video_embed_mode_button = QPushButton(VIDEO_SUBTITLE_EMBED_LABEL)
        self.video_burn_mode_button = QPushButton(VIDEO_SUBTITLE_BURN_LABEL)
        for button in (self.video_embed_mode_button, self.video_burn_mode_button):
            button.setObjectName("SegmentButton")
            button.setCheckable(True)
            button.setMinimumHeight(36)
        self.video_embed_mode_button.clicked.connect(
            lambda _checked=False: self.set_video_subtitle_mode(VIDEO_SUBTITLE_EMBED_LABEL)
        )
        self.video_burn_mode_button.clicked.connect(
            lambda _checked=False: self.set_video_subtitle_mode(VIDEO_SUBTITLE_BURN_LABEL)
        )
        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_row.setSpacing(8)
        mode_row.addWidget(self.video_embed_mode_button)
        mode_row.addWidget(self.video_burn_mode_button)
        mode_row.addStretch(1)
        self.video_mode_note = QLabel(VIDEO_SUBTITLE_MODE_DESCRIPTIONS[VIDEO_SUBTITLE_EMBED_LABEL])
        self.video_mode_note.setObjectName("Muted")
        self.video_mode_note.setWordWrap(True)
        self.video_quality_label = QLabel("Burn-in quality")
        self.video_quality_combo = QComboBox()
        self.video_quality_combo.addItems(BURN_QUALITY_LABELS)
        self.video_quality_combo.setCurrentText(BURN_QUALITY_AUTO_LABEL)
        self.video_quality_combo.currentTextChanged.connect(self.update_video_quality_description)
        self.video_crf_note = QLabel(
            "CRF is constant quality: lower number means higher quality and a larger output file."
        )
        self.video_crf_note.setObjectName("Muted")
        self.video_crf_note.setWordWrap(True)
        self.video_quality_description = QLabel(BURN_QUALITY_DESCRIPTIONS[BURN_QUALITY_AUTO_LABEL])
        self.video_quality_description.setObjectName("Muted")
        self.video_quality_description.setWordWrap(True)
        self.video_style_panel = QWidget()
        self.video_style_panel.setObjectName("InlinePanel")
        style_layout = QGridLayout(self.video_style_panel)
        style_layout.setContentsMargins(0, 4, 0, 0)
        style_layout.setHorizontalSpacing(10)
        style_layout.setVerticalSpacing(8)
        self.video_font_size_spin = QSpinBox()
        self.video_font_size_spin.setRange(14, 72)
        self.video_font_size_spin.setValue(28)
        self.video_outline_spin = QSpinBox()
        self.video_outline_spin.setRange(0, 8)
        self.video_outline_spin.setValue(2)
        self.video_margin_spin = QSpinBox()
        self.video_margin_spin.setRange(0, 160)
        self.video_margin_spin.setValue(36)
        self.video_position_combo = QComboBox()
        self.video_position_combo.addItems(list(VIDEO_SUBTITLE_POSITION_LABELS))
        for spinbox in (self.video_font_size_spin, self.video_outline_spin, self.video_margin_spin):
            spinbox.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            spinbox.setAlignment(Qt.AlignmentFlag.AlignCenter)
            spinbox.setFixedWidth(82)
        self.video_position_combo.setMinimumWidth(180)
        self.video_font_size_spin.valueChanged.connect(lambda _value: self.save_user_settings())
        self.video_outline_spin.valueChanged.connect(lambda _value: self.save_user_settings())
        self.video_margin_spin.valueChanged.connect(lambda _value: self.save_user_settings())
        self.video_position_combo.currentTextChanged.connect(lambda _text: self.save_user_settings())
        style_layout.addWidget(QLabel("Font size"), 0, 0)
        style_layout.addWidget(self.video_font_size_spin, 0, 1)
        style_layout.addWidget(QLabel("Outline"), 0, 2)
        style_layout.addWidget(self.video_outline_spin, 0, 3)
        style_layout.addWidget(QLabel("Position"), 1, 0)
        style_layout.addWidget(self.video_position_combo, 1, 1)
        style_layout.addWidget(QLabel("Vertical margin"), 1, 2)
        style_layout.addWidget(self.video_margin_spin, 1, 3)
        settings_card.content_layout.addWidget(QLabel("Mode"))
        settings_card.content_layout.addLayout(mode_row)
        settings_card.content_layout.addWidget(self.video_mode_note)
        settings_card.content_layout.addWidget(self.video_quality_label)
        settings_card.content_layout.addWidget(self.video_quality_combo)
        settings_card.content_layout.addWidget(self.video_crf_note)
        settings_card.content_layout.addWidget(self.video_quality_description)
        settings_card.content_layout.addWidget(self.video_style_panel)

        grid.addWidget(files_card, 0, 0, Qt.AlignmentFlag.AlignTop)
        grid.addWidget(settings_card, 0, 1, Qt.AlignmentFlag.AlignTop)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        action_card = Card()
        action_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        self.video_start_button = QPushButton("Create video")
        self.video_start_button.setObjectName("PrimaryButton")
        self.video_preview_button = QPushButton("Preview style")
        self.video_cancel_button = QPushButton("Cancel")
        self.video_open_output_button = QPushButton("Open output")
        self.video_open_folder_button = QPushButton("Open folder")
        self.video_details_button = QPushButton("Show details")
        self.video_start_button.clicked.connect(self.start_video_subtitle_from_page)
        self.video_preview_button.clicked.connect(self.preview_video_subtitle_style)
        self.video_cancel_button.clicked.connect(self.cancel_video_subtitle_job)
        self.video_open_output_button.clicked.connect(self.open_video_subtitle_output)
        self.video_open_folder_button.clicked.connect(self.open_video_subtitle_output_folder)
        self.video_details_button.clicked.connect(self.toggle_video_details)
        actions.addWidget(self.video_start_button)
        actions.addWidget(self.video_preview_button)
        actions.addWidget(self.video_cancel_button)
        actions.addStretch(1)
        actions.addWidget(self.video_open_output_button)
        actions.addWidget(self.video_open_folder_button)
        actions.addWidget(self.video_details_button)
        action_card.content_layout.addLayout(actions)
        self.video_progress = QProgressBar()
        self.video_progress.setRange(0, 0)
        self.video_progress.hide()
        self.video_status = QLabel("Ready.")
        self.video_status.setObjectName("StatusText")
        self.video_log = QPlainTextEdit()
        self.video_log.setObjectName("LogBox")
        self.video_log.setReadOnly(True)
        self.video_log.setMinimumHeight(160)
        self.video_log.hide()
        action_card.content_layout.addWidget(self.video_progress)
        action_card.content_layout.addWidget(self.video_status)
        action_card.content_layout.addWidget(self.video_log)
        layout.addWidget(action_card)
        layout.addStretch(1)

        self.video_subtitle_mode_changed()
        self.update_video_subtitle_button_state()
        return page

    def build_video_cleanup_page(self):
        page, layout = self.page_container()
        self.page_header(
            layout,
            "CLEANUP",
            "Video Cleanup",
            "Detect isolated black-frame glitches and clean selected frames before export or subtitling.",
            "BadgeGreen",
        )

        grid = QGridLayout()
        grid.setSpacing(16)
        layout.addLayout(grid)

        files_card = Card("Files")
        files_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.cleanup_media_picker = FilePicker("Video file")
        self.cleanup_output_picker = FilePicker("Save repaired video as", "Save as...")
        self.cleanup_media_picker.button.clicked.connect(self.select_cleanup_media_file)
        self.cleanup_output_picker.button.clicked.connect(self.select_cleanup_output_file)
        self.cleanup_media_picker.edit.textChanged.connect(self.cleanup_media_changed)
        files_card.content_layout.addWidget(self.cleanup_media_picker)

        settings_card = Card("Detection")
        settings_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.cleanup_rule_note = QLabel(
            "Only isolated one-frame black glitches are repairable. "
            "Longer runs, including black heads/tails, are reported and left untouched."
        )
        self.cleanup_rule_note.setObjectName("Muted")
        self.cleanup_rule_note.setWordWrap(True)
        self.cleanup_repair_options = QWidget()
        repair_options_layout = QVBoxLayout(self.cleanup_repair_options)
        repair_options_layout.setContentsMargins(0, 8, 0, 0)
        repair_options_layout.setSpacing(8)
        self.cleanup_method_label = QLabel("Clean method")
        self.cleanup_method_combo = QComboBox()
        self.cleanup_method_combo.addItems(VIDEO_CLEANUP_METHOD_LABELS)
        self.cleanup_method_combo.setCurrentText(VIDEO_CLEANUP_FREEZE_LABEL)
        self.cleanup_method_combo.currentTextChanged.connect(self.update_cleanup_method_description)
        self.cleanup_method_description = QLabel(VIDEO_CLEANUP_METHOD_DESCRIPTIONS[VIDEO_CLEANUP_FREEZE_LABEL])
        self.cleanup_method_description.setObjectName("Muted")
        self.cleanup_method_description.setWordWrap(True)
        self.cleanup_quality_label = QLabel("Output quality")
        self.cleanup_quality_combo = QComboBox()
        self.cleanup_quality_combo.addItems(VIDEO_CLEANUP_QUALITY_LABELS)
        self.cleanup_quality_combo.setCurrentText(BURN_QUALITY_AUTO_LABEL)
        self.cleanup_quality_combo.currentTextChanged.connect(self.update_cleanup_quality_description)
        self.cleanup_quality_description = QLabel(VIDEO_CLEANUP_QUALITY_DESCRIPTIONS[BURN_QUALITY_AUTO_LABEL])
        self.cleanup_quality_description.setObjectName("Muted")
        self.cleanup_quality_description.setWordWrap(True)
        settings_card.content_layout.addWidget(self.cleanup_rule_note)
        repair_options_layout.addWidget(self.cleanup_output_picker)
        repair_options_layout.addWidget(self.cleanup_method_label)
        repair_options_layout.addWidget(self.cleanup_method_combo)
        repair_options_layout.addWidget(self.cleanup_method_description)
        repair_options_layout.addWidget(self.cleanup_quality_label)
        repair_options_layout.addWidget(self.cleanup_quality_combo)
        repair_options_layout.addWidget(self.cleanup_quality_description)
        settings_card.content_layout.addWidget(self.cleanup_repair_options)

        grid.addWidget(files_card, 0, 0)
        grid.addWidget(settings_card, 0, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        results_card = Card("Results")
        self.cleanup_results = QListWidget()
        self.cleanup_results.setMinimumHeight(160)
        results_card.content_layout.addWidget(self.cleanup_results)
        layout.addWidget(results_card)

        action_card = Card()
        action_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        self.cleanup_start_button = QPushButton("Detect black frames")
        self.cleanup_start_button.setObjectName("PrimaryButton")
        self.cleanup_repair_button = QPushButton("Clean selected frames")
        self.cleanup_repair_button.setObjectName("PrimaryButton")
        self.cleanup_cancel_button = QPushButton("Cancel")
        self.cleanup_open_output_button = QPushButton("Open output")
        self.cleanup_open_folder_button = QPushButton("Open folder")
        self.cleanup_details_button = QPushButton("Show details")
        self.cleanup_start_button.clicked.connect(self.start_video_cleanup_from_page)
        self.cleanup_repair_button.clicked.connect(self.start_video_cleanup_repair_from_page)
        self.cleanup_cancel_button.clicked.connect(self.cancel_video_cleanup_job)
        self.cleanup_open_output_button.clicked.connect(self.open_cleanup_output)
        self.cleanup_open_folder_button.clicked.connect(self.open_cleanup_output_folder)
        self.cleanup_details_button.clicked.connect(self.toggle_cleanup_details)
        actions.addWidget(self.cleanup_start_button)
        actions.addWidget(self.cleanup_repair_button)
        actions.addWidget(self.cleanup_cancel_button)
        actions.addStretch(1)
        actions.addWidget(self.cleanup_open_output_button)
        actions.addWidget(self.cleanup_open_folder_button)
        actions.addWidget(self.cleanup_details_button)
        action_card.content_layout.addLayout(actions)
        self.cleanup_progress = QProgressBar()
        self.cleanup_progress.setRange(0, 0)
        self.cleanup_progress.hide()
        self.cleanup_status = QLabel("Ready.")
        self.cleanup_status.setObjectName("StatusText")
        self.cleanup_log = QPlainTextEdit()
        self.cleanup_log.setObjectName("LogBox")
        self.cleanup_log.setReadOnly(True)
        self.cleanup_log.setMinimumHeight(160)
        self.cleanup_log.hide()
        action_card.content_layout.addWidget(self.cleanup_progress)
        action_card.content_layout.addWidget(self.cleanup_status)
        action_card.content_layout.addWidget(self.cleanup_log)
        layout.addWidget(action_card)
        layout.addStretch(1)

        self.cleanup_repair_options.hide()
        self.cleanup_repair_button.hide()
        self.update_video_cleanup_button_state()
        return page

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
        ready = (
            not self.is_loading_voices
            and not self.is_detecting_language
            and not self.is_converting
            and not self.is_stt_running
            and not self.is_video_running
            and not self.is_cleanup_running
            and not self.input_file_error_message
            and bool(self.current_voice_map)
        )
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
