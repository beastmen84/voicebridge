import threading
from contextlib import suppress
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar, QPushButton, QSizePolicy

from voicebridge.app_paths import external_base_dir, ml_python_path, voice_modeling_worker_path
from voicebridge.process_jobs import WorkerProcessOutput, run_worker_process_job
from voicebridge.runtime_errors import is_cuda_runtime_failure
from voicebridge.ui.helpers import open_path
from voicebridge.ui.widgets import Card
from voicebridge.voice_modeling import (
    build_voice_modeling_training_command,
    cleanup_incomplete_voice_modeling_job,
    list_voice_modeling_job_configs,
    load_voice_modeling_job_config,
    prepare_voice_modeling_training_job,
    prune_previous_voice_modeling_outputs,
    save_voice_modeling_job_config,
    update_voice_modeling_job_status,
    voice_modeling_job_label,
    voice_modeling_training_plan_text,
)

VOICE_TRAINING_PREPARE_STATUSES = {"", "configured", "failed", "cancelled"}
VOICE_TRAINING_DRY_RUN_STATUSES = {"prepared"}
VOICE_TRAINING_START_STATUSES = {"dry_run_ok"}


# noinspection PyAttributeOutsideInit,PyUnresolvedReferences
class VoiceTrainingWorkflowMixin:
    def voice_training_text(self, text: str, **kwargs) -> str:
        if kwargs and hasattr(self, "format_static_ui_text"):
            return self.format_static_ui_text(text, **kwargs)
        if kwargs:
            return text.format(**kwargs)
        return self.static_ui_text(text) if hasattr(self, "static_ui_text") else text

    def selected_voice_training_job_path(self) -> str:
        config_path = self.voice_training_job_combo.currentData(Qt.ItemDataRole.UserRole)
        return config_path if isinstance(config_path, str) else ""

    def selected_voice_training_job_status(self) -> str:
        config_path = self.selected_voice_training_job_path()
        if not config_path:
            return ""
        try:
            config = load_voice_modeling_job_config(config_path)
        except (OSError, ValueError):
            return ""
        status = config.get("status", "")
        return status if isinstance(status, str) else ""

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
                self.voice_training_job_combo.addItem(self.voice_training_text("No training jobs configured."), "")
                item = self.voice_training_job_combo.model().item(0)
                if item is not None:
                    item.setEnabled(False)
                self.voice_training_job_status.setPlainText(
                    self.voice_training_text("Save a training config from Setup first.")
                )
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

    def refresh_voice_training_jobs_preserving_status(self, selected_path: str = "") -> None:
        status_text = ""
        if hasattr(self, "voice_training_job_status"):
            status_text = self.voice_training_job_status.toPlainText()
        self.refresh_voice_training_jobs(selected_path)
        if status_text and hasattr(self, "voice_training_job_status"):
            self.voice_training_job_status.setPlainText(status_text)

    def voice_training_job_changed(self) -> None:
        config_path = self.selected_voice_training_job_path()
        if not config_path:
            self.voice_training_job_status.setPlainText(self.voice_training_text("No training job selected."))
            self.update_voice_training_buttons()
            return
        self.voice_training_job_status.setPlainText(
            self.voice_training_text("Selected job config:\n{path}", path=config_path)
        )
        self.update_voice_training_buttons()

    def update_voice_training_buttons(self) -> None:
        if not hasattr(self, "voice_training_open_folder_button"):
            return
        has_job = bool(self.selected_voice_training_job_path())
        status = self.selected_voice_training_job_status() if has_job else ""
        running = getattr(self, "voice_training_running", False)
        cancel_requested = getattr(self, "voice_training_cancel_requested", False)
        self.voice_training_job_combo.setEnabled(not running)
        self.voice_training_open_folder_button.setEnabled(has_job and not running)
        self.voice_training_prepare_button.setEnabled(
            has_job and not running and status in VOICE_TRAINING_PREPARE_STATUSES
        )
        self.voice_training_dry_run_button.setEnabled(
            has_job and not running and status in VOICE_TRAINING_DRY_RUN_STATUSES
        )
        self.voice_training_start_button.setEnabled(
            has_job and not running and status in VOICE_TRAINING_START_STATUSES
        )
        self.voice_training_cancel_button.setEnabled(running and not cancel_requested)
        self.voice_training_refresh_jobs_button.setEnabled(not running)

    def open_selected_voice_training_job_folder(self) -> None:
        config_path = self.selected_voice_training_job_path()
        if config_path:
            open_path(Path(config_path).parent)

    def prepare_selected_voice_training_job(self) -> None:
        config_path = self.selected_voice_training_job_path()
        if not config_path:
            return
        try:
            plan = prepare_voice_modeling_training_job(config_path)
        except (OSError, ValueError) as exc:
            self.voice_training_job_status.setPlainText(str(exc))
            self.show_error(self.voice_training_text("Voice Training"), str(exc))
            return
        self.refresh_voice_training_jobs(config_path)
        self.voice_training_job_status.setPlainText(voice_modeling_training_plan_text(plan))
        self.update_local_voice_tabs()

    def start_voice_training_dry_run(self) -> None:
        if self.selected_voice_training_job_status() not in VOICE_TRAINING_DRY_RUN_STATUSES:
            return
        self.start_voice_training_worker(dry_run=True)

    def start_voice_training_run(self) -> None:
        if self.selected_voice_training_job_status() not in VOICE_TRAINING_START_STATUSES:
            return
        if not self.ask_question(
            self.voice_training_text("Start voice training"),
            self.voice_training_text(
                "This will start XTTS-v2 fine-tuning in the ML runtime and can take a long time.\n\n"
                "Continue?"
            ),
            default_yes=False,
        ):
            return
        self.start_voice_training_worker(dry_run=False)

    def start_voice_training_worker(self, *, dry_run: bool) -> None:
        config_path = self.selected_voice_training_job_path()
        if not config_path:
            return
        self.start_voice_training_worker_for_config(config_path, dry_run=dry_run)

    def start_voice_training_worker_for_config(self, config_path: str, *, dry_run: bool) -> None:
        python_path = ml_python_path()
        worker_path = voice_modeling_worker_path()
        if not python_path.is_file():
            self.show_error(
                self.voice_training_text("Voice Training"),
                self.voice_training_text("Could not find the ML Python runtime:\n{path}", path=python_path),
            )
            return
        if not worker_path.is_file():
            self.show_error(
                self.voice_training_text("Voice Training"),
                self.voice_training_text("Could not find:\n{path}", path=worker_path),
            )
            return
        self.voice_training_running = True
        self.voice_training_cancel_requested = False
        self.voice_training_running_config_path = config_path
        self.voice_training_running_dry_run = dry_run
        self.voice_training_progress.setValue(0)
        self.voice_training_progress.show()
        self.voice_training_job_status.clear()
        self.append_voice_training_log(
            self.voice_training_text("Starting dry run...")
            if dry_run
            else self.voice_training_text("Starting training...")
        )
        self.update_voice_training_buttons()
        threading.Thread(
            target=self.voice_training_worker,
            args=(build_voice_modeling_training_command(config_path, dry_run=dry_run), dry_run),
            daemon=True,
        ).start()

    def voice_training_worker(self, command: list[str], dry_run: bool) -> None:
        try:
            result = run_worker_process_job(
                command,
                cwd=str(external_base_dir()),
                on_process_start=lambda process: setattr(self, "voice_training_process", process),
                on_output=self.handle_voice_training_worker_output,
                should_cancel=lambda: self.voice_training_cancel_requested,
            )
            if result.cancelled:
                self.post(self.voice_training_cancelled)
                return
            if result.return_code != 0:
                raise RuntimeError(
                    "\n".join(result.recent_output[-10:])
                    or f"Voice training exited with code {result.return_code}."
                )
            self.post(self.voice_training_succeeded, dry_run)
        except (OSError, RuntimeError, AssertionError) as exc:
            self.post(self.voice_training_failed, str(exc))
        finally:
            self.voice_training_process = None
            self.post(self.finish_voice_training_worker)

    def handle_voice_training_worker_output(self, output: WorkerProcessOutput) -> None:
        if output.is_progress:
            if output.progress_percent is not None:
                self.post(self.update_voice_training_progress_percent, output.progress_percent)
            return
        self.post(self.append_voice_training_log, output.line)

    def update_voice_training_progress_percent(self, percent: float) -> None:
        self.show_percent_progress(self.voice_training_progress, percent)

    def append_voice_training_log(self, message: str) -> None:
        if not hasattr(self, "voice_training_job_status"):
            return
        self.voice_training_job_status.appendPlainText(message)

    def voice_training_succeeded(self, dry_run: bool) -> None:
        self.append_voice_training_log(
            self.voice_training_text("Dry run completed.")
            if dry_run
            else self.voice_training_text("Training completed.")
        )
        config_path = getattr(self, "voice_training_running_config_path", "")
        if not dry_run and config_path:
            with suppress(OSError, ValueError):
                deleted_outputs = prune_previous_voice_modeling_outputs(config_path)
                if deleted_outputs:
                    self.append_voice_training_log(
                        self.voice_training_text(
                            "Removed {count} previous trained model output(s) for this profile.",
                            count=len(deleted_outputs),
                        )
                    )
        self.refresh_voice_training_jobs_preserving_status(config_path)
        self.refresh_local_voice_profile_combo()
        self.update_local_voice_tabs()

    def voice_training_failed(self, message: str) -> None:
        self.append_voice_training_log(f"ERROR: {message}")
        config_path = getattr(self, "voice_training_running_config_path", "") or self.selected_voice_training_job_path()
        if (
            is_cuda_runtime_failure(message)
            and self.ask_question(
                self.voice_training_text("Voice Training CUDA failed"),
                self.voice_training_text(
                    "Voice training failed in the CUDA runtime.\n\nSwitch this job to CPU and retry?"
                ),
                default_yes=False,
            )
        ):
            try:
                config = load_voice_modeling_job_config(config_path)
                config["device"] = "cpu"
                save_voice_modeling_job_config(config)
            except (OSError, ValueError) as exc:
                self.show_error(
                    self.voice_training_text("Voice Training"),
                    self.voice_training_text("Could not switch the training job to CPU.\n\n{message}", message=exc),
                )
            else:
                self.append_voice_training_log(self.voice_training_text("Job switched to CPU. Retrying..."))
                self.refresh_voice_training_jobs_preserving_status(config_path)
                QTimer.singleShot(250, lambda: self.start_voice_training_worker_for_config(config_path, dry_run=False))
                return
        if config_path and not getattr(self, "voice_training_running_dry_run", False):
            with suppress(OSError, ValueError):
                cleanup = cleanup_incomplete_voice_modeling_job(config_path, reason="failed")
                if cleanup["archive_dir"]:
                    self.append_voice_training_log(
                        self.voice_training_text("Training log archived: {path}", path=cleanup["archive_dir"])
                    )
        self.show_error(self.voice_training_text("Voice Training"), message)
        self.refresh_voice_training_jobs_preserving_status(config_path)
        self.update_local_voice_tabs()

    def voice_training_cancelled(self) -> None:
        self.append_voice_training_log(self.voice_training_text("Cancelled."))
        config_path = getattr(self, "voice_training_running_config_path", "") or self.selected_voice_training_job_path()
        if config_path:
            with suppress(OSError, ValueError):
                update_voice_modeling_job_status(config_path, "cancelled")
            if not getattr(self, "voice_training_running_dry_run", False):
                with suppress(OSError, ValueError):
                    cleanup = cleanup_incomplete_voice_modeling_job(config_path, reason="cancelled")
                    if cleanup["archive_dir"]:
                        self.append_voice_training_log(
                            self.voice_training_text("Training log archived: {path}", path=cleanup["archive_dir"])
                        )
            self.refresh_voice_training_jobs_preserving_status(config_path)
            self.update_local_voice_tabs()

    def finish_voice_training_worker(self) -> None:
        self.voice_training_running = False
        self.voice_training_running_config_path = ""
        self.voice_training_running_dry_run = False
        self.voice_training_progress.hide()
        self.update_voice_training_buttons()

    def cancel_voice_training(self) -> None:
        if not getattr(self, "voice_training_running", False):
            return
        self.voice_training_cancel_requested = True
        process = getattr(self, "voice_training_process", None)
        if process is not None and process.poll() is None:
            process.terminate()
        self.append_voice_training_log(self.voice_training_text("Cancelling..."))
        self.update_voice_training_buttons()

    def build_voice_training_page(self, include_header: bool = True):
        page, layout = self.page_container()
        if not include_header:
            layout.setContentsMargins(0, 26, 0, 24)
        if include_header:
            self.page_header(
                layout,
                "Training",
                "Run configured local voice training jobs.",
            )

        jobs_card = Card("Training jobs")
        jobs_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.voice_training_job_combo = QComboBox()
        self.voice_training_job_combo.currentIndexChanged.connect(lambda _index: self.voice_training_job_changed())
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        self.voice_training_refresh_jobs_button = QPushButton("Refresh")
        self.voice_training_prepare_button = QPushButton("Prepare")
        self.voice_training_dry_run_button = QPushButton("Dry run")
        self.voice_training_start_button = QPushButton("Start training")
        self.voice_training_start_button.setObjectName("PrimaryButton")
        self.voice_training_cancel_button = QPushButton("Cancel")
        self.voice_training_open_folder_button = QPushButton("Open job folder")
        self.voice_training_refresh_jobs_button.clicked.connect(self.refresh_voice_training_jobs)
        self.voice_training_prepare_button.clicked.connect(self.prepare_selected_voice_training_job)
        self.voice_training_dry_run_button.clicked.connect(self.start_voice_training_dry_run)
        self.voice_training_start_button.clicked.connect(self.start_voice_training_run)
        self.voice_training_cancel_button.clicked.connect(self.cancel_voice_training)
        self.voice_training_open_folder_button.clicked.connect(self.open_selected_voice_training_job_folder)
        actions.addWidget(self.voice_training_refresh_jobs_button)
        actions.addWidget(self.voice_training_prepare_button)
        actions.addWidget(self.voice_training_dry_run_button)
        actions.addWidget(self.voice_training_start_button)
        actions.addWidget(self.voice_training_cancel_button)
        actions.addStretch(1)
        actions.addWidget(self.voice_training_open_folder_button)
        self.voice_training_progress = QProgressBar()
        self.voice_training_progress.hide()
        self.voice_training_job_status = QPlainTextEdit()
        self.voice_training_job_status.setObjectName("LogBox")
        self.voice_training_job_status.setReadOnly(True)
        self.voice_training_job_status.setMinimumHeight(260)
        jobs_card.content_layout.addWidget(QLabel("Job config"))
        jobs_card.content_layout.addWidget(self.voice_training_job_combo)
        jobs_card.content_layout.addLayout(actions)
        jobs_card.content_layout.addWidget(self.voice_training_progress)
        jobs_card.content_layout.addWidget(self.voice_training_job_status)
        layout.addWidget(jobs_card)
        layout.addStretch(1)
        self.voice_training_running = False
        self.voice_training_cancel_requested = False
        self.voice_training_process = None
        self.refresh_voice_training_jobs()
        return page
