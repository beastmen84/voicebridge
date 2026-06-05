import queue
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractButton,
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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from voicebridge.app_paths import external_base_dir, resource_path, source_base_dir, stt_alignment_model_ready
from voicebridge.app_settings import cleanup_app_config_on_startup, load_app_settings, save_app_settings
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
    VIDEO_CLEANUP_QUALITY_LABELS,
    VIDEO_SUBTITLE_BOX_COLOR_LABELS,
    VIDEO_SUBTITLE_OUTLINE_COLOR_LABELS,
    VIDEO_SUBTITLE_POSITION_LABELS,
    VIDEO_SUBTITLE_TEXT_COLOR_LABELS,
)
from voicebridge.i18n import UI_LANGUAGES, normalize_ui_language, translate_static_ui_text, translate_ui
from voicebridge.languages import LANGUAGE_NAMES
from voicebridge.media_tools import (
    BlackFrame,
)
from voicebridge.modeling_datasets import ModelingDataset
from voicebridge.models import JobHistoryEntry, TtsSegment
from voicebridge.pages.audio_cleanup import AudioCleanupWorkflowMixin
from voicebridge.pages.builders import PageBuilderMixin
from voicebridge.pages.cleanup import VideoCleanupWorkflowMixin
from voicebridge.pages.local_voices import LocalVoicesWorkflowMixin
from voicebridge.pages.modeling_datasets import ModelingDatasetsWorkflowMixin
from voicebridge.pages.stt import SttWorkflowMixin
from voicebridge.pages.subtitles import SubtitlesWorkflowMixin
from voicebridge.pages.tts import TtsWorkflowMixin
from voicebridge.pages.voice_modeling import VoiceModelingWorkflowMixin
from voicebridge.pages.voice_profiles import VoiceProfilesWorkflowMixin
from voicebridge.pages.voice_training import VoiceTrainingWorkflowMixin
from voicebridge.ui.helpers import open_path
from voicebridge.ui.styles import apply_app_style
from voicebridge.ui.waveform import AudioWaveformWidget
from voicebridge.ui.widgets import FilePicker
from voicebridge.voice_modeling import VoiceModelingExportInfo
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
    VoiceModelingWorkflowMixin,
    ModelingDatasetsWorkflowMixin,
    VoiceProfilesWorkflowMixin,
    VoiceTrainingWorkflowMixin,
    LocalVoicesWorkflowMixin,
    PageBuilderMixin,
    QMainWindow,
):
    I18N_SOURCE_TEXT_PROPERTY = "voicebridge_i18n_source_text"
    I18N_SOURCE_PLACEHOLDER_PROPERTY = "voicebridge_i18n_source_placeholder"
    I18N_SOURCE_TOOLTIP_PROPERTY = "voicebridge_i18n_source_tooltip"
    stack: QStackedWidget
    nav_home: QPushButton
    nav_tts: QPushButton
    nav_local_voices: QPushButton
    nav_stt: QPushButton
    nav_video: QPushButton
    nav_audio_cleanup: QPushButton
    nav_cleanup: QPushButton
    app_subtitle_label: QLabel
    main_tools_label: QLabel
    advanced_tools_label: QLabel
    support_tools_label: QLabel
    ui_language_label: QLabel
    ui_language_combo: QComboBox
    status_section_label: QLabel
    local_voice_tabs: QTabWidget
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
    profile_notes_edit: QPlainTextEdit
    profile_status_label: QLabel
    profile_save_button: QPushButton
    profile_open_reference_button: QPushButton
    profile_open_folder_button: QPushButton
    profile_audio_output: Any
    profile_media_player: Any

    modeling_datasets: list[ModelingDataset]
    selected_modeling_dataset_id: str
    selected_modeling_clip_id: str
    modeling_datasets_list: QListWidget
    modeling_clips_list: QListWidget
    modeling_clip_text_edit: QPlainTextEdit
    modeling_clip_details: QPlainTextEdit
    modeling_dataset_status: QLabel
    modeling_refresh_button: QPushButton
    modeling_open_dataset_folder_button: QPushButton
    modeling_load_text_button: QPushButton
    modeling_record_text_button: QPushButton
    modeling_record_free_button: QPushButton
    modeling_save_text_button: QPushButton
    modeling_play_clip_button: QPushButton
    modeling_open_clip_button: QPushButton
    modeling_retry_clip_button: QPushButton
    modeling_verify_clip_button: QPushButton
    modeling_toggle_export_clip_button: QPushButton
    modeling_delete_clip_button: QPushButton
    modeling_transcribe_clip_button: QPushButton
    modeling_clip_audio_output: Any
    modeling_clip_media_player: Any
    modeling_verification_queue: list[dict[str, str]]
    modeling_verification_running: bool
    modeling_verification_queued_clip_ids: set[str]

    voice_modeling_export_info: VoiceModelingExportInfo | None
    voice_modeling_export_combo: QComboBox
    voice_modeling_output_picker: FilePicker
    voice_modeling_resume_picker: FilePicker
    voice_modeling_dataset_info: QPlainTextEdit
    voice_modeling_status: QLabel
    voice_modeling_device_combo: QComboBox
    voice_modeling_epochs_spin: QSpinBox
    voice_modeling_batch_spin: QSpinBox
    voice_modeling_refresh_exports_button: QPushButton
    voice_modeling_browse_export_button: QPushButton
    voice_modeling_preflight_box: QFrame
    voice_modeling_preflight_label: QLabel
    voice_modeling_preflight_details_box: QPlainTextEdit
    voice_modeling_preflight_refresh_button: QPushButton
    voice_modeling_download_dvae_button: QPushButton
    voice_modeling_cancel_dvae_button: QPushButton
    voice_modeling_dvae_progress: QProgressBar
    voice_modeling_clear_resume_button: QPushButton
    voice_modeling_save_config_button: QPushButton
    voice_modeling_open_output_button: QPushButton
    voice_modeling_preflight_ok: bool
    voice_modeling_preflight_details: list[str]
    voice_modeling_auto_preflight_enabled: bool
    voice_modeling_dvae_download_running: bool
    voice_modeling_dvae_cancel_requested: bool
    voice_training_job_combo: QComboBox
    voice_training_refresh_jobs_button: QPushButton
    voice_training_prepare_button: QPushButton
    voice_training_dry_run_button: QPushButton
    voice_training_start_button: QPushButton
    voice_training_cancel_button: QPushButton
    voice_training_open_folder_button: QPushButton
    voice_training_progress: QProgressBar
    voice_training_job_status: QPlainTextEdit
    voice_training_running: bool
    voice_training_cancel_requested: bool
    voice_training_running_config_path: str
    voice_training_process: Any

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
    video_shadow_spin: QSpinBox
    video_margin_spin: QSpinBox
    video_position_combo: QComboBox
    video_text_color_combo: QComboBox
    video_outline_color_combo: QComboBox
    video_background_box_check: QCheckBox
    video_box_color_combo: QComboBox
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
    audio_cleanup_start_spin: QDoubleSpinBox
    audio_cleanup_end_spin: QDoubleSpinBox
    audio_cleanup_selection_note: QLabel
    audio_cleanup_cut_button: QPushButton
    audio_cleanup_silence_button: QPushButton
    audio_cleanup_fade_button: QPushButton
    audio_cleanup_changes: list[dict[str, Any]]
    audio_cleanup_changes_list: QListWidget
    audio_cleanup_changes_status: QLabel
    audio_cleanup_tts_timeline: dict[str, Any] | None
    audio_cleanup_tts_blocks_list: QListWidget
    audio_cleanup_tts_block_preview: QPlainTextEdit
    audio_cleanup_tts_block_status: QLabel
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
    audio_cleanup_preview_pending_start_ms: int | None
    audio_cleanup_preview_pending_timer_ms: int | None
    audio_cleanup_preview_tracks_waveform: bool
    audio_cleanup_preview_timer: QTimer

    cleanup_media_picker: FilePicker
    cleanup_output_picker: FilePicker
    cleanup_rule_note: QLabel
    cleanup_quality_label: QLabel
    cleanup_quality_combo: QComboBox
    cleanup_quality_description: QLabel
    cleanup_changes: list[dict[str, Any]]
    cleanup_changes_list: QListWidget
    cleanup_changes_status: QLabel
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
    cleanup_detected_frame_map: dict[int, BlackFrame]
    cleanup_marked_frame_numbers: set[int]

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
        cleanup_app_config_on_startup()
        self.app_settings = load_app_settings()
        self.ui_language = normalize_ui_language(self.app_settings.get("ui_language"))
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
        self.is_loading_voices = False
        self.edge_tts_auto_switched_to_local = False
        self.edge_tts_retry_timer: QTimer | None = None
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
        self.load_modeling_dataset_store()
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
        self.audio_cleanup_changes = []
        self.audio_cleanup_tts_timeline = None
        self.audio_cleanup_waveform_generation = 0
        self.audio_cleanup_waveform_syncing = False
        self.audio_cleanup_waveform_view_syncing = False
        self.audio_cleanup_preview_end_ms = None
        self.audio_cleanup_preview_pending_start_ms = None
        self.audio_cleanup_preview_pending_timer_ms = None
        self.audio_cleanup_preview_tracks_waveform = False
        self.is_cleanup_running = False
        self.cleanup_cancel_requested = False
        self.cleanup_process = None
        self.cleanup_last_output_path = ""
        self.cleanup_last_auto_output_path = ""
        self.cleanup_detected_frames: list[BlackFrame] = []
        self.cleanup_detected_media_path = ""
        self.cleanup_repairable_frame_map: dict[int, BlackFrame] = {}
        self.cleanup_detected_frame_map: dict[int, BlackFrame] = {}
        self.cleanup_suspicious_frames: list[dict[str, Any]] = []
        self.cleanup_suspicious_frame_map: dict[int, dict[str, Any]] = {}
        self.cleanup_marked_frame_numbers: set[int] = set()
        self.cleanup_changes = []
        self.cleanup_video_fps = 0.0
        self.cleanup_video_duration_seconds = 0.0
        self.cleanup_video_total_frames = 0
        self.cleanup_filmstrip_generation = 0
        self.cleanup_filmstrip_thumbnail_cache: dict[tuple[int, int], bytes] = {}
        self.cleanup_filmstrip_loading_keys: set[tuple[int, int]] = set()
        self.cleanup_filmstrip_load_sequence_frames: list[int] = []
        self.cleanup_filmstrip_loaded_frame_count = 0
        self.cleanup_filmstrip_process = None
        self.cleanup_log_lines = []
        self._stt_preflight_refreshing = False
        self._voice_modeling_preflight_refreshing = False
        self._voice_modeling_preflight_stale = False
        self._voice_modeling_preflight_snapshot = None
        self.voice_modeling_preflight_ok = False
        self.voice_modeling_preflight_details = []
        self.voice_modeling_auto_preflight_enabled = False
        self.voice_modeling_dvae_download_running = False
        self.voice_modeling_dvae_cancel_requested = False
        self.voice_training_running = False
        self.voice_training_cancel_requested = False
        self.voice_training_running_config_path = ""
        self.voice_training_process = None
        self.warning_callback: Callable[[], None] = self.no_warning_action

        self.apply_style()
        self.build_ui()
        self.start_voice_loading()
        self.refresh_stt_preflight_async()

    def apply_style(self):
        check_icon = resource_path(Path("images") / "checkbox_check.svg").as_posix()
        chevron_icon = resource_path(Path("images") / "chevron_down.svg").as_posix()
        apply_app_style(self, check_icon, chevron_icon)

    def ui_text(self, key: str, **kwargs: Any) -> str:
        return translate_ui(key, self.ui_language, **kwargs)

    def static_ui_text(self, text: str) -> str:
        return translate_static_ui_text(text, self.ui_language)

    def format_static_ui_text(self, text: str, **kwargs: Any) -> str:
        return self.static_ui_text(text).format(**kwargs)

    def translated_widget_text(self, widget: QWidget, current_text: str, property_name: str) -> str:
        source_text = widget.property(property_name)
        if not isinstance(source_text, str) or current_text not in {
            source_text,
            translate_static_ui_text(source_text, "it"),
        }:
            source_text = current_text
            widget.setProperty(property_name, source_text)
        return self.static_ui_text(source_text)

    def translate_widget_tooltip(self, widget: QWidget) -> None:
        tooltip = widget.toolTip()
        if not tooltip:
            return
        widget.setToolTip(self.translated_widget_text(widget, tooltip, self.I18N_SOURCE_TOOLTIP_PROPERTY))

    def apply_static_ui_translations(self) -> None:
        if not hasattr(self, "stack"):
            return
        for widget in self.findChildren(QWidget):
            if isinstance(widget, QAbstractButton):
                text = widget.text()
                if text:
                    widget.setText(self.translated_widget_text(widget, text, self.I18N_SOURCE_TEXT_PROPERTY))
                self.translate_widget_tooltip(widget)
            elif isinstance(widget, QLabel):
                text = widget.text()
                if text and widget.objectName() != "StatusTile":
                    widget.setText(self.translated_widget_text(widget, text, self.I18N_SOURCE_TEXT_PROPERTY))
                self.translate_widget_tooltip(widget)
            elif isinstance(widget, QLineEdit | QPlainTextEdit):
                placeholder = widget.placeholderText()
                if placeholder:
                    widget.setPlaceholderText(
                        self.translated_widget_text(
                            widget,
                            placeholder,
                            self.I18N_SOURCE_PLACEHOLDER_PROPERTY,
                        )
                    )
                self.translate_widget_tooltip(widget)

    def populate_ui_language_combo(self) -> None:
        self.ui_language_combo.blockSignals(True)
        try:
            self.ui_language_combo.clear()
            for language_code, label in UI_LANGUAGES.items():
                self.ui_language_combo.addItem(label, language_code)
                if language_code == self.ui_language:
                    self.ui_language_combo.setCurrentIndex(self.ui_language_combo.count() - 1)
        finally:
            self.ui_language_combo.blockSignals(False)

    def ui_language_changed(self) -> None:
        language_code = self.ui_language_combo.currentData(Qt.ItemDataRole.UserRole)
        self.ui_language = normalize_ui_language(language_code)
        self.retranslate_ui()
        self.save_user_settings()

    def retranslate_ui(self) -> None:
        if not hasattr(self, "nav_home"):
            return
        self.apply_static_ui_translations()
        self.app_subtitle_label.setText(self.ui_text("app.subtitle"))
        self.manual_button.setText(self.ui_text("sidebar.manual"))
        self.manual_button.setToolTip(self.ui_text("sidebar.manual.tooltip"))
        self.nav_home.setText(self.ui_text("nav.dashboard"))
        self.nav_tts.setText(self.ui_text("nav.tts"))
        self.nav_local_voices.setText(self.ui_text("nav.local_voices"))
        self.nav_stt.setText(self.ui_text("nav.transcription"))
        self.nav_video.setText(self.ui_text("nav.subtitles"))
        self.nav_audio_cleanup.setText(self.ui_text("nav.audio_cleanup"))
        self.nav_cleanup.setText(self.ui_text("nav.video_cleanup"))
        self.main_tools_label.setText(self.ui_text("sidebar.main_tools"))
        self.advanced_tools_label.setText(self.ui_text("sidebar.advanced_tools"))
        self.support_tools_label.setText(self.ui_text("sidebar.support_tools"))
        self.ui_language_label.setText(self.ui_text("sidebar.ui_language"))
        self.ui_language_combo.setToolTip(self.ui_text("sidebar.ui_language.tooltip"))
        self.status_section_label.setText(self.ui_text("sidebar.status"))
        self.retranslate_local_voices_page()
        self.retranslate_voice_profiles_page()
        self.retranslate_subtitles_page()
        self.retranslate_stt_page()
        self.retranslate_tts_page()
        self.retranslate_audio_cleanup_page()
        self.retranslate_video_cleanup_page()

    def open_user_manual(self) -> None:
        candidates = [
            external_base_dir() / "Manual.html",
            source_base_dir() / "Manual.html",
            external_base_dir() / "Manual.md",
            source_base_dir() / "Manual.md",
        ]
        for path in candidates:
            if path.is_file():
                open_path(path)
                return
        self.show_error(
            self.ui_text("manual.missing.title"),
            self.ui_text("manual.missing.message"),
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

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        title = QLabel(APP_NAME)
        title.setObjectName("AppTitle")
        self.manual_button = QPushButton(self.ui_text("sidebar.manual"))
        self.manual_button.setObjectName("SecondaryButton")
        self.manual_button.setToolTip(self.ui_text("sidebar.manual.tooltip"))
        self.manual_button.clicked.connect(self.open_user_manual)
        title_row.addWidget(title, 1)
        title_row.addWidget(self.manual_button)
        self.app_subtitle_label = QLabel(self.ui_text("app.subtitle"))
        self.app_subtitle_label.setObjectName("AppSubtitle")
        side_layout.addLayout(title_row)
        side_layout.addWidget(self.app_subtitle_label)
        side_layout.addSpacing(18)

        self.nav_home = self.nav_button(self.ui_text("nav.dashboard"), lambda: self.show_page(0))
        self.nav_tts = self.nav_button(self.ui_text("nav.tts"), lambda: self.show_page(1))
        self.nav_local_voices = self.nav_button(self.ui_text("nav.local_voices"), lambda: self.show_page(2))
        self.nav_stt = self.nav_button(self.ui_text("nav.transcription"), lambda: self.show_page(3))
        self.nav_video = self.nav_button(self.ui_text("nav.subtitles"), lambda: self.show_page(4))
        self.nav_audio_cleanup = self.nav_button(self.ui_text("nav.audio_cleanup"), lambda: self.show_page(5))
        self.nav_cleanup = self.nav_button(self.ui_text("nav.video_cleanup"), lambda: self.show_page(6))
        side_layout.addWidget(self.nav_home)

        self.main_tools_label = QLabel(self.ui_text("sidebar.main_tools"))
        self.main_tools_label.setObjectName("SidebarSection")
        side_layout.addSpacing(8)
        side_layout.addWidget(self.main_tools_label)
        side_layout.addWidget(self.nav_tts)
        side_layout.addWidget(self.nav_stt)

        self.advanced_tools_label = QLabel(self.ui_text("sidebar.advanced_tools"))
        self.advanced_tools_label.setObjectName("SidebarSection")
        side_layout.addSpacing(8)
        side_layout.addWidget(self.advanced_tools_label)
        side_layout.addWidget(self.nav_local_voices)

        self.support_tools_label = QLabel(self.ui_text("sidebar.support_tools"))
        self.support_tools_label.setObjectName("SidebarSection")
        side_layout.addSpacing(8)
        side_layout.addWidget(self.support_tools_label)
        side_layout.addWidget(self.nav_video)
        side_layout.addWidget(self.nav_audio_cleanup)
        side_layout.addWidget(self.nav_cleanup)
        side_layout.addStretch(1)

        self.ui_language_label = QLabel(self.ui_text("sidebar.ui_language"))
        self.ui_language_label.setObjectName("SidebarSection")
        self.ui_language_combo = QComboBox()
        self.ui_language_combo.setToolTip(self.ui_text("sidebar.ui_language.tooltip"))
        self.populate_ui_language_combo()
        self.ui_language_combo.currentIndexChanged.connect(lambda _index: self.ui_language_changed())
        side_layout.addWidget(self.ui_language_label)
        side_layout.addWidget(self.ui_language_combo)

        self.status_section_label = QLabel(self.ui_text("sidebar.status"))
        self.status_section_label.setObjectName("SidebarSection")
        side_layout.addWidget(self.status_section_label)

        status_panel = QWidget()
        status_panel.setObjectName("SidebarStatus")
        status_layout = QGridLayout(status_panel)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(6)
        self.status_tiles = {}
        for index, key in enumerate(("TTS", "LOCAL", "DVAE", "STT", "FFMPEG", "DOC", "OCR", "CPU")):
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
        self.stack.addWidget(self.build_local_voices_page())
        self.stack.addWidget(self.build_stt_page())
        self.stack.addWidget(self.build_video_subtitle_page())
        self.stack.addWidget(self.build_audio_cleanup_page())
        self.stack.addWidget(self.build_video_cleanup_page())
        root_layout.addWidget(sidebar)
        root_layout.addWidget(self.stack, 1)
        self.restore_user_settings()
        self.retranslate_ui()
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
    def combo_current_data(combo: QComboBox) -> str:
        value = combo.currentData(Qt.ItemDataRole.UserRole)
        return value if isinstance(value, str) and value else combo.currentText()

    @staticmethod
    def set_combo_data(combo: QComboBox, value: Any, allowed_values: list[str] | None = None) -> None:
        if not isinstance(value, str) or not value:
            return
        if allowed_values is not None and value not in allowed_values:
            return
        index = combo.findData(value, Qt.ItemDataRole.UserRole)
        if index >= 0:
            combo.setCurrentIndex(index)
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
            self.set_combo_data(
                self.tts_split_combo,
                tts_settings.get("split_mode"),
                [TTS_SPLIT_PARAGRAPHS, TTS_SPLIT_LINES],
            )
            tab_index = self.safe_int(tts_settings.get("tab_index"), 0, 0, 1)
            self.set_tts_mode(tab_index)

            stt_settings = self.setting_section("stt")
            self.set_combo_data(self.stt_mode_combo, stt_settings.get("mode_label"), list(STT_MODE_LABELS))
            self.restore_stt_language_selection(stt_settings)
            self.preferred_stt_device_key = self.setting_str(stt_settings.get("device"), "auto")
            self.set_stt_device_key(self.preferred_stt_device_key)

            video_settings = self.setting_section("video_subtitles")
            self.set_video_subtitle_mode(video_settings.get("mode_label"))
            self.set_combo_data(self.video_quality_combo, video_settings.get("quality_label"), BURN_QUALITY_LABELS)
            self.set_combo_data(
                self.video_position_combo,
                video_settings.get("position_label"),
                list(VIDEO_SUBTITLE_POSITION_LABELS),
            )
            self.video_font_size_spin.setValue(self.safe_int(video_settings.get("font_size"), 28, 14, 72))
            self.video_outline_spin.setValue(self.safe_int(video_settings.get("outline"), 2, 0, 8))
            self.video_shadow_spin.setValue(self.safe_int(video_settings.get("shadow"), 0, 0, 4))
            self.video_margin_spin.setValue(self.safe_int(video_settings.get("margin_v"), 36, 0, 160))
            self.set_combo_data(
                self.video_text_color_combo,
                video_settings.get("text_color_label"),
                VIDEO_SUBTITLE_TEXT_COLOR_LABELS,
            )
            self.set_combo_data(
                self.video_outline_color_combo,
                video_settings.get("outline_color_label"),
                VIDEO_SUBTITLE_OUTLINE_COLOR_LABELS,
            )
            self.video_background_box_check.setChecked(bool(video_settings.get("background_box", False)))
            self.set_combo_data(
                self.video_box_color_combo,
                video_settings.get("box_color_label"),
                VIDEO_SUBTITLE_BOX_COLOR_LABELS,
            )

            cleanup_settings = self.setting_section("video_cleanup")
            self.set_combo_data(
                self.cleanup_quality_combo,
                cleanup_settings.get("quality_label"),
                VIDEO_CLEANUP_QUALITY_LABELS,
            )
        finally:
            self.is_restoring_settings = False

        self.set_tts_mode(self.tts_mode_index())
        self.stt_mode_changed()
        self.video_subtitle_mode_changed()
        self.update_video_subtitle_style_options()
        self.update_video_quality_description()
        self.refresh_audio_cleanup_input_info()
        self.cleanup_media_changed()
        self.update_cleanup_quality_description()
        self.refresh_job_history()

    def save_user_settings(self) -> None:
        if getattr(self, "is_restoring_settings", False):
            return

        settings = dict(self.app_settings)
        settings["ui_language"] = self.ui_language
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
                "split_mode": self.combo_current_data(self.tts_split_combo),
            }

        if hasattr(self, "stt_mode_combo"):
            settings["stt"] = {
                "mode_label": self.combo_current_data(self.stt_mode_combo),
                "language_label": self.stt_language_combo.currentText(),
                "language_code": self.stt_language_key(),
                "device": self.stt_device_key(),
            }

        if hasattr(self, "video_embed_mode_button"):
            settings["video_subtitles"] = {
                "mode_label": self.video_subtitle_mode_label(),
                "quality_label": self.combo_current_data(self.video_quality_combo),
                "font_size": self.video_font_size_spin.value(),
                "outline": self.video_outline_spin.value(),
                "shadow": self.video_shadow_spin.value(),
                "margin_v": self.video_margin_spin.value(),
                "position_label": self.combo_current_data(self.video_position_combo),
                "text_color_label": self.combo_current_data(self.video_text_color_combo),
                "outline_color_label": self.combo_current_data(self.video_outline_color_combo),
                "background_box": self.video_background_box_check.isChecked(),
                "box_color_label": self.combo_current_data(self.video_box_color_combo),
            }

        if hasattr(self, "cleanup_quality_combo"):
            settings["video_cleanup"] = {
                "quality_label": self.combo_current_data(self.cleanup_quality_combo),
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

    def message_box_button_text(self, button):
        if button == QMessageBox.StandardButton.Yes:
            return self.static_ui_text("Yes")
        if button == QMessageBox.StandardButton.No:
            return self.static_ui_text("No")
        return self.static_ui_text("OK")

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
            return self.static_ui_text(STT_LANGUAGE_AUTO_LABEL)
        suffix = (
            self.static_ui_text("offline ready")
            if self.stt_alignment_language_ready(language_code)
            else self.static_ui_text("download for SRT")
        )
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
                tooltip = self.static_ui_text("Detects the spoken language automatically.")
            elif code in STT_ALIGNMENT_READY_LANGUAGES and stt_alignment_model_ready(code):
                tooltip = self.static_ui_text("Included in the offline package for SRT alignment.")
            elif code in self.downloaded_alignment_languages:
                tooltip = self.static_ui_text("Downloaded on this computer and available offline for SRT alignment.")
            else:
                tooltip = self.static_ui_text(
                    "Markdown transcripts work offline; SRT alignment downloads this language on request."
                )
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
