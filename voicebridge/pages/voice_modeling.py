from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
)

from voicebridge.constants import STT_DEVICE_BY_LABEL, STT_DEVICE_LABEL_BY_KEY, STT_DEVICE_LABELS
from voicebridge.modeling_datasets import modeling_dataset_exports_root
from voicebridge.ui.helpers import open_path
from voicebridge.ui.widgets import Card, FilePicker
from voicebridge.voice_modeling import (
    VoiceModelingExportInfo,
    build_voice_modeling_job_config,
    default_voice_modeling_output_dir,
    save_voice_modeling_job_config,
    validate_voice_modeling_export,
    voice_modeling_export_summary_text,
)


class VoiceModelingWorkflowMixin:
    def voice_modeling_device_key(self) -> str:
        device = self.voice_modeling_device_combo.currentData(Qt.ItemDataRole.UserRole)
        return device if isinstance(device, str) and device in STT_DEVICE_LABEL_BY_KEY else "auto"

    def set_voice_modeling_device_key(self, device: str) -> None:
        device = device if isinstance(device, str) and device in STT_DEVICE_LABEL_BY_KEY else "auto"
        for index in range(self.voice_modeling_device_combo.count()):
            if self.voice_modeling_device_combo.itemData(index, Qt.ItemDataRole.UserRole) == device:
                self.voice_modeling_device_combo.setCurrentIndex(index)
                return
        self.voice_modeling_device_combo.setCurrentIndex(0)

    def voice_modeling_device_changed(self) -> None:
        if self.voice_modeling_device_key() == "cuda" and not self.stt_cuda_available:
            self.set_voice_modeling_device_key("auto")

    def update_voice_modeling_device_options(self) -> None:
        if not hasattr(self, "voice_modeling_device_combo"):
            return
        selected_device = self.voice_modeling_device_key()
        if selected_device == "cuda" and not self.stt_cuda_available:
            selected_device = "auto"
        self.voice_modeling_device_combo.blockSignals(True)
        try:
            for index in range(self.voice_modeling_device_combo.count()):
                device = self.voice_modeling_device_combo.itemData(index, Qt.ItemDataRole.UserRole)
                item = self.voice_modeling_device_combo.model().item(index)
                enabled = device != "cuda" or self.stt_cuda_available
                if item is not None:
                    item.setEnabled(enabled)
                if device == "auto":
                    tooltip = "Uses CUDA when available; otherwise falls back to CPU."
                elif device == "cpu":
                    tooltip = "Forces CPU training."
                elif enabled:
                    tooltip = "Uses the detected CUDA GPU."
                else:
                    tooltip = "CUDA is not available in the current ML runtime on this machine."
                self.voice_modeling_device_combo.setItemData(index, tooltip, Qt.ItemDataRole.ToolTipRole)
            self.set_voice_modeling_device_key(selected_device)
        finally:
            self.voice_modeling_device_combo.blockSignals(False)

    def select_voice_modeling_dataset_folder(self) -> None:
        initial = self.voice_modeling_dataset_picker.text() or str(modeling_dataset_exports_root())
        path = QFileDialog.getExistingDirectory(self, "Select exported dataset", initial)
        if path:
            self.voice_modeling_dataset_picker.set_text(path)
            self.validate_voice_modeling_dataset()

    def validate_voice_modeling_dataset(self) -> VoiceModelingExportInfo | None:
        dataset_dir = self.voice_modeling_dataset_picker.text()
        if not dataset_dir:
            self.voice_modeling_export_info = None
            self.voice_modeling_dataset_info.setPlainText("Select an exported dataset folder.")
            self.update_voice_modeling_buttons()
            return None
        try:
            export_info = validate_voice_modeling_export(dataset_dir)
        except ValueError as exc:
            self.voice_modeling_export_info = None
            self.voice_modeling_dataset_info.setPlainText(str(exc))
            self.voice_modeling_status.setText("Dataset not ready.")
            self.update_voice_modeling_buttons()
            return None
        self.voice_modeling_export_info = export_info
        self.voice_modeling_dataset_info.setPlainText(voice_modeling_export_summary_text(export_info))
        self.voice_modeling_output_picker.set_text(str(default_voice_modeling_output_dir(export_info)))
        self.voice_modeling_status.setText("Dataset export validated.")
        self.update_voice_modeling_buttons()
        return export_info

    def select_voice_modeling_output_folder(self) -> None:
        initial = self.voice_modeling_output_picker.text() or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "Select model output folder", initial)
        if path:
            self.voice_modeling_output_picker.set_text(path)
            self.update_voice_modeling_buttons()

    def select_voice_modeling_resume_checkpoint(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select resume checkpoint",
            self.voice_modeling_resume_picker.text() or str(Path.home()),
            "Checkpoint files (*.pth *.pt *.ckpt);;All files (*.*)",
        )
        if path:
            self.voice_modeling_resume_picker.set_text(path)

    def clear_voice_modeling_resume_checkpoint(self) -> None:
        self.voice_modeling_resume_picker.set_text("")

    def save_voice_modeling_config(self) -> None:
        export_info = self.voice_modeling_export_info or self.validate_voice_modeling_dataset()
        if not export_info:
            self.show_error("Voice Modeling", "Select a valid exported dataset first.")
            return
        try:
            config = build_voice_modeling_job_config(
                export_info,
                output_dir=self.voice_modeling_output_picker.text(),
                resume_checkpoint=self.voice_modeling_resume_picker.text(),
                device=self.voice_modeling_device_key(),
                max_epochs=self.voice_modeling_epochs_spin.value(),
                batch_size=self.voice_modeling_batch_spin.value(),
            )
            config_path = save_voice_modeling_job_config(config)
        except (OSError, ValueError) as exc:
            self.voice_modeling_status.setText("Error.")
            self.show_error("Voice Modeling", str(exc))
            return
        self.voice_modeling_status.setText(f"Training job configured: {config_path}")
        self.show_info("Voice Modeling", f"Training job config saved:\n{config_path}")
        open_path(config_path.parent)

    def open_voice_modeling_output_folder(self) -> None:
        output_path = self.voice_modeling_output_picker.text()
        if output_path:
            Path(output_path).mkdir(parents=True, exist_ok=True)
            open_path(output_path)

    def update_voice_modeling_buttons(self) -> None:
        if not hasattr(self, "voice_modeling_save_config_button"):
            return
        has_dataset = self.voice_modeling_export_info is not None
        has_output = bool(self.voice_modeling_output_picker.text())
        self.voice_modeling_save_config_button.setEnabled(has_dataset and has_output)
        self.voice_modeling_open_output_button.setEnabled(has_output)

    def build_voice_modeling_page(self, include_header: bool = True):
        page, layout = self.page_container()
        if not include_header:
            layout.setContentsMargins(0, 26, 0, 24)
        if include_header:
            self.page_header(
                layout,
                "TRAINING",
                "Voice Modeling",
                "Validate an exported dataset and prepare a controlled XTTS-v2 training job configuration.",
                "BadgeGreen",
            )

        grid = QGridLayout()
        grid.setSpacing(16)
        layout.addLayout(grid)

        dataset_card = Card("Exported dataset")
        dataset_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.voice_modeling_dataset_picker = FilePicker("Dataset export folder")
        self.voice_modeling_dataset_picker.button.clicked.connect(self.select_voice_modeling_dataset_folder)
        self.voice_modeling_dataset_picker.edit.textChanged.connect(lambda _text: self.update_voice_modeling_buttons())
        self.voice_modeling_validate_button = QPushButton("Validate")
        self.voice_modeling_validate_button.clicked.connect(self.validate_voice_modeling_dataset)
        self.voice_modeling_dataset_info = QPlainTextEdit()
        self.voice_modeling_dataset_info.setObjectName("LogBox")
        self.voice_modeling_dataset_info.setReadOnly(True)
        self.voice_modeling_dataset_info.setMinimumHeight(240)
        self.voice_modeling_dataset_info.setPlainText("Select an exported dataset folder.")
        dataset_card.content_layout.addWidget(self.voice_modeling_dataset_picker)
        dataset_card.content_layout.addWidget(self.voice_modeling_validate_button)
        dataset_card.content_layout.addWidget(self.voice_modeling_dataset_info)

        config_card = Card("Training configuration")
        config_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.voice_modeling_output_picker = FilePicker("Model output folder")
        self.voice_modeling_output_picker.button.clicked.connect(self.select_voice_modeling_output_folder)
        self.voice_modeling_output_picker.edit.textChanged.connect(lambda _text: self.update_voice_modeling_buttons())
        self.voice_modeling_resume_picker = FilePicker("Resume checkpoint", "Browse...")
        self.voice_modeling_resume_picker.button.clicked.connect(self.select_voice_modeling_resume_checkpoint)
        self.voice_modeling_clear_resume_button = QPushButton("Clear checkpoint")
        self.voice_modeling_clear_resume_button.clicked.connect(self.clear_voice_modeling_resume_checkpoint)
        self.voice_modeling_device_combo = QComboBox()
        for label in STT_DEVICE_LABELS:
            self.voice_modeling_device_combo.addItem(label, STT_DEVICE_BY_LABEL[label])
        self.voice_modeling_device_combo.currentTextChanged.connect(lambda _text: self.voice_modeling_device_changed())
        self.voice_modeling_epochs_spin = QSpinBox()
        self.voice_modeling_epochs_spin.setRange(1, 500)
        self.voice_modeling_epochs_spin.setValue(50)
        self.voice_modeling_batch_spin = QSpinBox()
        self.voice_modeling_batch_spin.setRange(1, 16)
        self.voice_modeling_batch_spin.setValue(2)
        config_grid = QGridLayout()
        config_grid.setContentsMargins(0, 0, 0, 0)
        config_grid.setHorizontalSpacing(10)
        config_grid.setVerticalSpacing(8)
        config_grid.addWidget(QLabel("Device"), 0, 0)
        config_grid.addWidget(self.voice_modeling_device_combo, 0, 1)
        config_grid.addWidget(QLabel("Max epochs"), 1, 0)
        config_grid.addWidget(self.voice_modeling_epochs_spin, 1, 1)
        config_grid.addWidget(QLabel("Batch size"), 2, 0)
        config_grid.addWidget(self.voice_modeling_batch_spin, 2, 1)
        config_grid.setColumnStretch(1, 1)
        config_card.content_layout.addWidget(self.voice_modeling_output_picker)
        config_card.content_layout.addWidget(self.voice_modeling_resume_picker)
        config_card.content_layout.addWidget(self.voice_modeling_clear_resume_button)
        config_card.content_layout.addLayout(config_grid)

        actions_card = Card()
        actions_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        self.voice_modeling_save_config_button = QPushButton("Save training config")
        self.voice_modeling_save_config_button.setObjectName("PrimaryButton")
        self.voice_modeling_open_output_button = QPushButton("Open output folder")
        self.voice_modeling_save_config_button.clicked.connect(self.save_voice_modeling_config)
        self.voice_modeling_open_output_button.clicked.connect(self.open_voice_modeling_output_folder)
        action_row.addWidget(self.voice_modeling_save_config_button)
        action_row.addStretch(1)
        action_row.addWidget(self.voice_modeling_open_output_button)
        self.voice_modeling_status = QLabel("No training job configured.")
        self.voice_modeling_status.setObjectName("StatusText")
        self.voice_modeling_status.setWordWrap(True)
        actions_card.content_layout.addLayout(action_row)
        actions_card.content_layout.addWidget(self.voice_modeling_status)

        grid.addWidget(dataset_card, 0, 0)
        grid.addWidget(config_card, 0, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        layout.addWidget(actions_card)
        layout.addStretch(1)

        self.voice_modeling_export_info = None
        self.update_voice_modeling_device_options()
        self.update_voice_modeling_buttons()
        return page
