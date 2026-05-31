import queue
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
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
    QSlider,
    QSpinBox,
    QStackedWidget,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from voicebridge.app_paths import resource_path, stt_alignment_model_ready
from voicebridge.app_settings import load_app_settings, save_app_settings
from voicebridge.constants import (
    APP_ATTRIBUTION,
    APP_ICON,
    APP_NAME,
    BURN_QUALITY_LABELS,
    RATE_CHOICES,
    STT_ALIGNMENT_READY_LANGUAGES,
    STT_DEVICE_LABEL_BY_KEY,
    STT_LANGUAGE_AUTO_LABEL,
    STT_LANGUAGE_CODES,
    STT_LANGUAGE_LEGACY_LABELS,
    STT_MODE_LABELS,
    TTS_ENGINE_LABEL_BY_KEY,
    TTS_SPLIT_LINES,
    TTS_SPLIT_PARAGRAPHS,
    UI_QUEUE_POLL_MS,
    VIDEO_CLEANUP_METHOD_LABELS,
    VIDEO_CLEANUP_QUALITY_LABELS,
    VIDEO_SUBTITLE_POSITION_LABELS,
)
from voicebridge.languages import LANGUAGE_NAMES
from voicebridge.media_tools import (
    BlackFrame,
)
from voicebridge.models import JobHistoryEntry, TtsSegment
from voicebridge.pages.audio_cleanup import AudioCleanupWorkflowMixin
from voicebridge.pages.builders import PageBuilderMixin
from voicebridge.pages.cleanup import VideoCleanupWorkflowMixin
from voicebridge.pages.stt import SttWorkflowMixin
from voicebridge.pages.subtitles import SubtitlesWorkflowMixin
from voicebridge.pages.tts import TtsWorkflowMixin
from voicebridge.pages.voice_profiles import VoiceProfilesWorkflowMixin
from voicebridge.ui.styles import apply_app_style
from voicebridge.ui.waveform import AudioWaveformWidget
from voicebridge.ui.widgets import FilePicker
from voicebridge.voice_profiles import VoiceProfile
from voicebridge.voices import (
    load_preferred_voice_short_names,
)


