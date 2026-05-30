from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
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

from media_tools import find_ffmpeg_exe
from readers import load_ocr_dependencies
from voicebridge.constants import (
    BURN_QUALITY_AUTO_LABEL,
    BURN_QUALITY_DESCRIPTIONS,
    BURN_QUALITY_LABELS,
    DEFAULT_RATE,
    RATE_CHOICES,
    STT_CPU_ONLY_STATUS,
    STT_MODE_LABELS,
    TTS_SPLIT_LINES,
    TTS_SPLIT_PARAGRAPHS,
    VIDEO_CLEANUP_FREEZE_LABEL,
    VIDEO_CLEANUP_METHOD_DESCRIPTIONS,
    VIDEO_CLEANUP_METHOD_LABELS,
    VIDEO_CLEANUP_QUALITY_DESCRIPTIONS,
    VIDEO_CLEANUP_QUALITY_LABELS,
    VIDEO_SUBTITLE_BURN_LABEL,
    VIDEO_SUBTITLE_EMBED_LABEL,
    VIDEO_SUBTITLE_MODE_DESCRIPTIONS,
    VIDEO_SUBTITLE_POSITION_LABELS,
)
from voicebridge.models import JobHistoryEntry
from voicebridge.ui.helpers import open_path
from voicebridge.ui.widgets import Card, FilePicker


class PageBuilderMixin:
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
