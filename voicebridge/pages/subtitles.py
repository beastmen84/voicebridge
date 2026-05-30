import os
import re
import subprocess
import tempfile
import threading
from contextlib import suppress
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from media_tools import (
    SubtitleStyle,
    auto_burn_quality,
    can_create_video_subtitles,
    find_ffmpeg_exe,
    first_srt_timestamp_seconds,
    probe_video_info,
    suggest_video_subtitle_output_path,
    video_subtitle_commands,
    video_subtitle_preview_command,
)
from voicebridge.constants import (
    BURN_QUALITY_AUTO,
    BURN_QUALITY_BY_LABEL,
    BURN_QUALITY_CRF_VALUES,
    BURN_QUALITY_DESCRIPTIONS,
    BURN_QUALITY_ORIGINAL_BITRATE,
    BURN_QUALITY_STANDARD,
    VIDEO_SUBTITLE_BURN_LABEL,
    VIDEO_SUBTITLE_EMBED_LABEL,
    VIDEO_SUBTITLE_MODE_BY_LABEL,
    VIDEO_SUBTITLE_MODE_DESCRIPTIONS,
    VIDEO_SUBTITLE_POSITION_LABELS,
)
from voicebridge.ui.helpers import (
    normalize_video_subtitle_output_path,
    open_path,
    validate_video_subtitle_inputs,
)


