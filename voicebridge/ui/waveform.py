from collections.abc import Sequence

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class AudioWaveformWidget(QWidget):
    selectionChanged = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._peaks: list[float] = []
        self._duration = 0.0
        self._start = 0.0
        self._end = 0.0
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
        self.setEnabled(False)
        self.update()

    def set_waveform(self, peaks: Sequence[float], duration_seconds: float) -> None:
        self._peaks = [min(1.0, max(0.0, float(peak))) for peak in peaks]
        self._duration = max(0.0, float(duration_seconds))
        self.setEnabled(bool(self._peaks and self._duration > 0))
        self.set_selection(self._start, self._end)
        self.update()

    def has_waveform(self) -> bool:
        return bool(self._peaks and self._duration > 0)

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

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        plot_rect = self._plot_rect()
        painter.fillRect(self.rect(), QColor("#f7f3e8"))
        painter.setPen(QPen(QColor("#d8cdb5"), 1))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)

        center_y = plot_rect.center().y()
        painter.setPen(QPen(QColor("#d8cdb5"), 1))
        painter.drawLine(plot_rect.left(), center_y, plot_rect.right(), center_y)

        if not self._peaks:
            return

        peaks = self._peaks_for_width(max(1, int(plot_rect.width())))
        painter.setPen(QPen(QColor("#2f6fed"), 1.4))
        for index, peak in enumerate(peaks):
            x = plot_rect.left() + index + 0.5
            half_height = max(1.0, peak * plot_rect.height() * 0.46)
            painter.drawLine(QPointF(x, center_y - half_height), QPointF(x, center_y + half_height))

        if self._duration > 0 and self._end > self._start:
            start_x = self._x_for_seconds(self._start, plot_rect)
            end_x = self._x_for_seconds(self._end, plot_rect)
            selection_rect = QRectF(start_x, plot_rect.top(), max(1.0, end_x - start_x), plot_rect.height())
            painter.fillRect(selection_rect, QColor(47, 111, 237, 44))
            painter.setPen(QPen(QColor("#1d4ed8"), 2))
            painter.drawLine(QPointF(start_x, plot_rect.top()), QPointF(start_x, plot_rect.bottom()))
            painter.drawLine(QPointF(end_x, plot_rect.top()), QPointF(end_x, plot_rect.bottom()))

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
        for index in range(width):
            start = int((index * source_count) / width)
            end = int(((index + 1) * source_count) / width)
            if end <= start:
                end = min(source_count, start + 1)
            peaks.append(max(self._peaks[start:end]))
        return peaks

    def _x_for_seconds(self, seconds: float, plot_rect: QRectF | None = None) -> float:
        rect = plot_rect or self._plot_rect()
        if self._duration <= 0:
            return rect.left()
        return rect.left() + (min(self._duration, max(0.0, seconds)) / self._duration) * rect.width()

    def _seconds_for_x(self, x: float) -> float:
        rect = self._plot_rect()
        if rect.width() <= 0 or self._duration <= 0:
            return 0.0
        ratio = (x - rect.left()) / rect.width()
        return min(self._duration, max(0.0, ratio * self._duration))

    def _near_handle(self, x: float, seconds: float) -> bool:
        if self._duration <= 0:
            return False
        return abs(x - self._x_for_seconds(seconds)) <= 8
