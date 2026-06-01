from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QSizePolicy

from voicebridge.ui.helpers import open_path
from voicebridge.ui.widgets import Card
from voicebridge.voice_modeling import (
    list_voice_modeling_job_configs,
    voice_modeling_job_label,
)


class VoiceTrainingWorkflowMixin:
    def selected_voice_training_job_path(self) -> str:
        config_path = self.voice_training_job_combo.currentData(Qt.ItemDataRole.UserRole)
        return config_path if isinstance(config_path, str) else ""

    def refresh_voice_training_jobs(self, selected_path: str = "") -> None:
        if not hasattr(self, "voice_training_job_combo"):
            return
        selected_path = selected_path if isinstance(selected_path, str) else ""
        selected_path = selected_path or self.selected_voice_training_job_path()
        if selected_path:
            selected_path = str(Path(selected_path).expanduser().resolve())
        jobs = list_voice_modeling_job_configs()
        self.voice_training_job_combo.blockSignals(True)
        try:
            self.voice_training_job_combo.clear()
            if not jobs:
                self.voice_training_job_combo.addItem("No training jobs configured.", "")
                item = self.voice_training_job_combo.model().item(0)
                if item is not None:
                    item.setEnabled(False)
                self.voice_training_job_status.setPlainText("Save a training config from Setup first.")
                self.update_voice_training_buttons()
                return
            selected_index = 0
            for job in jobs:
                self.voice_training_job_combo.addItem(voice_modeling_job_label(job), job["config_path"])
                index = self.voice_training_job_combo.count() - 1
                self.voice_training_job_combo.setItemData(index, job["config_path"], Qt.ItemDataRole.ToolTipRole)
                if selected_path and job["config_path"] == selected_path:
                    selected_index = index
            self.voice_training_job_combo.setCurrentIndex(selected_index)
        finally:
            self.voice_training_job_combo.blockSignals(False)
        self.voice_training_job_changed()

    def voice_training_job_changed(self) -> None:
        config_path = self.selected_voice_training_job_path()
        if not config_path:
            self.voice_training_job_status.setPlainText("No training job selected.")
            self.update_voice_training_buttons()
            return
        self.voice_training_job_status.setPlainText(f"Selected job config:\n{config_path}")
        self.update_voice_training_buttons()

    def update_voice_training_buttons(self) -> None:
        if not hasattr(self, "voice_training_open_folder_button"):
            return
        self.voice_training_open_folder_button.setEnabled(bool(self.selected_voice_training_job_path()))

    def open_selected_voice_training_job_folder(self) -> None:
        config_path = self.selected_voice_training_job_path()
        if config_path:
            open_path(Path(config_path).parent)

    def build_voice_training_page(self, include_header: bool = True):
        page, layout = self.page_container()
        if not include_header:
            layout.setContentsMargins(0, 26, 0, 24)
        if include_header:
            self.page_header(
                layout,
                "TRAINING",
                "Training",
                "Run configured local voice training jobs.",
                "BadgeGreen",
            )

        jobs_card = Card("Training jobs")
        jobs_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.voice_training_job_combo = QComboBox()
        self.voice_training_job_combo.currentIndexChanged.connect(lambda _index: self.voice_training_job_changed())
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        self.voice_training_refresh_jobs_button = QPushButton("Refresh")
        self.voice_training_open_folder_button = QPushButton("Open job folder")
        self.voice_training_refresh_jobs_button.clicked.connect(self.refresh_voice_training_jobs)
        self.voice_training_open_folder_button.clicked.connect(self.open_selected_voice_training_job_folder)
        actions.addWidget(self.voice_training_refresh_jobs_button)
        actions.addStretch(1)
        actions.addWidget(self.voice_training_open_folder_button)
        self.voice_training_job_status = QPlainTextEdit()
        self.voice_training_job_status.setObjectName("LogBox")
        self.voice_training_job_status.setReadOnly(True)
        self.voice_training_job_status.setMinimumHeight(160)
        jobs_card.content_layout.addWidget(QLabel("Job config"))
        jobs_card.content_layout.addWidget(self.voice_training_job_combo)
        jobs_card.content_layout.addLayout(actions)
        jobs_card.content_layout.addWidget(self.voice_training_job_status)
        layout.addWidget(jobs_card)
        layout.addStretch(1)
        self.refresh_voice_training_jobs()
        return page
