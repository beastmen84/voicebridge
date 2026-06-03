import json
import os
import subprocess
import tempfile
import threading
from contextlib import suppress
from pathlib import Path

from PySide6.QtCore import QRect, QSize, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap
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
    QToolButton,
    QWidget,
)

from voicebridge.app_paths import ml_python_path, video_anomaly_worker_path
from voicebridge.constants import (
    BURN_QUALITY_AUTO,
    BURN_QUALITY_AUTO_LABEL,
    VIDEO_CLEANUP_FREEZE_LABEL,
    VIDEO_CLEANUP_METHOD_BY_LABEL,
    VIDEO_CLEANUP_METHOD_FREEZE,
    VIDEO_CLEANUP_METHOD_REMOVE,
    VIDEO_CLEANUP_QUALITY_BY_LABEL,
    VIDEO_CLEANUP_QUALITY_DESCRIPTIONS,
    VIDEO_CLEANUP_QUALITY_LABELS,
    VIDEO_CLEANUP_REMOVE_LABEL,
)
from voicebridge.ffmpeg_jobs import ffmpeg_progress_percent as ffmpeg_job_progress_percent
from voicebridge.ffmpeg_jobs import should_keep_ffmpeg_log_line
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
    video_filmstrip_preview_command,
)
from voicebridge.process_jobs import WorkerProcessOutput, run_worker_process_job
from voicebridge.ui.helpers import open_path
from voicebridge.ui.widgets import Card, FilePicker
from voicebridge.video_anomalies import CUT_BOUNDARY_ANOMALY, SINGLE_FRAME_INTERRUPTION, FrameAnomaly

VIDEO_OUTPUT_MIN_FREE_BYTES = 512 * 1024 * 1024
VIDEO_CLEANUP_FILMSTRIP_MAX_ITEMS = 30
VIDEO_CLEANUP_FILMSTRIP_CONTEXT_BEFORE = 1
VIDEO_CLEANUP_FILMSTRIP_BATCH_SIZE = 30
VIDEO_CLEANUP_FILMSTRIP_ICON_SIZE = QSize(384, 216)
VIDEO_CLEANUP_FILMSTRIP_UNSELECTED_INSET = 3
VIDEO_CLEANUP_FILMSTRIP_MIN_ICON_HEIGHT = 180
VIDEO_CLEANUP_FILMSTRIP_LABEL_HEIGHT = 24
VIDEO_CLEANUP_FILMSTRIP_ITEM_GAP = 4
VIDEO_CLEANUP_FILMSTRIP_TIMEOUT_SECONDS = 180
VIDEO_CLEANUP_FILMSTRIP_REFRESH_DEBOUNCE_MS = 180
VIDEO_ANOMALY_RESULT_PREFIX = "ANOMALY_RESULT_JSON: "
VIDEO_CLEANUP_BLACK_EMPTY_TEXT = "Load frame review, then run Detect black frames."
VIDEO_CLEANUP_SUSPICIOUS_EMPTY_TEXT = "Load frame review, then run Detect frame glitches."
VIDEO_CLEANUP_BLACK_READY_TEXT = "Run Detect black frames to list black-frame candidates."
VIDEO_CLEANUP_SUSPICIOUS_READY_TEXT = "Run Detect frame glitches to list non-black suspicious frames."
VIDEO_CLEANUP_ACTIONS = {
    VIDEO_CLEANUP_METHOD_FREEZE,
    VIDEO_CLEANUP_METHOD_REMOVE,
}


def normalize_video_cleanup_change_plan(changes: list[dict]) -> list[dict]:
    frame_actions: dict[int, str] = {}
    for change in changes:
        action = str(change.get("action") or "")
        if action not in VIDEO_CLEANUP_ACTIONS:
            continue
        for raw_frame in change.get("frames") or []:
            try:
                frame_number = int(raw_frame)
            except (TypeError, ValueError):
                continue
            if frame_number <= 0:
                continue
            existing_action = frame_actions.get(frame_number)
            if existing_action is None:
                frame_actions[frame_number] = action

    return [
        {"action": action, "frames": [frame_number]}
        for frame_number, action in sorted(frame_actions.items())
    ]


def conflicting_video_cleanup_change_frames(changes: list[dict]) -> dict[int, set[str]]:
    frame_actions: dict[int, set[str]] = {}
    for change in changes:
        action = str(change.get("action") or "")
        if action not in VIDEO_CLEANUP_ACTIONS:
            continue
        for raw_frame in change.get("frames") or []:
            try:
                frame_number = int(raw_frame)
            except (TypeError, ValueError):
                continue
            if frame_number <= 0:
                continue
            frame_actions.setdefault(frame_number, set()).add(action)
    return {
        frame_number: actions
        for frame_number, actions in frame_actions.items()
        if len(actions) > 1
    }


def format_video_cleanup_conflicts(conflicts: dict[int, set[str]]) -> str:
    frames = ", ".join(f"#{frame_number}" for frame_number in sorted(conflicts)[:8])
    suffix = f", +{len(conflicts) - 8} more" if len(conflicts) > 8 else ""
    return f"Frame(s) {frames}{suffix} have more than one queued cleanup action."


class ClearableFilmstripListWidget(QListWidget):
    def mousePressEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if item is None:
            self.clearSelection()
        elif (
            event.button() == Qt.MouseButton.LeftButton
            and item.isSelected()
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
        ):
            self.clearSelection()
            event.accept()
            return
        super().mousePressEvent(event)

    def wheelEvent(self, event):
        event.accept()