class SubtitlesWorkflowMixin:
    def video_subtitle_mode_label(self):
        if getattr(self, "video_burn_mode_button", None) and self.video_burn_mode_button.isChecked():
            return VIDEO_SUBTITLE_BURN_LABEL
        return VIDEO_SUBTITLE_EMBED_LABEL

    def video_subtitle_mode_key(self):
        return VIDEO_SUBTITLE_MODE_BY_LABEL.get(self.video_subtitle_mode_label(), "embed")

    def set_video_subtitle_mode(self, mode_or_label):
        if not hasattr(self, "video_embed_mode_button"):
            return
        if mode_or_label in VIDEO_SUBTITLE_MODE_BY_LABEL:
            label = mode_or_label
        else:
            label = VIDEO_SUBTITLE_BURN_LABEL if mode_or_label == "burn" else VIDEO_SUBTITLE_EMBED_LABEL
        burn = label == VIDEO_SUBTITLE_BURN_LABEL
        self.video_embed_mode_button.setChecked(not burn)
        self.video_burn_mode_button.setChecked(burn)
        self.video_subtitle_mode_changed()

    def sync_video_subtitle_inputs_from_stt(self):
        if not hasattr(self, "video_media_picker"):
            return
        if can_create_video_subtitles(self.stt_last_srt_path, self.stt_last_media_path):
            if not self.video_media_picker.text():
                self.video_media_picker.set_text(self.stt_last_media_path)
            if not self.video_srt_picker.text():
                self.video_srt_picker.set_text(self.stt_last_srt_path)
            self.update_video_subtitle_output(force=False)
            self.save_user_settings()

    def video_subtitle_mode_changed(self):
        mode = self.video_subtitle_mode_key()
        burn = mode == "burn"
        self.video_mode_note.setText(
            VIDEO_SUBTITLE_MODE_DESCRIPTIONS[VIDEO_SUBTITLE_BURN_LABEL if burn else VIDEO_SUBTITLE_EMBED_LABEL]
        )
        for widget in (
            self.video_quality_label,
            self.video_quality_combo,
            self.video_crf_note,
            self.video_quality_description,
            self.video_style_panel,
        ):
            widget.setVisible(burn)
        self.video_preview_button.setVisible(burn)
        self.update_video_subtitle_output(force=False)
        self.save_user_settings()

    def update_video_quality_description(self, text):
        self.video_quality_description.setText(BURN_QUALITY_DESCRIPTIONS.get(text, ""))
        self.save_user_settings()

    def collect_video_subtitle_style(self) -> SubtitleStyle:
        return {
            "font_size": self.video_font_size_spin.value(),
            "outline": self.video_outline_spin.value(),
            "margin_v": self.video_margin_spin.value(),
            "alignment": VIDEO_SUBTITLE_POSITION_LABELS.get(self.video_position_combo.currentText(), 2),
        }

    def suggested_video_subtitle_output_path(self):
        media_path = self.video_media_picker.text()
        if not media_path:
            return ""
        try:
            return suggest_video_subtitle_output_path(media_path, self.video_subtitle_mode_key())
        except ValueError:
            return ""

    def update_video_subtitle_output(self, force=False):
        if not hasattr(self, "video_output_picker"):
            return
        current = self.video_output_picker.text()
        suggested = self.suggested_video_subtitle_output_path()
        if not suggested:
            return
        if force or not current or current == self.video_last_auto_output_path:
            self.video_output_picker.set_text(suggested)
            self.video_last_auto_output_path = suggested

    def select_video_subtitle_media_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select video file",
            self.video_media_picker.text() or str(Path.home()),
            "Video files (*.mp4 *.mkv *.mov *.avi *.webm *.m4v);;All files (*.*)",
        )
        if path:
            self.video_media_picker.set_text(path)
            self.video_last_media_path = path
            self.update_video_subtitle_output(force=False)
            self.save_user_settings()

    def select_video_subtitle_srt_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select SRT subtitle file",
            self.video_srt_picker.text() or str(Path.home()),
            "SubRip subtitles (*.srt);;All files (*.*)",
        )
        if path:
            self.video_srt_picker.set_text(path)
            self.video_last_srt_path = path
            self.save_user_settings()

    def select_video_subtitle_output_file(self):
        mode = self.video_subtitle_mode_key()
        suggested = self.video_output_picker.text() or self.suggested_video_subtitle_output_path()
        if not suggested:
            suggested = str(Path.home() / ("subtitled_video.mp4" if mode == "burn" else "subtitled_video.mkv"))
        if mode == "burn":
            filter_text = "MP4 video (*.mp4);;All files (*.*)"
        else:
            filter_text = "MP4 video (*.mp4);;Matroska video (*.mkv);;All files (*.*)"
        path, selected_filter = QFileDialog.getSaveFileName(self, "Save subtitled video as", suggested, filter_text)
        if path:
            default_suffix = ".mkv" if mode == "embed" and "Matroska" in selected_filter else ".mp4"
            self.video_output_picker.set_text(normalize_video_subtitle_output_path(path, mode, default_suffix))
            self.video_last_auto_output_path = ""
            self.save_user_settings()

    def collect_video_subtitle_options(self):
        mode = self.video_subtitle_mode_key()
        media_path = self.video_media_picker.text()
        srt_path = self.video_srt_picker.text()
        output_path = self.video_output_picker.text()
        if media_path and not output_path:
            output_path = self.suggested_video_subtitle_output_path()
            self.video_output_picker.set_text(output_path)
        output_path = normalize_video_subtitle_output_path(
            output_path,
            mode,
            Path(output_path).suffix.lower() if output_path else "",
        )
        validate_video_subtitle_inputs(mode, media_path, srt_path, output_path)
        burn_quality = BURN_QUALITY_BY_LABEL.get(self.video_quality_combo.currentText(), BURN_QUALITY_AUTO)
        subtitle_style = self.collect_video_subtitle_style() if mode == "burn" else None
        self.video_output_picker.set_text(output_path)
        self.save_user_settings()
        return mode, media_path, srt_path, output_path, burn_quality, subtitle_style

    def start_video_subtitle_from_page(self):
        try:
            (
                mode,
                media_path,
                srt_path,
                output_path,
                burn_quality,
                subtitle_style,
            ) = self.collect_video_subtitle_options()
        except ValueError as exc:
            self.video_status.setText("Error.")
            self.show_error("Subtitles", str(exc))
            return
        self.start_video_subtitle_job(mode, media_path, srt_path, output_path, burn_quality, subtitle_style)

    def preview_video_subtitle_style(self) -> None:
        if self.video_subtitle_mode_key() != "burn":
            return
        media_path = self.video_media_picker.text()
        srt_path = self.video_srt_picker.text()
        if not media_path or not Path(media_path).is_file():
            self.show_error("Preview subtitles", "Select an existing video file.")
            return
        if not srt_path or not Path(srt_path).is_file() or Path(srt_path).suffix.lower() != ".srt":
            self.show_error("Preview subtitles", "Select an existing .srt subtitle file.")
            return
        ffmpeg = find_ffmpeg_exe()
        if not ffmpeg:
            self.show_error("ffmpeg missing", "Could not find ffmpeg. Use the full VoiceBridge bundle.")
            return

        timestamp_seconds = first_srt_timestamp_seconds(srt_path)
        subtitle_style = self.collect_video_subtitle_style()
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        with tempfile.TemporaryDirectory(prefix="voicebridge-subtitle-preview-") as temp_dir:
            preview_path = str(Path(temp_dir) / "subtitle-preview.jpg")
            command = video_subtitle_preview_command(
                ffmpeg,
                media_path,
                srt_path,
                preview_path,
                subtitle_style=subtitle_style,
                timestamp_seconds=timestamp_seconds,
            )
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
                timeout=90,
                check=False,
            )
            if result.returncode != 0 or not Path(preview_path).is_file():
                self.show_error(
                    "Preview subtitles",
                    (result.stderr or result.stdout or "Could not generate subtitle preview.").strip(),
                )
                return

            dialog = QDialog(self)
            dialog.setWindowTitle("Subtitle style preview")
            dialog.setMinimumWidth(860)
            layout = QVBoxLayout(dialog)
            header = QLabel(f"Preview at {timestamp_seconds:.2f}s")
            header.setObjectName("CardTitle")
            image = QLabel()
            image.setAlignment(Qt.AlignmentFlag.AlignCenter)
            image.setStyleSheet("background: #0f172a; border-radius: 6px;")
            pixmap = QPixmap(preview_path)
            if not pixmap.isNull():
                image.setPixmap(
                    pixmap.scaled(
                        820,
                        462,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            else:
                image.setText("Preview unavailable")
            close_button = QPushButton("Close")
            close_button.clicked.connect(dialog.accept)
            footer = QHBoxLayout()
            footer.addStretch(1)
            footer.addWidget(close_button)
            layout.addWidget(header)
            layout.addWidget(image)
            layout.addLayout(footer)
            dialog.exec()

    def start_video_subtitle_job(
        self,
        mode,
        media_path,
        srt_path,
        output_path,
        burn_quality=BURN_QUALITY_AUTO,
        subtitle_style: SubtitleStyle | None = None,
    ):
        ffmpeg = find_ffmpeg_exe()
        if not ffmpeg:
            self.video_status.setText("ffmpeg missing.")
            self.show_error("ffmpeg missing", "Could not find ffmpeg. Use the full VoiceBridge bundle.")
            return
        try:
            validate_video_subtitle_inputs(mode, media_path, srt_path, output_path)
        except ValueError as exc:
            self.video_status.setText("Error.")
            self.show_error("Subtitles", str(exc))
            return
        self.video_cancel_requested = False
        self.video_process = None
        self.video_last_output_path = ""
        self.video_last_media_path = media_path
        self.video_last_srt_path = srt_path
        self.is_video_running = True
        self.show_indeterminate_progress(self.video_progress)
        self.video_status.setText(
            "Embedding subtitle track..." if mode == "embed" else "Burning subtitles into video..."
        )
        self.reset_video_log()
        log_line = f"Starting video subtitle mode={mode}, media={media_path}, srt={srt_path}, output={output_path}"
        if mode == "burn":
            log_line = f"{log_line}, quality={burn_quality}, style={subtitle_style}"
        self.append_video_log(log_line)
        self.update_video_subtitle_button_state()
        self.update_stt_button_state()
        self.update_tts_button_state()
        self.update_video_cleanup_button_state()
        threading.Thread(
            target=self.video_subtitle_worker,
            args=(mode, str(ffmpeg), media_path, srt_path, output_path, burn_quality, subtitle_style),
            daemon=True,
        ).start()

    def video_subtitle_worker(self, mode, ffmpeg, media_path, srt_path, output_path, burn_quality, subtitle_style):
        output_path = Path(output_path)
        temp_output_path = None
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(
                prefix=f".{output_path.stem}.voicebridge-",
                suffix=output_path.suffix,
                dir=str(output_path.parent),
            )
            os.close(fd)
            temp_output_path = Path(temp_name)
            temp_output_path.unlink(missing_ok=True)

            self.post(self.append_video_log, "Detecting source video details...")
            source_video_info = probe_video_info(ffmpeg, media_path)
            source_video_bitrate_kbps = source_video_info.get("bitrate_kbps")
            source_video_width = source_video_info.get("width")
            source_video_height = source_video_info.get("height")
            source_video_duration_seconds = source_video_info.get("duration_seconds")
            if source_video_duration_seconds:
                self.post(self.update_video_progress_percent, 0)
            else:
                self.post(self.set_video_progress_indeterminate)
            if mode == "burn" and burn_quality == BURN_QUALITY_AUTO:
                selected_quality = auto_burn_quality(
                    source_video_bitrate_kbps,
                    source_video_width,
                    source_video_height,
                )
                selected_crf = BURN_QUALITY_CRF_VALUES.get(
                    selected_quality,
                    BURN_QUALITY_CRF_VALUES[BURN_QUALITY_STANDARD],
                )
                source_parts = []
                if source_video_width and source_video_height:
                    source_parts.append(f"{source_video_width}x{source_video_height}")
                if source_video_bitrate_kbps:
                    source_parts.append(f"{source_video_bitrate_kbps} kb/s")
                source_note = f" ({', '.join(source_parts)})" if source_parts else ""
                self.post(self.append_video_log, f"Auto burn-in quality selected: CRF {selected_crf}{source_note}")
            if mode == "burn" and burn_quality == BURN_QUALITY_ORIGINAL_BITRATE and not source_video_bitrate_kbps:
                raise RuntimeError("Could not detect the original video bitrate. Choose a CRF option instead.")

            commands = video_subtitle_commands(
                mode,
                ffmpeg,
                media_path,
                srt_path,
                str(temp_output_path),
                burn_quality=burn_quality,
                source_video_bitrate_kbps=source_video_bitrate_kbps,
                source_video_width=source_video_width,
                source_video_height=source_video_height,
                subtitle_style=subtitle_style,
            )
            recent_output = []
            for command in commands:
                return_code, recent_output = self.run_ffmpeg_process(command, source_video_duration_seconds)
                if return_code == 0:
                    if self.video_cancel_requested:
                        self.post(self.video_subtitle_job_cancelled)
                        return
                    os.replace(temp_output_path, output_path)
                    self.post(self.update_video_progress_percent, 100)
                    self.post(self.video_subtitle_job_succeeded, str(output_path), mode)
                    return
                if self.video_cancel_requested:
                    self.post(self.video_subtitle_job_cancelled)
                    return
            raise RuntimeError("\n".join(recent_output[-8:]) or "ffmpeg could not create the subtitled video.")
        except (OSError, RuntimeError, ValueError) as exc:
            self.post(self.video_subtitle_job_failed, str(exc))
        finally:
            if temp_output_path:
                with suppress(OSError):
                    temp_output_path.unlink(missing_ok=True)
            self.video_process = None
            self.post(self.finish_video_subtitle_job)

    @staticmethod
    def parse_ffmpeg_time_seconds(value):
        value = value.strip()
        time_match = re.match(r"(\d+):(\d+):(\d+(?:\.\d+)?)", value)
        if time_match:
            return int(time_match.group(1)) * 3600 + int(time_match.group(2)) * 60 + float(time_match.group(3))
        try:
            return float(value) / 1_000_000
        except ValueError:
            return None

    def ffmpeg_progress_percent(self, line, duration_seconds):
        if not duration_seconds:
            return None
        if line.startswith("out_time=") or line.startswith(("out_time_us=", "out_time_ms=")):
            seconds = self.parse_ffmpeg_time_seconds(line.split("=", 1)[1])
        else:
            return None
        if seconds is None:
            return None
        return min(99, max(0, round((seconds / duration_seconds) * 100)))

    @staticmethod
    def is_ffmpeg_progress_line(line):
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

    def run_ffmpeg_process(self, command, duration_seconds=None):
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
        self.video_process = process
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.strip()
            if not line:
                continue
            progress_percent = self.ffmpeg_progress_percent(line, duration_seconds)
            if progress_percent is not None:
                if progress_percent > last_progress_percent:
                    last_progress_percent = progress_percent
                    self.post(self.update_video_progress_percent, progress_percent)
                continue
            if self.is_ffmpeg_progress_line(line):
                continue
            recent_output.append(line)
            recent_output = recent_output[-12:]
            self.post(self.append_video_log, line)
            if self.video_cancel_requested and process.poll() is None:
                process.terminate()
        return process.wait(), recent_output

    def cancel_video_subtitle_job(self):
        if not self.is_video_running:
            return
        self.video_cancel_requested = True
        self.video_status.setText("Cancelling...")
        self.append_video_log("Cancellation requested.")
        self.update_video_subtitle_button_state()
        process = self.video_process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError as exc:
                self.append_video_log(f"Could not terminate process cleanly: {exc}")

    def video_subtitle_job_succeeded(self, output_path, mode):
        self.video_last_output_path = output_path
        self.video_status.setText("Subtitles embedded." if mode == "embed" else "Subtitles burned into video.")
        self.append_video_log(f"Video saved: {output_path}")
        self.record_job(
            "VIDEO",
            "Subtitled video",
            self.video_media_picker.text(),
            output_path,
            "embedded" if mode == "embed" else "burned",
        )
        self.show_info("Success", f"Video saved:\n{output_path}")

    def video_subtitle_job_cancelled(self):
        self.video_status.setText("Cancelled.")
        self.append_video_log("Job cancelled.")

    def video_subtitle_job_failed(self, message):
        self.video_status.setText("Error.")
        self.append_video_log(f"ERROR: {message}")
        self.show_error("Subtitles", message)

    def finish_video_subtitle_job(self):
        self.is_video_running = False
        self.video_progress.hide()
        self.update_video_subtitle_button_state()
        self.update_stt_button_state()
        self.update_tts_button_state()
        self.update_video_cleanup_button_state()

    def open_video_subtitle_output(self):
        open_path(self.video_last_output_path)

    def open_video_subtitle_output_folder(self):
        if self.video_last_output_path and Path(self.video_last_output_path).is_file():
            open_path(Path(self.video_last_output_path).parent)

    def update_video_subtitle_button_state(self):
        if not hasattr(self, "video_start_button"):
            return
        busy_elsewhere = self.is_converting or self.is_stt_running or self.is_cleanup_running
        burn_mode = self.video_subtitle_mode_key() == "burn"
        self.video_start_button.setEnabled(not self.is_video_running and not busy_elsewhere)
        self.video_preview_button.setEnabled(not self.is_video_running and not busy_elsewhere and burn_mode)
        self.video_cancel_button.setEnabled(self.is_video_running and not self.video_cancel_requested)
        output_ready = bool(self.video_last_output_path and Path(self.video_last_output_path).is_file())
        self.video_open_output_button.setEnabled(output_ready)
        self.video_open_folder_button.setEnabled(output_ready)
        for widget in (
            self.video_media_picker,
            self.video_srt_picker,
            self.video_output_picker,
            self.video_embed_mode_button,
            self.video_burn_mode_button,
            self.video_quality_combo,
            self.video_font_size_spin,
            self.video_outline_spin,
            self.video_margin_spin,
            self.video_position_combo,
        ):
            widget.setEnabled(not self.is_video_running)
        self.update_navigation_state()

    def append_video_log(self, line):
        self.video_log_lines.append(line)
        self.video_log_lines = self.video_log_lines[-300:]
        self.video_log.appendPlainText(line)
        scrollbar = self.video_log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def reset_video_log(self):
        self.video_log_lines = []
        self.video_log.clear()

    def toggle_video_details(self):
        if self.video_log.isVisible():
            self.video_log.hide()
            self.video_details_button.setText("Show details")
            return
        self.video_log.show()
        self.video_details_button.setText("Hide details")

