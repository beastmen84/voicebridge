from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from voicebridge.app_paths import (
    local_tts_model_cache_dir,
    local_tts_model_ready,
    local_tts_worker_path,
    ml_python_path,
    stt_model_dir,
    stt_whisper_model_ready,
)
from voicebridge.constants import STT_CPU_STATUS, STT_CUDA_STATUS
from voicebridge.media_tools import find_ffmpeg_exe
from voicebridge.models import JobHistoryEntry
from voicebridge.readers import load_ocr_dependencies
from voicebridge.ui.helpers import open_path
from voicebridge.ui.widgets import Card


class HomePageMixin:
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
        profiles_card = self.home_card(
            "VOICE",
            "Voice Profiles",
            "Prepare authorized local voice references for Local TTS.",
            "Reference voices",
            "BadgeGreen",
        )
        modeling_card = self.home_card(
            "MODEL",
            "Modeling Datasets",
            "Collect authorized audio and text clip pairs for future voice model training.",
            "Dataset preparation",
            "BadgeGreen",
        )
        voice_modeling_card = self.home_card(
            "TRAIN",
            "Voice Modeling",
            "Validate an exported dataset and prepare training configuration.",
            "Training setup",
            "BadgeGreen",
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
        audio_cleanup_card = self.home_card(
            "AUDIO",
            "Audio Cleanup",
            "Remove short AI TTS artifacts or hallucinated fragments without rebuilding the whole output.",
            "TTS artifact repair",
            "BadgeGreen",
        )
        cleanup_card = self.home_card(
            "FIX",
            "Video Cleanup",
            "Detect isolated black-frame glitches and repair them without shortening the video.",
            "Frame repair/removal",
            "BadgeGreen",
        )
        for card in (
            tts_card,
            profiles_card,
            modeling_card,
            voice_modeling_card,
            stt_card,
            video_card,
            audio_cleanup_card,
            cleanup_card,
        ):
            modules_layout.addWidget(card)

        note = QLabel("TTS requires internet. Local voice profiles are prepared separately.")
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
    def local_tts_diagnostic_detail() -> tuple[str, str]:
        python_path = ml_python_path()
        worker_path = local_tts_worker_path()
        missing = []
        if not python_path.is_file():
            missing.append(f"ML Python runtime missing: {python_path}")
        if not worker_path.is_file():
            missing.append(f"Local TTS worker missing: {worker_path}")
        if missing:
            return "bad", missing[0]
        if not local_tts_model_ready():
            return "warn", "XTTS-v2 model not downloaded. Open Local TTS and use Download XTTS-v2."
        return "ok", f"Coqui XTTS-v2 ready: {local_tts_model_cache_dir()}"

    @staticmethod
    def diagnostic_state_label(state: str) -> str:
        return {
            "ok": "OK",
            "warn": "WARN",
            "bad": "BAD",
            "info": "INFO",
        }.get(state, "INFO")

    def set_status_tile(self, key: str, state: str, detail: str, display_label: str | None = None) -> None:
        tile = self.status_tiles.get(key)
        if tile is None:
            return
        tile.setText(f"{display_label or key}\n{self.diagnostic_state_label(state)}")
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

        local_state, local_detail = self.local_tts_diagnostic_detail()
        self.set_status_tile("LOCAL", local_state, local_detail, display_label="LOCAL")

        if self.stt_preflight_ok:
            self.set_status_tile("STT", "ok", "Offline STT package complete")
        elif not stt_whisper_model_ready():
            self.set_status_tile("STT", "warn", f"Whisper large-v3 model not downloaded: {stt_model_dir()}")
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

        runtime_label = "CUDA" if self.stt_cuda_available else "CPU"
        runtime_detail = self.stt_runtime_detail or (
            STT_CUDA_STATUS if self.stt_cuda_available else STT_CPU_STATUS
        )
        self.set_status_tile("CPU", "ok", runtime_detail, display_label=runtime_label)

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

