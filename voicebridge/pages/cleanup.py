import os
import subprocess
import tempfile
import threading
from contextlib import suppress
from functools import partial
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from media_tools import (
    STT_VIDEO_SUFFIXES,
    BlackFrame,
    black_frame_detect_command,
    find_ffmpeg_exe,
    isolated_black_frame_numbers,
    parse_blackframe_line,
    probe_video_info,
    suggest_video_cleanup_output_path,
    video_cleanup_repair_commands,
    video_frame_preview_command,
)
from voicebridge.constants import (
    BURN_QUALITY_AUTO,
    BURN_QUALITY_AUTO_LABEL,
    VIDEO_CLEANUP_FREEZE_LABEL,
    VIDEO_CLEANUP_METHOD_BY_LABEL,
    VIDEO_CLEANUP_METHOD_DESCRIPTIONS,
    VIDEO_CLEANUP_METHOD_FREEZE,
    VIDEO_CLEANUP_METHOD_LABELS,
    VIDEO_CLEANUP_METHOD_REMOVE,
    VIDEO_CLEANUP_QUALITY_BY_LABEL,
    VIDEO_CLEANUP_QUALITY_DESCRIPTIONS,
    VIDEO_CLEANUP_QUALITY_LABELS,
)
from voicebridge.ui.helpers import open_path
from voicebridge.ui.widgets import Card, FilePicker


