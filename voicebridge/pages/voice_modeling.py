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
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
)

from voicebridge.app_paths import (
    local_tts_dvae_path,
    local_tts_dvae_ready,
    local_tts_mel_stats_path,
    local_tts_mel_stats_ready,
)
from voicebridge.constants import STT_DEVICE_BY_LABEL, STT_DEVICE_LABEL_BY_KEY, STT_DEVICE_LABELS
from voicebridge.ui.helpers import open_path
from voicebridge.ui.widgets import Card, FilePicker
from voicebridge.voice_modeling import (
    VOICE_MODELING_DEFAULT_BATCH_SIZE,
    VOICE_MODELING_DEFAULT_MAX_EPOCHS,
    VoiceModelingDownloadCancelled,
    VoiceModelingExportInfo,
    build_voice_modeling_job_config,
    check_voice_modeling_preflight,
    default_voice_modeling_output_dir,
    download_xtts_training_assets,
    latest_voice_modeling_job_config_for_export,
    load_voice_modeling_job_config,
    recommended_voice_modeling_training_defaults,
    save_voice_modeling_job_config,
    validate_voice_modeling_export,
    voice_modeling_export_summary_text,
)


# noinspection PyAttributeOutsideInit,PyUnresolvedReferences,PyTypeChecker
class VoiceModelingWorkflowMixin:
    def voice_modeling_text(self, text: str, **kwargs) -> str:
        if kwargs and hasattr(self, "format_static_ui_text"):
            return self.format_static_ui_text(text, **kwargs)
        if kwargs:
            return text.format(**kwargs)
        return self.static_ui_text(text) if hasattr(self, "static_ui_text") else text

    def populate_voice_modeling_device_combo(self) -> None:
        selected_device = self.voice_modeling_device_key() if self.voice_modeling_device_combo.count() else "auto"
        self.voice_modeling_device_combo.blockSignals(True)
        try:
            self.voice_modeling_device_combo.clear()
            for label in STT_DEVICE_LABELS:
                self.voice_modeling_device_combo.addItem(self.voice_modeling_text(label), STT_DEVICE_BY_LABEL[label])
            self.set_voice_modeling_device_key(selected_device)
        finally:
            self.voice_modeling_device_combo.blockSignals(False)

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
        self.mark_voice_modeling_config_changed()
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
                    tooltip = self.voice_modeling_text("Uses CUDA when available; otherwise falls back to CPU.")
                elif device == "cpu":
                    tooltip = self.voice_modeling_text("Forces CPU training.")
                elif enabled:
                    tooltip = self.voice_modeling_text("Uses the detected CUDA GPU.")
                else:
                    tooltip = self.voice_modeling_text(
                        "CUDA is not available in the current ML runtime on this machine."
                    )
                self.voice_modeling_device_combo.setItemData(index, tooltip, Qt.ItemDataRole.ToolTipRole)
            self.set_voice_modeling_device_key(selected_device)
        finally:
            self.voice_modeling_device_combo.blockSignals(False)

    def selected_voice_modeling_export_path(self) -> str:
        selected_path = getattr(self, "voice_modeling_selected_export_path", "")
        return selected_path if isinstance(selected_path, str) else ""

    def refresh_voice_modeling_exports(self, selected_path: str = "") -> None:
        if not hasattr(self, "voice_modeling_dataset_info"):
            return
        selected_path = selected_path if isinstance(selected_path, str) else ""
        selected_path = selected_path or self.selected_voice_modeling_export_path()
        if selected_path:
            selected_path = str(Path(selected_path).expanduser().resolve())
        if selected_path:
            self.voice_modeling_selected_export_path = selected_path
            self.validate_voice_modeling_dataset()
            return
        self.voice_modeling_selected_export_path = ""
        self.voice_modeling_export_info = None
        self.voice_modeling_saved_config_path = ""
        self.voice_modeling_saved_config_snapshot = None
        self.voice_modeling_config_dirty = True
        self.voice_modeling_dataset_info.setPlainText(
            self.voice_modeling_text("Use Dataset > Setup Dataset first.")
        )
        self.voice_modeling_output_picker.set_text("")
        self.voice_modeling_status.setText(self.voice_modeling_text("No dataset export selected."))
        self.update_voice_modeling_buttons()

    def validate_voice_modeling_dataset(self) -> VoiceModelingExportInfo | None:
        dataset_dir = self.selected_voice_modeling_export_path()
        if not dataset_dir:
            self.voice_modeling_export_info = None
            self.voice_modeling_saved_config_path = ""
            self.voice_modeling_saved_config_snapshot = None
            self.voice_modeling_config_dirty = True
            self.voice_modeling_dataset_info.setPlainText(self.voice_modeling_text("Select an exported dataset."))
            self.voice_modeling_output_picker.set_text("")
            self.voice_modeling_status.setText(self.voice_modeling_text("No dataset selected."))
            self.update_voice_modeling_buttons()
            return None
        try:
            export_info = validate_voice_modeling_export(dataset_dir)
        except ValueError as exc:
            self.voice_modeling_export_info = None
            self.voice_modeling_saved_config_path = ""
            self.voice_modeling_saved_config_snapshot = None
            self.voice_modeling_config_dirty = True
            self.voice_modeling_dataset_info.setPlainText(str(exc))
            self.voice_modeling_output_picker.set_text("")
            self.voice_modeling_status.setText(self.voice_modeling_text("Dataset not ready."))
            self.update_voice_modeling_buttons()
            return None
        self.voice_modeling_selected_export_path = export_info["dataset_dir"]
        self.apply_voice_modeling_export(export_info)
        return export_info

    def apply_voice_modeling_export(self, export_info: VoiceModelingExportInfo) -> None:
        self.voice_modeling_export_info = export_info
        self.voice_modeling_selected_export_path = export_info["dataset_dir"]
        self.voice_modeling_dataset_info.setPlainText(voice_modeling_export_summary_text(export_info))
        existing_job = latest_voice_modeling_job_config_for_export(export_info)
        if existing_job:
            self.apply_voice_modeling_existing_config(existing_job["config_path"])
        else:
            self.voice_modeling_saved_config_path = ""
            self.voice_modeling_saved_config_snapshot = None
            self.voice_modeling_output_picker.set_text(str(default_voice_modeling_output_dir(export_info)))
            defaults = self.apply_voice_modeling_training_defaults(export_info)
            self.voice_modeling_status.setText(
                self.voice_modeling_text(
                    "Dataset export validated. Suggested training: {epochs} max epochs, batch size {batch}.",
                    epochs=defaults["max_epochs"],
                    batch=defaults["batch_size"],
                )
            )
            self.voice_modeling_config_dirty = True
        self.update_voice_modeling_buttons()
        if getattr(self, "voice_modeling_auto_preflight_enabled", False):
            self.refresh_voice_modeling_preflight_async()
        elif hasattr(self, "voice_modeling_preflight_label"):
            self.voice_modeling_preflight_label.setText(
                self.voice_modeling_text("Preflight not run yet. Use Refresh preflight.")
            )

    def apply_voice_modeling_existing_config(self, config_path: str) -> None:
        try:
            config = load_voice_modeling_job_config(config_path)
        except (OSError, ValueError):
            self.voice_modeling_saved_config_path = ""
            self.voice_modeling_saved_config_snapshot = None
            self.voice_modeling_config_dirty = True
            return
        self.voice_modeling_saved_config_path = str(Path(config_path).expanduser().resolve())
        self.voice_modeling_output_picker.set_text(config["output_dir"])
        self.set_voice_modeling_device_key(config.get("device", "auto"))
        self.voice_modeling_epochs_spin.blockSignals(True)
        self.voice_modeling_batch_spin.blockSignals(True)
        try:
            self.voice_modeling_epochs_spin.setValue(int(config.get("max_epochs", VOICE_MODELING_DEFAULT_MAX_EPOCHS)))
            self.voice_modeling_batch_spin.setValue(int(config.get("batch_size", VOICE_MODELING_DEFAULT_BATCH_SIZE)))
        finally:
            self.voice_modeling_batch_spin.blockSignals(False)
            self.voice_modeling_epochs_spin.blockSignals(False)
        self.voice_modeling_saved_config_snapshot = self.current_voice_modeling_config_snapshot()
        self.voice_modeling_config_dirty = False
        self.voice_modeling_status.setText(
            self.voice_modeling_text("Training config available. Use Go to Training.")
        )

    def current_voice_modeling_config_snapshot(self) -> dict:
        return {
            "dataset_dir": self.voice_modeling_export_info["dataset_dir"] if self.voice_modeling_export_info else "",
            "output_dir": self.voice_modeling_output_picker.text()
            if hasattr(self, "voice_modeling_output_picker")
            else "",
            "device": self.voice_modeling_device_key() if hasattr(self, "voice_modeling_device_combo") else "auto",
            "max_epochs": self.voice_modeling_epochs_spin.value()
            if hasattr(self, "voice_modeling_epochs_spin")
            else VOICE_MODELING_DEFAULT_MAX_EPOCHS,
            "batch_size": self.voice_modeling_batch_spin.value()
            if hasattr(self, "voice_modeling_batch_spin")
            else VOICE_MODELING_DEFAULT_BATCH_SIZE,
        }

    def mark_voice_modeling_config_changed(self) -> None:
        if not hasattr(self, "voice_modeling_save_config_button"):
            return
        saved_snapshot = getattr(self, "voice_modeling_saved_config_snapshot", None)
        self.voice_modeling_config_dirty = saved_snapshot != self.current_voice_modeling_config_snapshot()
        if (
            self.voice_modeling_config_dirty
            and getattr(self, "voice_modeling_saved_config_path", "")
            and hasattr(self, "voice_modeling_status")
        ):
            self.voice_modeling_status.setText(
                self.voice_modeling_text("Training config changed. Save Config before going to Training.")
            )
        self.update_voice_modeling_buttons()

    def open_voice_modeling_setup_for_export(self, dataset_dir: str) -> None:
        self.voice_modeling_selected_export_path = str(Path(dataset_dir).expanduser().resolve())
        export_info = self.validate_voice_modeling_dataset()
        if not export_info:
            return
        if hasattr(self, "open_local_voice_workflow_tab"):
            self.open_local_voice_workflow_tab(2)
        else:
            self.show_local_voices_tab(2)

    def apply_voice_modeling_training_defaults(
        self,
        export_info: VoiceModelingExportInfo,
    ) -> dict[str, int]:
        defaults = recommended_voice_modeling_training_defaults(
            export_info,
            cuda_total_memory_bytes=self.voice_modeling_cuda_total_memory_bytes(),
        )
        if hasattr(self, "voice_modeling_epochs_spin"):
            self.voice_modeling_epochs_spin.blockSignals(True)
            try:
                self.voice_modeling_epochs_spin.setValue(defaults["max_epochs"])
            finally:
                self.voice_modeling_epochs_spin.blockSignals(False)
            self.voice_modeling_epochs_spin.setToolTip(
                self.voice_modeling_text(
                    "Suggested from dataset size; lower values reduce overfitting risk."
                )
            )
        if hasattr(self, "voice_modeling_batch_spin"):
            self.voice_modeling_batch_spin.blockSignals(True)
            try:
                self.voice_modeling_batch_spin.setValue(defaults["batch_size"])
            finally:
                self.voice_modeling_batch_spin.blockSignals(False)
            self.voice_modeling_batch_spin.setToolTip(
                self.voice_modeling_text(
                    "Batch size controls samples per training step; higher values use more VRAM."
                )
            )
        return defaults

    def voice_modeling_cuda_total_memory_bytes(self) -> int:
        runtime_info = getattr(self, "stt_runtime_info", {}) or {}
        try:
            return max(0, int(runtime_info.get("cuda_total_memory_bytes", 0)))
        except (TypeError, ValueError):
            return 0

    def select_voice_modeling_output_folder(self) -> None:
        initial = self.voice_modeling_output_picker.text() or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, self.voice_modeling_text("Select model output folder"), initial)
        if path:
            self.voice_modeling_output_picker.set_text(path)
            self.update_voice_modeling_buttons()
            self.mark_voice_modeling_preflight_stale()

    def current_voice_modeling_preflight_snapshot(self) -> dict:
        return {
            "export_info": dict(self.voice_modeling_export_info) if self.voice_modeling_export_info else None,
            "output_dir": self.voice_modeling_output_picker.text()
            if hasattr(self, "voice_modeling_output_picker")
            else "",
            "resume_checkpoint": "",
            "device": self.voice_modeling_device_key() if hasattr(self, "voice_modeling_device_combo") else "auto",
        }

    def mark_voice_modeling_preflight_stale(self) -> None:
        if not hasattr(self, "voice_modeling_preflight_label"):
            return
        self._voice_modeling_preflight_stale = True
        self.voice_modeling_preflight_ok = False
        self.voice_modeling_preflight_label.setText(
            self.voice_modeling_text("Preflight needs refresh after configuration changes.")
        )
        self.voice_modeling_preflight_box.setObjectName("WarningBox")
        self.voice_modeling_preflight_box.style().unpolish(self.voice_modeling_preflight_box)
        self.voice_modeling_preflight_box.style().polish(self.voice_modeling_preflight_box)
        self.update_voice_modeling_buttons()

    def refresh_voice_modeling_preflight_async(self) -> None:
        if not hasattr(self, "voice_modeling_preflight_label"):
            return
        if getattr(self, "_voice_modeling_preflight_refreshing", False):
            return
        snapshot = self.current_voice_modeling_preflight_snapshot()
        export_info = snapshot["export_info"]
        output_dir = snapshot["output_dir"]
        resume_checkpoint = snapshot["resume_checkpoint"]
        device = snapshot["device"]
        self._voice_modeling_preflight_refreshing = True
        self._voice_modeling_preflight_stale = False
        self._voice_modeling_preflight_snapshot = snapshot
        self.voice_modeling_preflight_refresh_button.setEnabled(False)
        self.voice_modeling_preflight_label.setText(
            self.voice_modeling_text("Checking Voice Modeling prerequisites...")
        )
        threading.Thread(
            target=self.refresh_voice_modeling_preflight_worker,
            args=(snapshot, export_info, output_dir, resume_checkpoint, device),
            daemon=True,
        ).start()

    def refresh_voice_modeling_preflight_worker(
        self,
        snapshot: dict,
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
        self.post(self.voice_modeling_preflight_finished, snapshot, result)

    def voice_modeling_preflight_finished(self, snapshot: dict, result) -> None:
        self._voice_modeling_preflight_refreshing = False
        if (
            getattr(self, "_voice_modeling_preflight_stale", False)
            or snapshot != self.current_voice_modeling_preflight_snapshot()
        ):
            self._voice_modeling_preflight_snapshot = None
            self.mark_voice_modeling_preflight_stale()
            self.refresh_home_diagnostics()
            self.update_voice_modeling_dvae_status()
            return
        self._voice_modeling_preflight_stale = False
        self.voice_modeling_preflight_ok = bool(result["ok"])
        self.voice_modeling_preflight_details = result["details"]
        self.voice_modeling_preflight_label.setText(result["summary"])
        self.voice_modeling_preflight_details_box.setPlainText("\n".join(result["details"]))
        self.voice_modeling_preflight_box.setObjectName("GoodBox" if result["ok"] else "WarningBox")
        self.voice_modeling_preflight_box.style().unpolish(self.voice_modeling_preflight_box)
        self.voice_modeling_preflight_box.style().polish(self.voice_modeling_preflight_box)
        self.update_voice_modeling_buttons()
        self.refresh_home_diagnostics()
        self.update_voice_modeling_dvae_status()

    def update_voice_modeling_dvae_status(self) -> None:
        if not hasattr(self, "voice_modeling_download_dvae_button"):
            return
        ready = local_tts_dvae_ready() and local_tts_mel_stats_ready()
        running = getattr(self, "voice_modeling_dvae_download_running", False)
        cancel_requested = getattr(self, "voice_modeling_dvae_cancel_requested", False)
        self.voice_modeling_download_dvae_button.setEnabled(not ready and not running)
        self.voice_modeling_download_dvae_button.setVisible(not ready)
        self.voice_modeling_cancel_dvae_button.setEnabled(running and not cancel_requested)
        self.voice_modeling_cancel_dvae_button.setVisible(running)
        if ready:
            self.voice_modeling_dvae_progress.hide()
        elif running:
            self.voice_modeling_dvae_progress.show()
        else:
            self.voice_modeling_dvae_progress.hide()

    def confirm_xtts_dvae_download(self) -> bool:
        return self.ask_question(
            self.voice_modeling_text("Download XTTS-v2 training assets"),
            self.voice_modeling_text(
                "XTTS-v2 DVAE is about 211 MB and mel_stats.pth is also needed for voice modeling/fine-tuning.\n\n"
                "The file is distributed with XTTS-v2 under the Coqui Public Model License, "
                "limited to non-commercial use.\n\n"
                "Download the missing training asset(s) now?"
            ),
        )

    def start_xtts_dvae_download(self) -> None:
        if local_tts_dvae_ready() and local_tts_mel_stats_ready():
            self.update_voice_modeling_dvae_status()
            self.show_info(
                self.voice_modeling_text("Voice Modeling"),
                self.voice_modeling_text(
                    "XTTS-v2 training assets are already downloaded:\n"
                    "{dvae_path}\n{mel_stats_path}",
                    dvae_path=local_tts_dvae_path(),
                    mel_stats_path=local_tts_mel_stats_path(),
                ),
            )
            return
        if not self.confirm_xtts_dvae_download():
            self.voice_modeling_status.setText(self.voice_modeling_text("Training assets download cancelled."))
            return
        self.voice_modeling_dvae_download_running = True
        self.voice_modeling_dvae_cancel_requested = False
        self.voice_modeling_dvae_progress.setRange(0, 100)
        self.voice_modeling_dvae_progress.setValue(0)
        self.voice_modeling_dvae_progress.setFormat("%p%")
        self.voice_modeling_dvae_progress.show()
        self.voice_modeling_preflight_label.setText(
            self.voice_modeling_text("Downloading XTTS-v2 training assets...")
        )
        self.update_voice_modeling_dvae_status()
        threading.Thread(target=self.xtts_dvae_download_worker, daemon=True).start()

    def xtts_dvae_download_worker(self) -> None:
        try:
            paths = download_xtts_training_assets(
                progress_callback=lambda percent: self.post(self.update_voice_modeling_dvae_progress, percent),
                should_cancel=lambda: self.voice_modeling_dvae_cancel_requested,
            )
        except VoiceModelingDownloadCancelled:
            self.post(self.xtts_dvae_download_cancelled)
            return
        except (OSError, ValueError, TimeoutError) as exc:
            self.post(self.xtts_dvae_download_failed, str(exc))
            return
        self.post(self.xtts_dvae_download_succeeded, "\n".join(str(path) for path in paths))

    def update_voice_modeling_dvae_progress(self, percent: float) -> None:
        self.show_percent_progress(self.voice_modeling_dvae_progress, percent)

    def cancel_xtts_dvae_download(self) -> None:
        if not getattr(self, "voice_modeling_dvae_download_running", False):
            return
        self.voice_modeling_dvae_cancel_requested = True
        self.voice_modeling_status.setText(self.voice_modeling_text("Cancelling training assets download..."))
        self.voice_modeling_preflight_label.setText(
            self.voice_modeling_text("Cancelling training assets download...")
        )
        self.update_voice_modeling_dvae_status()

    def xtts_dvae_download_cancelled(self) -> None:
        self.voice_modeling_dvae_download_running = False
        self.voice_modeling_dvae_cancel_requested = False
        self.voice_modeling_status.setText(self.voice_modeling_text("Training assets download cancelled."))
        self.voice_modeling_preflight_label.setText(
            self.voice_modeling_text("Training assets download cancelled.")
        )
        self.update_voice_modeling_dvae_status()
        self.refresh_home_diagnostics()

    def xtts_dvae_download_succeeded(self, path: str) -> None:
        self.voice_modeling_dvae_download_running = False
        self.voice_modeling_dvae_cancel_requested = False
        self.voice_modeling_status.setText(self.voice_modeling_text("XTTS-v2 training assets ready."))
        self.update_voice_modeling_dvae_status()
        self.refresh_home_diagnostics()
        self.refresh_voice_modeling_preflight_async()
        self.show_info(
            self.voice_modeling_text("Voice Modeling"),
            self.voice_modeling_text("XTTS-v2 training assets ready:\n{path}", path=path),
        )

    def xtts_dvae_download_failed(self, message: str) -> None:
        self.voice_modeling_dvae_download_running = False
        self.voice_modeling_dvae_cancel_requested = False
        self.voice_modeling_status.setText(self.voice_modeling_text("Training assets download failed."))
        self.update_voice_modeling_dvae_status()
        self.show_error(self.voice_modeling_text("Voice Modeling"), message)

    def save_voice_modeling_config(self) -> None:
        export_info = self.voice_modeling_export_info or self.validate_voice_modeling_dataset()
        if not export_info:
            self.show_error(
                self.voice_modeling_text("Voice Modeling"),
                self.voice_modeling_text("Select a valid exported dataset first."),
            )
            return
        try:
            config = build_voice_modeling_job_config(
                export_info,
                output_dir=self.voice_modeling_output_picker.text(),
                resume_checkpoint="",
                device=self.voice_modeling_device_key(),
                max_epochs=self.voice_modeling_epochs_spin.value(),
                batch_size=self.voice_modeling_batch_spin.value(),
            )
            config_path = save_voice_modeling_job_config(config)
        except (OSError, ValueError) as exc:
            self.voice_modeling_status.setText(self.voice_modeling_text("Error."))
            self.show_error(self.voice_modeling_text("Voice Modeling"), str(exc))
            return
        self.voice_modeling_status.setText(
            self.voice_modeling_text("Training job configured: {path}", path=config_path)
        )
        self.voice_modeling_saved_config_path = str(config_path)
        self.voice_modeling_saved_config_snapshot = self.current_voice_modeling_config_snapshot()
        self.voice_modeling_config_dirty = False
        if hasattr(self, "refresh_voice_training_jobs"):
            self.refresh_voice_training_jobs(str(config_path))
        self.update_local_voice_tabs()
        self.update_voice_modeling_buttons()

    def go_to_voice_training(self) -> None:
        config_path = getattr(self, "voice_modeling_saved_config_path", "")
        if not config_path or getattr(self, "voice_modeling_config_dirty", True):
            return
        self.refresh_voice_training_jobs(config_path)
        if hasattr(self, "open_local_voice_workflow_tab"):
            self.open_local_voice_workflow_tab(3)
        else:
            self.show_local_voices_tab(3)

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
        config_path = getattr(self, "voice_modeling_saved_config_path", "")
        config_dirty = getattr(self, "voice_modeling_config_dirty", True)
        preflight_refreshing = getattr(self, "_voice_modeling_preflight_refreshing", False)
        self.voice_modeling_save_config_button.setEnabled(has_dataset and has_output and config_dirty)
        if hasattr(self, "voice_modeling_go_training_button"):
            self.voice_modeling_go_training_button.setEnabled(
                has_dataset and has_output and bool(config_path) and not config_dirty
            )
        self.voice_modeling_open_output_button.setEnabled(has_output)
        if hasattr(self, "voice_modeling_preflight_refresh_button"):
            self.voice_modeling_preflight_refresh_button.setEnabled(
                has_dataset and has_output and not preflight_refreshing
            )

    def build_voice_modeling_page(self, include_header: bool = True):
        page, layout = self.page_container()
        if not include_header:
            layout.setContentsMargins(0, 26, 14, 24)
        if include_header:
            self.page_header(
                layout,
                "Voice Modeling",
                "Validate an exported dataset and prepare a controlled XTTS-v2 training job configuration.",
            )

        grid = QGridLayout()
        grid.setSpacing(16)
        layout.addLayout(grid)

        dataset_card = Card("Selected dataset export")
        dataset_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.voice_modeling_dataset_info = QPlainTextEdit()
        self.voice_modeling_dataset_info.setObjectName("LogBox")
        self.voice_modeling_dataset_info.setReadOnly(True)
        self.voice_modeling_dataset_info.setMinimumHeight(240)
        self.voice_modeling_dataset_info.setPlainText("Use Dataset > Setup Dataset first.")
        dataset_card.content_layout.addWidget(self.voice_modeling_dataset_info)

        config_card = Card("Training configuration")
        config_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.voice_modeling_output_picker = FilePicker("Model output folder")
        self.voice_modeling_output_picker.button.clicked.connect(self.select_voice_modeling_output_folder)
        self.voice_modeling_output_picker.edit.textChanged.connect(
            lambda _text: self.mark_voice_modeling_config_changed()
        )
        self.voice_modeling_output_picker.edit.textChanged.connect(
            lambda _text: self.mark_voice_modeling_preflight_stale()
        )
        self.voice_modeling_device_combo = QComboBox()
        self.populate_voice_modeling_device_combo()
        self.voice_modeling_device_combo.currentTextChanged.connect(lambda _text: self.voice_modeling_device_changed())
        self.voice_modeling_epochs_spin = QSpinBox()
        self.voice_modeling_epochs_spin.setRange(1, 500)
        self.voice_modeling_epochs_spin.setValue(VOICE_MODELING_DEFAULT_MAX_EPOCHS)
        self.voice_modeling_epochs_spin.valueChanged.connect(lambda _value: self.mark_voice_modeling_config_changed())
        self.voice_modeling_batch_spin = QSpinBox()
        self.voice_modeling_batch_spin.setRange(1, 16)
        self.voice_modeling_batch_spin.setValue(VOICE_MODELING_DEFAULT_BATCH_SIZE)
        self.voice_modeling_batch_spin.valueChanged.connect(lambda _value: self.mark_voice_modeling_config_changed())
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
        preflight_actions = QHBoxLayout()
        preflight_actions.setContentsMargins(0, 0, 0, 0)
        self.voice_modeling_download_dvae_button = QPushButton("Download training assets")
        self.voice_modeling_download_dvae_button.clicked.connect(self.start_xtts_dvae_download)
        self.voice_modeling_cancel_dvae_button = QPushButton("Cancel download")
        self.voice_modeling_cancel_dvae_button.clicked.connect(self.cancel_xtts_dvae_download)
        self.voice_modeling_preflight_refresh_button = QPushButton("Refresh preflight")
        self.voice_modeling_preflight_refresh_button.clicked.connect(self.refresh_voice_modeling_preflight_async)
        preflight_actions.addWidget(self.voice_modeling_download_dvae_button)
        preflight_actions.addWidget(self.voice_modeling_cancel_dvae_button)
        preflight_actions.addStretch(1)
        preflight_actions.addWidget(self.voice_modeling_preflight_refresh_button)
        self.voice_modeling_dvae_progress = QProgressBar()
        self.voice_modeling_dvae_progress.hide()
        preflight_box_layout.addWidget(self.voice_modeling_preflight_label)
        preflight_box_layout.addWidget(self.voice_modeling_preflight_details_box)
        preflight_box_layout.addWidget(self.voice_modeling_dvae_progress)
        preflight_box_layout.addLayout(preflight_actions)
        preflight_card.content_layout.addWidget(self.voice_modeling_preflight_box)

        actions_card = Card()
        actions_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        self.voice_modeling_save_config_button = QPushButton("Save Config")
        self.voice_modeling_save_config_button.setObjectName("FlowButton")
        self.voice_modeling_go_training_button = QPushButton("Go to Training")
        self.voice_modeling_go_training_button.setObjectName("FlowButton")
        self.voice_modeling_open_output_button = QPushButton("Open output folder")
        self.voice_modeling_save_config_button.clicked.connect(self.save_voice_modeling_config)
        self.voice_modeling_go_training_button.clicked.connect(self.go_to_voice_training)
        self.voice_modeling_open_output_button.clicked.connect(self.open_voice_modeling_output_folder)
        action_row.addWidget(self.voice_modeling_save_config_button)
        action_row.addWidget(self.voice_modeling_go_training_button)
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
        self.voice_modeling_selected_export_path = ""
        self.voice_modeling_saved_config_path = ""
        self.voice_modeling_saved_config_snapshot = None
        self.voice_modeling_config_dirty = True
        self.voice_modeling_preflight_ok = False
        self.voice_modeling_preflight_details = []
        self.voice_modeling_auto_preflight_enabled = False
        self.voice_modeling_dvae_download_running = False
        self.voice_modeling_dvae_cancel_requested = False
        self.update_voice_modeling_device_options()
        self.refresh_voice_modeling_exports()
        self.voice_modeling_auto_preflight_enabled = True
        self.update_voice_modeling_dvae_status()
        self.update_voice_modeling_buttons()
        return page
