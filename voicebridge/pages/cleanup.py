import os
import subprocess
import tempfile
import threading
from contextlib import suppress
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
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
from voicebridge.file_checks import ensure_free_space, validate_output_path
from voicebridge.media_tools import (
    STT_VIDEO_SUFFIXES,
    BlackFrame,
    black_frame_detect_command,
    find_ffmpeg_exe,
    isolated_black_frame_numbers,
    parse_blackframe_line,
    probe_video_info,
    suggest_video_cleanup_output_path,
    video_cleanup_repair_commands,
    video_filmstrip_frame_numbers,
    video_frame_preview_command,
)
from voicebridge.ui.helpers import open_path
from voicebridge.ui.widgets import Card, FilePicker

VIDEO_OUTPUT_MIN_FREE_BYTES = 512 * 1024 * 1024
VIDEO_CLEANUP_FILMSTRIP_ITEMS = 36
VIDEO_CLEANUP_FILMSTRIP_ZOOM_WINDOWS = (0, 720, 240, 96, 36)
VIDEO_CLEANUP_FILMSTRIP_ICON_SIZES = (
    QSize(118, 66),
    QSize(138, 78),
    QSize(160, 90),
    QSize(184, 104),
    QSize(212, 120),
)


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
        self.cleanup_detected_frame_map = {}
        self.cleanup_marked_frame_numbers = set()
        self.cleanup_video_fps = 0.0
        self.cleanup_video_duration_seconds = 0.0
        self.cleanup_video_total_frames = 0
        self.cleanup_filmstrip_zoom_level = 0
        self.cleanup_filmstrip_generation = getattr(self, "cleanup_filmstrip_generation", 0) + 1
        if hasattr(self, "cleanup_results"):
            self.cleanup_results.clear()
        if hasattr(self, "cleanup_filmstrip_list"):
            self.cleanup_filmstrip_list.clear()
        if hasattr(self, "cleanup_filmstrip_status"):
            self.cleanup_filmstrip_status.setText("Run detection to load frame review.")
        if hasattr(self, "cleanup_filmstrip_scroll"):
            self.cleanup_filmstrip_scroll.setEnabled(False)
            self.cleanup_filmstrip_scroll.setValue(0)
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
        ffmpeg = find_ffmpeg_exe()
        if ffmpeg:
            info = probe_video_info(ffmpeg, media)
            if not info.get("width") or not info.get("height") or not info.get("duration_seconds"):
                raise ValueError("The selected video file could not be inspected or has no readable video stream.")
        return media_path

    def selected_cleanup_frame_numbers(self) -> list[int]:
        return sorted(
            int(frame_number)
            for frame_number in getattr(self, "cleanup_marked_frame_numbers", set())
            if int(frame_number) > 0
        )

    def cleanup_frame_time_seconds(self, frame_number: int) -> float:
        frame_number = int(frame_number)
        frame_info = self.cleanup_detected_frame_map.get(frame_number) or self.cleanup_repairable_frame_map.get(
            frame_number
        )
        if frame_info:
            return float(frame_info["time"])
        fps = float(getattr(self, "cleanup_video_fps", 0.0) or 0.0)
        if fps > 0:
            return frame_number / fps
        return 0.0

    def selected_cleanup_frame_times(self, selected_frames: list[int]) -> list[float]:
        return [self.cleanup_frame_time_seconds(frame_number) for frame_number in selected_frames]

    def collect_video_cleanup_repair_options(self):
        media_path = self.collect_video_cleanup_media()
        if self.cleanup_detected_media_path != media_path:
            raise ValueError("Run detection on this video before repairing frames.")
        selected_frames = self.selected_cleanup_frame_numbers()
        if not selected_frames:
            raise ValueError("Mark at least one frame to clean.")

        output_path = self.cleanup_output_picker.text()
        if not output_path:
            output_path = suggest_video_cleanup_output_path(media_path)
            self.cleanup_output_picker.set_text(output_path)
        output_path = self.normalize_cleanup_output_path(output_path, media_path)
        output = Path(output_path)
        if output.suffix.lower() not in {".mp4", ".mkv", ".mov", ".m4v"}:
            raise ValueError("Repaired video output must be .mp4, .mkv, .mov or .m4v.")
        validate_output_path(output, source_path=media_path, expected_suffixes={".mp4", ".mkv", ".mov", ".m4v"})
        source_size = Path(media_path).stat().st_size if Path(media_path).is_file() else 0
        ensure_free_space(output, max(VIDEO_OUTPUT_MIN_FREE_BYTES, source_size), "video cleanup output")
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
        self.update_audio_cleanup_button_state()
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
        self.update_audio_cleanup_button_state()
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
            self.post(
                self.cleanup_detection_finished,
                media_path,
                source_video_info,
                black_frames,
                isolated_frames,
                longer_runs,
            )
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

    def cleanup_filmstrip_window_frames(self) -> int:
        zoom_level = max(0, min(self.cleanup_filmstrip_zoom_level, len(VIDEO_CLEANUP_FILMSTRIP_ZOOM_WINDOWS) - 1))
        return VIDEO_CLEANUP_FILMSTRIP_ZOOM_WINDOWS[zoom_level]

    def cleanup_filmstrip_icon_size(self) -> QSize:
        zoom_level = max(0, min(self.cleanup_filmstrip_zoom_level, len(VIDEO_CLEANUP_FILMSTRIP_ICON_SIZES) - 1))
        return VIDEO_CLEANUP_FILMSTRIP_ICON_SIZES[zoom_level]

    def cleanup_filmstrip_selected_frames(self) -> list[int]:
        if not hasattr(self, "cleanup_filmstrip_list"):
            return []
        frames = []
        for item in self.cleanup_filmstrip_list.selectedItems():
            frame_number = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(frame_number, int):
                frames.append(frame_number)
        return sorted(set(frames))

    def configure_cleanup_filmstrip_scroll(self) -> None:
        if not hasattr(self, "cleanup_filmstrip_scroll"):
            return
        total_frames = int(getattr(self, "cleanup_video_total_frames", 0) or 0)
        window_frames = self.cleanup_filmstrip_window_frames() or total_frames
        enabled = total_frames > 0 and window_frames < total_frames
        self.cleanup_filmstrip_scroll.blockSignals(True)
        try:
            self.cleanup_filmstrip_scroll.setEnabled(enabled and not self.is_cleanup_running)
            self.cleanup_filmstrip_scroll.setRange(0, max(0, total_frames - window_frames))
            self.cleanup_filmstrip_scroll.setPageStep(max(1, window_frames // 2))
            self.cleanup_filmstrip_scroll.setSingleStep(max(1, window_frames // 12))
            if not enabled:
                self.cleanup_filmstrip_scroll.setValue(0)
        finally:
            self.cleanup_filmstrip_scroll.blockSignals(False)

    def cleanup_filmstrip_frame_numbers(self) -> list[int]:
        total_frames = int(getattr(self, "cleanup_video_total_frames", 0) or 0)
        if total_frames <= 0:
            return []
        window_frames = self.cleanup_filmstrip_window_frames() or total_frames
        start_frame = self.cleanup_filmstrip_scroll.value() if hasattr(self, "cleanup_filmstrip_scroll") else 0
        return video_filmstrip_frame_numbers(
            total_frames,
            start_frame=start_frame,
            window_frames=window_frames,
            max_items=VIDEO_CLEANUP_FILMSTRIP_ITEMS,
        )

    def refresh_cleanup_filmstrip(self) -> None:
        if not hasattr(self, "cleanup_filmstrip_list"):
            return
        media_path = self.cleanup_detected_media_path
        total_frames = int(getattr(self, "cleanup_video_total_frames", 0) or 0)
        if not media_path or total_frames <= 0:
            self.cleanup_filmstrip_list.clear()
            self.cleanup_filmstrip_status.setText("Run detection to load frame review.")
            return
        ffmpeg = find_ffmpeg_exe()
        if not ffmpeg:
            self.cleanup_filmstrip_status.setText("ffmpeg unavailable for frame review.")
            return
        frame_numbers = self.cleanup_filmstrip_frame_numbers()
        if not frame_numbers:
            self.cleanup_filmstrip_status.setText("No frames available for review.")
            return
        self.cleanup_filmstrip_generation += 1
        generation = self.cleanup_filmstrip_generation
        icon_size = self.cleanup_filmstrip_icon_size()
        self.cleanup_filmstrip_list.setIconSize(icon_size)
        self.cleanup_filmstrip_list.clear()
        self.cleanup_filmstrip_status.setText("Loading frame review...")
        self.update_video_cleanup_button_state()
        threading.Thread(
            target=self.video_cleanup_filmstrip_worker,
            args=(generation, str(ffmpeg), media_path, frame_numbers, icon_size.width()),
            daemon=True,
        ).start()

    def video_cleanup_filmstrip_worker(
        self,
        generation: int,
        ffmpeg: str,
        media_path: str,
        frame_numbers: list[int],
        thumb_width: int,
    ) -> None:
        thumbnails: list[tuple[int, bytes]] = []
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            with tempfile.TemporaryDirectory(prefix="voicebridge-filmstrip-") as temp_dir:
                for frame_number in frame_numbers:
                    if self.cleanup_cancel_requested or generation != self.cleanup_filmstrip_generation:
                        return
                    output_path = Path(temp_dir) / f"frame_{frame_number}.jpg"
                    command = video_frame_preview_command(
                        ffmpeg,
                        media_path,
                        frame_number,
                        str(output_path),
                        thumb_width,
                    )
                    result = subprocess.run(
                        command,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        creationflags=creationflags,
                        timeout=45,
                        check=False,
                    )
                    if result.returncode == 0 and output_path.is_file():
                        thumbnails.append((frame_number, output_path.read_bytes()))
        except (OSError, RuntimeError, TimeoutError):
            thumbnails = []
        self.post(self.cleanup_filmstrip_loaded, generation, thumbnails)

    def cleanup_filmstrip_loaded(self, generation: int, thumbnails: list[tuple[int, bytes]]) -> None:
        if generation != self.cleanup_filmstrip_generation:
            return
        self.cleanup_filmstrip_list.clear()
        if not thumbnails:
            self.cleanup_filmstrip_status.setText("Frame review unavailable.")
            self.update_video_cleanup_button_state()
            return
        for frame_number, image_data in thumbnails:
            pixmap = QPixmap()
            pixmap.loadFromData(image_data)
            item = QListWidgetItem(QIcon(pixmap), self.cleanup_filmstrip_item_text(frame_number))
            item.setData(Qt.ItemDataRole.UserRole, frame_number)
            item.setToolTip(self.cleanup_filmstrip_item_tooltip(frame_number))
            self.apply_cleanup_filmstrip_item_style(item, frame_number)
            self.cleanup_filmstrip_list.addItem(item)
        self.update_cleanup_filmstrip_status()
        self.update_video_cleanup_button_state()

    def cleanup_filmstrip_item_text(self, frame_number: int) -> str:
        time_seconds = self.cleanup_frame_time_seconds(frame_number)
        marker = "Marked" if frame_number in self.cleanup_marked_frame_numbers else ""
        marker_suffix = f"\n{marker}" if marker else ""
        return f"#{frame_number}\n{time_seconds:.3f}s{marker_suffix}"

    def cleanup_filmstrip_item_tooltip(self, frame_number: int) -> str:
        status = "Marked for cleanup" if frame_number in self.cleanup_marked_frame_numbers else "Not marked"
        if frame_number in self.cleanup_repairable_frame_map:
            status += "; auto-detected isolated black frame"
        elif frame_number in self.cleanup_detected_frame_map:
            status += "; auto-detected black frame"
        return f"Frame {frame_number} at {self.cleanup_frame_time_seconds(frame_number):.3f}s\n{status}"

    def apply_cleanup_filmstrip_item_style(self, item: QListWidgetItem, frame_number: int) -> None:
        if frame_number in self.cleanup_marked_frame_numbers:
            item.setBackground(QBrush(QColor("#fee2e2")))
            item.setForeground(QBrush(QColor("#7f1d1d")))
        elif frame_number in self.cleanup_detected_frame_map:
            item.setBackground(QBrush(QColor("#fff7e6")))
            item.setForeground(QBrush(QColor("#7a4b00")))
        else:
            item.setBackground(QBrush(QColor("#ffffff")))
            item.setForeground(QBrush(QColor("#111827")))

    def update_cleanup_filmstrip_item_styles(self) -> None:
        if not hasattr(self, "cleanup_filmstrip_list"):
            return
        for index in range(self.cleanup_filmstrip_list.count()):
            item = self.cleanup_filmstrip_list.item(index)
            frame_number = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(frame_number, int):
                item.setText(self.cleanup_filmstrip_item_text(frame_number))
                item.setToolTip(self.cleanup_filmstrip_item_tooltip(frame_number))
                self.apply_cleanup_filmstrip_item_style(item, frame_number)
        self.update_cleanup_filmstrip_status()

    def update_cleanup_filmstrip_status(self) -> None:
        if not hasattr(self, "cleanup_filmstrip_status"):
            return
        total_frames = int(getattr(self, "cleanup_video_total_frames", 0) or 0)
        marked_count = len(self.selected_cleanup_frame_numbers())
        selected = self.cleanup_filmstrip_selected_frames()
        selected_text = f" | selected #{selected[0]}" if len(selected) == 1 else ""
        self.cleanup_filmstrip_status.setText(
            f"Frame review ready: {total_frames} frame(s), {marked_count} marked{selected_text}."
        )

    def cleanup_filmstrip_selection_changed(self) -> None:
        self.update_cleanup_filmstrip_status()
        self.update_video_cleanup_button_state()

    def cleanup_filmstrip_scroll_changed(self, _value: int) -> None:
        self.refresh_cleanup_filmstrip()

    def set_cleanup_filmstrip_zoom(self, zoom_level: int) -> None:
        zoom_level = max(0, min(int(zoom_level), len(VIDEO_CLEANUP_FILMSTRIP_ZOOM_WINDOWS) - 1))
        if zoom_level == self.cleanup_filmstrip_zoom_level:
            return
        center_frame = self.cleanup_current_filmstrip_center_frame()
        self.cleanup_filmstrip_zoom_level = zoom_level
        self.configure_cleanup_filmstrip_scroll()
        self.center_cleanup_filmstrip_on_frame(center_frame, refresh=False)
        self.refresh_cleanup_filmstrip()

    def cleanup_current_filmstrip_center_frame(self) -> int:
        selected = self.cleanup_filmstrip_selected_frames()
        if selected:
            return selected[0]
        total_frames = int(getattr(self, "cleanup_video_total_frames", 0) or 0)
        window_frames = self.cleanup_filmstrip_window_frames() or total_frames
        start_frame = self.cleanup_filmstrip_scroll.value() if hasattr(self, "cleanup_filmstrip_scroll") else 0
        return min(max(0, total_frames - 1), start_frame + max(0, window_frames // 2))

    def center_cleanup_filmstrip_on_frame(self, frame_number: int, *, refresh: bool = True) -> None:
        if not hasattr(self, "cleanup_filmstrip_scroll"):
            return
        total_frames = int(getattr(self, "cleanup_video_total_frames", 0) or 0)
        if total_frames <= 0:
            return
        window_frames = self.cleanup_filmstrip_window_frames() or total_frames
        start_frame = max(0, min(int(frame_number) - (window_frames // 2), max(0, total_frames - window_frames)))
        self.cleanup_filmstrip_scroll.blockSignals(True)
        try:
            self.cleanup_filmstrip_scroll.setValue(start_frame)
        finally:
            self.cleanup_filmstrip_scroll.blockSignals(False)
        if refresh:
            self.refresh_cleanup_filmstrip()

    def mark_selected_cleanup_filmstrip_frames(self) -> None:
        selected = [frame for frame in self.cleanup_filmstrip_selected_frames() if frame > 0]
        if not selected:
            self.cleanup_status.setText("Select one or more frames in the frame review first.")
            return
        self.cleanup_marked_frame_numbers.update(selected)
        self.update_cleanup_filmstrip_item_styles()
        self.update_video_cleanup_button_state()

    def unmark_selected_cleanup_filmstrip_frames(self) -> None:
        selected = self.cleanup_filmstrip_selected_frames()
        if not selected:
            self.cleanup_status.setText("Select one or more frames in the frame review first.")
            return
        for frame_number in selected:
            self.cleanup_marked_frame_numbers.discard(frame_number)
        self.update_cleanup_filmstrip_item_styles()
        self.update_video_cleanup_button_state()

    def clear_cleanup_marked_frames(self) -> None:
        self.cleanup_marked_frame_numbers.clear()
        self.update_cleanup_filmstrip_item_styles()
        self.update_video_cleanup_button_state()

    def cleanup_result_item_clicked(self, item: QListWidgetItem) -> None:
        frame_number = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(frame_number, int):
            if self.cleanup_filmstrip_zoom_level == 0:
                self.cleanup_filmstrip_zoom_level = 3
                self.configure_cleanup_filmstrip_scroll()
            self.center_cleanup_filmstrip_on_frame(frame_number)

    def add_cleanup_result_row(self, frame: BlackFrame, repairable: bool, reason: str) -> None:
        frame_number = frame["frame"]
        item = QListWidgetItem()
        item.setText(f"Frame {frame_number} | {frame['time']:.3f}s | {frame['pblack']}% black | {reason}")
        item.setData(Qt.ItemDataRole.UserRole, frame_number)
        if repairable:
            item.setBackground(QBrush(QColor("#fee2e2")))
        self.cleanup_results.addItem(item)

    def cleanup_detection_finished(
        self,
        media_path: str,
        source_video_info: dict,
        black_frames: list[BlackFrame],
        isolated_frames: list[int],
        longer_runs: list[list[BlackFrame]],
    ) -> None:
        self.cleanup_detected_frames = black_frames
        self.cleanup_detected_media_path = media_path
        self.cleanup_detected_frame_map = {frame["frame"]: frame for frame in black_frames}
        self.cleanup_repairable_frame_map = {
            frame["frame"]: frame for frame in black_frames if frame["frame"] in set(isolated_frames)
        }
        self.cleanup_marked_frame_numbers = set(self.cleanup_repairable_frame_map)
        self.cleanup_video_fps = float(source_video_info.get("fps") or 0.0)
        self.cleanup_video_duration_seconds = float(source_video_info.get("duration_seconds") or 0.0)
        self.cleanup_video_total_frames = 0
        if self.cleanup_video_fps > 0 and self.cleanup_video_duration_seconds > 0:
            self.cleanup_video_total_frames = max(
                1,
                round(self.cleanup_video_fps * self.cleanup_video_duration_seconds),
            )
        self.cleanup_results.clear()
        self.configure_cleanup_filmstrip_scroll()
        self.refresh_cleanup_filmstrip()
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
            reason = "Auto-marked" if repairable else reason_by_frame.get(
                frame["frame"],
                "Skipped: not an isolated one-frame glitch",
            )
            self.add_cleanup_result_row(frame, repairable, reason)
        if len(black_frames) > 120:
            self.cleanup_results.addItem(f"...and {len(black_frames) - 120} more candidates in the log.")
        self.update_video_cleanup_button_state()

    def video_cleanup_detect_succeeded(self, black_frames, isolated_frames, longer_runs):
        if black_frames:
            self.cleanup_status.setText(
                f"Detected {len(black_frames)} black-frame candidate(s); {len(isolated_frames)} auto-marked."
            )
        else:
            self.cleanup_status.setText("No black-frame candidates found.")
        if longer_runs:
            self.append_cleanup_log(
                f"Longer black runs were detected and left untouched: {len(longer_runs)}. "
                "These may be fades or intentional black sections."
            )

    def video_cleanup_no_repair_needed(self):
        self.cleanup_status.setText("No marked frames to clean.")
        self.append_cleanup_log("No frames were marked. No output video was created.")

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
        self.update_audio_cleanup_button_state()

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
        busy_elsewhere = (
            self.is_converting
            or self.is_stt_running
            or self.is_video_running
            or self.is_audio_cleanup_running
        )
        current_media = self.cleanup_media_picker.text()
        detection_ready = bool(
            self.cleanup_detected_media_path
            and self.cleanup_detected_media_path == current_media
            and self.cleanup_video_total_frames
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
        for widget in (
            self.cleanup_filmstrip_list,
            self.cleanup_filmstrip_scroll,
            self.cleanup_mark_frame_button,
            self.cleanup_unmark_frame_button,
            self.cleanup_clear_marks_button,
            self.cleanup_filmstrip_fit_button,
            self.cleanup_filmstrip_zoom_in_button,
            self.cleanup_filmstrip_zoom_out_button,
        ):
            widget.setEnabled(detection_ready and not self.is_cleanup_running)
        self.cleanup_filmstrip_zoom_out_button.setEnabled(
            detection_ready and not self.is_cleanup_running and self.cleanup_filmstrip_zoom_level > 0
        )
        self.cleanup_filmstrip_zoom_in_button.setEnabled(
            detection_ready
            and not self.is_cleanup_running
            and self.cleanup_filmstrip_zoom_level < len(VIDEO_CLEANUP_FILMSTRIP_ZOOM_WINDOWS) - 1
        )
        self.cleanup_mark_frame_button.setEnabled(
            detection_ready and bool(self.cleanup_filmstrip_selected_frames()) and not self.is_cleanup_running
        )
        self.cleanup_unmark_frame_button.setEnabled(
            detection_ready and bool(self.cleanup_filmstrip_selected_frames()) and not self.is_cleanup_running
        )
        self.cleanup_clear_marks_button.setEnabled(
            detection_ready and bool(self.cleanup_marked_frame_numbers) and not self.is_cleanup_running
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
            "Video Cleanup",
            "Detect black-frame glitches, review frames manually and clean marked frames before export or subtitling.",
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
            "Detection auto-marks isolated black-frame glitches. "
            "Use frame review to mark or unmark any frame before cleanup."
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

        filmstrip_card = Card("Frame review")
        filmstrip_toolbar = QHBoxLayout()
        filmstrip_toolbar.setContentsMargins(0, 0, 0, 0)
        self.cleanup_filmstrip_status = QLabel("Run detection to load frame review.")
        self.cleanup_filmstrip_status.setObjectName("Muted")
        self.cleanup_filmstrip_status.setWordWrap(True)
        self.cleanup_filmstrip_fit_button = QPushButton("Fit")
        self.cleanup_filmstrip_zoom_out_button = QPushButton("Zoom -")
        self.cleanup_filmstrip_zoom_in_button = QPushButton("Zoom +")
        self.cleanup_mark_frame_button = QPushButton("Mark selected")
        self.cleanup_unmark_frame_button = QPushButton("Unmark selected")
        self.cleanup_clear_marks_button = QPushButton("Clear marks")
        self.cleanup_filmstrip_fit_button.clicked.connect(lambda: self.set_cleanup_filmstrip_zoom(0))
        self.cleanup_filmstrip_zoom_out_button.clicked.connect(
            lambda: self.set_cleanup_filmstrip_zoom(self.cleanup_filmstrip_zoom_level - 1)
        )
        self.cleanup_filmstrip_zoom_in_button.clicked.connect(
            lambda: self.set_cleanup_filmstrip_zoom(self.cleanup_filmstrip_zoom_level + 1)
        )
        self.cleanup_mark_frame_button.clicked.connect(self.mark_selected_cleanup_filmstrip_frames)
        self.cleanup_unmark_frame_button.clicked.connect(self.unmark_selected_cleanup_filmstrip_frames)
        self.cleanup_clear_marks_button.clicked.connect(self.clear_cleanup_marked_frames)
        filmstrip_toolbar.addWidget(self.cleanup_filmstrip_status, 1)
        filmstrip_toolbar.addWidget(self.cleanup_filmstrip_fit_button)
        filmstrip_toolbar.addWidget(self.cleanup_filmstrip_zoom_out_button)
        filmstrip_toolbar.addWidget(self.cleanup_filmstrip_zoom_in_button)
        filmstrip_toolbar.addWidget(self.cleanup_mark_frame_button)
        filmstrip_toolbar.addWidget(self.cleanup_unmark_frame_button)
        filmstrip_toolbar.addWidget(self.cleanup_clear_marks_button)
        self.cleanup_filmstrip_list = QListWidget()
        self.cleanup_filmstrip_list.setViewMode(QListView.ViewMode.IconMode)
        self.cleanup_filmstrip_list.setFlow(QListView.Flow.LeftToRight)
        self.cleanup_filmstrip_list.setWrapping(False)
        self.cleanup_filmstrip_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.cleanup_filmstrip_list.setMovement(QListView.Movement.Static)
        self.cleanup_filmstrip_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.cleanup_filmstrip_list.setIconSize(VIDEO_CLEANUP_FILMSTRIP_ICON_SIZES[0])
        self.cleanup_filmstrip_list.setSpacing(8)
        self.cleanup_filmstrip_list.setMinimumHeight(152)
        self.cleanup_filmstrip_list.itemSelectionChanged.connect(self.cleanup_filmstrip_selection_changed)
        self.cleanup_filmstrip_scroll = QSlider(Qt.Orientation.Horizontal)
        self.cleanup_filmstrip_scroll.setEnabled(False)
        self.cleanup_filmstrip_scroll.setTracking(False)
        self.cleanup_filmstrip_scroll.valueChanged.connect(self.cleanup_filmstrip_scroll_changed)
        filmstrip_card.content_layout.addLayout(filmstrip_toolbar)
        filmstrip_card.content_layout.addWidget(self.cleanup_filmstrip_list)
        filmstrip_card.content_layout.addWidget(self.cleanup_filmstrip_scroll)
        layout.addWidget(filmstrip_card)

        results_card = Card("Detected frames")
        self.cleanup_results = QListWidget()
        self.cleanup_results.setMinimumHeight(160)
        self.cleanup_results.itemClicked.connect(self.cleanup_result_item_clicked)
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