class VideoCleanupWorkflowMixin:
    def cleanup_media_changed(self):
        self.update_cleanup_output(force=False)
        if self.cleanup_detected_media_path and self.cleanup_media_picker.text() != self.cleanup_detected_media_path:
            self.clear_cleanup_detection_results("Ready.")
        self.update_video_cleanup_button_state()
        self.save_user_settings()

    def clear_cleanup_detection_results(self, status_text=None):
        self.cleanup_detected_frames = []
        self.cleanup_detected_media_path = ""
        self.cleanup_repairable_frame_map = {}
        self.cleanup_frame_checkboxes = {}
        if hasattr(self, "cleanup_results"):
            self.cleanup_results.clear()
        if hasattr(self, "cleanup_repair_options"):
            self.cleanup_repair_options.hide()
        if hasattr(self, "cleanup_repair_button"):
            self.cleanup_repair_button.hide()
        if status_text is not None and hasattr(self, "cleanup_status"):
            self.cleanup_status.setText(status_text)

    def update_cleanup_quality_description(self, text):
        self.cleanup_quality_description.setText(VIDEO_CLEANUP_QUALITY_DESCRIPTIONS.get(text, ""))
        self.save_user_settings()

    def update_cleanup_method_description(self, text):
        self.cleanup_method_description.setText(VIDEO_CLEANUP_METHOD_DESCRIPTIONS.get(text, ""))
        self.save_user_settings()

    def cleanup_method_key(self):
        return VIDEO_CLEANUP_METHOD_BY_LABEL.get(self.cleanup_method_combo.currentText(), VIDEO_CLEANUP_METHOD_FREEZE)

    def update_cleanup_output(self, force=False):
        if not hasattr(self, "cleanup_output_picker"):
            return
        media_path = self.cleanup_media_picker.text()
        if not media_path:
            return
        suggested = suggest_video_cleanup_output_path(media_path)
        current = self.cleanup_output_picker.text()
        if force or not current or current == self.cleanup_last_auto_output_path:
            self.cleanup_output_picker.set_text(suggested)
            self.cleanup_last_auto_output_path = suggested

    def select_cleanup_media_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select video file",
            self.cleanup_media_picker.text() or str(Path.home()),
            "Video files (*.mp4 *.mkv *.mov *.avi *.webm *.m4v);;All files (*.*)",
        )
        if path:
            self.cleanup_media_picker.set_text(path)
            self.update_cleanup_output(force=False)
            self.save_user_settings()

    def select_cleanup_output_file(self):
        media_path = self.cleanup_media_picker.text()
        suggested = self.cleanup_output_picker.text() or (
            suggest_video_cleanup_output_path(media_path) if media_path else str(Path.home() / "cleaned_video.mp4")
        )
        filter_text = "MP4 video (*.mp4);;Matroska video (*.mkv);;QuickTime video (*.mov);;All files (*.*)"
        path, selected_filter = QFileDialog.getSaveFileName(self, "Save repaired video as", suggested, filter_text)
        if path:
            default_suffix = (
                ".mkv"
                if "Matroska" in selected_filter
                else ".mov"
                if "QuickTime" in selected_filter
                else ".mp4"
            )
            self.cleanup_output_picker.set_text(self.normalize_cleanup_output_path(path, media_path, default_suffix))
            self.cleanup_last_auto_output_path = ""
            self.save_user_settings()

    @staticmethod
    def normalize_cleanup_output_path(output_path, media_path, default_suffix=".mp4"):
        path = Path(output_path)
        if path.suffix:
            return str(path)
        media_suffix = Path(media_path).suffix.lower() if media_path else ""
        fallback = media_suffix if media_suffix in {".mp4", ".mkv", ".mov", ".m4v"} else default_suffix
        return str(path.with_suffix(fallback))

    def collect_video_cleanup_media(self):
        media_path = self.cleanup_media_picker.text()
        if not media_path:
            raise ValueError("Please select a video file.")
        media = Path(media_path)
        if not media.is_file():
            raise ValueError("The selected video file does not exist.")
        if media.suffix.lower() not in STT_VIDEO_SUFFIXES:
            raise ValueError("The selected file must be a video.")
        return media_path

    def selected_cleanup_frame_numbers(self) -> list[int]:
        selected: list[int] = []
        for frame_number, checkbox in self.cleanup_frame_checkboxes.items():
            if frame_number in self.cleanup_repairable_frame_map and checkbox.isChecked():
                selected.append(frame_number)
        return sorted(selected)

    def selected_cleanup_frame_times(self, selected_frames: list[int]) -> list[float]:
        return [
            self.cleanup_repairable_frame_map[frame_number]["time"]
            for frame_number in selected_frames
            if frame_number in self.cleanup_repairable_frame_map
        ]

    def collect_video_cleanup_repair_options(self):
        media_path = self.collect_video_cleanup_media()
        if self.cleanup_detected_media_path != media_path:
            raise ValueError("Run detection on this video before repairing frames.")
        selected_frames = self.selected_cleanup_frame_numbers()
        if not selected_frames:
            raise ValueError("Select at least one repairable frame to repair.")

        output_path = self.cleanup_output_picker.text()
        if not output_path:
            output_path = suggest_video_cleanup_output_path(media_path)
            self.cleanup_output_picker.set_text(output_path)
        output_path = self.normalize_cleanup_output_path(output_path, media_path)
        output = Path(output_path)
        if output.suffix.lower() not in {".mp4", ".mkv", ".mov", ".m4v"}:
            raise ValueError("Repaired video output must be .mp4, .mkv, .mov or .m4v.")
        try:
            if output.resolve() == Path(media_path).resolve():
                raise ValueError("Choose an output path different from the source video.")
        except OSError:
            pass
        self.cleanup_output_picker.set_text(output_path)
        self.save_user_settings()

        cleanup_quality = VIDEO_CLEANUP_QUALITY_BY_LABEL.get(
            self.cleanup_quality_combo.currentText(),
            BURN_QUALITY_AUTO,
        )
        cleanup_method = self.cleanup_method_key()
        selected_frame_times = self.selected_cleanup_frame_times(selected_frames)
        return media_path, output_path, cleanup_quality, cleanup_method, selected_frames, selected_frame_times

    def start_video_cleanup_from_page(self):
        try:
            media_path = self.collect_video_cleanup_media()
        except ValueError as exc:
            self.cleanup_status.setText("Error.")
            self.show_error("Video Cleanup", str(exc))
            return
        ffmpeg = find_ffmpeg_exe()
        if not ffmpeg:
            self.cleanup_status.setText("ffmpeg missing.")
            self.show_error("ffmpeg missing", "Could not find ffmpeg. Use the full VoiceBridge bundle.")
            return

        self.cleanup_cancel_requested = False
        self.cleanup_process = None
        self.cleanup_last_output_path = ""
        self.clear_cleanup_detection_results()
        self.reset_cleanup_log()
        self.cleanup_results.clear()
        self.is_cleanup_running = True
        self.show_indeterminate_progress(self.cleanup_progress)
        self.cleanup_status.setText("Detecting black frames...")
        self.append_cleanup_log(f"Detecting black frames: {media_path}")
        self.update_video_cleanup_button_state()
        self.update_tts_button_state()
        self.update_stt_button_state()
        self.update_video_subtitle_button_state()
        threading.Thread(
            target=self.video_cleanup_detect_worker,
            args=(str(ffmpeg), media_path),
            daemon=True,
        ).start()

    def start_video_cleanup_repair_from_page(self):
        try:
            (
                media_path,
                output_path,
                cleanup_quality,
                cleanup_method,
                selected_frames,
                selected_frame_times,
            ) = self.collect_video_cleanup_repair_options()
        except ValueError as exc:
            self.cleanup_status.setText("Error.")
            self.show_error("Video Cleanup", str(exc))
            return
        ffmpeg = find_ffmpeg_exe()
        if not ffmpeg:
            self.cleanup_status.setText("ffmpeg missing.")
            self.show_error("ffmpeg missing", "Could not find ffmpeg. Use the full VoiceBridge bundle.")
            return

        self.cleanup_cancel_requested = False
        self.cleanup_process = None
        self.cleanup_last_output_path = ""
        self.is_cleanup_running = True
        self.update_cleanup_progress_percent(0)
        action = "Removing" if cleanup_method == VIDEO_CLEANUP_METHOD_REMOVE else "Repairing"
        self.cleanup_status.setText(f"{action} {len(selected_frames)} selected frame(s)...")
        self.append_cleanup_log("")
        self.append_cleanup_log(f"{action} selected frames: {', '.join(str(frame) for frame in selected_frames)}")
        self.update_video_cleanup_button_state()
        self.update_tts_button_state()
        self.update_stt_button_state()
        self.update_video_subtitle_button_state()
        threading.Thread(
            target=self.video_cleanup_repair_worker,
            args=(
                str(ffmpeg),
                media_path,
                output_path,
                cleanup_quality,
                cleanup_method,
                selected_frames,
                selected_frame_times,
            ),
            daemon=True,
        ).start()

    def video_cleanup_detect_worker(self, ffmpeg, media_path):
        try:
            self.post(self.append_cleanup_log, "Detecting source video details...")
            source_video_info = probe_video_info(ffmpeg, media_path)
            duration_seconds = source_video_info.get("duration_seconds")
            if duration_seconds:
                self.post(self.update_cleanup_progress_percent, 0)
            else:
                self.post(self.set_cleanup_progress_indeterminate)

            command = black_frame_detect_command(ffmpeg, media_path)
            black_frames, recent_output = self.run_blackframe_detect_process(command, duration_seconds, 0, 100)
            if self.cleanup_cancel_requested:
                self.post(self.video_cleanup_job_cancelled)
                return
            isolated_frames, longer_runs = isolated_black_frame_numbers(black_frames, max_run_length=1)
            self.post(self.cleanup_detection_finished, media_path, black_frames, isolated_frames, longer_runs)
            self.post(self.video_cleanup_detect_succeeded, black_frames, isolated_frames, longer_runs)
        except (OSError, RuntimeError, ValueError) as exc:
            self.post(self.video_cleanup_job_failed, str(exc))
        finally:
            self.cleanup_process = None
            self.post(self.finish_video_cleanup_job)

    def video_cleanup_repair_worker(
        self,
        ffmpeg,
        media_path,
        output_path,
        cleanup_quality,
        cleanup_method,
        selected_frames,
        selected_frame_times,
    ):
        temp_output_path = None
        try:
            self.post(self.append_cleanup_log, "Detecting source video details...")
            source_video_info = probe_video_info(ffmpeg, media_path)
            duration_seconds = source_video_info.get("duration_seconds")
            if duration_seconds:
                self.post(self.update_cleanup_progress_percent, 0)
            else:
                self.post(self.set_cleanup_progress_indeterminate)

            if not selected_frames:
                self.post(self.video_cleanup_no_repair_needed)
                return

            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(
                prefix=f".{output_path.stem}.voicebridge-clean-",
                suffix=output_path.suffix,
                dir=str(output_path.parent),
            )
            os.close(fd)
            temp_output_path = Path(temp_name)
            temp_output_path.unlink(missing_ok=True)

            removing_frames = cleanup_method == VIDEO_CLEANUP_METHOD_REMOVE
            action = "Removing" if removing_frames else "Repairing"
            self.post(self.cleanup_status.setText, f"{action} {len(selected_frames)} selected frame(s)...")
            self.post(self.append_cleanup_log, f"Clean method: {cleanup_method}")
            self.post(self.append_cleanup_log, f"Output quality: {cleanup_quality}")
            if removing_frames:
                source_fps = source_video_info.get("fps")
                fps_note = f"{source_fps:.3f} fps" if source_fps else "fps unavailable; assuming 25 fps"
                self.post(self.append_cleanup_log, f"Removing matching audio slices too ({fps_note}).")
            self.post(
                self.append_cleanup_log,
                f"{action} frames: {', '.join(str(frame) for frame in selected_frames[:40])}",
            )
            if len(selected_frames) > 40:
                self.post(self.append_cleanup_log, f"...and {len(selected_frames) - 40} more.")

            commands = video_cleanup_repair_commands(
                ffmpeg,
                media_path,
                str(temp_output_path),
                selected_frames,
                repair_method=cleanup_method,
                cleanup_quality=cleanup_quality,
                source_video_bitrate_kbps=source_video_info.get("bitrate_kbps"),
                source_video_width=source_video_info.get("width"),
                source_video_height=source_video_info.get("height"),
                source_video_fps=source_video_info.get("fps"),
                source_has_audio=source_video_info.get("has_audio", True),
                frame_times_seconds=selected_frame_times,
            )
            recent_output = []
            for command in commands:
                return_code, recent_output = self.run_cleanup_ffmpeg_process(command, duration_seconds, 0, 100)
                if return_code == 0:
                    if self.cleanup_cancel_requested:
                        self.post(self.video_cleanup_job_cancelled)
                        return
                    os.replace(temp_output_path, output_path)
                    self.post(self.update_cleanup_progress_percent, 100)
                    self.post(
                        self.video_cleanup_repair_succeeded,
                        str(output_path),
                        len(selected_frames),
                        cleanup_method,
                    )
                    return
                if self.cleanup_cancel_requested:
                    self.post(self.video_cleanup_job_cancelled)
                    return
            raise RuntimeError("\n".join(recent_output[-8:]) or "ffmpeg could not repair the video.")
        except (OSError, RuntimeError, ValueError) as exc:
            self.post(self.video_cleanup_job_failed, str(exc))
        finally:
            if temp_output_path:
                with suppress(OSError):
                    temp_output_path.unlink(missing_ok=True)
            self.cleanup_process = None
            self.post(self.finish_video_cleanup_job)

    def run_blackframe_detect_process(
        self,
        command: list[str],
        duration_seconds: float | None = None,
        progress_start: int = 0,
        progress_end: int = 100,
    ) -> tuple[list[BlackFrame], list[str]]:
        black_frames: list[BlackFrame] = []
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
        self.cleanup_process = process
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.strip()
            if not line:
                continue
            progress_percent = self.ffmpeg_progress_percent(line, duration_seconds)
            if progress_percent is not None:
                mapped = progress_start + ((progress_end - progress_start) * progress_percent / 100)
                if mapped > last_progress_percent:
                    last_progress_percent = mapped
                    self.post(self.update_cleanup_progress_percent, mapped)
                continue
            if self.is_ffmpeg_progress_line(line):
                continue
            black_frame = parse_blackframe_line(line)
            if black_frame:
                black_frames.append(black_frame)
                self.post(
                    self.append_cleanup_log,
                    f"Black frame candidate: frame {black_frame['frame']} at {black_frame['time']:.3f}s "
                    f"({black_frame['pblack']}% black)",
                )
                continue
            recent_output.append(line)
            recent_output = recent_output[-12:]
            if self.cleanup_cancel_requested and process.poll() is None:
                process.terminate()
        return_code = process.wait()
        if return_code != 0 and not self.cleanup_cancel_requested:
            raise RuntimeError("\n".join(recent_output[-8:]) or f"ffmpeg exited with code {return_code}.")
        return black_frames, recent_output

    def run_cleanup_ffmpeg_process(self, command, duration_seconds=None, progress_start=0, progress_end=100):
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
        self.cleanup_process = process
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.strip()
            if not line:
                continue
            progress_percent = self.ffmpeg_progress_percent(line, duration_seconds)
            if progress_percent is not None:
                mapped = progress_start + ((progress_end - progress_start) * progress_percent / 100)
                if mapped > last_progress_percent:
                    last_progress_percent = mapped
                    self.post(self.update_cleanup_progress_percent, mapped)
                continue
            if self.is_ffmpeg_progress_line(line):
                continue
            recent_output.append(line)
            recent_output = recent_output[-12:]
            self.post(self.append_cleanup_log, line)
            if self.cleanup_cancel_requested and process.poll() is None:
                process.terminate()
        return process.wait(), recent_output

    @staticmethod
    def cleanup_long_run_reason_map(longer_runs: list[list[BlackFrame]]) -> dict[int, str]:
        reasons: dict[int, str] = {}
        for run in longer_runs:
            if not run:
                continue
            frame_numbers = [frame["frame"] for frame in run]
            if len(run) == 1 and frame_numbers[0] == 0:
                reason = "Skipped: first frame / edge candidate"
            else:
                reason = "Skipped: longer black run, fade or head/tail section"
            for frame_number in frame_numbers:
                reasons[frame_number] = reason
        return reasons

    def add_cleanup_result_row(self, frame: BlackFrame, repairable: bool, reason: str) -> None:
        frame_number = frame["frame"]
        item = QListWidgetItem()
        item.setSizeHint(QSize(0, 46))
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(8, 4, 8, 4)
        row_layout.setSpacing(10)

        checkbox = QCheckBox()
        checkbox.setChecked(repairable)
        checkbox.setEnabled(repairable and not self.is_cleanup_running)
        checkbox.stateChanged.connect(lambda _state: self.update_video_cleanup_button_state())
        self.cleanup_frame_checkboxes[frame_number] = checkbox

        title = QLabel(f"Frame {frame_number} | {frame['time']:.3f}s | {frame['pblack']}% black")
        title.setWordWrap(True)
        title.setMinimumWidth(260)
        state = QLabel("Repairable" if repairable else reason)
        state.setObjectName("Muted")
        state.setWordWrap(True)
        detail_button = QPushButton("Details")
        detail_button.setEnabled(repairable)
        detail_button.clicked.connect(partial(self.show_cleanup_frame_details_from_button, frame))

        row_layout.addWidget(checkbox)
        row_layout.addWidget(title, 2)
        row_layout.addWidget(state, 2)
        row_layout.addWidget(detail_button)
        self.cleanup_results.addItem(item)
        self.cleanup_results.setItemWidget(item, row)

    def cleanup_detection_finished(
        self,
        media_path: str,
        black_frames: list[BlackFrame],
        isolated_frames: list[int],
        longer_runs: list[list[BlackFrame]],
    ) -> None:
        self.cleanup_detected_frames = black_frames
        self.cleanup_detected_media_path = media_path
        self.cleanup_repairable_frame_map = {
            frame["frame"]: frame for frame in black_frames if frame["frame"] in set(isolated_frames)
        }
        self.cleanup_frame_checkboxes = {}
        self.cleanup_results.clear()
        if not black_frames:
            self.cleanup_results.addItem("No black-frame candidates found.")
            self.update_video_cleanup_button_state()
            return
        self.cleanup_results.addItem(f"Black-frame candidates: {len(black_frames)}")
        self.cleanup_results.addItem(f"Repairable isolated frames: {len(isolated_frames)}")
        if longer_runs:
            self.cleanup_results.addItem(f"Longer black runs left untouched: {len(longer_runs)}")
        reason_by_frame = self.cleanup_long_run_reason_map(longer_runs)
        isolated_set = set(isolated_frames)
        for frame in black_frames[:120]:
            repairable = frame["frame"] in isolated_set
            reason = reason_by_frame.get(frame["frame"], "Skipped: not an isolated one-frame glitch")
            self.add_cleanup_result_row(frame, repairable, reason)
        if len(black_frames) > 120:
            self.cleanup_results.addItem(f"...and {len(black_frames) - 120} more candidates. See details.")
        self.update_video_cleanup_button_state()

    def show_cleanup_frame_details_from_button(self, frame: BlackFrame, _checked: bool = False) -> None:
        self.show_cleanup_frame_details(frame)

    def show_cleanup_frame_details(self, frame: BlackFrame) -> None:
        media_path = self.cleanup_detected_media_path or self.cleanup_media_picker.text()
        if not media_path:
            self.show_error("Frame details", "Select a video and run detection first.")
            return
        ffmpeg = find_ffmpeg_exe()
        if not ffmpeg:
            self.show_error("ffmpeg missing", "Could not find ffmpeg. Use the full VoiceBridge bundle.")
            return

        frame_number = int(frame["frame"])
        preview_specs = [
            ("Previous frame", max(0, frame_number - 1)),
            ("Problem frame", frame_number),
            ("Next frame", frame_number + 1),
        ]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        with tempfile.TemporaryDirectory(prefix="voicebridge-frame-preview-") as temp_dir:
            preview_paths = []
            for title, preview_frame in preview_specs:
                output_path = str(Path(temp_dir) / f"frame_{preview_frame}.png")
                command = video_frame_preview_command(ffmpeg, media_path, preview_frame, output_path)
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=creationflags,
                    timeout=60,
                    check=False,
                )
                preview_path = (
                    output_path
                    if result.returncode == 0 and Path(output_path).is_file()
                    else ""
                )
                preview_paths.append((title, preview_frame, preview_path))

            dialog = QDialog(self)
            dialog.setWindowTitle(f"Frame {frame_number} details")
            dialog.setMinimumWidth(980)
            layout = QVBoxLayout(dialog)
            header = QLabel(f"Frame {frame_number} at {frame['time']:.3f}s")
            header.setObjectName("CardTitle")
            layout.addWidget(header)
            row = QHBoxLayout()
            row.setSpacing(12)
            layout.addLayout(row)

            for title, preview_frame, preview_path in preview_paths:
                panel = QVBoxLayout()
                label = QLabel(f"{title}\n#{preview_frame}")
                label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                image = QLabel()
                image.setAlignment(Qt.AlignmentFlag.AlignCenter)
                image.setMinimumSize(300, 170)
                image.setStyleSheet("background: #0f172a; border-radius: 6px; color: #e5e7eb;")
                if preview_path:
                    pixmap = QPixmap(preview_path)
                    if not pixmap.isNull():
                        image.setPixmap(
                            pixmap.scaled(
                                300,
                                170,
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation,
                            )
                        )
                    else:
                        image.setText("Preview unavailable")
                else:
                    image.setText("Preview unavailable")
                panel.addWidget(label)
                panel.addWidget(image)
                row.addLayout(panel)

            close_button = QPushButton("Close")
            close_button.clicked.connect(dialog.accept)
            footer = QHBoxLayout()
            footer.addStretch(1)
            footer.addWidget(close_button)
            layout.addLayout(footer)
            dialog.exec()

    def video_cleanup_detect_succeeded(self, black_frames, isolated_frames, longer_runs):
        if black_frames:
            self.cleanup_status.setText(
                f"Detected {len(black_frames)} black-frame candidate(s); {len(isolated_frames)} repairable."
            )
        else:
            self.cleanup_status.setText("No black-frame candidates found.")
        if longer_runs:
            self.append_cleanup_log(
                f"Longer black runs were detected and left untouched: {len(longer_runs)}. "
                "These may be fades or intentional black sections."
            )

    def video_cleanup_no_repair_needed(self):
        self.cleanup_status.setText("No isolated black frames to clean.")
        self.append_cleanup_log("No one-frame black glitches were selected. No output video was created.")

    def video_cleanup_repair_succeeded(self, output_path, repaired_count, cleanup_method):
        self.cleanup_last_output_path = output_path
        removed = cleanup_method == VIDEO_CLEANUP_METHOD_REMOVE
        status_text = (
            f"Removed {repaired_count} selected frame(s)."
            if removed
            else f"Repaired {repaired_count} selected frame(s)."
        )
        self.cleanup_status.setText(status_text)
        self.append_cleanup_log(f"Video saved: {output_path}")
        self.record_job(
            "CLEAN",
            "Video cleaned",
            self.cleanup_media_picker.text(),
            output_path,
            f"{repaired_count} frame(s), {'removed' if removed else 'freeze'}",
        )
        self.show_info("Video Cleanup", f"Video saved:\n{output_path}")

    def video_cleanup_job_cancelled(self):
        self.cleanup_status.setText("Cancelled.")
        self.append_cleanup_log("Job cancelled.")

    def video_cleanup_job_failed(self, message):
        self.cleanup_status.setText("Error.")
        self.append_cleanup_log(f"ERROR: {message}")
        self.show_error("Video Cleanup", message)

    def finish_video_cleanup_job(self):
        self.is_cleanup_running = False
        self.cleanup_progress.hide()
        self.update_video_cleanup_button_state()
        self.update_tts_button_state()
        self.update_stt_button_state()
        self.update_video_subtitle_button_state()

    def cancel_video_cleanup_job(self):
        if not self.is_cleanup_running:
            return
        self.cleanup_cancel_requested = True
        self.cleanup_status.setText("Cancelling...")
        self.append_cleanup_log("Cancellation requested.")
        self.update_video_cleanup_button_state()
        process = self.cleanup_process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError as exc:
                self.append_cleanup_log(f"Could not terminate process cleanly: {exc}")

    def open_cleanup_output(self):
        open_path(self.cleanup_last_output_path)

    def open_cleanup_output_folder(self):
        if self.cleanup_last_output_path and Path(self.cleanup_last_output_path).is_file():
            open_path(Path(self.cleanup_last_output_path).parent)

    def update_video_cleanup_button_state(self):
        if not hasattr(self, "cleanup_start_button"):
            return
        busy_elsewhere = self.is_converting or self.is_stt_running or self.is_video_running
        current_media = self.cleanup_media_picker.text()
        detection_ready = bool(
            self.cleanup_detected_media_path
            and self.cleanup_detected_media_path == current_media
            and self.cleanup_repairable_frame_map
        )
        selected_frames = self.selected_cleanup_frame_numbers() if detection_ready else []
        self.cleanup_start_button.setEnabled(not self.is_cleanup_running and not busy_elsewhere)
        self.cleanup_repair_button.setVisible(detection_ready)
        self.cleanup_repair_button.setEnabled(
            detection_ready
            and bool(selected_frames)
            and not self.is_cleanup_running
            and not busy_elsewhere
        )
        self.cleanup_cancel_button.setEnabled(self.is_cleanup_running and not self.cleanup_cancel_requested)
        output_ready = bool(self.cleanup_last_output_path and Path(self.cleanup_last_output_path).is_file())
        self.cleanup_open_output_button.setEnabled(output_ready)
        self.cleanup_open_folder_button.setEnabled(output_ready)
        self.cleanup_repair_options.setVisible(detection_ready)
        for widget in (
            self.cleanup_media_picker,
            self.cleanup_output_picker,
            self.cleanup_method_combo,
            self.cleanup_quality_combo,
        ):
            widget.setEnabled(not self.is_cleanup_running)
        for frame_number, checkbox in self.cleanup_frame_checkboxes.items():
            checkbox.setEnabled(
                detection_ready
                and frame_number in self.cleanup_repairable_frame_map
                and not self.is_cleanup_running
            )
        self.update_navigation_state()

    def append_cleanup_log(self, line):
        self.cleanup_log_lines.append(line)
        self.cleanup_log_lines = self.cleanup_log_lines[-300:]
        self.cleanup_log.appendPlainText(line)
        scrollbar = self.cleanup_log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def reset_cleanup_log(self):
        self.cleanup_log_lines = []
        self.cleanup_log.clear()

    def toggle_cleanup_details(self):
        if self.cleanup_log.isVisible():
            self.cleanup_log.hide()
            self.cleanup_details_button.setText("Show details")
            return
        self.cleanup_log.show()
        self.cleanup_details_button.setText("Hide details")

    def build_video_cleanup_page(self):
        page, layout = self.page_container()
        self.page_header(
            layout,
            "CLEANUP",
            "Video Cleanup",
            "Detect isolated black-frame glitches and clean selected frames before export or subtitling.",
            "BadgeGreen",
        )

        grid = QGridLayout()
        grid.setSpacing(16)
        layout.addLayout(grid)

        files_card = Card("Files")
        files_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.cleanup_media_picker = FilePicker("Video file")
        self.cleanup_output_picker = FilePicker("Save repaired video as", "Save as...")
        self.cleanup_media_picker.button.clicked.connect(self.select_cleanup_media_file)
        self.cleanup_output_picker.button.clicked.connect(self.select_cleanup_output_file)
        self.cleanup_media_picker.edit.textChanged.connect(self.cleanup_media_changed)
        files_card.content_layout.addWidget(self.cleanup_media_picker)

        settings_card = Card("Detection")
        settings_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.cleanup_rule_note = QLabel(
            "Only isolated one-frame black glitches are repairable. "
            "Longer runs, including black heads/tails, are reported and left untouched."
        )
        self.cleanup_rule_note.setObjectName("Muted")
        self.cleanup_rule_note.setWordWrap(True)
        self.cleanup_repair_options = QWidget()
        repair_options_layout = QVBoxLayout(self.cleanup_repair_options)
        repair_options_layout.setContentsMargins(0, 8, 0, 0)
        repair_options_layout.setSpacing(8)
        self.cleanup_method_label = QLabel("Clean method")
        self.cleanup_method_combo = QComboBox()
        self.cleanup_method_combo.addItems(VIDEO_CLEANUP_METHOD_LABELS)
        self.cleanup_method_combo.setCurrentText(VIDEO_CLEANUP_FREEZE_LABEL)
        self.cleanup_method_combo.currentTextChanged.connect(self.update_cleanup_method_description)
        self.cleanup_method_description = QLabel(VIDEO_CLEANUP_METHOD_DESCRIPTIONS[VIDEO_CLEANUP_FREEZE_LABEL])
        self.cleanup_method_description.setObjectName("Muted")
        self.cleanup_method_description.setWordWrap(True)
        self.cleanup_quality_label = QLabel("Output quality")
        self.cleanup_quality_combo = QComboBox()
        self.cleanup_quality_combo.addItems(VIDEO_CLEANUP_QUALITY_LABELS)
        self.cleanup_quality_combo.setCurrentText(BURN_QUALITY_AUTO_LABEL)
        self.cleanup_quality_combo.currentTextChanged.connect(self.update_cleanup_quality_description)
        self.cleanup_quality_description = QLabel(VIDEO_CLEANUP_QUALITY_DESCRIPTIONS[BURN_QUALITY_AUTO_LABEL])
        self.cleanup_quality_description.setObjectName("Muted")
        self.cleanup_quality_description.setWordWrap(True)
        settings_card.content_layout.addWidget(self.cleanup_rule_note)
        repair_options_layout.addWidget(self.cleanup_output_picker)
        repair_options_layout.addWidget(self.cleanup_method_label)
        repair_options_layout.addWidget(self.cleanup_method_combo)
        repair_options_layout.addWidget(self.cleanup_method_description)
        repair_options_layout.addWidget(self.cleanup_quality_label)
        repair_options_layout.addWidget(self.cleanup_quality_combo)
        repair_options_layout.addWidget(self.cleanup_quality_description)
        settings_card.content_layout.addWidget(self.cleanup_repair_options)

        grid.addWidget(files_card, 0, 0)
        grid.addWidget(settings_card, 0, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        results_card = Card("Results")
        self.cleanup_results = QListWidget()
        self.cleanup_results.setMinimumHeight(160)
        results_card.content_layout.addWidget(self.cleanup_results)
        layout.addWidget(results_card)

        action_card = Card()
        action_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        self.cleanup_start_button = QPushButton("Detect black frames")
        self.cleanup_start_button.setObjectName("PrimaryButton")
        self.cleanup_repair_button = QPushButton("Clean selected frames")
        self.cleanup_repair_button.setObjectName("PrimaryButton")
        self.cleanup_cancel_button = QPushButton("Cancel")
        self.cleanup_open_output_button = QPushButton("Open output")
        self.cleanup_open_folder_button = QPushButton("Open folder")
        self.cleanup_details_button = QPushButton("Show details")
        self.cleanup_start_button.clicked.connect(self.start_video_cleanup_from_page)
        self.cleanup_repair_button.clicked.connect(self.start_video_cleanup_repair_from_page)
        self.cleanup_cancel_button.clicked.connect(self.cancel_video_cleanup_job)
        self.cleanup_open_output_button.clicked.connect(self.open_cleanup_output)
        self.cleanup_open_folder_button.clicked.connect(self.open_cleanup_output_folder)
        self.cleanup_details_button.clicked.connect(self.toggle_cleanup_details)
        actions.addWidget(self.cleanup_start_button)
        actions.addWidget(self.cleanup_repair_button)
        actions.addWidget(self.cleanup_cancel_button)
        actions.addStretch(1)
        actions.addWidget(self.cleanup_open_output_button)
        actions.addWidget(self.cleanup_open_folder_button)
        actions.addWidget(self.cleanup_details_button)
        action_card.content_layout.addLayout(actions)
        self.cleanup_progress = QProgressBar()
        self.cleanup_progress.setRange(0, 0)
        self.cleanup_progress.hide()
        self.cleanup_status = QLabel("Ready.")
        self.cleanup_status.setObjectName("StatusText")
        self.cleanup_log = QPlainTextEdit()
        self.cleanup_log.setObjectName("LogBox")
        self.cleanup_log.setReadOnly(True)
        self.cleanup_log.setMinimumHeight(160)
        self.cleanup_log.hide()
        action_card.content_layout.addWidget(self.cleanup_progress)
        action_card.content_layout.addWidget(self.cleanup_status)
        action_card.content_layout.addWidget(self.cleanup_log)
        layout.addWidget(action_card)
        layout.addStretch(1)

        self.cleanup_repair_options.hide()
        self.cleanup_repair_button.hide()
        self.update_video_cleanup_button_state()
        return page

