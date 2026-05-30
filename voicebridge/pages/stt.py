import os
import subprocess
import tempfile
import threading
from contextlib import suppress
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from voicebridge.app_paths import external_base_dir, stt_python_path, stt_worker_path
from voicebridge.constants import (
    MISSING_ALIGNMENT_PREFIX,
    STT_DEVICE_BY_LABEL,
    STT_DEVICE_LABEL_BY_KEY,
    STT_DEVICE_LABELS,
    STT_MODE_LABELS,
    STT_MODEL,
    STT_SRT_MODES,
)
from voicebridge.languages import language_name
from voicebridge.readers import read_input_file
from voicebridge.stt_preflight import check_stt_preflight
from voicebridge.ui.helpers import open_path
from voicebridge.ui.widgets import Card, FilePicker


class SttWorkflowMixin:
    def stt_mode_key(self):
        return STT_MODE_LABELS.get(self.stt_mode_combo.currentText(), "transcript")

    def stt_language_key(self):
        language_code = self.stt_language_combo.currentData(Qt.ItemDataRole.UserRole)
        return language_code if isinstance(language_code, str) else "auto"

    def stt_device_key(self):
        device = self.stt_device_combo.currentData(Qt.ItemDataRole.UserRole)
        return device if isinstance(device, str) and device in STT_DEVICE_LABEL_BY_KEY else "auto"

    def set_stt_device_key(self, device):
        device = device if isinstance(device, str) and device in STT_DEVICE_LABEL_BY_KEY else "auto"
        for index in range(self.stt_device_combo.count()):
            if self.stt_device_combo.itemData(index, Qt.ItemDataRole.UserRole) == device:
                self.stt_device_combo.setCurrentIndex(index)
                return

    def stt_device_changed(self):
        device = self.stt_device_key()
        if device == "cuda" and not self.stt_cuda_available:
            self.set_stt_device_key("auto")
            device = "auto"
        self.preferred_stt_device_key = device
        self.save_user_settings()

    def update_stt_device_options(self):
        if not hasattr(self, "stt_device_combo"):
            return
        selected_device = self.preferred_stt_device_key
        if selected_device == "cuda" and not self.stt_cuda_available:
            selected_device = "auto"

        self.stt_device_combo.blockSignals(True)
        try:
            for index in range(self.stt_device_combo.count()):
                device = self.stt_device_combo.itemData(index, Qt.ItemDataRole.UserRole)
                item = self.stt_device_combo.model().item(index)
                enabled = device != "cuda" or self.stt_cuda_available
                if item is not None:
                    item.setEnabled(enabled)
                if device == "auto":
                    tooltip = "Uses CUDA when available; otherwise falls back to CPU."
                elif device == "cpu":
                    tooltip = "Forces CPU execution."
                elif enabled:
                    tooltip = "Uses the detected CUDA GPU."
                else:
                    tooltip = "CUDA is not available in the current STT runtime on this machine."
                self.stt_device_combo.setItemData(index, tooltip, Qt.ItemDataRole.ToolTipRole)
            self.set_stt_device_key(selected_device)
        finally:
            self.stt_device_combo.blockSignals(False)

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
        ok, summary, details, runtime_info = check_stt_preflight()
        self.post(self.stt_preflight_finished, ok, summary, details, runtime_info)

    def stt_preflight_finished(self, ok, summary, details, runtime_info):
        self._stt_preflight_refreshing = False
        self.stt_preflight_ok = ok
        self.stt_preflight_details = details
        self.stt_cuda_available = bool(runtime_info.get("cuda_available"))
        self.stt_runtime_detail = runtime_info.get("detail", "STT runtime inspected.")
        self.update_stt_device_options()
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
        if not media_path:
            raise ValueError("Please select an audio or video file.")
        if not os.path.isfile(media_path):
            raise ValueError("The selected media file does not exist.")
        if not output_path:
            raise ValueError("Please choose where to save the output file.")
        device = self.stt_device_key()
        if device == "cuda" and not self.stt_cuda_available:
            raise ValueError("CUDA is not available in the current STT runtime on this machine.")
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
        self.stt_device_combo = QComboBox()
        self.stt_device_combo.addItems(STT_DEVICE_LABELS)
        for index in range(self.stt_device_combo.count()):
            label = self.stt_device_combo.itemText(index)
            self.stt_device_combo.setItemData(index, STT_DEVICE_BY_LABEL[label], Qt.ItemDataRole.UserRole)
        self.stt_device_combo.currentTextChanged.connect(lambda _text: self.stt_device_changed())
        self.update_stt_device_options()
        settings_card.content_layout.addWidget(QLabel("Mode"))
        settings_card.content_layout.addWidget(self.stt_mode_combo)
        settings_row = QHBoxLayout()
        settings_row.addWidget(QLabel("Language"))
        settings_row.addWidget(self.stt_language_combo, 1)
        settings_row.addWidget(QLabel("Device"))
        settings_row.addWidget(self.stt_device_combo)
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

