import re
import subprocess
import threading
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
)

from voicebridge.constants import (
    AUDIO_CLEANUP_ACTION_BY_LABEL,
    AUDIO_CLEANUP_ACTION_DESCRIPTIONS,
    AUDIO_CLEANUP_ACTION_LABELS,
    AUDIO_CLEANUP_REMOVE_LABEL,
)
from voicebridge.media_tools import (
    SUPPORTED_AUDIO_SUFFIXES,
    audio_cleanup_command,
    find_ffmpeg_exe,
    probe_audio_info,
    suggest_audio_cleanup_output_path,
)
from voicebridge.ui.helpers import open_path
from voicebridge.ui.widgets import Card, FilePicker


class AudioCleanupWorkflowMixin:
    def audio_cleanup_input_changed(self):
        self.audio_cleanup_last_output_path = ""
        self.update_audio_cleanup_output(force=False)
        self.refresh_audio_cleanup_input_info()
        self.update_audio_cleanup_button_state()
        self.save_user_settings()

    def audio_cleanup_action_changed(self, text):
        self.audio_cleanup_action_description.setText(AUDIO_CLEANUP_ACTION_DESCRIPTIONS.get(text, ""))
        self.save_user_settings()

    def update_audio_cleanup_output(self, force=False):
        if not hasattr(self, "audio_cleanup_output_picker"):
            return
        input_path = self.audio_cleanup_input_picker.text()
        if not input_path:
            return
        suggested = suggest_audio_cleanup_output_path(input_path)
        current = self.audio_cleanup_output_picker.text()
        if force or not current or current == self.audio_cleanup_last_auto_output_path:
            self.audio_cleanup_output_picker.set_text(suggested)
            self.audio_cleanup_last_auto_output_path = suggested

    def select_audio_cleanup_input_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select audio file",
            self.audio_cleanup_input_picker.text() or str(Path.home()),
            "Audio files (*.mp3 *.wav *.m4a *.aac *.flac *.ogg);;All files (*.*)",
        )
        if path:
            self.audio_cleanup_input_picker.set_text(path)
            self.update_audio_cleanup_output(force=False)
            self.save_user_settings()

    def select_audio_cleanup_output_file(self):
        input_path = self.audio_cleanup_input_picker.text()
        suggested = self.audio_cleanup_output_picker.text() or (
            suggest_audio_cleanup_output_path(input_path) if input_path else str(Path.home() / "audio_cleaned.mp3")
        )
        filter_text = (
            "MP3 audio (*.mp3);;WAV audio (*.wav);;M4A audio (*.m4a);;"
            "AAC audio (*.aac);;FLAC audio (*.flac);;OGG audio (*.ogg);;All files (*.*)"
        )
        path, selected_filter = QFileDialog.getSaveFileName(self, "Save cleaned audio as", suggested, filter_text)
        if path:
            default_suffix = self.audio_cleanup_output_suffix_from_filter(selected_filter)
            self.audio_cleanup_output_picker.set_text(
                self.normalize_audio_cleanup_output_path(path, input_path, default_suffix)
            )
            self.audio_cleanup_last_auto_output_path = ""
            self.save_user_settings()

    @staticmethod
    def audio_cleanup_output_suffix_from_filter(selected_filter):
        for label, suffix in (
            ("WAV", ".wav"),
            ("M4A", ".m4a"),
            ("AAC", ".aac"),
            ("FLAC", ".flac"),
            ("OGG", ".ogg"),
        ):
            if label in selected_filter:
                return suffix
        return ".mp3"

    @staticmethod
    def normalize_audio_cleanup_output_path(output_path, input_path="", default_suffix=".mp3"):
        path = Path(output_path)
        if path.suffix:
            return str(path)
        input_suffix = Path(input_path).suffix.lower() if input_path else ""
        suffix = input_suffix if input_suffix in SUPPORTED_AUDIO_SUFFIXES else default_suffix
        return str(path.with_suffix(suffix))

    def refresh_audio_cleanup_input_info(self):
        if not hasattr(self, "audio_cleanup_duration_label"):
            return
        self.audio_cleanup_duration_seconds = 0.0
        input_path = self.audio_cleanup_input_picker.text()
        if not input_path:
            self.audio_cleanup_duration_label.setText("No audio selected.")
            self.update_audio_cleanup_time_limits(0.0)
            return
        audio_path = Path(input_path)
        if not audio_path.is_file():
            self.audio_cleanup_duration_label.setText("Selected audio file does not exist.")
            self.update_audio_cleanup_time_limits(0.0)
            return
        ffmpeg = find_ffmpeg_exe()
        if not ffmpeg:
            self.audio_cleanup_duration_label.setText("ffmpeg missing.")
            self.update_audio_cleanup_time_limits(0.0)
            return
        try:
            info = probe_audio_info(ffmpeg, audio_path)
        except (OSError, RuntimeError, ValueError) as exc:
            self.audio_cleanup_duration_label.setText(f"Could not inspect audio: {exc}")
            self.update_audio_cleanup_time_limits(0.0)
            return
        duration = float(info.get("duration_seconds") or 0.0)
        if not info.get("has_audio") or duration <= 0:
            self.audio_cleanup_duration_label.setText("Could not detect an audio stream.")
            self.update_audio_cleanup_time_limits(0.0)
            return
        self.audio_cleanup_duration_seconds = duration
        self.audio_cleanup_duration_label.setText(f"Duration: {self.format_audio_cleanup_time(duration)}")
        self.update_audio_cleanup_time_limits(duration)

    def update_audio_cleanup_time_limits(self, duration):
        duration = max(0.0, float(duration))
        for spin in (self.audio_cleanup_start_spin, self.audio_cleanup_end_spin):
            spin.blockSignals(True)
            spin.setMaximum(max(0.001, duration))
            spin.blockSignals(False)
        if duration <= 0:
            self.audio_cleanup_start_spin.setValue(0.0)
            self.audio_cleanup_end_spin.setValue(0.0)
            self.update_audio_cleanup_selection_note()
            return
        self.audio_cleanup_start_spin.blockSignals(True)
        self.audio_cleanup_end_spin.blockSignals(True)
        self.audio_cleanup_start_spin.setValue(0.0)
        self.audio_cleanup_end_spin.setValue(min(duration, 1.0))
        self.audio_cleanup_start_spin.blockSignals(False)
        self.audio_cleanup_end_spin.blockSignals(False)
        self.update_audio_cleanup_selection_note()

    def audio_cleanup_time_changed(self):
        self.update_audio_cleanup_selection_note()
        self.update_audio_cleanup_button_state()

    def update_audio_cleanup_selection_note(self):
        if not hasattr(self, "audio_cleanup_selection_note"):
            return
        start = self.audio_cleanup_start_spin.value()
        end = self.audio_cleanup_end_spin.value()
        duration = max(0.0, end - start)
        self.audio_cleanup_selection_note.setText(f"Selection: {duration:.3f}s")

    def audio_cleanup_action_key(self):
        return AUDIO_CLEANUP_ACTION_BY_LABEL.get(
            self.audio_cleanup_action_combo.currentText(),
            AUDIO_CLEANUP_ACTION_BY_LABEL[AUDIO_CLEANUP_REMOVE_LABEL],
        )

    def collect_audio_cleanup_options(self):
        input_path = self.audio_cleanup_input_picker.text()
        if not input_path:
            raise ValueError("Please select an audio file.")
        input_file = Path(input_path)
        if not input_file.is_file():
            raise ValueError("The selected audio file does not exist.")
        if input_file.suffix.lower() not in SUPPORTED_AUDIO_SUFFIXES:
            raise ValueError("The selected file must be .mp3, .wav, .m4a, .aac, .flac or .ogg.")
        if self.audio_cleanup_duration_seconds <= 0:
            raise ValueError("Could not detect the selected audio duration.")

        start = self.audio_cleanup_start_spin.value()
        end = self.audio_cleanup_end_spin.value()
        if start < 0 or end <= start:
            raise ValueError("Choose a valid cleanup range.")
        if end > self.audio_cleanup_duration_seconds + 0.001:
            raise ValueError("Cleanup range exceeds the audio duration.")

        output_path = self.audio_cleanup_output_picker.text()
        if not output_path:
            output_path = suggest_audio_cleanup_output_path(input_path)
        output_path = self.normalize_audio_cleanup_output_path(output_path, input_path)
        output_file = Path(output_path)
        if output_file.suffix.lower() not in SUPPORTED_AUDIO_SUFFIXES:
            raise ValueError("Cleaned audio output must be .mp3, .wav, .m4a, .aac, .flac or .ogg.")
        if not output_file.parent.is_dir():
            raise ValueError("The output folder does not exist.")
        try:
            if output_file.resolve() == input_file.resolve():
                raise ValueError("Choose an output path different from the source audio.")
        except OSError:
            pass
        self.audio_cleanup_output_picker.set_text(output_path)
        self.save_user_settings()
        return input_path, output_path, self.audio_cleanup_action_key(), start, end, self.audio_cleanup_duration_seconds

    def start_audio_cleanup_job(self):
        try:
            input_path, output_path, action, start, end, duration = self.collect_audio_cleanup_options()
        except ValueError as exc:
            self.audio_cleanup_status.setText("Error.")
            self.show_error("Audio Cleanup", str(exc))
            return
        ffmpeg = find_ffmpeg_exe()
        if not ffmpeg:
            self.audio_cleanup_status.setText("ffmpeg missing.")
            self.show_error("ffmpeg missing", "Could not find ffmpeg. Use the full VoiceBridge bundle.")
            return

        self.stop_audio_cleanup_playback()
        self.audio_cleanup_cancel_requested = False
        self.audio_cleanup_process = None
        self.audio_cleanup_last_output_path = ""
        self.reset_audio_cleanup_log()
        self.is_audio_cleanup_running = True
        self.update_audio_cleanup_progress_percent(0)
        self.audio_cleanup_status.setText("Cleaning selected audio range...")
        self.append_audio_cleanup_log(f"Input: {input_path}")
        self.append_audio_cleanup_log(f"Range: {start:.3f}s - {end:.3f}s")
        self.update_audio_cleanup_button_state()
        self.update_tts_button_state()
        self.update_stt_button_state()
        self.update_video_subtitle_button_state()
        self.update_video_cleanup_button_state()
        threading.Thread(
            target=self.audio_cleanup_worker,
            args=(str(ffmpeg), input_path, output_path, action, start, end, duration),
            daemon=True,
        ).start()

    def audio_cleanup_worker(self, ffmpeg, input_path, output_path, action, start, end, duration):
        try:
            output_duration = max(0.001, duration - (end - start)) if action == "remove" else duration
            command = audio_cleanup_command(ffmpeg, input_path, output_path, action, start, end, duration)
            return_code, recent_output = self.run_audio_cleanup_ffmpeg_process(command, output_duration)
            if self.audio_cleanup_cancel_requested:
                self.post(self.audio_cleanup_job_cancelled)
            elif return_code == 0 and Path(output_path).is_file():
                self.post(self.audio_cleanup_job_succeeded, output_path, action)
            else:
                message = "\n".join(recent_output[-8:]) or f"Audio cleanup exited with code {return_code}."
                self.post(self.audio_cleanup_job_failed, message)
        except (OSError, RuntimeError, ValueError, AssertionError) as exc:
            self.post(self.audio_cleanup_job_failed, str(exc))
        finally:
            self.post(self.finish_audio_cleanup_job)

    @staticmethod
    def parse_audio_cleanup_ffmpeg_time_seconds(value):
        value = value.strip()
        time_match = re.match(r"(\d+):(\d+):(\d+(?:\.\d+)?)", value)
        if time_match:
            return int(time_match.group(1)) * 3600 + int(time_match.group(2)) * 60 + float(time_match.group(3))
        try:
            return float(value) / 1_000_000
        except ValueError:
            return None

    def audio_cleanup_progress_percent(self, line, duration_seconds):
        if not duration_seconds:
            return None
        if line.startswith("out_time=") or line.startswith(("out_time_us=", "out_time_ms=")):
            seconds = self.parse_audio_cleanup_ffmpeg_time_seconds(line.split("=", 1)[1])
        else:
            return None
        if seconds is None:
            return None
        return min(99, max(0, round((seconds / duration_seconds) * 100)))

    @staticmethod
    def is_audio_cleanup_ffmpeg_progress_line(line):
        key = line.split("=", 1)[0]
        return key in {
            "bitrate",
            "drop_frames",
            "dup_frames",
            "fps",
            "frame",
            "out_time",
            "out_time_ms",
            "out_time_us",
            "progress",
            "speed",
            "stream_0_0_q",
            "total_size",
        }

    def run_audio_cleanup_ffmpeg_process(self, command, duration_seconds=None):
        recent_output = []
        last_progress_percent = -1
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )
        self.audio_cleanup_process = process
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.strip()
            if not line:
                continue
            progress_percent = self.audio_cleanup_progress_percent(line, duration_seconds)
            if progress_percent is not None:
                if progress_percent > last_progress_percent:
                    last_progress_percent = progress_percent
                    self.post(self.update_audio_cleanup_progress_percent, progress_percent)
                continue
            if self.is_audio_cleanup_ffmpeg_progress_line(line):
                continue
            recent_output.append(line)
            recent_output = recent_output[-12:]
            self.post(self.append_audio_cleanup_log, line)
            if self.audio_cleanup_cancel_requested and process.poll() is None:
                process.terminate()
        return process.wait(), recent_output

    def cancel_audio_cleanup_job(self):
        if not self.is_audio_cleanup_running:
            return
        self.audio_cleanup_cancel_requested = True
        self.audio_cleanup_status.setText("Cancelling...")
        self.append_audio_cleanup_log("Cancellation requested.")
        self.update_audio_cleanup_button_state()
        process = self.audio_cleanup_process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError as exc:
                self.append_audio_cleanup_log(f"Could not terminate process cleanly: {exc}")

    def audio_cleanup_job_succeeded(self, output_path, action):
        self.audio_cleanup_last_output_path = output_path
        self.audio_cleanup_status.setText("Cleaned audio saved.")
        self.append_audio_cleanup_log(f"Output saved: {output_path}")
        self.update_audio_cleanup_progress_percent(100)
        self.record_job("AUDIO", "Audio cleanup", self.audio_cleanup_input_picker.text(), output_path, action)
        self.show_info("Audio Cleanup", f"Audio saved:\n{output_path}")

    def audio_cleanup_job_failed(self, message):
        self.audio_cleanup_status.setText("Error.")
        self.append_audio_cleanup_log(f"ERROR: {message}")
        self.show_error("Audio Cleanup", message)

    def audio_cleanup_job_cancelled(self):
        self.audio_cleanup_status.setText("Cancelled.")
        self.append_audio_cleanup_log("Job cancelled.")

    def finish_audio_cleanup_job(self):
        self.is_audio_cleanup_running = False
        self.audio_cleanup_progress.hide()
        self.audio_cleanup_process = None
        self.update_audio_cleanup_button_state()
        self.update_tts_button_state()
        self.update_stt_button_state()
        self.update_video_subtitle_button_state()
        self.update_video_cleanup_button_state()

    def update_audio_cleanup_button_state(self):
        if not hasattr(self, "audio_cleanup_start_button"):
            return
        busy_elsewhere = self.is_converting or self.is_stt_running or self.is_video_running or self.is_cleanup_running
        has_input = bool(self.audio_cleanup_input_picker.text() and self.audio_cleanup_duration_seconds > 0)
        has_range = self.audio_cleanup_end_spin.value() > self.audio_cleanup_start_spin.value()
        self.audio_cleanup_start_button.setEnabled(
            has_input and has_range and not self.is_audio_cleanup_running and not busy_elsewhere
        )
        self.audio_cleanup_cancel_button.setEnabled(
            self.is_audio_cleanup_running and not self.audio_cleanup_cancel_requested
        )
        self.audio_cleanup_play_selection_button.setEnabled(
            has_input and has_range and not self.is_audio_cleanup_running
        )
        output_ready = bool(
            self.audio_cleanup_last_output_path and Path(self.audio_cleanup_last_output_path).is_file()
        )
        self.audio_cleanup_play_output_button.setEnabled(output_ready and not self.is_audio_cleanup_running)
        self.audio_cleanup_open_output_button.setEnabled(output_ready)
        self.audio_cleanup_open_folder_button.setEnabled(output_ready)
        for widget in (
            self.audio_cleanup_input_picker,
            self.audio_cleanup_output_picker,
            self.audio_cleanup_action_combo,
            self.audio_cleanup_start_spin,
            self.audio_cleanup_end_spin,
        ):
            widget.setEnabled(not self.is_audio_cleanup_running)
        self.update_navigation_state()

    def play_audio_cleanup_selection(self):
        if self.audio_cleanup_media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.stop_audio_cleanup_playback()
            return
        input_path = self.audio_cleanup_input_picker.text()
        if not input_path or not Path(input_path).is_file():
            return
        start = self.audio_cleanup_start_spin.value()
        end = self.audio_cleanup_end_spin.value()
        if end <= start:
            return
        self.play_audio_cleanup_path(input_path, start_seconds=start, stop_after_seconds=end - start)

    def play_audio_cleanup_output(self):
        if self.audio_cleanup_media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.stop_audio_cleanup_playback()
            return
        if not self.audio_cleanup_last_output_path or not Path(self.audio_cleanup_last_output_path).is_file():
            return
        self.play_audio_cleanup_path(self.audio_cleanup_last_output_path)

    def play_audio_cleanup_path(self, path, start_seconds=0.0, stop_after_seconds=None):
        self.audio_cleanup_preview_timer.stop()
        self.audio_cleanup_media_player.stop()
        self.audio_cleanup_media_player.setSource(QUrl.fromLocalFile(str(Path(path).resolve())))
        self.audio_cleanup_media_player.setPosition(max(0, int(start_seconds * 1000)))
        self.audio_cleanup_media_player.play()
        if stop_after_seconds:
            self.audio_cleanup_preview_timer.start(max(1, int(stop_after_seconds * 1000)))

    def stop_audio_cleanup_playback(self):
        if not hasattr(self, "audio_cleanup_media_player"):
            return
        self.audio_cleanup_preview_timer.stop()
        self.audio_cleanup_media_player.stop()

    def open_audio_cleanup_output(self):
        open_path(self.audio_cleanup_last_output_path)

    def open_audio_cleanup_output_folder(self):
        if self.audio_cleanup_last_output_path and Path(self.audio_cleanup_last_output_path).is_file():
            open_path(Path(self.audio_cleanup_last_output_path).parent)

    def append_audio_cleanup_log(self, line):
        self.audio_cleanup_log_lines.append(line)
        self.audio_cleanup_log_lines = self.audio_cleanup_log_lines[-300:]
        self.audio_cleanup_log.appendPlainText(line)
        scrollbar = self.audio_cleanup_log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def reset_audio_cleanup_log(self):
        self.audio_cleanup_log_lines = []
        self.audio_cleanup_log.clear()

    def toggle_audio_cleanup_details(self):
        if self.audio_cleanup_log.isVisible():
            self.audio_cleanup_log.hide()
            self.audio_cleanup_details_button.setText("Show details")
            return
        self.audio_cleanup_log.show()
        self.audio_cleanup_details_button.setText("Hide details")

    @staticmethod
    def format_audio_cleanup_time(seconds):
        seconds = max(0.0, float(seconds))
        minutes, remainder = divmod(seconds, 60)
        hours, minutes = divmod(int(minutes), 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{remainder:06.3f}"
        return f"{minutes:02d}:{remainder:06.3f}"

    def build_audio_cleanup_page(self):
        page, layout = self.page_container()
        self.page_header(
            layout,
            "AUDIO",
            "Audio Cleanup",
            "Manually remove, silence or fade short problem ranges in an existing audio file.",
            "BadgeGreen",
        )

        grid = QGridLayout()
        grid.setSpacing(16)
        layout.addLayout(grid)

        files_card = Card("Files")
        files_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.audio_cleanup_input_picker = FilePicker("Audio file")
        self.audio_cleanup_output_picker = FilePicker("Save cleaned audio as", "Save as...")
        self.audio_cleanup_input_picker.button.clicked.connect(self.select_audio_cleanup_input_file)
        self.audio_cleanup_output_picker.button.clicked.connect(self.select_audio_cleanup_output_file)
        self.audio_cleanup_input_picker.edit.textChanged.connect(self.audio_cleanup_input_changed)
        self.audio_cleanup_output_picker.edit.textChanged.connect(lambda _text: self.save_user_settings())
        self.audio_cleanup_duration_label = QLabel("No audio selected.")
        self.audio_cleanup_duration_label.setObjectName("Muted")
        files_card.content_layout.addWidget(self.audio_cleanup_input_picker)
        files_card.content_layout.addWidget(self.audio_cleanup_output_picker)
        files_card.content_layout.addWidget(self.audio_cleanup_duration_label)

        settings_card = Card("Cleanup range")
        settings_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.audio_cleanup_action_combo = QComboBox()
        self.audio_cleanup_action_combo.addItems(AUDIO_CLEANUP_ACTION_LABELS)
        self.audio_cleanup_action_combo.setCurrentText(AUDIO_CLEANUP_REMOVE_LABEL)
        self.audio_cleanup_action_combo.currentTextChanged.connect(self.audio_cleanup_action_changed)
        self.audio_cleanup_action_description = QLabel(AUDIO_CLEANUP_ACTION_DESCRIPTIONS[AUDIO_CLEANUP_REMOVE_LABEL])
        self.audio_cleanup_action_description.setObjectName("Muted")
        self.audio_cleanup_action_description.setWordWrap(True)
        self.audio_cleanup_start_spin = QDoubleSpinBox()
        self.audio_cleanup_end_spin = QDoubleSpinBox()
        for spin in (self.audio_cleanup_start_spin, self.audio_cleanup_end_spin):
            spin.setDecimals(3)
            spin.setRange(0.0, 0.001)
            spin.setSingleStep(0.1)
            spin.setSuffix(" s")
            spin.valueChanged.connect(lambda _value: self.audio_cleanup_time_changed())
        self.audio_cleanup_selection_note = QLabel("Selection: 0.000s")
        self.audio_cleanup_selection_note.setObjectName("Muted")
        settings_grid = QGridLayout()
        settings_grid.setContentsMargins(0, 0, 0, 0)
        settings_grid.setHorizontalSpacing(8)
        settings_grid.setVerticalSpacing(8)
        settings_grid.addWidget(QLabel("Action"), 0, 0)
        settings_grid.addWidget(self.audio_cleanup_action_combo, 0, 1, 1, 3)
        settings_grid.addWidget(QLabel("Start"), 1, 0)
        settings_grid.addWidget(self.audio_cleanup_start_spin, 1, 1)
        settings_grid.addWidget(QLabel("End"), 1, 2)
        settings_grid.addWidget(self.audio_cleanup_end_spin, 1, 3)
        settings_card.content_layout.addLayout(settings_grid)
        settings_card.content_layout.addWidget(self.audio_cleanup_action_description)
        settings_card.content_layout.addWidget(self.audio_cleanup_selection_note)

        grid.addWidget(files_card, 0, 0)
        grid.addWidget(settings_card, 0, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        action_card = Card()
        action_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        self.audio_cleanup_start_button = QPushButton("Clean audio")
        self.audio_cleanup_start_button.setObjectName("PrimaryButton")
        self.audio_cleanup_cancel_button = QPushButton("Cancel")
        self.audio_cleanup_play_selection_button = QPushButton("Play selection")
        self.audio_cleanup_play_output_button = QPushButton("Play output")
        self.audio_cleanup_open_output_button = QPushButton("Open output")
        self.audio_cleanup_open_folder_button = QPushButton("Open folder")
        self.audio_cleanup_details_button = QPushButton("Show details")
        self.audio_cleanup_start_button.clicked.connect(self.start_audio_cleanup_job)
        self.audio_cleanup_cancel_button.clicked.connect(self.cancel_audio_cleanup_job)
        self.audio_cleanup_play_selection_button.clicked.connect(self.play_audio_cleanup_selection)
        self.audio_cleanup_play_output_button.clicked.connect(self.play_audio_cleanup_output)
        self.audio_cleanup_open_output_button.clicked.connect(self.open_audio_cleanup_output)
        self.audio_cleanup_open_folder_button.clicked.connect(self.open_audio_cleanup_output_folder)
        self.audio_cleanup_details_button.clicked.connect(self.toggle_audio_cleanup_details)
        actions.addWidget(self.audio_cleanup_start_button)
        actions.addWidget(self.audio_cleanup_cancel_button)
        actions.addWidget(self.audio_cleanup_play_selection_button)
        actions.addStretch(1)
        actions.addWidget(self.audio_cleanup_play_output_button)
        actions.addWidget(self.audio_cleanup_open_output_button)
        actions.addWidget(self.audio_cleanup_open_folder_button)
        actions.addWidget(self.audio_cleanup_details_button)
        action_card.content_layout.addLayout(actions)
        self.audio_cleanup_progress = QProgressBar()
        self.audio_cleanup_progress.setRange(0, 0)
        self.audio_cleanup_progress.hide()
        self.audio_cleanup_status = QLabel("Ready.")
        self.audio_cleanup_status.setObjectName("StatusText")
        self.audio_cleanup_log = QPlainTextEdit()
        self.audio_cleanup_log.setObjectName("LogBox")
        self.audio_cleanup_log.setReadOnly(True)
        self.audio_cleanup_log.setMinimumHeight(160)
        self.audio_cleanup_log.hide()
        action_card.content_layout.addWidget(self.audio_cleanup_progress)
        action_card.content_layout.addWidget(self.audio_cleanup_status)
        action_card.content_layout.addWidget(self.audio_cleanup_log)
        layout.addWidget(action_card)
        layout.addStretch(1)

        self.audio_cleanup_audio_output = QAudioOutput(self)
        self.audio_cleanup_media_player = QMediaPlayer(self)
        self.audio_cleanup_media_player.setAudioOutput(self.audio_cleanup_audio_output)
        self.audio_cleanup_preview_timer = QTimer(self)
        self.audio_cleanup_preview_timer.setSingleShot(True)
        self.audio_cleanup_preview_timer.timeout.connect(self.stop_audio_cleanup_playback)
        self.update_audio_cleanup_button_state()
        return page
