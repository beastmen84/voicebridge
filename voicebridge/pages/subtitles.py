import os
import re
import subprocess
import tempfile
import threading
from contextlib import suppress
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
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

from voicebridge.constants import (
    BURN_QUALITY_AUTO,
    BURN_QUALITY_AUTO_LABEL,
    BURN_QUALITY_BY_LABEL,
    BURN_QUALITY_CRF_VALUES,
    BURN_QUALITY_DESCRIPTIONS,
    BURN_QUALITY_LABELS,
    BURN_QUALITY_ORIGINAL_BITRATE,
    BURN_QUALITY_STANDARD,
    VIDEO_SUBTITLE_BOX_COLOR_BY_LABEL,
    VIDEO_SUBTITLE_BOX_COLOR_LABELS,
    VIDEO_SUBTITLE_BURN_LABEL,
    VIDEO_SUBTITLE_EMBED_LABEL,
    VIDEO_SUBTITLE_MODE_BY_LABEL,
    VIDEO_SUBTITLE_MODE_DESCRIPTIONS,
    VIDEO_SUBTITLE_OUTLINE_COLOR_BY_LABEL,
    VIDEO_SUBTITLE_OUTLINE_COLOR_LABELS,
    VIDEO_SUBTITLE_POSITION_LABELS,
    VIDEO_SUBTITLE_TEXT_COLOR_BY_LABEL,
    VIDEO_SUBTITLE_TEXT_COLOR_LABELS,
)
from voicebridge.ffmpeg_jobs import ffmpeg_progress_percent as ffmpeg_job_progress_percent
from voicebridge.ffmpeg_jobs import should_keep_ffmpeg_log_line
from voicebridge.file_checks import ensure_free_space
from voicebridge.media_tools import (
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
from voicebridge.ui.helpers import (
    normalize_video_subtitle_output_path,
    open_path,
    validate_video_subtitle_inputs,
)
from voicebridge.ui.widgets import Card, FilePicker

VIDEO_OUTPUT_MIN_FREE_BYTES = 512 * 1024 * 1024


# noinspection PyAttributeOutsideInit,PyUnresolvedReferences,PyTypeChecker
class SubtitlesWorkflowMixin:
    def subtitle_text(self, text: str, **kwargs) -> str:
        if kwargs and hasattr(self, "format_static_ui_text"):
            return self.format_static_ui_text(text, **kwargs)
        if kwargs:
            return text.format(**kwargs)
        return self.static_ui_text(text) if hasattr(self, "static_ui_text") else text

    def populate_video_subtitle_combo(self, combo: QComboBox, labels: list[str] | tuple[str, ...]) -> None:
        selected = self.combo_current_data(combo) if combo.count() else labels[0]
        combo.blockSignals(True)
        try:
            combo.clear()
            for label in labels:
                combo.addItem(self.subtitle_text(label), label)
            self.set_combo_data(combo, selected, list(labels))
        finally:
            combo.blockSignals(False)

    def retranslate_subtitles_page(self) -> None:
        if not hasattr(self, "video_quality_combo"):
            return
        self.video_embed_mode_button.setText(self.subtitle_text(VIDEO_SUBTITLE_EMBED_LABEL))
        self.video_burn_mode_button.setText(self.subtitle_text(VIDEO_SUBTITLE_BURN_LABEL))
        self.populate_video_subtitle_combo(self.video_quality_combo, BURN_QUALITY_LABELS)
        self.populate_video_subtitle_combo(self.video_position_combo, tuple(VIDEO_SUBTITLE_POSITION_LABELS))
        self.populate_video_subtitle_combo(self.video_text_color_combo, tuple(VIDEO_SUBTITLE_TEXT_COLOR_LABELS))
        self.populate_video_subtitle_combo(self.video_outline_color_combo, tuple(VIDEO_SUBTITLE_OUTLINE_COLOR_LABELS))
        self.populate_video_subtitle_combo(self.video_box_color_combo, tuple(VIDEO_SUBTITLE_BOX_COLOR_LABELS))
        self.video_subtitle_mode_changed()
        self.update_video_quality_description()

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
        mode_description_label = VIDEO_SUBTITLE_BURN_LABEL if burn else VIDEO_SUBTITLE_EMBED_LABEL
        self.video_mode_note.setText(
            self.subtitle_text(VIDEO_SUBTITLE_MODE_DESCRIPTIONS[mode_description_label])
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

    def update_video_quality_description(self, _text=None):
        quality_label = self.combo_current_data(self.video_quality_combo)
        self.video_quality_description.setText(self.subtitle_text(BURN_QUALITY_DESCRIPTIONS.get(quality_label, "")))
        self.save_user_settings()

    def collect_video_subtitle_style(self) -> SubtitleStyle:
        return {
            "font_size": self.video_font_size_spin.value(),
            "outline": self.video_outline_spin.value(),
            "margin_v": self.video_margin_spin.value(),
            "alignment": VIDEO_SUBTITLE_POSITION_LABELS.get(self.combo_current_data(self.video_position_combo), 2),
            "text_color": VIDEO_SUBTITLE_TEXT_COLOR_BY_LABEL.get(
                self.combo_current_data(self.video_text_color_combo),
                VIDEO_SUBTITLE_TEXT_COLOR_BY_LABEL["White"],
            ),
            "outline_color": VIDEO_SUBTITLE_OUTLINE_COLOR_BY_LABEL.get(
                self.combo_current_data(self.video_outline_color_combo),
                VIDEO_SUBTITLE_OUTLINE_COLOR_BY_LABEL["Black"],
            ),
            "shadow": self.video_shadow_spin.value(),
            "background_box": self.video_background_box_check.isChecked(),
            "box_color": VIDEO_SUBTITLE_BOX_COLOR_BY_LABEL.get(
                self.combo_current_data(self.video_box_color_combo),
                VIDEO_SUBTITLE_BOX_COLOR_BY_LABEL["Black 70%"],
            ),
        }

    def update_video_subtitle_style_options(self):
        if not hasattr(self, "video_box_color_combo"):
            return
        self.video_box_color_combo.setEnabled(self.video_background_box_check.isChecked())
        self.save_user_settings()

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
            self.subtitle_text("Select video file"),
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
            self.subtitle_text("Select SRT subtitle file"),
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
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            self.subtitle_text("Save subtitled video as"),
            suggested,
            filter_text,
        )
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
        source_size = Path(media_path).stat().st_size if Path(media_path).is_file() else 0
        ensure_free_space(output_path, max(VIDEO_OUTPUT_MIN_FREE_BYTES, source_size), "subtitled video output")
        burn_quality = BURN_QUALITY_BY_LABEL.get(self.combo_current_data(self.video_quality_combo), BURN_QUALITY_AUTO)
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
            self.video_status.setText(self.subtitle_text("Error."))
            self.show_error(self.subtitle_text("Subtitles"), str(exc))
            return
        self.start_video_subtitle_job(mode, media_path, srt_path, output_path, burn_quality, subtitle_style)

    def preview_video_subtitle_style(self) -> None:
        if self.video_subtitle_mode_key() != "burn":
            return
        media_path = self.video_media_picker.text()
        srt_path = self.video_srt_picker.text()
        if not media_path or not Path(media_path).is_file():
            self.show_error(
                self.subtitle_text("Preview subtitles"),
                self.subtitle_text("Select an existing video file."),
            )
            return
        if not srt_path or not Path(srt_path).is_file() or Path(srt_path).suffix.lower() != ".srt":
            self.show_error(
                self.subtitle_text("Preview subtitles"),
                self.subtitle_text("Select an existing .srt subtitle file."),
            )
            return
        ffmpeg = find_ffmpeg_exe()
        if not ffmpeg:
            self.show_error(
                self.subtitle_text("ffmpeg missing"),
                self.subtitle_text("Could not find ffmpeg. Use the full VoiceBridge bundle."),
            )
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
                    self.subtitle_text("Preview subtitles"),
                    (result.stderr or result.stdout or "Could not generate subtitle preview.").strip(),
                )
                return

            dialog = QDialog(self)
            dialog.setWindowTitle(self.subtitle_text("Subtitle style preview"))
            dialog.setMinimumWidth(860)
            layout = QVBoxLayout(dialog)
            header = QLabel(self.subtitle_text("Preview at {time:.2f}s", time=timestamp_seconds))
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
                image.setText(self.subtitle_text("Preview unavailable"))
            close_button = QPushButton(self.subtitle_text("Close"))
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
            self.video_status.setText(self.subtitle_text("ffmpeg missing."))
            self.show_error(
                self.subtitle_text("ffmpeg missing"),
                self.subtitle_text("Could not find ffmpeg. Use the full VoiceBridge bundle."),
            )
            return
        try:
            validate_video_subtitle_inputs(mode, media_path, srt_path, output_path)
        except ValueError as exc:
            self.video_status.setText(self.subtitle_text("Error."))
            self.show_error(self.subtitle_text("Subtitles"), str(exc))
            return
        self.video_cancel_requested = False
        self.video_process = None
        self.video_last_output_path = ""
        self.video_last_media_path = media_path
        self.video_last_srt_path = srt_path
        self.is_video_running = True
        self.show_indeterminate_progress(self.video_progress)
        self.video_status.setText(
            self.subtitle_text("Embedding subtitle track...")
            if mode == "embed"
            else self.subtitle_text("Burning subtitles into video...")
        )
        self.reset_video_log()
        log_line = f"Starting video subtitle mode={mode}, media={media_path}, srt={srt_path}, output={output_path}"
        if mode == "burn":
            log_line = f"{log_line}, quality={burn_quality}, style={subtitle_style}"
        self.append_video_log(log_line)
        self.update_video_subtitle_button_state()
        self.update_stt_button_state()
        self.update_tts_button_state()
        self.update_audio_cleanup_button_state()
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
            progress_percent = ffmpeg_job_progress_percent(line, duration_seconds)
            if progress_percent is not None:
                if progress_percent > last_progress_percent:
                    last_progress_percent = progress_percent
                    self.post(self.update_video_progress_percent, progress_percent)
                continue
            if not should_keep_ffmpeg_log_line(line):
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
        self.video_status.setText(self.subtitle_text("Cancelling..."))
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
        self.video_status.setText(
            self.subtitle_text("Subtitles embedded.")
            if mode == "embed"
            else self.subtitle_text("Subtitles burned into video.")
        )
        self.append_video_log(f"Video saved: {output_path}")
        self.record_job(
            "VIDEO",
            "Subtitled video",
            self.video_media_picker.text(),
            output_path,
            "embedded" if mode == "embed" else "burned",
        )
        self.show_info(
            self.subtitle_text("Success"),
            self.subtitle_text("Video saved:\n{path}", path=output_path),
        )

    def video_subtitle_job_cancelled(self):
        self.video_status.setText(self.subtitle_text("Cancelled."))
        self.append_video_log("Job cancelled.")

    def video_subtitle_job_failed(self, message):
        self.video_status.setText(self.subtitle_text("Error."))
        self.append_video_log(f"ERROR: {message}")
        self.show_error(self.subtitle_text("Subtitles"), message)

    def finish_video_subtitle_job(self):
        self.is_video_running = False
        self.video_progress.hide()
        self.update_video_subtitle_button_state()
        self.update_stt_button_state()
        self.update_tts_button_state()
        self.update_audio_cleanup_button_state()
        self.update_video_cleanup_button_state()

    def open_video_subtitle_output(self):
        open_path(self.video_last_output_path)

    def open_video_subtitle_output_folder(self):
        if self.video_last_output_path and Path(self.video_last_output_path).is_file():
            open_path(Path(self.video_last_output_path).parent)

    def update_video_subtitle_button_state(self):
        if not hasattr(self, "video_start_button"):
            return
        busy_elsewhere = (
            self.is_converting
            or self.is_stt_running
            or self.is_audio_cleanup_running
            or self.is_cleanup_running
        )
        burn_mode = self.video_subtitle_mode_key() == "burn"
        can_create = not self.is_video_running and not busy_elsewhere and self.video_subtitle_input_ready()
        self.video_start_button.setEnabled(can_create)
        self.set_video_subtitle_start_button_primary(can_create)
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
            self.video_shadow_spin,
            self.video_margin_spin,
            self.video_position_combo,
            self.video_text_color_combo,
            self.video_outline_color_combo,
            self.video_background_box_check,
            self.video_box_color_combo,
        ):
            widget.setEnabled(not self.is_video_running)
        self.video_box_color_combo.setEnabled(
            not self.is_video_running and self.video_background_box_check.isChecked()
        )
        self.update_navigation_state()

    def video_subtitle_input_ready(self) -> bool:
        if not hasattr(self, "video_media_picker") or not hasattr(self, "video_srt_picker"):
            return False
        media_path = self.video_media_picker.text()
        srt_path = self.video_srt_picker.text()
        return bool(
            media_path
            and srt_path
            and Path(media_path).is_file()
            and Path(srt_path).is_file()
            and Path(srt_path).suffix.lower() == ".srt"
        )

    def set_video_subtitle_start_button_primary(self, is_primary: bool) -> None:
        if not hasattr(self, "video_start_button"):
            return
        if not hasattr(self.video_start_button, "objectName"):
            return
        object_name = "PrimaryButton" if is_primary else ""
        if self.video_start_button.objectName() == object_name:
            return
        self.video_start_button.setObjectName(object_name)
        self.video_start_button.style().unpolish(self.video_start_button)
        self.video_start_button.style().polish(self.video_start_button)

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
            self.video_details_button.setText(self.subtitle_text("Show details"))
            return
        self.video_log.show()
        self.video_details_button.setText(self.subtitle_text("Hide details"))

    def build_video_subtitle_page(self):
        page, layout = self.page_container()
        self.page_header(
            layout,
            "Subtitles",
            "Embed an SRT track without re-encoding or burn subtitles directly into the video frames.",
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
        self.video_media_picker.edit.textChanged.connect(lambda _text: self.update_video_subtitle_output(force=False))
        self.video_media_picker.edit.textChanged.connect(lambda _text: self.update_video_subtitle_button_state())
        self.video_srt_picker.edit.textChanged.connect(lambda _text: self.update_video_subtitle_button_state())
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
        self.populate_video_subtitle_combo(self.video_quality_combo, BURN_QUALITY_LABELS)
        self.video_quality_combo.currentIndexChanged.connect(lambda _index: self.update_video_quality_description())
        self.video_crf_note = QLabel(
            "CRF is constant quality: lower number means higher quality and a larger output file."
        )
        self.video_crf_note.setObjectName("Muted")
        self.video_crf_note.setWordWrap(True)
        self.video_quality_description = QLabel(self.subtitle_text(BURN_QUALITY_DESCRIPTIONS[BURN_QUALITY_AUTO_LABEL]))
        self.video_quality_description.setObjectName("Muted")
        self.video_quality_description.setWordWrap(True)
        self.video_style_panel = Card("Burn-in font")
        self.video_style_panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        style_layout = QGridLayout()
        style_layout.setContentsMargins(0, 0, 0, 0)
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
        self.video_shadow_spin = QSpinBox()
        self.video_shadow_spin.setRange(0, 4)
        self.video_shadow_spin.setValue(0)
        self.video_position_combo = QComboBox()
        self.populate_video_subtitle_combo(self.video_position_combo, tuple(VIDEO_SUBTITLE_POSITION_LABELS))
        self.video_text_color_combo = QComboBox()
        self.populate_video_subtitle_combo(self.video_text_color_combo, tuple(VIDEO_SUBTITLE_TEXT_COLOR_LABELS))
        self.video_outline_color_combo = QComboBox()
        self.populate_video_subtitle_combo(self.video_outline_color_combo, tuple(VIDEO_SUBTITLE_OUTLINE_COLOR_LABELS))
        self.video_background_box_check = QCheckBox("Background box")
        self.video_box_color_combo = QComboBox()
        self.populate_video_subtitle_combo(self.video_box_color_combo, tuple(VIDEO_SUBTITLE_BOX_COLOR_LABELS))
        for spinbox in (
            self.video_font_size_spin,
            self.video_outline_spin,
            self.video_shadow_spin,
            self.video_margin_spin,
        ):
            spinbox.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            spinbox.setAlignment(Qt.AlignmentFlag.AlignCenter)
            spinbox.setFixedWidth(82)
        self.video_position_combo.setMinimumWidth(180)
        self.video_text_color_combo.setMinimumWidth(150)
        self.video_outline_color_combo.setMinimumWidth(130)
        self.video_box_color_combo.setMinimumWidth(150)
        self.video_font_size_spin.valueChanged.connect(lambda _value: self.save_user_settings())
        self.video_outline_spin.valueChanged.connect(lambda _value: self.save_user_settings())
        self.video_shadow_spin.valueChanged.connect(lambda _value: self.save_user_settings())
        self.video_margin_spin.valueChanged.connect(lambda _value: self.save_user_settings())
        self.video_position_combo.currentIndexChanged.connect(lambda _index: self.save_user_settings())
        self.video_text_color_combo.currentIndexChanged.connect(lambda _index: self.save_user_settings())
        self.video_outline_color_combo.currentIndexChanged.connect(lambda _index: self.save_user_settings())
        self.video_background_box_check.toggled.connect(lambda _checked: self.update_video_subtitle_style_options())
        self.video_box_color_combo.currentIndexChanged.connect(lambda _index: self.save_user_settings())
        layout_label = QLabel("Layout")
        layout_label.setObjectName("Muted")
        legibility_label = QLabel("Legibility")
        legibility_label.setObjectName("Muted")
        colors_label = QLabel("Colors")
        colors_label.setObjectName("Muted")
        style_layout.addWidget(layout_label, 0, 0)
        style_layout.addWidget(QLabel("Position"), 0, 1)
        style_layout.addWidget(self.video_position_combo, 0, 2)
        style_layout.addWidget(QLabel("Vertical margin"), 0, 3)
        style_layout.addWidget(self.video_margin_spin, 0, 4)
        style_layout.addWidget(QLabel("Font size"), 0, 5)
        style_layout.addWidget(self.video_font_size_spin, 0, 6)
        style_layout.addWidget(legibility_label, 1, 0)
        style_layout.addWidget(QLabel("Outline"), 1, 1)
        style_layout.addWidget(self.video_outline_spin, 1, 2)
        style_layout.addWidget(QLabel("Shadow"), 1, 3)
        style_layout.addWidget(self.video_shadow_spin, 1, 4)
        style_layout.addWidget(self.video_background_box_check, 1, 5, 1, 2)
        style_layout.addWidget(colors_label, 2, 0)
        style_layout.addWidget(QLabel("Text"), 2, 1)
        style_layout.addWidget(self.video_text_color_combo, 2, 2)
        style_layout.addWidget(QLabel("Outline"), 2, 3)
        style_layout.addWidget(self.video_outline_color_combo, 2, 4)
        style_layout.addWidget(QLabel("Box"), 2, 5)
        style_layout.addWidget(self.video_box_color_combo, 2, 6)
        style_layout.setColumnStretch(7, 1)
        self.video_style_panel.content_layout.addLayout(style_layout)
        settings_card.content_layout.addWidget(QLabel("Mode"))
        settings_card.content_layout.addLayout(mode_row)
        settings_card.content_layout.addWidget(self.video_mode_note)
        settings_card.content_layout.addWidget(self.video_quality_label)
        settings_card.content_layout.addWidget(self.video_quality_combo)
        settings_card.content_layout.addWidget(self.video_crf_note)
        settings_card.content_layout.addWidget(self.video_quality_description)

        grid.addWidget(files_card, 0, 0, Qt.AlignmentFlag.AlignTop)
        grid.addWidget(settings_card, 0, 1, Qt.AlignmentFlag.AlignTop)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        layout.addWidget(self.video_style_panel)

        action_card = Card()
        action_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        self.video_start_button = QPushButton("Create video")
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
        self.update_video_subtitle_style_options()
        self.update_video_subtitle_button_state()
        return page
