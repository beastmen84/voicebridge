import threading
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
)

from voicebridge.constants import STT_DEVICE_BY_LABEL, STT_DEVICE_LABEL_BY_KEY, STT_DEVICE_LABELS
from voicebridge.modeling_datasets import modeling_dataset_exports_root
from voicebridge.ui.helpers import open_path
from voicebridge.ui.widgets import Card, FilePicker
from voicebridge.voice_modeling import (
    VoiceModelingExportInfo,
    build_voice_modeling_job_config,
    check_voice_modeling_preflight,
    default_voice_modeling_output_dir,
    list_voice_modeling_exports,
    save_voice_modeling_job_config,
    validate_voice_modeling_export,
    voice_modeling_export_label,
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
        self.mark_voice_modeling_preflight_stale()

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

    def selected_voice_modeling_export_path(self) -> str:
        export_path = self.voice_modeling_export_combo.currentData(Qt.ItemDataRole.UserRole)
        return export_path if isinstance(export_path, str) else ""

    def refresh_voice_modeling_exports(self, selected_path: str = "") -> None:
        if not hasattr(self, "voice_modeling_export_combo"):
            return
        selected_path = selected_path if isinstance(selected_path, str) else ""
        selected_path = selected_path or self.selected_voice_modeling_export_path()
        if selected_path:
            selected_path = str(Path(selected_path).expanduser().resolve())
        exports = list_voice_modeling_exports()
        self.voice_modeling_export_combo.blockSignals(True)
        try:
            self.voice_modeling_export_combo.clear()
            if not exports:
                self.voice_modeling_export_combo.addItem("No valid dataset exports found.", "")
                item = self.voice_modeling_export_combo.model().item(0)
                if item is not None:
                    item.setEnabled(False)
                self.voice_modeling_export_info = None
                self.voice_modeling_dataset_info.setPlainText(
                    "Export a Usable or Good dataset from Local Voices > Datasets first."
                )
                self.voice_modeling_output_picker.set_text("")
                self.voice_modeling_status.setText("No valid dataset export found.")
                self.update_voice_modeling_buttons()
                return
            selected_index = 0
            for export_info in exports:
                self.voice_modeling_export_combo.addItem(
                    voice_modeling_export_label(export_info),
                    export_info["dataset_dir"],
                )
                index = self.voice_modeling_export_combo.count() - 1
                self.voice_modeling_export_combo.setItemData(
                    index,
                    export_info["dataset_dir"],
                    Qt.ItemDataRole.ToolTipRole,
                )
                if selected_path and export_info["dataset_dir"] == selected_path:
                    selected_index = index
            self.voice_modeling_export_combo.setCurrentIndex(selected_index)
        finally:
            self.voice_modeling_export_combo.blockSignals(False)
        self.validate_voice_modeling_dataset()

    def select_voice_modeling_dataset_folder(self) -> None:
        initial = self.selected_voice_modeling_export_path() or str(modeling_dataset_exports_root())
        path = QFileDialog.getExistingDirectory(self, "Select exported dataset", initial)
        if path:
            self.set_external_voice_modeling_export(path)

    def set_external_voice_modeling_export(self, dataset_dir: str) -> None:
        try:
            export_info = validate_voice_modeling_export(dataset_dir)
        except ValueError as exc:
            self.voice_modeling_export_info = None
            self.voice_modeling_dataset_info.setPlainText(str(exc))
            self.voice_modeling_output_picker.set_text("")
            self.voice_modeling_status.setText("Dataset not ready.")
            self.update_voice_modeling_buttons()
            return
        export_path = export_info["dataset_dir"]
        self.voice_modeling_export_combo.blockSignals(True)
        try:
            for index in range(self.voice_modeling_export_combo.count()):
                if self.voice_modeling_export_combo.itemData(index, Qt.ItemDataRole.UserRole) == export_path:
                    self.voice_modeling_export_combo.setCurrentIndex(index)
                    break
            else:
                self.voice_modeling_export_combo.addItem(
                    f"External | {voice_modeling_export_label(export_info)}",
                    export_path,
                )
                index = self.voice_modeling_export_combo.count() - 1
                self.voice_modeling_export_combo.setItemData(index, export_path, Qt.ItemDataRole.ToolTipRole)
                self.voice_modeling_export_combo.setCurrentIndex(index)
        finally:
            self.voice_modeling_export_combo.blockSignals(False)
        self.apply_voice_modeling_export(export_info)

    def validate_voice_modeling_dataset(self) -> VoiceModelingExportInfo | None:
        dataset_dir = self.selected_voice_modeling_export_path()
        if not dataset_dir:
            self.voice_modeling_export_info = None
            self.voice_modeling_dataset_info.setPlainText("Select an exported dataset.")
            self.voice_modeling_output_picker.set_text("")
            self.voice_modeling_status.setText("No dataset selected.")
            self.update_voice_modeling_buttons()
            return None
        try:
            export_info = validate_voice_modeling_export(dataset_dir)
        except ValueError as exc:
            self.voice_modeling_export_info = None
            self.voice_modeling_dataset_info.setPlainText(str(exc))
            self.voice_modeling_output_picker.set_text("")
            self.voice_modeling_status.setText("Dataset not ready.")
            self.update_voice_modeling_buttons()
            return None
        self.apply_voice_modeling_export(export_info)
        return export_info

    def voice_modeling_export_changed(self) -> None:
        self.validate_voice_modeling_dataset()

    def apply_voice_modeling_export(self, export_info: VoiceModelingExportInfo) -> None:
        self.voice_modeling_export_info = export_info
        self.voice_modeling_dataset_info.setPlainText(voice_modeling_export_summary_text(export_info))
        self.voice_modeling_output_picker.set_text(str(default_voice_modeling_output_dir(export_info)))
        self.voice_modeling_status.setText("Dataset export validated.")
        self.update_voice_modeling_buttons()
        if getattr(self, "voice_modeling_auto_preflight_enabled", False):
            self.refresh_voice_modeling_preflight_async()
        elif hasattr(self, "voice_modeling_preflight_label"):
            self.voice_modeling_preflight_label.setText("Preflight not run yet. Use Refresh preflight.")

    def select_voice_modeling_output_folder(self) -> None:
        initial = self.voice_modeling_output_picker.text() or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "Select model output folder", initial)
        if path:
            self.voice_modeling_output_picker.set_text(path)
            self.update_voice_modeling_buttons()
            self.mark_voice_modeling_preflight_stale()

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
        self.mark_voice_modeling_preflight_stale()

    def mark_voice_modeling_preflight_stale(self) -> None:
        if not hasattr(self, "voice_modeling_preflight_label"):
            return
        if getattr(self, "_voice_modeling_preflight_refreshing", False):
            return
        self.voice_modeling_preflight_ok = False
        self.voice_modeling_preflight_label.setText("Preflight needs refresh after configuration changes.")
        self.voice_modeling_preflight_box.setObjectName("WarningBox")
        self.voice_modeling_preflight_box.style().unpolish(self.voice_modeling_preflight_box)
        self.voice_modeling_preflight_box.style().polish(self.voice_modeling_preflight_box)

    def refresh_voice_modeling_preflight_async(self) -> None:
        if not hasattr(self, "voice_modeling_preflight_label"):
            return
        if getattr(self, "_voice_modeling_preflight_refreshing", False):
            return
        export_info = dict(self.voice_modeling_export_info) if self.voice_modeling_export_info else None
        output_dir = self.voice_modeling_output_picker.text() if hasattr(self, "voice_modeling_output_picker") else ""
        resume_checkpoint = (
            self.voice_modeling_resume_picker.text() if hasattr(self, "voice_modeling_resume_picker") else ""
        )
        device = self.voice_modeling_device_key() if hasattr(self, "voice_modeling_device_combo") else "auto"
        self._voice_modeling_preflight_refreshing = True
        self.voice_modeling_preflight_refresh_button.setEnabled(False)
        self.voice_modeling_preflight_label.setText("Checking Voice Modeling prerequisites...")
        threading.Thread(
            target=self.refresh_voice_modeling_preflight_worker,
            args=(export_info, output_dir, resume_checkpoint, device),
            daemon=True,
        ).start()

    def refresh_voice_modeling_preflight_worker(
        self,
        export_info,
        output_dir: str,
        resume_checkpoint: str,
        device: str,
    ) -> None:
        result = check_voice_modeling_preflight(
            export_info,
            output_dir=output_dir,
            resume_checkpoint=resume_checkpoint,
            device=device,
        )
        self.post(self.voice_modeling_preflight_finished, result)

    def voice_modeling_preflight_finished(self, result) -> None:
        self._voice_modeling_preflight_refreshing = False
        self.voice_modeling_preflight_ok = bool(result["ok"])
        self.voice_modeling_preflight_details = result["details"]
        self.voice_modeling_preflight_label.setText(result["summary"])
        self.voice_modeling_preflight_details_box.setPlainText("\n".join(result["details"]))
        self.voice_modeling_preflight_refresh_button.setEnabled(True)
        self.voice_modeling_preflight_box.setObjectName("GoodBox" if result["ok"] else "WarningBox")
        self.voice_modeling_preflight_box.style().unpolish(self.voice_modeling_preflight_box)
        self.voice_modeling_preflight_box.style().polish(self.voice_modeling_preflight_box)
        self.refresh_home_diagnostics()

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
        self.voice_modeling_export_combo = QComboBox()
        self.voice_modeling_export_combo.currentIndexChanged.connect(
            lambda _index: self.voice_modeling_export_changed()
        )
        export_actions = QHBoxLayout()
        export_actions.setContentsMargins(0, 0, 0, 0)
        self.voice_modeling_refresh_exports_button = QPushButton("Refresh")
        self.voice_modeling_browse_export_button = QPushButton("Browse external...")
        self.voice_modeling_refresh_exports_button.clicked.connect(self.refresh_voice_modeling_exports)
        self.voice_modeling_browse_export_button.clicked.connect(self.select_voice_modeling_dataset_folder)
        export_actions.addWidget(self.voice_modeling_refresh_exports_button)
        export_actions.addStretch(1)
        export_actions.addWidget(self.voice_modeling_browse_export_button)
        self.voice_modeling_dataset_info = QPlainTextEdit()
        self.voice_modeling_dataset_info.setObjectName("LogBox")
        self.voice_modeling_dataset_info.setReadOnly(True)
        self.voice_modeling_dataset_info.setMinimumHeight(240)
        self.voice_modeling_dataset_info.setPlainText("Select an exported dataset.")
        dataset_card.content_layout.addWidget(QLabel("Dataset export"))
        dataset_card.content_layout.addWidget(self.voice_modeling_export_combo)
        dataset_card.content_layout.addLayout(export_actions)
        dataset_card.content_layout.addWidget(self.voice_modeling_dataset_info)

        config_card = Card("Training configuration")
        config_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.voice_modeling_output_picker = FilePicker("Model output folder")
        self.voice_modeling_output_picker.button.clicked.connect(self.select_voice_modeling_output_folder)
        self.voice_modeling_output_picker.edit.textChanged.connect(lambda _text: self.update_voice_modeling_buttons())
        self.voice_modeling_output_picker.edit.textChanged.connect(
            lambda _text: self.mark_voice_modeling_preflight_stale()
        )
        self.voice_modeling_resume_picker = FilePicker("Resume checkpoint", "Browse...")
        self.voice_modeling_resume_picker.button.clicked.connect(self.select_voice_modeling_resume_checkpoint)
        self.voice_modeling_resume_picker.edit.textChanged.connect(
            lambda _text: self.mark_voice_modeling_preflight_stale()
        )
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

        preflight_card = Card("Training preflight")
        preflight_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.voice_modeling_preflight_box = QFrame()
        self.voice_modeling_preflight_box.setObjectName("WarningBox")
        preflight_box_layout = QVBoxLayout(self.voice_modeling_preflight_box)
        preflight_box_layout.setContentsMargins(12, 10, 12, 10)
        preflight_box_layout.setSpacing(8)
        self.voice_modeling_preflight_label = QLabel("Select a dataset export to check training prerequisites.")
        self.voice_modeling_preflight_label.setWordWrap(True)
        self.voice_modeling_preflight_details_box = QPlainTextEdit()
        self.voice_modeling_preflight_details_box.setObjectName("LogBox")
        self.voice_modeling_preflight_details_box.setReadOnly(True)
        self.voice_modeling_preflight_details_box.setMinimumHeight(120)
        self.voice_modeling_preflight_refresh_button = QPushButton("Refresh preflight")
        self.voice_modeling_preflight_refresh_button.clicked.connect(self.refresh_voice_modeling_preflight_async)
        preflight_box_layout.addWidget(self.voice_modeling_preflight_label)
        preflight_box_layout.addWidget(self.voice_modeling_preflight_details_box)
        preflight_box_layout.addWidget(self.voice_modeling_preflight_refresh_button)
        preflight_card.content_layout.addWidget(self.voice_modeling_preflight_box)

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
        grid.addWidget(preflight_card, 1, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        layout.addWidget(actions_card)
        layout.addStretch(1)

        self.voice_modeling_export_info = None
        self.voice_modeling_preflight_ok = False
        self.voice_modeling_preflight_details = []
        self.voice_modeling_auto_preflight_enabled = False
        self.update_voice_modeling_device_options()
        self.refresh_voice_modeling_exports()
        self.voice_modeling_auto_preflight_enabled = True
        self.update_voice_modeling_buttons()
        return page