# noinspection PyAttributeOutsideInit,PyUnresolvedReferences,PyTypeChecker
class VideoCleanupWorkflowMixin:
    def cleanup_media_changed(self):
        self.update_cleanup_output(force=False)
        media_path = self.cleanup_media_picker.text()
        if self.cleanup_detected_media_path and media_path != self.cleanup_detected_media_path:
            self.cleanup_last_output_path = ""
            self.clear_cleanup_detection_results("Ready.")
            self.reset_video_cleanup_changes()
        if media_path and Path(media_path).is_file() and media_path != self.cleanup_detected_media_path:
            self.start_video_cleanup_review_load(media_path)
        self.update_video_cleanup_button_state()
        self.save_user_settings()

    def clear_cleanup_detection_results(self, status_text=None):
        self.cleanup_detected_frames = []
        self.cleanup_detected_media_path = ""
        self.cleanup_repairable_frame_map = {}
        self.cleanup_detected_frame_map = {}
        self.cleanup_suspicious_frames = []
        self.cleanup_suspicious_frame_map = {}
        self.cleanup_marked_frame_numbers = set()
        self.cleanup_video_fps = 0.0
        self.cleanup_video_duration_seconds = 0.0
        self.cleanup_video_total_frames = 0
        self.cleanup_filmstrip_generation = getattr(self, "cleanup_filmstrip_generation", 0) + 1
        self.clear_cleanup_filmstrip_cache()
        if hasattr(self, "cleanup_results"):
            self.cleanup_results.clear()
        if hasattr(self, "cleanup_suspicious_results"):
            self.cleanup_suspicious_results.clear()
        if hasattr(self, "cleanup_filmstrip_list"):
            self.cleanup_filmstrip_list.clear()
        if hasattr(self, "cleanup_filmstrip_status"):
            self.cleanup_filmstrip_status.setText("Select a video file to load frame review.")
        if hasattr(self, "cleanup_filmstrip_scroll"):
            self.cleanup_filmstrip_scroll.setEnabled(False)
            self.cleanup_filmstrip_scroll.setValue(0)
        self.update_cleanup_filmstrip_timeline_label()
        self.reset_cleanup_black_results_empty()
        self.reset_cleanup_suspicious_results_empty()
        if status_text is not None and hasattr(self, "cleanup_status"):
            self.cleanup_status.setText(status_text)

    def reset_cleanup_black_results_empty(self) -> None:
        if not hasattr(self, "cleanup_results"):
            return
        self.cleanup_results.clear()
        self.cleanup_results.addItem(VIDEO_CLEANUP_BLACK_EMPTY_TEXT)

    def reset_cleanup_suspicious_results_empty(self) -> None:
        if not hasattr(self, "cleanup_suspicious_results"):
            return
        self.cleanup_suspicious_results.clear()
        self.cleanup_suspicious_results.addItem(VIDEO_CLEANUP_SUSPICIOUS_EMPTY_TEXT)

    def reset_cleanup_results_ready(self) -> None:
        if hasattr(self, "cleanup_results"):
            self.cleanup_results.clear()
            self.cleanup_results.addItem(VIDEO_CLEANUP_BLACK_READY_TEXT)
        if hasattr(self, "cleanup_suspicious_results"):
            self.cleanup_suspicious_results.clear()
            self.cleanup_suspicious_results.addItem(VIDEO_CLEANUP_SUSPICIOUS_READY_TEXT)

    def clear_cleanup_detected_marks(self):
        self.cleanup_detected_frames = []
        self.cleanup_repairable_frame_map = {}
        self.cleanup_detected_frame_map = {}
        self.cleanup_marked_frame_numbers = set()
        if hasattr(self, "cleanup_results"):
            self.cleanup_results.clear()
        self.update_cleanup_filmstrip_item_styles()
        self.update_video_cleanup_button_state()

    def clear_cleanup_suspicious_results(self):
        self.cleanup_suspicious_frames = []
        self.cleanup_suspicious_frame_map = {}
        self.reset_cleanup_suspicious_results_empty()
        self.update_cleanup_filmstrip_item_styles()
        self.update_video_cleanup_button_state()

    def update_cleanup_quality_description(self, text):
        self.cleanup_quality_description.setText(VIDEO_CLEANUP_QUALITY_DESCRIPTIONS.get(text, ""))
        self.save_user_settings()

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
        path, selected_filter = QFileDialog.getSaveFileName(self, "Save cleaned video as", suggested, filter_text)
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

    def start_video_cleanup_review_load(self, media_path: str | None = None) -> None:
        media_path = media_path or self.cleanup_media_picker.text()
        if not media_path:
            return
        media = Path(media_path)
        if not media.is_file() or media.suffix.lower() not in STT_VIDEO_SUFFIXES:
            self.cleanup_filmstrip_status.setText("Select a readable video file to load frame review.")
            return
        ffmpeg = find_ffmpeg_exe()
        if not ffmpeg:
            self.cleanup_filmstrip_status.setText("ffmpeg unavailable for frame review.")
            return
        self.cleanup_filmstrip_generation += 1
        generation = self.cleanup_filmstrip_generation
        self.cleanup_detected_media_path = media_path
        self.cleanup_video_fps = 0.0
        self.cleanup_video_duration_seconds = 0.0
        self.cleanup_video_total_frames = 0
        self.cleanup_detected_frame_map = {}
        self.cleanup_repairable_frame_map = {}
        self.cleanup_suspicious_frames = []
        self.cleanup_suspicious_frame_map = {}
        self.cleanup_marked_frame_numbers = set()
        self.clear_cleanup_filmstrip_cache()
        self.reset_cleanup_black_results_empty()
        self.reset_cleanup_suspicious_results_empty()
        if hasattr(self, "cleanup_filmstrip_list"):
            self.cleanup_filmstrip_list.clear()
        self.cleanup_filmstrip_status.setText("Loading frame review...")
        self.update_video_cleanup_button_state()
        threading.Thread(
            target=self.video_cleanup_review_worker,
            args=(generation, str(ffmpeg), media_path),
            daemon=True,
        ).start()

    def video_cleanup_review_worker(self, generation: int, ffmpeg: str, media_path: str) -> None:
        try:
            source_video_info = probe_video_info(ffmpeg, media_path)
            if not source_video_info.get("width") or not source_video_info.get("height"):
                raise ValueError("The selected video has no readable video stream.")
            self.post(self.cleanup_frame_review_loaded, generation, media_path, source_video_info)
        except (OSError, RuntimeError, ValueError) as exc:
            self.post(self.cleanup_frame_review_failed, generation, media_path, str(exc))

    def cleanup_frame_review_loaded(self, generation: int, media_path: str, source_video_info: dict) -> None:
        if generation != self.cleanup_filmstrip_generation or media_path != self.cleanup_media_picker.text():
            return
        self.cleanup_detected_media_path = media_path
        self.cleanup_video_fps = float(source_video_info.get("fps") or 0.0)
        self.cleanup_video_duration_seconds = float(source_video_info.get("duration_seconds") or 0.0)
        self.cleanup_video_total_frames = self.cleanup_total_frames_from_video_info(source_video_info)
        self.reset_cleanup_results_ready()
        self.configure_cleanup_filmstrip_scroll()
        self.refresh_cleanup_filmstrip()
        self.cleanup_status.setText("Frame review ready.")
        self.update_video_cleanup_button_state()

    def cleanup_frame_review_failed(self, generation: int, media_path: str, message: str) -> None:
        if generation != self.cleanup_filmstrip_generation or media_path != self.cleanup_media_picker.text():
            return
        self.cleanup_detected_media_path = ""
        self.clear_cleanup_filmstrip_cache()
        self.cleanup_filmstrip_status.setText("Frame review unavailable.")
        self.update_cleanup_filmstrip_timeline_label()
        self.cleanup_status.setText("Error.")
        self.append_cleanup_log(f"ERROR: {message}")
        self.update_video_cleanup_button_state()

    def selected_cleanup_frame_numbers(self) -> list[int]:
        queued_frames = self.cleanup_queued_frame_numbers()
        return sorted(
            int(frame_number)
            for frame_number in getattr(self, "cleanup_marked_frame_numbers", set())
            if int(frame_number) > 0 and int(frame_number) not in queued_frames
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

    @staticmethod
    def cleanup_total_frames_from_video_info(source_video_info: dict) -> int:
        frame_count = source_video_info.get("frame_count")
        with suppress(TypeError, ValueError):
            if frame_count is not None and int(frame_count) > 0:
                return int(frame_count)

        fps = float(source_video_info.get("fps") or 0.0)
        duration_seconds = float(source_video_info.get("duration_seconds") or 0.0)
        if fps > 0 and duration_seconds > 0:
            return max(1, round(fps * duration_seconds))
        return 0

    @staticmethod
    def cleanup_action_label_for_key(action: str) -> str:
        for label, key in VIDEO_CLEANUP_METHOD_BY_LABEL.items():
            if key == action:
                return label
        return str(action)

    @staticmethod
    def format_cleanup_frame_ranges(frames: list[int]) -> str:
        unique_frames = sorted(set(int(frame) for frame in frames if int(frame) > 0))
        if not unique_frames:
            return "no frames"
        ranges = []
        start = previous = unique_frames[0]
        for frame_number in unique_frames[1:]:
            if frame_number == previous + 1:
                previous = frame_number
                continue
            ranges.append(f"#{start}" if start == previous else f"#{start}-#{previous}")
            start = previous = frame_number
        ranges.append(f"#{start}" if start == previous else f"#{start}-#{previous}")
        return ", ".join(ranges[:6]) + (f", +{len(ranges) - 6} range(s)" if len(ranges) > 6 else "")

    def cleanup_change_label(self, index: int, change: dict) -> str:
        frames = list(change.get("frames") or [])
        return (
            f"C. {index} - {self.cleanup_action_label_for_key(change.get('action', ''))} | "
            f"{self.format_cleanup_frame_ranges(frames)}"
        )

    def cleanup_change_row_widget(self, index: int, change: dict) -> QWidget:
        row = QWidget()
        row.setObjectName("InlinePanel")
        row_index = index - 1

        def select_change(_event):
            self.cleanup_changes_list.setCurrentRow(row_index)

        def jump_change(_event):
            frames = list(change.get("frames") or [])
            if frames:
                self.center_cleanup_filmstrip_on_frame(frames[0])

        row.mousePressEvent = select_change
        row.mouseDoubleClickEvent = jump_change
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)
        label = QLabel(self.cleanup_change_label(index, change))
        label.setObjectName("Muted")
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        remove_button = QToolButton()
        remove_button.setObjectName("InlineDangerButton")
        remove_button.setText("X")
        remove_button.setToolTip("Remove this change")
        remove_button.setAutoRaise(True)
        remove_button.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_button.clicked.connect(lambda _checked=False: self.remove_video_cleanup_change_at_index(row_index))
        row_layout.addWidget(label, 1)
        row_layout.addWidget(remove_button)
        return row

    def cleanup_pending_marked_row_widget(self, frame_number: int, row_index: int) -> QWidget:
        row = QWidget()
        row.setObjectName("InlinePanel")

        def select_marked(_event):
            self.cleanup_changes_list.setCurrentRow(row_index)

        def jump_marked(_event):
            self.center_cleanup_filmstrip_on_frame(frame_number)

        row.mousePressEvent = select_marked
        row.mouseDoubleClickEvent = jump_marked
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)
        label = QLabel(
            f"Marked frame pending action | #{frame_number} / "
            f"{self.cleanup_frame_time_seconds(frame_number):.3f}s"
        )
        label.setObjectName("Muted")
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        row_layout.addWidget(label, 1)
        return row

    def reset_video_cleanup_changes(self):
        self.cleanup_changes = []
        if hasattr(self, "cleanup_changes_list"):
            self.refresh_video_cleanup_changes_list()

    def refresh_video_cleanup_changes_list(self):
        if not hasattr(self, "cleanup_changes_list"):
            return
        conflicts = conflicting_video_cleanup_change_frames(self.cleanup_changes)
        if not conflicts:
            self.cleanup_changes = normalize_video_cleanup_change_plan(self.cleanup_changes)
            self.cleanup_marked_frame_numbers.difference_update(self.cleanup_queued_frame_numbers())
        self.cleanup_changes_list.blockSignals(True)
        try:
            self.cleanup_changes_list.clear()
            pending_frames = self.selected_cleanup_frame_numbers()
            if not self.cleanup_changes and not pending_frames:
                self.cleanup_changes_list.addItem("No applied changes.")
            else:
                for index, change in enumerate(self.cleanup_changes, start=1):
                    item = QListWidgetItem()
                    item.setData(Qt.ItemDataRole.UserRole, index - 1)
                    row = self.cleanup_change_row_widget(index, change)
                    item.setSizeHint(row.sizeHint())
                    self.cleanup_changes_list.addItem(item)
                    self.cleanup_changes_list.setItemWidget(item, row)
                for pending_index, frame_number in enumerate(pending_frames):
                    item = QListWidgetItem()
                    item.setData(Qt.ItemDataRole.UserRole, ("pending_marked", frame_number))
                    row_index = len(self.cleanup_changes) + pending_index
                    row = self.cleanup_pending_marked_row_widget(frame_number, row_index)
                    item.setSizeHint(row.sizeHint())
                    self.cleanup_changes_list.addItem(item)
                    self.cleanup_changes_list.setItemWidget(item, row)
        finally:
            self.cleanup_changes_list.blockSignals(False)
        pending_count = len(self.selected_cleanup_frame_numbers())
        if conflicts:
            self.cleanup_changes_status.setText(
                f"{format_video_cleanup_conflicts(conflicts)} Remove the duplicate queued change before cleaning."
            )
        else:
            self.cleanup_changes_status.setText(
                f"{len(self.cleanup_changes)} change(s) queued; {pending_count} marked frame(s) pending action."
                if self.cleanup_changes and pending_count
                else f"{len(self.cleanup_changes)} change(s) queued."
                if self.cleanup_changes
                else f"{pending_count} marked frame(s) pending Freeze or Remove."
                if pending_count
                else "Mark frames, then apply Freeze or Remove before cleaning video."
            )
        self.update_cleanup_filmstrip_item_styles()
        self.update_video_cleanup_button_state()

    def cleanup_change_selection_changed(self):
        item = self.cleanup_changes_list.currentItem()
        if item is None:
            self.update_video_cleanup_button_state()
            return
        index = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(index, int) or not (0 <= index < len(self.cleanup_changes)):
            self.update_video_cleanup_button_state()
            return
        self.update_video_cleanup_button_state()

    def cleanup_change_item_double_clicked(self, item: QListWidgetItem) -> None:
        index = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(index, tuple) and len(index) == 2 and index[0] == "pending_marked":
            self.center_cleanup_filmstrip_on_frame(int(index[1]))
            return
        if not isinstance(index, int) or not (0 <= index < len(self.cleanup_changes)):
            return
        frames = list(self.cleanup_changes[index].get("frames") or [])
        if frames:
            self.center_cleanup_filmstrip_on_frame(frames[0])

    def cleanup_pending_action_frames(self) -> list[int]:
        marked_frames = set(self.selected_cleanup_frame_numbers())
        if not marked_frames:
            return []

        if hasattr(self, "cleanup_changes_list"):
            item = self.cleanup_changes_list.currentItem()
            if item is not None:
                value = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(value, tuple) and len(value) == 2 and value[0] == "pending_marked":
                    frame_number = int(value[1])
                    if frame_number in marked_frames:
                        return [frame_number]

        selected_visible_marked = [
            frame_number
            for frame_number in self.cleanup_filmstrip_selected_frames()
            if frame_number in marked_frames
        ]
        if selected_visible_marked:
            return sorted(set(selected_visible_marked))

        return []

    def apply_video_cleanup_change(self, action: str):
        frames = self.cleanup_pending_action_frames()
        if not frames:
            self.show_error("Video Cleanup", "Select a pending marked row or a marked frame before applying cleanup.")
            return
        queued_frames = self.cleanup_queued_frame_numbers()
        duplicate_frames = sorted(set(frames) & queued_frames)
        if duplicate_frames:
            self.show_error(
                "Video Cleanup",
                f"{self.format_cleanup_frame_ranges(duplicate_frames)} already has a queued cleanup action. "
                "Remove that queued change before choosing another action.",
            )
            return
        self.cleanup_changes.extend({"action": action, "frames": [frame_number]} for frame_number in frames)
        self.cleanup_changes = normalize_video_cleanup_change_plan(self.cleanup_changes)
        for frame_number in frames:
            self.cleanup_marked_frame_numbers.discard(frame_number)
        if hasattr(self, "cleanup_filmstrip_list"):
            self.cleanup_filmstrip_list.clearSelection()
        self.refresh_video_cleanup_changes_list()
        target_frame = min(frames)
        target_row = next(
            (
                index
                for index, change in enumerate(self.cleanup_changes)
                if change["action"] == action and change["frames"] == [target_frame]
            ),
            len(self.cleanup_changes) - 1,
        )
        self.cleanup_changes_list.setCurrentRow(target_row)
        if len(frames) == 1:
            self.cleanup_status.setText(f"Queued video cleanup change {target_row + 1}.")
        else:
            self.cleanup_status.setText(f"Queued {len(frames)} video cleanup changes.")

    def remove_selected_video_cleanup_change(self):
        item = self.cleanup_changes_list.currentItem()
        if item is None:
            return
        self.remove_video_cleanup_change_at_index(item.data(Qt.ItemDataRole.UserRole))

    def remove_video_cleanup_change_at_index(self, index):
        if not isinstance(index, int) or not (0 <= index < len(self.cleanup_changes)):
            return
        del self.cleanup_changes[index]
        self.refresh_video_cleanup_changes_list()
        if self.cleanup_changes:
            self.cleanup_changes_list.setCurrentRow(min(index, len(self.cleanup_changes) - 1))
        self.cleanup_status.setText("Removed queued video cleanup change.")

    def collect_video_cleanup_repair_options(self):
        media_path = self.collect_video_cleanup_media()
        if self.cleanup_detected_media_path != media_path:
            raise ValueError("Load frame review for this video before cleaning frames.")
        if not self.cleanup_video_total_frames:
            raise ValueError("Frame review is not ready yet.")
        if not self.cleanup_changes:
            raise ValueError("Apply at least one video cleanup change before cleaning video.")

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
        conflicts = conflicting_video_cleanup_change_frames(self.cleanup_changes)
        if conflicts:
            raise ValueError(
                f"{format_video_cleanup_conflicts(conflicts)} Remove the duplicate queued change before cleaning."
            )
        self.cleanup_changes = normalize_video_cleanup_change_plan(self.cleanup_changes)
        changes = list(self.cleanup_changes)
        if not changes:
            raise ValueError("Apply at least one video cleanup change before cleaning video.")
        return media_path, output_path, cleanup_quality, changes

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
        self.stop_cleanup_filmstrip_background_work()
        self.clear_cleanup_detected_marks()
        self.reset_cleanup_log()
        self.cleanup_results.clear()
        self.cleanup_results.addItem("Detecting black-frame candidates...")
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

    def start_video_anomaly_detection_from_page(self):
        try:
            media_path = self.collect_video_cleanup_media()
        except ValueError as exc:
            self.cleanup_status.setText("Error.")
            self.show_error("Video Cleanup", str(exc))
            return
        if self.cleanup_detected_media_path != media_path or not self.cleanup_video_total_frames:
            self.cleanup_status.setText("Frame review not ready.")
            self.show_error("Video Cleanup", "Load frame review for this video before detecting frame glitches.")
            return

        python_path = ml_python_path()
        worker_path = video_anomaly_worker_path()
        if not python_path.is_file():
            self.cleanup_status.setText("ML runtime missing.")
            self.show_error("Video Cleanup", f"Could not find ML Python runtime:\n{python_path}")
            return
        if not worker_path.is_file():
            self.cleanup_status.setText("Anomaly worker missing.")
            self.show_error("Video Cleanup", f"Could not find:\n{worker_path}")
            return

        self.cleanup_cancel_requested = False
        self.cleanup_process = None
        self.stop_cleanup_filmstrip_background_work()
        self.clear_cleanup_suspicious_results()
        self.cleanup_suspicious_results.clear()
        self.cleanup_suspicious_results.addItem("Detecting suspicious frame glitches...")
        self.is_cleanup_running = True
        self.update_cleanup_progress_percent(0)
        self.cleanup_status.setText("Detecting suspicious frame glitches...")
        self.append_cleanup_log("")
        self.append_cleanup_log(f"Detecting suspicious frame glitches: {media_path}")
        self.update_video_cleanup_button_state()
        self.update_tts_button_state()
        self.update_stt_button_state()
        self.update_video_subtitle_button_state()
        self.update_audio_cleanup_button_state()
        threading.Thread(
            target=self.video_anomaly_detection_worker,
            args=(str(python_path), str(worker_path), media_path),
            daemon=True,
        ).start()

    def start_video_cleanup_repair_from_page(self):
        try:
            media_path, output_path, cleanup_quality, changes = self.collect_video_cleanup_repair_options()
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
        total_frames = sum(len(change["frames"]) for change in changes)
        self.cleanup_status.setText(f"Cleaning {len(changes)} queued change(s)...")
        self.append_cleanup_log("")
        self.append_cleanup_log(f"Queued video cleanup changes: {len(changes)}")
        for index, change in enumerate(changes, start=1):
            self.append_cleanup_log(
                f"C. {index}: {self.cleanup_action_label_for_key(change['action'])} | "
                f"{self.format_cleanup_frame_ranges(change['frames'])}"
            )
        self.append_cleanup_log(f"Total affected frame references: {total_frames}")
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
                changes,
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

    def video_anomaly_detection_worker(self, python_path: str, worker_path: str, media_path: str) -> None:
        result_payload: dict | None = None

        def handle_worker_output(output: WorkerProcessOutput) -> None:
            nonlocal result_payload
            if output.is_status and output.status:
                self.post(self.cleanup_status.setText, output.status)
                self.post(self.append_cleanup_log, output.status)
                return
            if output.is_progress and output.progress_percent is not None:
                self.post(self.update_cleanup_progress_percent, output.progress_percent)
                return
            if output.line.startswith(VIDEO_ANOMALY_RESULT_PREFIX):
                result_payload = json.loads(output.line.removeprefix(VIDEO_ANOMALY_RESULT_PREFIX))
                return
            self.post(self.append_cleanup_log, output.line)

        try:
            command = [
                str(python_path),
                str(worker_path),
                "--input",
                media_path,
            ]
            result = run_worker_process_job(
                command,
                cwd=Path(worker_path).resolve().parent,
                on_output=handle_worker_output,
                on_process_start=lambda process: setattr(self, "cleanup_process", process),
                should_cancel=lambda: bool(self.cleanup_cancel_requested),
            )
            if result.cancelled:
                self.post(self.video_cleanup_job_cancelled)
                return
            if result.return_code != 0:
                message = (
                    "\n".join(result.recent_output[-8:])
                    or f"Frame anomaly worker exited with code {result.return_code}."
                )
                self.post(
                    self.video_cleanup_job_failed,
                    message,
                )
                return
            anomalies = list((result_payload or {}).get("anomalies") or [])
            self.post(self.cleanup_anomaly_detection_finished, media_path, anomalies)
            self.post(self.video_anomaly_detect_succeeded, anomalies)
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
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
        changes,
    ):
        try:
            self.post(self.append_cleanup_log, "Detecting source video details...")
            source_video_info = probe_video_info(ffmpeg, media_path)
            current_duration_seconds = float(source_video_info.get("duration_seconds") or 0.0)
            if current_duration_seconds:
                self.post(self.update_cleanup_progress_percent, 0)
            else:
                self.post(self.set_cleanup_progress_indeterminate)

            if not changes:
                self.post(self.video_cleanup_no_repair_needed)
                return

            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            self.post(self.append_cleanup_log, f"Output quality: {cleanup_quality}")

            original_fps = float(source_video_info.get("fps") or 0.0)
            safe_fps = original_fps if original_fps > 0 else 25.0
            removed_original_frames: set[int] = set()
            total_references = sum(len(change["frames"]) for change in changes)
            change_count = max(1, len(changes))
            current_input = Path(media_path)

            with tempfile.TemporaryDirectory(
                prefix="voicebridge-video-cleanup-",
                dir=str(output_path.resolve().parent),
            ) as temp_dir_name:
                temp_dir = Path(temp_dir_name)
                final_temp_output = temp_dir / output_path.name
                for index, change in enumerate(changes, start=1):
                    if self.cleanup_cancel_requested:
                        self.post(self.video_cleanup_job_cancelled)
                        return

                    action = change["action"]
                    source_frames = sorted(set(int(frame) for frame in change["frames"] if int(frame) > 0))
                    adjusted_frames = [
                        frame - sum(1 for removed_frame in removed_original_frames if removed_frame < frame)
                        for frame in source_frames
                        if frame not in removed_original_frames
                    ]
                    adjusted_frames = sorted(set(frame for frame in adjusted_frames if frame > 0))
                    if not adjusted_frames:
                        self.post(self.append_cleanup_log, f"C. {index}: skipped, frames already removed.")
                        continue

                    removing_frames = action == VIDEO_CLEANUP_METHOD_REMOVE
                    stage_output = (
                        final_temp_output
                        if index == change_count
                        else temp_dir / f"stage-{index:04d}{output_path.suffix}"
                    )
                    frame_times = [frame / safe_fps for frame in adjusted_frames]
                    self.post(
                        self.cleanup_status.setText,
                        f"Cleaning change {index} of {len(changes)}...",
                    )
                    self.post(
                        self.append_cleanup_log,
                        f"C. {index}: {self.cleanup_action_label_for_key(action)} | "
                        f"{self.format_cleanup_frame_ranges(source_frames)}",
                    )
                    if removing_frames:
                        fps_note = f"{safe_fps:.3f} fps"
                        self.post(self.append_cleanup_log, f"Removing matching audio slices too ({fps_note}).")

                    commands = video_cleanup_repair_commands(
                        ffmpeg,
                        str(current_input),
                        str(stage_output),
                        adjusted_frames,
                        repair_method=action,
                        cleanup_quality=cleanup_quality,
                        source_video_bitrate_kbps=source_video_info.get("bitrate_kbps"),
                        source_video_width=source_video_info.get("width"),
                        source_video_height=source_video_info.get("height"),
                        source_video_fps=safe_fps,
                        source_has_audio=source_video_info.get("has_audio", True),
                        frame_times_seconds=frame_times,
                    )
                    recent_output = []
                    success = False
                    for command in commands:
                        progress_start = ((index - 1) / change_count) * 99
                        progress_end = (index / change_count) * 99
                        return_code, recent_output = self.run_cleanup_ffmpeg_process(
                            command,
                            current_duration_seconds,
                            progress_start,
                            progress_end,
                        )
                        if return_code == 0 and stage_output.is_file():
                            success = True
                            break
                        if self.cleanup_cancel_requested:
                            self.post(self.video_cleanup_job_cancelled)
                            return
                    if not success:
                        raise RuntimeError("\n".join(recent_output[-8:]) or "ffmpeg could not clean the video.")

                    current_input = stage_output
                    if removing_frames:
                        removed_original_frames.update(source_frames)
                        current_duration_seconds = max(
                            0.001,
                            current_duration_seconds - (len(adjusted_frames) / safe_fps),
                        )

                if not final_temp_output.is_file():
                    if current_input.is_file() and current_input != Path(media_path):
                        os.replace(current_input, final_temp_output)
                    else:
                        raise RuntimeError("ffmpeg did not create the cleaned video.")
                os.replace(final_temp_output, output_path)
            self.post(self.update_cleanup_progress_percent, 100)
            self.post(self.video_cleanup_repair_succeeded, str(output_path), len(changes), total_references)
        except (OSError, RuntimeError, ValueError) as exc:
            self.post(self.video_cleanup_job_failed, str(exc))
        finally:
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
            progress_percent = ffmpeg_job_progress_percent(line, duration_seconds)
            if progress_percent is not None:
                mapped = progress_start + ((progress_end - progress_start) * progress_percent / 100)
                if mapped > last_progress_percent:
                    last_progress_percent = mapped
                    self.post(self.update_cleanup_progress_percent, mapped)
                continue
            if not should_keep_ffmpeg_log_line(line):
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

    def cleanup_filmstrip_icon_size(self) -> QSize:
        if not hasattr(self, "cleanup_filmstrip_list"):
            return VIDEO_CLEANUP_FILMSTRIP_ICON_SIZE
        if not self.cleanup_filmstrip_list.isVisible():
            return VIDEO_CLEANUP_FILMSTRIP_ICON_SIZE
        available_height = self.cleanup_filmstrip_list.viewport().height()
        if available_height <= 0:
            return VIDEO_CLEANUP_FILMSTRIP_ICON_SIZE
        icon_height = max(
            VIDEO_CLEANUP_FILMSTRIP_MIN_ICON_HEIGHT,
            min(
                VIDEO_CLEANUP_FILMSTRIP_ICON_SIZE.height(),
                available_height - VIDEO_CLEANUP_FILMSTRIP_LABEL_HEIGHT - VIDEO_CLEANUP_FILMSTRIP_ITEM_GAP,
            ),
        )
        icon_width = round(icon_height * 16 / 9)
        return QSize(icon_width, icon_height)

    def cleanup_filmstrip_grid_size(self) -> QSize:
        icon_size = self.cleanup_filmstrip_icon_size()
        return QSize(
            icon_size.width() + VIDEO_CLEANUP_FILMSTRIP_ITEM_GAP,
            icon_size.height() + VIDEO_CLEANUP_FILMSTRIP_LABEL_HEIGHT + VIDEO_CLEANUP_FILMSTRIP_ITEM_GAP,
        )

    def cleanup_filmstrip_item_count(self) -> int:
        return self.cleanup_filmstrip_item_count_for_focus()

    def cleanup_filmstrip_full_item_count(self) -> int:
        if not hasattr(self, "cleanup_filmstrip_list"):
            return 20
        available_width = max(1, self.cleanup_filmstrip_list.viewport().width())
        item_width = max(1, self.cleanup_filmstrip_grid_size().width() + self.cleanup_filmstrip_list.spacing())
        item_count = available_width // item_width
        return max(1, min(VIDEO_CLEANUP_FILMSTRIP_MAX_ITEMS, item_count))

    def cleanup_filmstrip_item_count_for_focus(self, focus_frame: int | None = None) -> int:
        if not hasattr(self, "cleanup_filmstrip_list"):
            return 20
        available_width = max(1, self.cleanup_filmstrip_list.viewport().width())
        item_width = max(1, self.cleanup_filmstrip_grid_size().width() + self.cleanup_filmstrip_list.spacing())
        total_frames = int(getattr(self, "cleanup_video_total_frames", 0) or 0)
        focus = self.cleanup_filmstrip_focus_frame() if focus_frame is None else max(0, int(focus_frame))
        if total_frames > 0 and focus >= total_frames - 1:
            item_count = available_width // item_width
        else:
            item_count = (available_width + item_width - 1) // item_width
        return max(1, min(VIDEO_CLEANUP_FILMSTRIP_MAX_ITEMS, item_count))

    def cleanup_filmstrip_selected_frames(self) -> list[int]:
        if not hasattr(self, "cleanup_filmstrip_list"):
            return []
        frames = []
        for item in self.cleanup_filmstrip_list.selectedItems():
            frame_number = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(frame_number, int):
                frames.append(frame_number)
        return sorted(set(frames))

    def clear_cleanup_filmstrip_cache(self) -> None:
        self.cancel_cleanup_filmstrip_process()
        self.cleanup_filmstrip_thumbnail_cache = {}
        self.cleanup_filmstrip_loading_keys = set()
        self.cleanup_filmstrip_load_sequence_frames = []
        self.cleanup_filmstrip_loaded_frame_count = 0

    def cancel_cleanup_filmstrip_process(self) -> None:
        if hasattr(self, "cleanup_filmstrip_refresh_timer"):
            self.cleanup_filmstrip_refresh_timer.stop()
        process = getattr(self, "cleanup_filmstrip_process", None)
        if process is not None and process.poll() is None:
            with suppress(OSError):
                process.terminate()
        self.cleanup_filmstrip_process = None

    def stop_cleanup_filmstrip_background_work(self) -> None:
        self.cancel_cleanup_filmstrip_process()
        self.cleanup_filmstrip_loading_keys = set()
        self.cleanup_filmstrip_load_sequence_frames = []
        self.cleanup_filmstrip_loaded_frame_count = 0

    @staticmethod
    def cleanup_filmstrip_cache_key(frame_number: int, thumb_width: int) -> tuple[int, int]:
        return int(thumb_width), int(frame_number)

    @staticmethod
    def format_cleanup_timecode(seconds: float) -> str:
        seconds = max(0, round(float(seconds or 0.0)))
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours:d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:d}:{seconds:02d}"

    @staticmethod
    def format_cleanup_precise_timecode(seconds: float) -> str:
        seconds = max(0.0, float(seconds or 0.0))
        whole_minutes = int(seconds // 60)
        remaining_seconds = seconds - (whole_minutes * 60)
        hours, minutes = divmod(whole_minutes, 60)
        if hours:
            return f"{hours:d}:{minutes:02d}:{remaining_seconds:06.3f}"
        return f"{minutes:d}:{remaining_seconds:06.3f}"

    def cleanup_filmstrip_focus_frame(self) -> int:
        if not hasattr(self, "cleanup_filmstrip_scroll"):
            return 0
        return max(0, int(self.cleanup_filmstrip_scroll.value()))

    def cleanup_filmstrip_start_frame(self, focus_frame: int | None = None) -> int:
        total_frames = int(getattr(self, "cleanup_video_total_frames", 0) or 0)
        if total_frames <= 0:
            return 0
        visible_count = self.cleanup_filmstrip_item_count_for_focus(focus_frame)
        context_before = min(VIDEO_CLEANUP_FILMSTRIP_CONTEXT_BEFORE, max(0, visible_count - 1))
        focus = self.cleanup_filmstrip_focus_frame() if focus_frame is None else max(0, int(focus_frame))
        return max(0, min(focus - context_before, max(0, total_frames - visible_count)))

    def cleanup_filmstrip_slider_time_text(self, focus_frame: int | None = None) -> str:
        total_frames = int(getattr(self, "cleanup_video_total_frames", 0) or 0)
        fps = float(getattr(self, "cleanup_video_fps", 0.0) or 0.0)
        duration_seconds = float(getattr(self, "cleanup_video_duration_seconds", 0.0) or 0.0)
        if total_frames <= 0 or fps <= 0 or duration_seconds <= 0:
            return "Timeline: --"
        focus = self.cleanup_filmstrip_focus_frame() if focus_frame is None else max(0, int(focus_frame))
        start_frame = self.cleanup_filmstrip_start_frame(focus)
        visible_count = self.cleanup_filmstrip_item_count_for_focus(focus)
        end_frame = min(total_frames - 1, start_frame + max(0, visible_count - 1))
        focus_seconds = max(0.0, min(duration_seconds, focus / fps))
        total_text = self.format_cleanup_timecode(duration_seconds)
        return (
            f"Position: #{focus} | {self.format_cleanup_precise_timecode(focus_seconds)} / {total_text} | "
            f"showing #{start_frame}-#{end_frame}"
        )

    def update_cleanup_filmstrip_timeline_label(self, focus_frame: int | None = None) -> None:
        if hasattr(self, "cleanup_filmstrip_timeline_label"):
            self.cleanup_filmstrip_timeline_label.setText(self.cleanup_filmstrip_slider_time_text(focus_frame))

    def configure_cleanup_filmstrip_scroll(self) -> None:
        if not hasattr(self, "cleanup_filmstrip_scroll"):
            return
        total_frames = int(getattr(self, "cleanup_video_total_frames", 0) or 0)
        enabled = total_frames > 1
        self.cleanup_filmstrip_scroll.blockSignals(True)
        try:
            self.cleanup_filmstrip_scroll.setEnabled(enabled and not self.is_cleanup_running)
            self.cleanup_filmstrip_scroll.setRange(0, max(0, total_frames - 1))
            self.cleanup_filmstrip_scroll.setPageStep(max(1, self.cleanup_filmstrip_full_item_count()))
            self.cleanup_filmstrip_scroll.setSingleStep(1)
            if not enabled:
                self.cleanup_filmstrip_scroll.setValue(0)
        finally:
            self.cleanup_filmstrip_scroll.blockSignals(False)
        self.update_cleanup_filmstrip_timeline_label()

    def cleanup_filmstrip_frame_numbers(self, focus_frame: int | None = None) -> list[int]:
        total_frames = int(getattr(self, "cleanup_video_total_frames", 0) or 0)
        if total_frames <= 0:
            return []
        start_frame = self.cleanup_filmstrip_start_frame(focus_frame)
        end_frame = min(total_frames, start_frame + self.cleanup_filmstrip_item_count_for_focus(focus_frame))
        return list(range(start_frame, end_frame))

    def preview_cleanup_filmstrip_position(self, focus_frame: int) -> None:
        media_path = getattr(self, "cleanup_detected_media_path", "")
        total_frames = int(getattr(self, "cleanup_video_total_frames", 0) or 0)
        if not media_path or total_frames <= 0 or not hasattr(self, "cleanup_filmstrip_list"):
            return
        self.cancel_cleanup_filmstrip_process()
        self.cleanup_filmstrip_loading_keys = set()
        self.cleanup_filmstrip_load_sequence_frames = []
        self.cleanup_filmstrip_loaded_frame_count = 0
        frame_numbers = self.cleanup_filmstrip_frame_numbers(focus_frame)
        if not frame_numbers:
            return
        icon_size = self.cleanup_filmstrip_icon_size()
        self.cleanup_filmstrip_list.setIconSize(icon_size)
        thumb_width = icon_size.width()
        self.render_cleanup_filmstrip_items(frame_numbers, thumb_width)
        uncached_count = len(frame_numbers) - self.cached_cleanup_filmstrip_frame_count(frame_numbers, thumb_width)
        if uncached_count:
            self.cleanup_filmstrip_status.setText(f"Loading {uncached_count} frame review thumbnail(s)...")

    def cleanup_filmstrip_load_sequence(self, visible_frames: list[int]) -> list[int]:
        total_frames = int(getattr(self, "cleanup_video_total_frames", 0) or 0)
        if total_frames <= 0:
            return []
        visible = list(dict.fromkeys(int(frame_number) for frame_number in visible_frames))
        if not visible:
            return list(range(total_frames))
        after_visible = range(min(total_frames, visible[-1] + 1), total_frames)
        before_visible = range(0, max(0, visible[0]))
        return list(dict.fromkeys([*visible, *after_visible, *before_visible]))

    def cleanup_filmstrip_icon_pixmap(self, frame_number: int, image_data: bytes | None, *, selected: bool) -> QPixmap:
        icon_size = self.cleanup_filmstrip_icon_size()
        canvas = QPixmap(icon_size)
        canvas.fill(QColor("#f8fafc"))

        painter = QPainter(canvas)
        try:
            if frame_number in self.cleanup_marked_frame_numbers:
                border_color = QColor("#dc2626")
                fill_color = QColor("#fef2f2")
                border_width = 5
            elif self.cleanup_queued_actions_for_frame(frame_number):
                border_color = QColor("#0284c7")
                fill_color = QColor("#e0f2fe")
                border_width = 4
            elif frame_number in self.cleanup_detected_frame_map or frame_number in self.cleanup_suspicious_frame_map:
                border_color = QColor("#f59e0b")
                fill_color = QColor("#fffbeb")
                border_width = 3
            elif selected:
                border_color = QColor("#2563eb")
                fill_color = QColor("#eff6ff")
                border_width = 4
            else:
                border_color = QColor("#cbd5e1")
                fill_color = QColor("#f8fafc")
                border_width = 1
            canvas.fill(fill_color)
            inset = 0 if selected else VIDEO_CLEANUP_FILMSTRIP_UNSELECTED_INSET
            target = QRect(
                inset,
                inset,
                max(1, icon_size.width() - (inset * 2)),
                max(1, icon_size.height() - (inset * 2)),
            )

            painted_thumbnail = False
            if image_data:
                source = QPixmap()
                source.loadFromData(image_data)
                if not source.isNull():
                    scaled = source.scaled(
                        target.size(),
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    x = target.x() + ((target.width() - scaled.width()) // 2)
                    y = target.y() + ((target.height() - scaled.height()) // 2)
                    painter.setClipRect(target)
                    painter.drawPixmap(x, y, scaled)
                    painter.setClipping(False)
                    painted_thumbnail = True
            if not painted_thumbnail:
                painter.setPen(QColor("#64748b"))
                painter.drawText(target, Qt.AlignmentFlag.AlignCenter, "Loading")
            pen = QPen(border_color)
            pen.setWidth(border_width)
            painter.setPen(pen)
            half_width = max(1, border_width // 2)
            painter.drawRect(
                half_width,
                half_width,
                icon_size.width() - border_width,
                icon_size.height() - border_width,
            )
        finally:
            painter.end()

        return canvas

    def cleanup_filmstrip_item_widget(self, frame_number: int, pixmap: QPixmap) -> QWidget:
        icon_size = self.cleanup_filmstrip_icon_size()
        grid_size = self.cleanup_filmstrip_grid_size()
        widget = QWidget()
        widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        widget.setFixedSize(grid_size)

        image_label = QLabel()
        image_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        image_label.setParent(widget)
        image_label.setFixedSize(icon_size)
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_label.setPixmap(pixmap)
        image_label.move(0, 0)

        text_label = QLabel(self.cleanup_filmstrip_item_text(frame_number))
        text_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        text_label.setParent(widget)
        text_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        text_label.setWordWrap(False)
        font = text_label.font()
        font.setPointSize(9)
        text_label.setFont(font)
        text_label.setFixedSize(grid_size.width(), VIDEO_CLEANUP_FILMSTRIP_LABEL_HEIGHT)
        text_label.setStyleSheet("padding: 0; margin: 0;")
        text_label.move(0, icon_size.height() + 2)
        return widget

    def render_cleanup_filmstrip_items(self, frame_numbers: list[int], thumb_width: int) -> None:
        if not hasattr(self, "cleanup_filmstrip_list"):
            return
        selected_frames = set(self.cleanup_filmstrip_selected_frames())
        self.cleanup_filmstrip_list.blockSignals(True)
        try:
            self.cleanup_filmstrip_list.clear()
            icon_size = self.cleanup_filmstrip_icon_size()
            grid_size = self.cleanup_filmstrip_grid_size()
            self.cleanup_filmstrip_list.setIconSize(icon_size)
            self.cleanup_filmstrip_list.setGridSize(grid_size)
            cache = getattr(self, "cleanup_filmstrip_thumbnail_cache", {})
            for frame_number in frame_numbers:
                cache_key = self.cleanup_filmstrip_cache_key(frame_number, thumb_width)
                image_data = cache.get(cache_key)
                pixmap = self.cleanup_filmstrip_icon_pixmap(
                    frame_number,
                    image_data,
                    selected=frame_number in selected_frames,
                )
                item = QListWidgetItem()
                if image_data:
                    item.setToolTip(self.cleanup_filmstrip_item_tooltip(frame_number))
                else:
                    item.setToolTip(f"{self.cleanup_filmstrip_item_tooltip(frame_number)}\nThumbnail loading...")
                item.setData(Qt.ItemDataRole.UserRole, frame_number)
                item.setSizeHint(grid_size)
                self.apply_cleanup_filmstrip_item_style(item, frame_number)
                self.cleanup_filmstrip_list.addItem(item)
                self.cleanup_filmstrip_list.setItemWidget(
                    item,
                    self.cleanup_filmstrip_item_widget(frame_number, pixmap),
                )
                if frame_number in selected_frames:
                    item.setSelected(True)
        finally:
            self.cleanup_filmstrip_list.blockSignals(False)
        self.update_cleanup_filmstrip_status()
        self.update_video_cleanup_button_state()

    def missing_cleanup_filmstrip_frames(self, frame_numbers: list[int], thumb_width: int) -> list[int]:
        cache = getattr(self, "cleanup_filmstrip_thumbnail_cache", {})
        loading_keys = getattr(self, "cleanup_filmstrip_loading_keys", set())
        return [
            frame_number
            for frame_number in frame_numbers
            if self.cleanup_filmstrip_cache_key(frame_number, thumb_width) not in cache
            and self.cleanup_filmstrip_cache_key(frame_number, thumb_width) not in loading_keys
        ]

    def cached_cleanup_filmstrip_frame_count(self, frame_numbers: list[int], thumb_width: int) -> int:
        cache = getattr(self, "cleanup_filmstrip_thumbnail_cache", {})
        return sum(
            1
            for frame_number in frame_numbers
            if self.cleanup_filmstrip_cache_key(frame_number, thumb_width) in cache
        )

    def loading_cleanup_filmstrip_frame_count(self, frame_numbers: list[int], thumb_width: int) -> int:
        loading_keys = getattr(self, "cleanup_filmstrip_loading_keys", set())
        return sum(
            1
            for frame_number in frame_numbers
            if self.cleanup_filmstrip_cache_key(frame_number, thumb_width) in loading_keys
        )

    def cleanup_filmstrip_background_progress_text(self, thumb_width: int) -> str:
        loading_keys = getattr(self, "cleanup_filmstrip_loading_keys", set())
        sequence = list(getattr(self, "cleanup_filmstrip_load_sequence_frames", []))
        if not loading_keys or not sequence:
            return ""
        remaining = [
            frame_number
            for frame_number in sequence
            if self.cleanup_filmstrip_cache_key(frame_number, thumb_width) in loading_keys
        ]
        if not remaining:
            return ""
        loaded_count = max(0, len(sequence) - len(remaining))
        return f" | loading frame #{remaining[0]} ({loaded_count}/{len(sequence)})"

    @staticmethod
    def cleanup_filmstrip_batches(frame_numbers: list[int]) -> list[list[int]]:
        frames = list(dict.fromkeys(int(frame_number) for frame_number in frame_numbers))
        batches: list[list[int]] = []
        current_batch: list[int] = []
        previous_frame: int | None = None
        for frame_number in frames:
            starts_new_ordered_run = previous_frame is not None and frame_number <= previous_frame
            if current_batch and (len(current_batch) >= VIDEO_CLEANUP_FILMSTRIP_BATCH_SIZE or starts_new_ordered_run):
                batches.append(current_batch)
                current_batch = []
            current_batch.append(frame_number)
            previous_frame = frame_number
        if current_batch:
            batches.append(current_batch)
        return batches

    def start_cleanup_filmstrip_load(
        self,
        generation: int,
        ffmpeg: str,
        media_path: str,
        frame_numbers: list[int],
        thumb_width: int,
    ) -> None:
        self.cancel_cleanup_filmstrip_process()
        self.cleanup_filmstrip_loading_keys = set()
        frames_to_load = self.missing_cleanup_filmstrip_frames(frame_numbers, thumb_width)
        if not frames_to_load:
            self.cleanup_filmstrip_load_sequence_frames = []
            self.cleanup_filmstrip_loaded_frame_count = 0
            return
        self.cleanup_filmstrip_load_sequence_frames = frames_to_load
        self.cleanup_filmstrip_loaded_frame_count = 0
        loading_keys = getattr(self, "cleanup_filmstrip_loading_keys", set())
        loading_keys.update(
            self.cleanup_filmstrip_cache_key(frame_number, thumb_width)
            for frame_number in frames_to_load
        )
        self.cleanup_filmstrip_loading_keys = loading_keys
        threading.Thread(
            target=self.video_cleanup_filmstrip_worker,
            args=(generation, str(ffmpeg), media_path, frames_to_load, thumb_width),
            daemon=True,
        ).start()

    def schedule_cleanup_filmstrip_refresh(self) -> None:
        timer = getattr(self, "cleanup_filmstrip_refresh_timer", None)
        if timer is None:
            self.refresh_cleanup_filmstrip()
            return
        timer.start(VIDEO_CLEANUP_FILMSTRIP_REFRESH_DEBOUNCE_MS)

    def refresh_cleanup_filmstrip(self) -> None:
        if not hasattr(self, "cleanup_filmstrip_list"):
            return
        media_path = self.cleanup_detected_media_path
        total_frames = int(getattr(self, "cleanup_video_total_frames", 0) or 0)
        if not media_path or total_frames <= 0:
            self.cleanup_filmstrip_list.clear()
            self.cleanup_filmstrip_status.setText("Select a video file to load frame review.")
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
        thumb_width = icon_size.width()
        self.render_cleanup_filmstrip_items(frame_numbers, thumb_width)
        uncached_count = len(frame_numbers) - self.cached_cleanup_filmstrip_frame_count(frame_numbers, thumb_width)
        if uncached_count:
            self.cleanup_filmstrip_status.setText(
                f"Loading {uncached_count} frame review thumbnail(s)..."
            )
        else:
            self.update_cleanup_filmstrip_status()
        self.update_video_cleanup_button_state()
        self.start_cleanup_filmstrip_load(
            generation,
            str(ffmpeg),
            media_path,
            self.cleanup_filmstrip_load_sequence(frame_numbers),
            thumb_width,
        )
        self.update_cleanup_filmstrip_status()

    def video_cleanup_filmstrip_worker(
        self,
        generation: int,
        ffmpeg: str,
        media_path: str,
        frame_numbers: list[int],
        thumb_width: int,
    ) -> None:
        for batch in self.cleanup_filmstrip_batches(frame_numbers):
            if self.cleanup_cancel_requested or generation != self.cleanup_filmstrip_generation:
                return
            thumbnails = self.run_video_cleanup_filmstrip_batch(
                generation,
                ffmpeg,
                media_path,
                batch,
                thumb_width,
            )
            self.post(self.cleanup_filmstrip_loaded, generation, media_path, batch, thumb_width, thumbnails)
            if not thumbnails:
                break
        self.post(self.cleanup_filmstrip_load_finished, generation, media_path, thumb_width)

    def run_video_cleanup_filmstrip_batch(
        self,
        generation: int,
        ffmpeg: str,
        media_path: str,
        frame_numbers: list[int],
        thumb_width: int,
    ) -> list[tuple[int, bytes]]:
        thumbnails: list[tuple[int, bytes]] = []
        requested_frames = sorted({max(0, int(frame_number)) for frame_number in frame_numbers})
        if not requested_frames:
            return thumbnails
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        with tempfile.TemporaryDirectory(prefix="voicebridge-filmstrip-") as temp_dir:
            output_pattern = str(Path(temp_dir) / "frame_%05d.jpg")
            command = video_filmstrip_preview_command(ffmpeg, media_path, requested_frames, output_pattern, thumb_width)
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
            )
            self.cleanup_filmstrip_process = process
            try:
                _stdout, stderr = process.communicate(timeout=VIDEO_CLEANUP_FILMSTRIP_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                with suppress(OSError):
                    process.terminate()
                process.communicate()
                self.post(self.append_cleanup_log, "Frame review thumbnail generation timed out.")
                return []
            finally:
                if getattr(self, "cleanup_filmstrip_process", None) is process:
                    self.cleanup_filmstrip_process = None
            if generation != self.cleanup_filmstrip_generation:
                return []
            if process.returncode != 0:
                if stderr.strip():
                    self.post(self.append_cleanup_log, stderr.strip().splitlines()[-1])
                return []
            for index, frame_number in enumerate(requested_frames, start=1):
                output_path = Path(temp_dir) / f"frame_{index:05d}.jpg"
                if output_path.is_file():
                    thumbnails.append((frame_number, output_path.read_bytes()))
        return thumbnails

    def cleanup_filmstrip_loaded(
        self,
        generation: int,
        media_path: str,
        frame_numbers: list[int],
        thumb_width: int,
        thumbnails: list[tuple[int, bytes]],
    ) -> None:
        if media_path != self.cleanup_detected_media_path:
            return
        cache = getattr(self, "cleanup_filmstrip_thumbnail_cache", {})
        for frame_number, image_data in thumbnails:
            cache[self.cleanup_filmstrip_cache_key(frame_number, thumb_width)] = image_data
        self.cleanup_filmstrip_thumbnail_cache = cache

        if generation != self.cleanup_filmstrip_generation:
            return
        loading_keys = getattr(self, "cleanup_filmstrip_loading_keys", set())
        for frame_number in frame_numbers:
            loading_keys.discard(self.cleanup_filmstrip_cache_key(frame_number, thumb_width))
        self.cleanup_filmstrip_loading_keys = loading_keys
        sequence = list(getattr(self, "cleanup_filmstrip_load_sequence_frames", []))
        if sequence:
            self.cleanup_filmstrip_loaded_frame_count = min(
                len(sequence),
                max(
                    int(getattr(self, "cleanup_filmstrip_loaded_frame_count", 0)),
                    len(sequence) - len(loading_keys),
                ),
            )
        current_frame_numbers = self.cleanup_filmstrip_frame_numbers()
        if current_frame_numbers:
            self.render_cleanup_filmstrip_items(current_frame_numbers, thumb_width)
            self.update_cleanup_filmstrip_status()
        else:
            self.cleanup_filmstrip_status.setText("Frame review unavailable.")
            self.update_video_cleanup_button_state()
            return
        self.update_video_cleanup_button_state()

    def cleanup_filmstrip_load_finished(self, generation: int, media_path: str, thumb_width: int) -> None:
        if generation != self.cleanup_filmstrip_generation or media_path != self.cleanup_detected_media_path:
            return
        self.cleanup_filmstrip_loading_keys = set()
        self.cleanup_filmstrip_load_sequence_frames = []
        self.cleanup_filmstrip_loaded_frame_count = 0
        current_frame_numbers = self.cleanup_filmstrip_frame_numbers()
        if current_frame_numbers:
            self.render_cleanup_filmstrip_items(current_frame_numbers, thumb_width)
            self.update_cleanup_filmstrip_status()
        self.update_video_cleanup_button_state()

    def cleanup_filmstrip_item_text(self, frame_number: int) -> str:
        time_seconds = self.cleanup_frame_time_seconds(frame_number)
        markers = []
        queued_actions = self.cleanup_queued_actions_for_frame(frame_number)
        if queued_actions:
            markers.append("Queued")
        elif frame_number in self.cleanup_marked_frame_numbers:
            markers.append("Marked")
        elif frame_number in self.cleanup_suspicious_frame_map:
            markers.append("Suspicious")
        marker_suffix = f" | {' / '.join(markers)}" if markers else ""
        return f"#{frame_number} / {time_seconds:.3f}s{marker_suffix}"

    def cleanup_filmstrip_item_tooltip(self, frame_number: int) -> str:
        queued_actions = self.cleanup_queued_actions_for_frame(frame_number)
        if queued_actions:
            action_names = ", ".join(self.cleanup_action_label_for_key(action) for action in queued_actions)
            status = f"Queued: {action_names}"
        else:
            status = "Marked for cleanup" if frame_number in self.cleanup_marked_frame_numbers else "Not marked"
        if frame_number in self.cleanup_repairable_frame_map:
            status += "; auto-detected isolated black frame"
        elif frame_number in self.cleanup_detected_frame_map:
            status += "; auto-detected black frame"
        elif frame_number in self.cleanup_suspicious_frame_map:
            anomaly = self.cleanup_suspicious_frame_map[frame_number]
            status += f"; suspicious: {self.cleanup_suspicious_kind_label(str(anomaly.get('kind', '')))}"
        return f"Frame {frame_number} at {self.cleanup_frame_time_seconds(frame_number):.3f}s\n{status}"

    def cleanup_queued_actions_for_frame(self, frame_number: int) -> list[str]:
        actions = []
        for change in getattr(self, "cleanup_changes", []):
            for raw_frame in change.get("frames", []) or []:
                try:
                    if int(raw_frame) == frame_number:
                        actions.append(change.get("action", ""))
                except (TypeError, ValueError):
                    continue
        return [action for action in actions if action]

    def cleanup_queued_frame_numbers(self) -> set[int]:
        frame_numbers: set[int] = set()
        for change in getattr(self, "cleanup_changes", []):
            for raw_frame in change.get("frames") or []:
                try:
                    frame_number = int(raw_frame)
                except (TypeError, ValueError):
                    continue
                if frame_number > 0:
                    frame_numbers.add(frame_number)
        return frame_numbers

    def apply_cleanup_filmstrip_item_style(self, item: QListWidgetItem, frame_number: int) -> None:
        if self.cleanup_queued_actions_for_frame(frame_number):
            item.setBackground(QBrush(QColor("#e0f2fe")))
            item.setForeground(QBrush(QColor("#075985")))
        elif frame_number in self.cleanup_marked_frame_numbers:
            item.setBackground(QBrush(QColor("#fee2e2")))
            item.setForeground(QBrush(QColor("#7f1d1d")))
        elif frame_number in self.cleanup_detected_frame_map or frame_number in self.cleanup_suspicious_frame_map:
            item.setBackground(QBrush(QColor("#fff7e6")))
            item.setForeground(QBrush(QColor("#7a4b00")))
        else:
            item.setBackground(QBrush(QColor("#ffffff")))
            item.setForeground(QBrush(QColor("#111827")))

    def update_cleanup_filmstrip_item_styles(self) -> None:
        if not hasattr(self, "cleanup_filmstrip_list"):
            return
        frame_numbers = self.cleanup_filmstrip_frame_numbers()
        if frame_numbers:
            self.render_cleanup_filmstrip_items(frame_numbers, self.cleanup_filmstrip_icon_size().width())
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
        frame_numbers = self.cleanup_filmstrip_frame_numbers()
        thumb_width = self.cleanup_filmstrip_icon_size().width()
        uncached_count = len(frame_numbers) - self.cached_cleanup_filmstrip_frame_count(frame_numbers, thumb_width)
        background_text = self.cleanup_filmstrip_background_progress_text(thumb_width)
        if uncached_count:
            loading_count = self.loading_cleanup_filmstrip_frame_count(frame_numbers, thumb_width)
            if loading_count:
                self.cleanup_filmstrip_status.setText(
                    f"Loading {uncached_count} visible frame review thumbnail(s){selected_text}{background_text}..."
                )
            else:
                self.cleanup_filmstrip_status.setText(
                    f"Frame review ready: {uncached_count} thumbnail(s) unavailable{selected_text}{background_text}."
                )
            return
        self.cleanup_filmstrip_status.setText(
            f"Frame review ready: {total_frames} frame(s), {marked_count} marked{selected_text}{background_text}."
        )

    def cleanup_filmstrip_selection_changed(self) -> None:
        if hasattr(self, "cleanup_changes_list"):
            self.cleanup_changes_list.blockSignals(True)
            try:
                self.cleanup_changes_list.clearSelection()
                self.cleanup_changes_list.setCurrentRow(-1)
            finally:
                self.cleanup_changes_list.blockSignals(False)
        frame_numbers = self.cleanup_filmstrip_frame_numbers()
        if frame_numbers:
            self.render_cleanup_filmstrip_items(frame_numbers, self.cleanup_filmstrip_icon_size().width())
            return
        self.update_cleanup_filmstrip_status()
        self.update_video_cleanup_button_state()

    def cleanup_filmstrip_scroll_changed(self, _value: int) -> None:
        self.update_cleanup_filmstrip_timeline_label(_value)
        self.preview_cleanup_filmstrip_position(_value)
        self.schedule_cleanup_filmstrip_refresh()

    def cleanup_filmstrip_slider_moved(self, value: int) -> None:
        self.update_cleanup_filmstrip_timeline_label(value)

    def nudge_cleanup_filmstrip_frame(self, delta: int) -> None:
        if not hasattr(self, "cleanup_filmstrip_scroll"):
            return
        current_value = self.cleanup_filmstrip_scroll.value()
        target_value = max(
            self.cleanup_filmstrip_scroll.minimum(),
            min(self.cleanup_filmstrip_scroll.maximum(), current_value + int(delta)),
        )
        if target_value != current_value:
            self.cleanup_filmstrip_scroll.setValue(target_value)

    def center_cleanup_filmstrip_on_frame(self, frame_number: int, *, refresh: bool = True) -> None:
        if not hasattr(self, "cleanup_filmstrip_scroll"):
            return
        total_frames = int(getattr(self, "cleanup_video_total_frames", 0) or 0)
        if total_frames <= 0:
            return
        target_frame = max(0, min(int(frame_number), total_frames - 1))
        self.cleanup_filmstrip_scroll.blockSignals(True)
        try:
            self.cleanup_filmstrip_scroll.setValue(target_frame)
        finally:
            self.cleanup_filmstrip_scroll.blockSignals(False)
        self.update_cleanup_filmstrip_timeline_label(target_frame)
        if refresh:
            self.refresh_cleanup_filmstrip()

    def mark_selected_cleanup_filmstrip_frames(self) -> None:
        queued_frames = self.cleanup_queued_frame_numbers()
        selected = [
            frame
            for frame in self.cleanup_filmstrip_selected_frames()
            if frame > 0 and frame not in queued_frames
        ]
        if not selected:
            self.cleanup_status.setText("Select one or more unqueued frames in the frame review first.")
            return
        self.cleanup_marked_frame_numbers.update(selected)
        self.cleanup_filmstrip_list.clearSelection()
        self.refresh_video_cleanup_changes_list()
        self.update_video_cleanup_button_state()

    def unmark_selected_cleanup_filmstrip_frames(self) -> None:
        selected = self.cleanup_filmstrip_selected_frames()
        if not selected:
            self.cleanup_status.setText("Select one or more frames in the frame review first.")
            return
        for frame_number in selected:
            self.cleanup_marked_frame_numbers.discard(frame_number)
        self.cleanup_filmstrip_list.clearSelection()
        self.refresh_video_cleanup_changes_list()
        self.update_video_cleanup_button_state()

    def clear_cleanup_marked_frames(self) -> None:
        self.cleanup_marked_frame_numbers.clear()
        self.refresh_video_cleanup_changes_list()
        self.update_video_cleanup_button_state()

    def cleanup_result_item_double_clicked(self, item: QListWidgetItem) -> None:
        frame_number = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(frame_number, int):
            self.center_cleanup_filmstrip_on_frame(frame_number)

    def cleanup_suspicious_item_double_clicked(self, item: QListWidgetItem) -> None:
        frame_number = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(frame_number, int):
            self.center_cleanup_filmstrip_on_frame(frame_number)

    def add_cleanup_result_row(self, frame: BlackFrame, repairable: bool, reason: str) -> None:
        frame_number = frame["frame"]
        item = QListWidgetItem()
        item.setText(f"Frame {frame_number} | {frame['time']:.3f}s | {frame['pblack']}% black | {reason}")
        item.setData(Qt.ItemDataRole.UserRole, frame_number)
        self.cleanup_results.addItem(item)

    @staticmethod
    def cleanup_suspicious_kind_label(kind: str) -> str:
        if kind == SINGLE_FRAME_INTERRUPTION:
            return "Single-frame anomaly"
        if kind == CUT_BOUNDARY_ANOMALY:
            return "Cut-boundary anomaly"
        return "Suspicious frame"

    def add_cleanup_suspicious_row(self, anomaly: FrameAnomaly) -> None:
        frame_number = int(anomaly["frame"])
        item = QListWidgetItem()
        item.setText(
            f"Frame {frame_number} | {float(anomaly['time']):.3f}s | "
            f"{self.cleanup_suspicious_kind_label(str(anomaly['kind']))} | score {float(anomaly['score']):.1f}"
        )
        item.setToolTip(str(anomaly.get("reason") or "Review this frame before marking it manually."))
        item.setData(Qt.ItemDataRole.UserRole, frame_number)
        self.cleanup_suspicious_results.addItem(item)

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
        self.cleanup_marked_frame_numbers = {
            int(frame_number)
            for frame_number in isolated_frames
            if int(frame_number) > 0
        }
        self.cleanup_video_fps = float(source_video_info.get("fps") or 0.0)
        self.cleanup_video_duration_seconds = float(source_video_info.get("duration_seconds") or 0.0)
        self.cleanup_video_total_frames = self.cleanup_total_frames_from_video_info(source_video_info)
        self.refresh_video_cleanup_changes_list()
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
            reason = (
                "Marked pending action"
                if repairable
                else reason_by_frame.get(
                    frame["frame"],
                    "Detected; review before marking manually",
                )
            )
            self.add_cleanup_result_row(frame, repairable, reason)
        if len(black_frames) > 120:
            self.cleanup_results.addItem(f"...and {len(black_frames) - 120} more candidates in the log.")
        self.update_video_cleanup_button_state()

    def cleanup_anomaly_detection_finished(self, media_path: str, anomalies: list[dict]) -> None:
        if media_path != self.cleanup_detected_media_path:
            return
        self.cleanup_suspicious_frames = anomalies
        self.cleanup_suspicious_frame_map = {
            int(anomaly["frame"]): anomaly
            for anomaly in anomalies
            if int(anomaly.get("frame", -1)) >= 0
        }
        self.cleanup_suspicious_results.clear()
        if not anomalies:
            self.cleanup_suspicious_results.addItem("No suspicious frame anomalies found.")
        else:
            for anomaly in anomalies[:160]:
                self.add_cleanup_suspicious_row(anomaly)
            if len(anomalies) > 160:
                self.cleanup_suspicious_results.addItem(
                    f"...and {len(anomalies) - 160} more suspicious frame(s) in the log."
                )
        self.refresh_cleanup_filmstrip()
        self.update_video_cleanup_button_state()

    def video_cleanup_detect_succeeded(self, black_frames, isolated_frames, longer_runs):
        if black_frames:
            actionable_count = len([frame_number for frame_number in isolated_frames if int(frame_number) > 0])
            self.cleanup_status.setText(
                f"Detected {len(black_frames)} black-frame candidate(s); {actionable_count} marked pending action."
            )
        else:
            self.cleanup_status.setText("No black-frame candidates found.")
        if longer_runs:
            self.append_cleanup_log(
                f"Longer black runs were detected: {len(longer_runs)}. "
                "They were not auto-marked; review before marking manually."
            )

    def video_anomaly_detect_succeeded(self, anomalies: list[dict]) -> None:
        self.cleanup_status.setText(f"Detected {len(anomalies)} suspicious frame(s).")
        self.append_cleanup_log(
            f"Suspicious frame detection completed: {len(anomalies)} candidate(s), review only."
        )

    def video_cleanup_no_repair_needed(self):
        self.cleanup_status.setText("No video cleanup changes queued.")
        self.append_cleanup_log("No video cleanup changes were queued. No output video was created.")

    def video_cleanup_repair_succeeded(self, output_path, change_count, affected_frame_count):
        self.cleanup_last_output_path = output_path
        self.cleanup_status.setText(f"Applied {change_count} video cleanup change(s).")
        self.append_cleanup_log(f"Video saved: {output_path}")
        self.record_job(
            "CLEAN",
            "Video cleaned",
            self.cleanup_media_picker.text(),
            output_path,
            f"{change_count} change(s), {affected_frame_count} frame reference(s)",
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
        review_ready = bool(
            self.cleanup_detected_media_path
            and self.cleanup_detected_media_path == current_media
            and self.cleanup_video_total_frames
        )
        marked_frames = self.selected_cleanup_frame_numbers() if review_ready else []
        selected_visible_frames = self.cleanup_filmstrip_selected_frames() if review_ready else []
        queued_frames = self.cleanup_queued_frame_numbers() if review_ready else set()
        selected_markable_frames = [
            frame_number
            for frame_number in selected_visible_frames
            if (
                frame_number > 0
                and frame_number not in self.cleanup_marked_frame_numbers
                and frame_number not in queued_frames
            )
        ]
        selected_marked_frames = [
            frame_number
            for frame_number in selected_visible_frames
            if frame_number in self.cleanup_marked_frame_numbers
        ]
        selected_pending_change_frame = False
        current_change_item = self.cleanup_changes_list.currentItem()
        if current_change_item is not None:
            current_change_value = current_change_item.data(Qt.ItemDataRole.UserRole)
            selected_pending_change_frame = (
                isinstance(current_change_value, tuple)
                and len(current_change_value) == 2
                and current_change_value[0] == "pending_marked"
            )
        has_changes = bool(getattr(self, "cleanup_changes", []))
        has_pending_marked_frames = bool(marked_frames)
        has_action_target = bool(selected_marked_frames or selected_pending_change_frame)
        has_conflicting_changes = bool(conflicting_video_cleanup_change_frames(getattr(self, "cleanup_changes", [])))
        self.cleanup_start_button.setEnabled(review_ready and not self.is_cleanup_running and not busy_elsewhere)
        self.cleanup_anomaly_start_button.setEnabled(
            review_ready and not self.is_cleanup_running and not busy_elsewhere
        )
        self.cleanup_repair_button.setEnabled(
            review_ready
            and has_changes
            and not has_pending_marked_frames
            and not has_conflicting_changes
            and not self.is_cleanup_running
            and not busy_elsewhere
        )
        self.cleanup_cancel_button.setEnabled(self.is_cleanup_running and not self.cleanup_cancel_requested)
        output_ready = bool(self.cleanup_last_output_path and Path(self.cleanup_last_output_path).is_file())
        self.cleanup_open_output_button.setEnabled(output_ready)
        self.cleanup_open_folder_button.setEnabled(output_ready)
        for widget in (
            self.cleanup_media_picker,
            self.cleanup_output_picker,
            self.cleanup_quality_combo,
        ):
            widget.setEnabled(not self.is_cleanup_running)
        self.cleanup_changes_list.setEnabled((has_changes or has_pending_marked_frames) and not self.is_cleanup_running)
        for widget in (
            self.cleanup_filmstrip_list,
            self.cleanup_filmstrip_scroll,
            self.cleanup_filmstrip_prev_frame_button,
            self.cleanup_filmstrip_next_frame_button,
            self.cleanup_anomaly_start_button,
            self.cleanup_mark_frame_button,
            self.cleanup_unmark_frame_button,
            self.cleanup_clear_marks_button,
            self.cleanup_freeze_marked_button,
            self.cleanup_remove_marked_button,
        ):
            widget.setEnabled(review_ready and not self.is_cleanup_running)
        self.cleanup_mark_frame_button.setEnabled(
            review_ready and bool(selected_markable_frames) and not self.is_cleanup_running
        )
        self.cleanup_unmark_frame_button.setEnabled(
            review_ready and bool(selected_marked_frames) and not self.is_cleanup_running
        )
        self.cleanup_clear_marks_button.setEnabled(
            review_ready and bool(marked_frames) and not self.is_cleanup_running
        )
        self.cleanup_freeze_marked_button.setEnabled(
            review_ready and has_action_target and not self.is_cleanup_running
        )
        self.cleanup_remove_marked_button.setEnabled(
            review_ready and has_action_target and not self.is_cleanup_running
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
            "Review video frames, queue cleanup changes and export a repaired copy before subtitling.",
        )

        grid = QGridLayout()
        grid.setSpacing(16)
        layout.addLayout(grid)

        cleanup_top_card_min_height = 248

        files_card = Card("Files")
        files_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        files_card.setMinimumHeight(cleanup_top_card_min_height)
        self.cleanup_media_picker = FilePicker("Video file")
        self.cleanup_output_picker = FilePicker("Save cleaned video as", "Save as...")
        self.cleanup_media_picker.button.clicked.connect(self.select_cleanup_media_file)
        self.cleanup_output_picker.button.clicked.connect(self.select_cleanup_output_file)
        self.cleanup_media_picker.edit.textChanged.connect(self.cleanup_media_changed)
        self.cleanup_quality_label = QLabel("Output quality")
        self.cleanup_quality_combo = QComboBox()
        self.cleanup_quality_combo.addItems(VIDEO_CLEANUP_QUALITY_LABELS)
        self.cleanup_quality_combo.setCurrentText(BURN_QUALITY_AUTO_LABEL)
        self.cleanup_quality_combo.currentTextChanged.connect(self.update_cleanup_quality_description)
        self.cleanup_quality_description = QLabel(VIDEO_CLEANUP_QUALITY_DESCRIPTIONS[BURN_QUALITY_AUTO_LABEL])
        self.cleanup_quality_description.setObjectName("Muted")
        self.cleanup_quality_description.setWordWrap(True)
        self.cleanup_rule_note = QLabel(
            "Black-frame detection can auto-mark isolated black frames. Frame-glitch detection only marks "
            "suspicious frames for manual review."
        )
        self.cleanup_rule_note.setObjectName("Muted")
        self.cleanup_rule_note.setWordWrap(True)
        files_card.content_layout.addWidget(self.cleanup_media_picker)
        files_card.content_layout.addWidget(self.cleanup_output_picker)
        files_card.content_layout.addWidget(self.cleanup_quality_label)
        files_card.content_layout.addWidget(self.cleanup_quality_combo)
        files_card.content_layout.addWidget(self.cleanup_quality_description)
        files_card.content_layout.addWidget(self.cleanup_rule_note)

        changes_card = Card("Applied changes")
        changes_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        changes_card.setMinimumHeight(cleanup_top_card_min_height)
        self.cleanup_changes_list = QListWidget()
        self.cleanup_changes_list.setMinimumHeight(132)
        self.cleanup_changes_list.currentItemChanged.connect(
            lambda _current, _previous: self.cleanup_change_selection_changed()
        )
        self.cleanup_changes_list.itemDoubleClicked.connect(self.cleanup_change_item_double_clicked)
        self.cleanup_changes_status = QLabel("Mark frames, then apply Freeze or Remove before cleaning video.")
        self.cleanup_changes_status.setObjectName("Muted")
        self.cleanup_changes_status.setWordWrap(True)
        changes_card.content_layout.addWidget(self.cleanup_changes_list)
        changes_card.content_layout.addWidget(self.cleanup_changes_status)

        grid.addWidget(files_card, 0, 0)
        grid.addWidget(changes_card, 0, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        filmstrip_card = Card("Frame review")
        zoom_row = QHBoxLayout()
        zoom_row.setContentsMargins(0, 0, 0, 0)
        self.cleanup_filmstrip_status = QLabel("Select a video file to load frame review.")
        self.cleanup_filmstrip_status.setObjectName("Muted")
        self.cleanup_filmstrip_status.setWordWrap(True)
        zoom_row.addWidget(self.cleanup_filmstrip_status, 1)
        self.cleanup_filmstrip_list = ClearableFilmstripListWidget()
        self.cleanup_filmstrip_list.setViewMode(QListView.ViewMode.IconMode)
        self.cleanup_filmstrip_list.setFlow(QListView.Flow.LeftToRight)
        self.cleanup_filmstrip_list.setWrapping(False)
        self.cleanup_filmstrip_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.cleanup_filmstrip_list.setMovement(QListView.Movement.Static)
        self.cleanup_filmstrip_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.cleanup_filmstrip_list.setSpacing(8)
        filmstrip_list_height = self.cleanup_filmstrip_grid_size().height() + 4
        self.cleanup_filmstrip_list.setMinimumHeight(filmstrip_list_height)
        self.cleanup_filmstrip_list.setMaximumHeight(filmstrip_list_height)
        self.cleanup_filmstrip_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.cleanup_filmstrip_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.cleanup_filmstrip_list.itemSelectionChanged.connect(self.cleanup_filmstrip_selection_changed)
        timeline_row = QHBoxLayout()
        timeline_row.setContentsMargins(0, 0, 0, 0)
        self.cleanup_filmstrip_timeline_label = QLabel("Timeline: --")
        self.cleanup_filmstrip_timeline_label.setObjectName("Muted")
        self.cleanup_filmstrip_timeline_label.setMinimumWidth(520)
        self.cleanup_filmstrip_prev_frame_button = QToolButton()
        self.cleanup_filmstrip_prev_frame_button.setText("<")
        self.cleanup_filmstrip_prev_frame_button.setToolTip("Move frame review one frame left")
        self.cleanup_filmstrip_prev_frame_button.setAutoRepeat(True)
        self.cleanup_filmstrip_prev_frame_button.clicked.connect(
            lambda _checked=False: self.nudge_cleanup_filmstrip_frame(-1)
        )
        self.cleanup_filmstrip_next_frame_button = QToolButton()
        self.cleanup_filmstrip_next_frame_button.setText(">")
        self.cleanup_filmstrip_next_frame_button.setToolTip("Move frame review one frame right")
        self.cleanup_filmstrip_next_frame_button.setAutoRepeat(True)
        self.cleanup_filmstrip_next_frame_button.clicked.connect(
            lambda _checked=False: self.nudge_cleanup_filmstrip_frame(1)
        )
        self.cleanup_filmstrip_scroll = QSlider(Qt.Orientation.Horizontal)
        self.cleanup_filmstrip_scroll.setEnabled(False)
        self.cleanup_filmstrip_scroll.setTracking(True)
        self.cleanup_filmstrip_scroll.valueChanged.connect(self.cleanup_filmstrip_scroll_changed)
        self.cleanup_filmstrip_scroll.sliderMoved.connect(self.cleanup_filmstrip_slider_moved)
        self.cleanup_filmstrip_refresh_timer = QTimer(self)
        self.cleanup_filmstrip_refresh_timer.setSingleShot(True)
        self.cleanup_filmstrip_refresh_timer.timeout.connect(self.refresh_cleanup_filmstrip)
        timeline_row.addWidget(self.cleanup_filmstrip_timeline_label)
        timeline_row.addWidget(self.cleanup_filmstrip_prev_frame_button)
        timeline_row.addWidget(self.cleanup_filmstrip_next_frame_button)
        timeline_row.addWidget(self.cleanup_filmstrip_scroll, 1)
        frame_actions = QHBoxLayout()
        frame_actions.setContentsMargins(0, 0, 0, 0)
        self.cleanup_start_button = QPushButton("Detect black frames")
        self.cleanup_anomaly_start_button = QPushButton("Detect frame glitches")
        self.cleanup_mark_frame_button = QPushButton("Mark selected")
        self.cleanup_unmark_frame_button = QPushButton("Unmark selected")
        self.cleanup_clear_marks_button = QPushButton("Clear marks")
        self.cleanup_freeze_marked_button = QPushButton(VIDEO_CLEANUP_FREEZE_LABEL)
        self.cleanup_remove_marked_button = QPushButton(VIDEO_CLEANUP_REMOVE_LABEL)
        self.cleanup_start_button.clicked.connect(self.start_video_cleanup_from_page)
        self.cleanup_anomaly_start_button.clicked.connect(self.start_video_anomaly_detection_from_page)
        self.cleanup_mark_frame_button.clicked.connect(self.mark_selected_cleanup_filmstrip_frames)
        self.cleanup_unmark_frame_button.clicked.connect(self.unmark_selected_cleanup_filmstrip_frames)
        self.cleanup_clear_marks_button.clicked.connect(self.clear_cleanup_marked_frames)
        self.cleanup_freeze_marked_button.clicked.connect(
            lambda _checked=False: self.apply_video_cleanup_change(VIDEO_CLEANUP_METHOD_FREEZE)
        )
        self.cleanup_remove_marked_button.clicked.connect(
            lambda _checked=False: self.apply_video_cleanup_change(VIDEO_CLEANUP_METHOD_REMOVE)
        )
        frame_actions.addWidget(self.cleanup_start_button)
        frame_actions.addWidget(self.cleanup_anomaly_start_button)
        frame_actions.addWidget(QLabel("|"))
        frame_actions.addWidget(self.cleanup_mark_frame_button)
        frame_actions.addWidget(self.cleanup_unmark_frame_button)
        frame_actions.addWidget(self.cleanup_clear_marks_button)
        frame_actions.addStretch(1)
        frame_actions.addWidget(self.cleanup_freeze_marked_button)
        frame_actions.addWidget(self.cleanup_remove_marked_button)
        filmstrip_card.content_layout.addLayout(zoom_row)
        filmstrip_card.content_layout.addWidget(self.cleanup_filmstrip_list)
        filmstrip_card.content_layout.addLayout(timeline_row)
        filmstrip_card.content_layout.addLayout(frame_actions)
        layout.addWidget(filmstrip_card)

        results_grid = QGridLayout()
        results_grid.setSpacing(16)
        layout.addLayout(results_grid)

        results_card = Card("Black frames")
        self.cleanup_results = QListWidget()
        self.cleanup_results.setMinimumHeight(160)
        self.cleanup_results.itemDoubleClicked.connect(self.cleanup_result_item_double_clicked)
        self.cleanup_results.addItem(VIDEO_CLEANUP_BLACK_EMPTY_TEXT)
        results_card.content_layout.addWidget(self.cleanup_results)

        suspicious_card = Card("Suspicious frames")
        self.cleanup_suspicious_results = QListWidget()
        self.cleanup_suspicious_results.setMinimumHeight(160)
        self.cleanup_suspicious_results.itemDoubleClicked.connect(self.cleanup_suspicious_item_double_clicked)
        self.cleanup_suspicious_results.addItem(VIDEO_CLEANUP_SUSPICIOUS_EMPTY_TEXT)
        suspicious_card.content_layout.addWidget(self.cleanup_suspicious_results)

        results_grid.addWidget(results_card, 0, 0)
        results_grid.addWidget(suspicious_card, 0, 1)
        results_grid.setColumnStretch(0, 1)
        results_grid.setColumnStretch(1, 1)

        action_card = Card()
        action_card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        self.cleanup_repair_button = QPushButton("Clean video")
        self.cleanup_repair_button.setObjectName("PrimaryButton")
        self.cleanup_cancel_button = QPushButton("Cancel")
        self.cleanup_open_output_button = QPushButton("Open output")
        self.cleanup_open_folder_button = QPushButton("Open folder")
        self.cleanup_details_button = QPushButton("Show details")
        self.cleanup_repair_button.clicked.connect(self.start_video_cleanup_repair_from_page)
        self.cleanup_cancel_button.clicked.connect(self.cancel_video_cleanup_job)
        self.cleanup_open_output_button.clicked.connect(self.open_cleanup_output)
        self.cleanup_open_folder_button.clicked.connect(self.open_cleanup_output_folder)
        self.cleanup_details_button.clicked.connect(self.toggle_cleanup_details)
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

        self.refresh_video_cleanup_changes_list()
        self.update_video_cleanup_button_state()
        return page