class VoiceBridgeQt(
    AudioCleanupWorkflowMixin,
    VideoCleanupWorkflowMixin,
    SubtitlesWorkflowMixin,
    SttWorkflowMixin,
    TtsWorkflowMixin,
    VoiceProfilesWorkflowMixin,
    PageBuilderMixin,
    QMainWindow,
):
    stack: QStackedWidget
    nav_home: QPushButton
    nav_tts: QPushButton
    nav_profiles: QPushButton
    nav_stt: QPushButton
    nav_video: QPushButton
    nav_audio_cleanup: QPushButton
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
    tts_engine_combo: QComboBox
    edge_voice_panel: QWidget
    local_voice_panel: QWidget
    all_voices: list[dict[str, Any]]
    current_voice_candidates: list[dict[str, Any]]
    current_voice_map: dict[str, str]
    preferred_voice_short_names: set[str]
    voice_status: QLabel
    voice_combo: QComboBox
    voice_search: QLineEdit
    voice_preferred: QCheckBox
    local_voice_profile_combo: QComboBox
    local_voice_profile_status: QLabel
    tts_local_device_combo: QComboBox
    local_tts_model_status: QLabel
    local_tts_model_status_box: QFrame
    tts_download_model_button: QPushButton
    rate_combo: QComboBox
    tts_generate_button: QPushButton
    tts_cancel_button: QPushButton
    tts_open_output_button: QPushButton
    tts_open_folder_button: QPushButton
    tts_audio_cleanup_button: QPushButton
    tts_progress: QProgressBar
    tts_status: QLabel
    tts_process: Any
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
    voice_profiles_list: QListWidget
    profile_new_button: QPushButton
    profile_delete_button: QPushButton
    profile_name_edit: QLineEdit
    profile_type_combo: QComboBox
    profile_language_combo: QComboBox
    profile_reference_picker: FilePicker
    profile_microphone_combo: QComboBox
    profile_record_button: QPushButton
    profile_play_button: QPushButton
    profile_record_status_label: QLabel
    profile_consent_check: QCheckBox
    profile_notes_edit: QPlainTextEdit
    profile_status_label: QLabel
    profile_save_button: QPushButton
    profile_open_reference_button: QPushButton
    profile_open_folder_button: QPushButton
    profile_audio_output: Any
    profile_media_player: Any

    stt_media_picker: FilePicker
    stt_text_picker: FilePicker
    stt_output_picker: FilePicker
    stt_mode_combo: QComboBox
    stt_language_combo: QComboBox
    stt_device_combo: QComboBox
    stt_preflight_box: QFrame
    stt_preflight_label: QLabel
    stt_download_model_button: QPushButton
    stt_generate_button: QPushButton
    stt_cancel_button: QPushButton
    stt_open_output_button: QPushButton
    stt_open_folder_button: QPushButton
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

    audio_cleanup_input_picker: FilePicker
    audio_cleanup_output_picker: FilePicker
    audio_cleanup_duration_label: QLabel
    audio_cleanup_action_combo: QComboBox
    audio_cleanup_action_description: QLabel
    audio_cleanup_start_spin: QDoubleSpinBox
    audio_cleanup_end_spin: QDoubleSpinBox
    audio_cleanup_selection_note: QLabel
    audio_cleanup_waveform: AudioWaveformWidget
    audio_cleanup_waveform_status: QLabel
    audio_cleanup_waveform_zoom_combo: QComboBox
    audio_cleanup_waveform_scroll: QSlider
    audio_cleanup_start_button: QPushButton
    audio_cleanup_cancel_button: QPushButton
    audio_cleanup_play_selection_button: QPushButton
    audio_cleanup_play_output_button: QPushButton
    audio_cleanup_open_output_button: QPushButton
    audio_cleanup_open_folder_button: QPushButton
    audio_cleanup_details_button: QPushButton
    audio_cleanup_progress: QProgressBar
    audio_cleanup_status: QLabel
    audio_cleanup_log: QPlainTextEdit
    audio_cleanup_process: Any
    audio_cleanup_audio_output: Any
    audio_cleanup_media_devices: Any
    audio_cleanup_media_player: Any
    audio_cleanup_preview_end_ms: int | None
    audio_cleanup_preview_tracks_waveform: bool
    audio_cleanup_preview_timer: QTimer

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
    tts_local_preset_combo: QComboBox
    selected_tts_segment_index: int | None
    app_settings: dict[str, Any]
    is_restoring_settings: bool
    saved_tts_voice_short_name: str
    saved_tts_voice_profile_id: str
    job_history: list[JobHistoryEntry]
    voice_profiles: list[VoiceProfile]
    selected_voice_profile_id: str
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
        self.saved_tts_voice_profile_id = self.setting_str(self.setting_section("tts").get("voice_profile_id"))
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
        self.tts_process = None
        self.tts_last_output_path = ""
        self.last_auto_save_path = ""
        self.tts_segments: list[TtsSegment] = []
        self.selected_tts_segment_index = None
        self.status_tiles: dict[str, QLabel] = {}
        self.load_voice_profile_store()
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
        self.stt_cuda_available = False
        self.stt_runtime_detail = "Checking STT runtime."
        self.preferred_stt_device_key = self.setting_str(self.setting_section("stt").get("device"), "auto")
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
        self.is_audio_cleanup_running = False
        self.audio_cleanup_cancel_requested = False
        self.audio_cleanup_process = None
        self.audio_cleanup_last_output_path = ""
        self.audio_cleanup_last_auto_output_path = ""
        self.audio_cleanup_duration_seconds = 0.0
        self.audio_cleanup_log_lines = []
        self.audio_cleanup_waveform_generation = 0
        self.audio_cleanup_waveform_syncing = False
        self.audio_cleanup_waveform_view_syncing = False
        self.audio_cleanup_preview_end_ms = None
        self.audio_cleanup_preview_tracks_waveform = False
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
        self.nav_profiles = self.nav_button("Voice Profiles", lambda: self.show_page(2))
        self.nav_stt = self.nav_button("Transcription", lambda: self.show_page(3))
        self.nav_video = self.nav_button("Subtitles", lambda: self.show_page(4))
        self.nav_audio_cleanup = self.nav_button("Audio Cleanup", lambda: self.show_page(5))
        self.nav_cleanup = self.nav_button("Video Cleanup", lambda: self.show_page(6))
        side_layout.addWidget(self.nav_home)
        side_layout.addWidget(self.nav_tts)
        side_layout.addWidget(self.nav_profiles)
        side_layout.addWidget(self.nav_stt)
        side_layout.addWidget(self.nav_video)
        side_layout.addWidget(self.nav_audio_cleanup)
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
        for index, key in enumerate(("TTS", "LOCAL", "STT", "FFMPEG", "DOC", "OCR", "CPU")):
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
        self.stack.addWidget(self.build_voice_profiles_page())
        self.stack.addWidget(self.build_stt_page())
        self.stack.addWidget(self.build_video_subtitle_page())
        self.stack.addWidget(self.build_audio_cleanup_page())
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
            self.set_combo_text(self.rate_combo, tts_settings.get("rate"), RATE_CHOICES)
            tts_engine = self.setting_str(tts_settings.get("engine"), "edge")
            if tts_engine not in TTS_ENGINE_LABEL_BY_KEY:
                tts_engine = "edge"
            self.set_tts_engine_key(tts_engine)
            local_device = self.setting_str(tts_settings.get("local_device"), "auto")
            if local_device not in STT_DEVICE_LABEL_BY_KEY:
                local_device = "auto"
            self.set_tts_local_device_key(local_device)
            self.set_tts_local_preset_key(tts_settings.get("local_preset"))
            self.saved_tts_voice_profile_id = self.setting_str(tts_settings.get("voice_profile_id"))
            self.refresh_local_voice_profile_combo(self.saved_tts_voice_profile_id)
            self.set_combo_text(
                self.tts_split_combo,
                tts_settings.get("split_mode"),
                [TTS_SPLIT_PARAGRAPHS, TTS_SPLIT_LINES],
            )
            tab_index = self.safe_int(tts_settings.get("tab_index"), 0, 0, 1)
            self.set_tts_mode(tab_index)

            stt_settings = self.setting_section("stt")
            self.set_combo_text(self.stt_mode_combo, stt_settings.get("mode_label"), list(STT_MODE_LABELS))
            self.restore_stt_language_selection(stt_settings)
            self.preferred_stt_device_key = self.setting_str(stt_settings.get("device"), "auto")
            self.set_stt_device_key(self.preferred_stt_device_key)

            video_settings = self.setting_section("video_subtitles")
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

            audio_cleanup_settings = self.setting_section("audio_cleanup")
            self.set_combo_text(self.audio_cleanup_action_combo, audio_cleanup_settings.get("action_label"))

            cleanup_settings = self.setting_section("video_cleanup")
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
        self.refresh_audio_cleanup_input_info()
        self.audio_cleanup_action_changed(self.audio_cleanup_action_combo.currentText())
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
            selected_profile = self.selected_tts_voice_profile()
            if selected_profile:
                self.saved_tts_voice_profile_id = selected_profile["id"]
            settings["tts"] = {
                "engine": self.tts_engine_key(),
                "voice_short_name": self.saved_tts_voice_short_name,
                "voice_profile_id": self.saved_tts_voice_profile_id,
                "local_device": self.tts_local_device_key(),
                "local_preset": self.tts_local_preset_key(),
                "rate": self.rate_combo.currentText(),
                "tab_index": self.tts_mode_index(),
                "split_mode": self.tts_split_combo.currentText(),
            }

        if hasattr(self, "stt_mode_combo"):
            settings["stt"] = {
                "mode_label": self.stt_mode_combo.currentText(),
                "language_label": self.stt_language_combo.currentText(),
                "language_code": self.stt_language_key(),
                "device": self.stt_device_key(),
            }

        if hasattr(self, "video_embed_mode_button"):
            settings["video_subtitles"] = {
                "mode_label": self.video_subtitle_mode_label(),
                "quality_label": self.video_quality_combo.currentText(),
                "font_size": self.video_font_size_spin.value(),
                "outline": self.video_outline_spin.value(),
                "margin_v": self.video_margin_spin.value(),
                "position_label": self.video_position_combo.currentText(),
            }

        if hasattr(self, "audio_cleanup_action_combo"):
            settings["audio_cleanup"] = {
                "action_label": self.audio_cleanup_action_combo.currentText(),
            }

        if hasattr(self, "cleanup_quality_combo"):
            settings["video_cleanup"] = {
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
        self.show_message_box(title, message, QMessageBox.Icon.Critical)

    def show_info(self, title, message):
        self.show_message_box(title, message, QMessageBox.Icon.Information)

    def ask_question(
        self,
        title,
        message,
        default_yes=False,
    ):
        default_button = QMessageBox.StandardButton.Yes if default_yes else QMessageBox.StandardButton.No
        return self.show_message_box(
            title,
            message,
            QMessageBox.Icon.Question,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            default_button,
        ) == QMessageBox.StandardButton.Yes

    def show_message_box(
        self,
        title,
        message,
        icon,
        buttons=QMessageBox.StandardButton.Ok,
        default_button=QMessageBox.StandardButton.Ok,
    ):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setModal(True)
        dialog.setMinimumWidth(560)
        dialog.setMaximumWidth(680)
        dialog.setStyleSheet(
            """
            QDialog { background: #f8fafc; }
            QLabel { background: transparent; color: #111827; }
            QPushButton {
                min-width: 88px;
                min-height: 32px;
                padding: 7px 14px;
                border-radius: 6px;
                border: 1px solid #cfd6e2;
                background: #ffffff;
            }
            QPushButton:hover { background: #f1f5fb; border-color: #aeb9c8; }
            """
        )

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(18)

        content_row = QHBoxLayout()
        content_row.setSpacing(16)
        icon_label = QLabel()
        icon_label.setFixedSize(40, 40)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        standard_icon = self.message_box_standard_icon(icon)
        if standard_icon is not None:
            icon_label.setPixmap(self.style().standardIcon(standard_icon).pixmap(32, 32))
        message_label = QLabel(str(message))
        message_label.setTextFormat(Qt.TextFormat.PlainText)
        message_label.setWordWrap(True)
        message_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        message_label.setMinimumWidth(410)
        message_label.setMaximumWidth(520)
        content_row.addWidget(icon_label)
        content_row.addWidget(message_label, 1)
        layout.addLayout(content_row)

        result = {"button": QMessageBox.StandardButton.No}
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        for standard_button in self.message_box_button_order(buttons):
            button = QPushButton(self.message_box_button_text(standard_button))
            button.setDefault(standard_button == default_button)
            button.clicked.connect(
                lambda _checked=False, clicked_button=standard_button: self.close_message_box(
                    dialog,
                    result,
                    clicked_button,
                )
            )
            button_row.addWidget(button)
        layout.addLayout(button_row)

        dialog.exec()
        return result["button"]

    @staticmethod
    def close_message_box(dialog, result, button):
        result["button"] = button
        dialog.accept()

    @staticmethod
    def message_box_button_order(buttons):
        order = (
            QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Ok,
        )
        return [button for button in order if buttons & button]

    @staticmethod
    def message_box_button_text(button):
        if button == QMessageBox.StandardButton.Yes:
            return "Yes"
        if button == QMessageBox.StandardButton.No:
            return "No"
        return "OK"

    @staticmethod
    def message_box_standard_icon(icon):
        if icon == QMessageBox.Icon.Critical:
            return QStyle.StandardPixmap.SP_MessageBoxCritical
        if icon == QMessageBox.Icon.Warning:
            return QStyle.StandardPixmap.SP_MessageBoxWarning
        if icon == QMessageBox.Icon.Question:
            return QStyle.StandardPixmap.SP_MessageBoxQuestion
        if icon == QMessageBox.Icon.Information:
            return QStyle.StandardPixmap.SP_MessageBoxInformation
        return None

    def stt_alignment_language_ready(self, language_code):
        return (
            language_code == "auto"
            or (language_code in STT_ALIGNMENT_READY_LANGUAGES and stt_alignment_model_ready(language_code))
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
            elif code in STT_ALIGNMENT_READY_LANGUAGES and stt_alignment_model_ready(code):
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

    def update_audio_cleanup_progress_percent(self, percent):
        self.show_percent_progress(self.audio_cleanup_progress, percent)

    def update_cleanup_progress_percent(self, percent):
        self.show_percent_progress(self.cleanup_progress, percent)

    def set_video_progress_indeterminate(self):
        self.show_indeterminate_progress(self.video_progress)

    def set_cleanup_progress_indeterminate(self):
        self.show_indeterminate_progress(self.cleanup_progress)
