from collections.abc import Sequence

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class AudioWaveformWidget(QWidget):
    selectionChanged = Signal(float, float)
    viewChanged = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._peaks: list[float] = []
        self._duration = 0.0
        self._start = 0.0
        self._end = 0.0
        self._playhead: float | None = None
        self._zoom_factor = 1.0
        self._view_start = 0.0
        self._drag_mode: str | None = None
        self._drag_anchor = 0.0
        self.setMinimumHeight(170)
        self.setMouseTracking(True)
        self.setEnabled(False)

    def clear_waveform(self) -> None:
        self._peaks = []
        self._duration = 0.0
        self._start = 0.0
        self._end = 0.0
        self._playhead = None
        self._zoom_factor = 1.0
        self._view_start = 0.0
        self.setEnabled(False)
        self.update()
        self.viewChanged.emit(0.0, 0.0)

    def set_waveform(self, peaks: Sequence[float], duration_seconds: float) -> None:
        self._peaks = [min(1.0, max(0.0, float(peak))) for peak in peaks]
        self._duration = max(0.0, float(duration_seconds))
        self._view_start = 0.0
        self.setEnabled(bool(self._peaks and self._duration > 0))
        self.set_selection(self._start, self._end)
        self._emit_view_changed()
        self.update()

    def has_waveform(self) -> bool:
        return bool(self._peaks and self._duration > 0)

    def set_zoom_factor(self, zoom_factor: float) -> None:
        if self._duration <= 0:
            return
        old_start, old_end = self._visible_window()
        old_center = old_start + ((old_end - old_start) / 2)
        self._zoom_factor = min(32.0, max(1.0, float(zoom_factor)))
        visible_duration = self._visible_duration()
        self._view_start = self._clamped_view_start(old_center - (visible_duration / 2))
        self._emit_view_changed()
        self.update()

    def zoom_factor(self) -> float:
        return self._zoom_factor

    def set_view_position_ratio(self, ratio: float) -> None:
        if self._duration <= 0:
            return
        max_start = max(0.0, self._duration - self._visible_duration())
        self._view_start = min(max_start, max(0.0, float(ratio)) * max_start)
        self._emit_view_changed()
        self.update()

    def center_on(self, seconds: float) -> None:
        if self._duration <= 0:
            return
        visible_duration = self._visible_duration()
        self._view_start = self._clamped_view_start(float(seconds) - (visible_duration / 2))
        self._emit_view_changed()
        self.update()

    def view_position_ratio(self) -> float:
        max_start = max(0.0, self._duration - self._visible_duration())
        if max_start <= 0:
            return 0.0
        return self._view_start / max_start

    def visible_window(self) -> tuple[float, float]:
        return self._visible_window()

    def set_selection(self, start_seconds: float, end_seconds: float, emit: bool = False) -> None:
        if self._duration <= 0:
            self._start = 0.0
            self._end = 0.0
        else:
            start = min(self._duration, max(0.0, float(start_seconds)))
            end = min(self._duration, max(0.0, float(end_seconds)))
            if end < start:
                start, end = end, start
            self._start = start
            self._end = end
        self.update()
        if emit:
            self.selectionChanged.emit(self._start, self._end)

    def set_playhead(self, seconds: float | None) -> None:
        if seconds is None or self._duration <= 0:
            self._playhead = None
        else:
            self._playhead = min(self._duration, max(0.0, float(seconds)))
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        plot_rect = self._plot_rect()
        painter.fillRect(self.rect(), QColor("#f8fafc"))
        painter.setPen(QPen(QColor("#cfd6e2"), 1))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)

        center_y = plot_rect.center().y()
        painter.setPen(QPen(QColor("#d8dee8"), 1))
        painter.drawLine(plot_rect.left(), center_y, plot_rect.right(), center_y)

        if not self._peaks:
            return

        peaks = self._peaks_for_width(max(1, int(plot_rect.width())))
        painter.setPen(QPen(QColor("#365a7c"), 1.4))
        for index, peak in enumerate(peaks):
            x = plot_rect.left() + index + 0.5
            half_height = max(1.0, peak * plot_rect.height() * 0.46)
            painter.drawLine(QPointF(x, center_y - half_height), QPointF(x, center_y + half_height))

        if self._duration > 0 and self._end > self._start:
            visible_start, visible_end = self._visible_window()
            clipped_start = max(self._start, visible_start)
            clipped_end = min(self._end, visible_end)
            if clipped_end > clipped_start:
                start_x = self._x_for_seconds(clipped_start, plot_rect)
                end_x = self._x_for_seconds(clipped_end, plot_rect)
                selection_rect = QRectF(start_x, plot_rect.top(), max(1.0, end_x - start_x), plot_rect.height())
                painter.fillRect(selection_rect, QColor(245, 158, 11, 70))
            painter.setPen(QPen(QColor("#b45309"), 2.4))
            if visible_start <= self._start <= visible_end:
                start_x = self._x_for_seconds(self._start, plot_rect)
                painter.drawLine(QPointF(start_x, plot_rect.top()), QPointF(start_x, plot_rect.bottom()))
            if visible_start <= self._end <= visible_end:
                end_x = self._x_for_seconds(self._end, plot_rect)
                painter.drawLine(QPointF(end_x, plot_rect.top()), QPointF(end_x, plot_rect.bottom()))

        if self._playhead is not None and self._duration > 0:
            visible_start, visible_end = self._visible_window()
            if visible_start <= self._playhead <= visible_end:
                playhead_x = self._x_for_seconds(self._playhead, plot_rect)
                painter.setPen(QPen(QColor("#dc2626"), 2.2))
                painter.drawLine(QPointF(playhead_x, plot_rect.top()), QPointF(playhead_x, plot_rect.bottom()))

    def mousePressEvent(self, event) -> None:
        if not self.isEnabled() or self._duration <= 0:
            return
        seconds = self._seconds_for_x(event.position().x())
        if self._near_handle(event.position().x(), self._start):
            self._drag_mode = "start"
        elif self._near_handle(event.position().x(), self._end):
            self._drag_mode = "end"
        else:
            self._drag_mode = "range"
            self._drag_anchor = seconds
            self.set_selection(seconds, seconds, emit=True)
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if not self.isEnabled() or self._duration <= 0:
            return
        if not self._drag_mode:
            cursor = Qt.CursorShape.ArrowCursor
            if self._near_handle(event.position().x(), self._start) or self._near_handle(
                event.position().x(),
                self._end,
            ):
                cursor = Qt.CursorShape.SizeHorCursor
            self.setCursor(cursor)
            return

        seconds = self._seconds_for_x(event.position().x())
        if self._drag_mode == "start":
            self.set_selection(seconds, self._end, emit=True)
        elif self._drag_mode == "end":
            self.set_selection(self._start, seconds, emit=True)
        else:
            self.set_selection(self._drag_anchor, seconds, emit=True)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._drag_mode = None
        event.accept()

    def leaveEvent(self, _event) -> None:
        if not self._drag_mode:
            self.unsetCursor()

    def _plot_rect(self) -> QRectF:
        return QRectF(self.rect()).adjusted(14, 14, -14, -14)

    def _peaks_for_width(self, width: int) -> list[float]:
        width = max(1, int(width))
        peaks = []
        source_count = len(self._peaks)
        visible_start, visible_end = self._visible_window()
        source_start = int((visible_start / max(self._duration, 0.001)) * source_count)
        source_end = int((visible_end / max(self._duration, 0.001)) * source_count)
        source_start = min(source_count - 1, max(0, source_start))
        source_end = min(source_count, max(source_start + 1, source_end))
        visible_peaks = self._peaks[source_start:source_end]
        source_count = len(visible_peaks)
        for index in range(width):
            start = int((index * source_count) / width)
            end = int(((index + 1) * source_count) / width)
            if end <= start:
                end = min(source_count, start + 1)
            peaks.append(max(visible_peaks[start:end]))
        return peaks

    def _x_for_seconds(self, seconds: float, plot_rect: QRectF | None = None) -> float:
        rect = plot_rect or self._plot_rect()
        if self._duration <= 0:
            return rect.left()
        visible_start, visible_end = self._visible_window()
        visible_duration = max(0.001, visible_end - visible_start)
        return rect.left() + ((seconds - visible_start) / visible_duration) * rect.width()

    def _seconds_for_x(self, x: float) -> float:
        rect = self._plot_rect()
        if rect.width() <= 0 or self._duration <= 0:
            return 0.0
        ratio = (x - rect.left()) / rect.width()
        visible_start, visible_end = self._visible_window()
        visible_duration = visible_end - visible_start
        return min(visible_end, max(visible_start, visible_start + (ratio * visible_duration)))

    def _near_handle(self, x: float, seconds: float) -> bool:
        if self._duration <= 0:
            return False
        visible_start, visible_end = self._visible_window()
        if not visible_start <= seconds <= visible_end:
            return False
        return abs(x - self._x_for_seconds(seconds)) <= 8

    def _visible_duration(self) -> float:
        if self._duration <= 0:
            return 0.0
        return self._duration / max(1.0, self._zoom_factor)

    def _visible_window(self) -> tuple[float, float]:
        if self._duration <= 0:
            return 0.0, 0.0
        visible_duration = self._visible_duration()
        start = self._clamped_view_start(self._view_start)
        end = min(self._duration, start + visible_duration)
        return start, end

    def _clamped_view_start(self, view_start: float) -> float:
        max_start = max(0.0, self._duration - self._visible_duration())
        return min(max_start, max(0.0, float(view_start)))

    def _emit_view_changed(self) -> None:
        self._view_start = self._clamped_view_start(self._view_start)
        self.viewChanged.emit(*self._visible_window())
