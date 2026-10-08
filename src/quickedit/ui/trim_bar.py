"""Полоса обрезки: миниатюры кадров, две границы и текущая позиция."""

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from quickedit.core.video import MIN_CLIP_SECONDS

SIDE = 12.0  # поле слева и справа под ручки
HANDLE_GRAB = 9.0  # зона захвата ручки в пикселях
HEIGHT = 64


def format_precise(seconds: float) -> str:
    """1:05.3 — минуты, секунды и десятые."""
    seconds = max(seconds, 0.0)
    minutes, rest = divmod(seconds, 60)
    return f"{int(minutes)}:{rest:04.1f}"


class TrimBar(QWidget):
    seekRequested = Signal(float)
    trimming = Signal(float, float)  # во время перетаскивания границы
    trimCommitted = Signal(float, float)  # граница отпущена

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._duration = 0.0
        self._start = 0.0
        self._end = 0.0
        self._position = 0.0
        self._thumbs: list[QImage | None] = []
        self._drag: str | None = None
        self.setFixedHeight(HEIGHT)
        self.setMinimumWidth(240)
        self.setMouseTracking(True)

    # --- данные ------------------------------------------------------------------------------

    @property
    def start(self) -> float:
        return self._start

    @property
    def end(self) -> float:
        return self._end

    def set_clip(
        self, duration: float, start: float, end: float, thumbs: list[QImage | None]
    ) -> None:
        self._duration = duration
        self._start, self._end = start, end
        self._thumbs = list(thumbs)
        self.update()

    def set_range(self, start: float, end: float) -> None:
        if self._drag is None:
            self._start, self._end = start, end
            self.update()

    def set_thumbnail(self, index: int, image: QImage) -> None:
        if 0 <= index < len(self._thumbs):
            self._thumbs[index] = image
            self.update()

    def set_position(self, seconds: float) -> None:
        self._position = seconds
        self.update()

    # --- координаты --------------------------------------------------------------------------

    def _track(self) -> QRectF:
        return QRectF(SIDE, 6, max(self.width() - 2 * SIDE, 1.0), self.height() - 12)

    def _x(self, seconds: float) -> float:
        track = self._track()
        if self._duration <= 0:
            return track.left()
        return track.left() + seconds / self._duration * track.width()

    def _time_at(self, x: float) -> float:
        track = self._track()
        fraction = (x - track.left()) / track.width()
        return min(max(fraction, 0.0), 1.0) * self._duration

    # --- рисование ---------------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(28, 28, 28))
        track = self._track()
        painter.fillRect(track, QColor(60, 60, 60))
        count = len(self._thumbs)
        for index, image in enumerate(self._thumbs):
            if image is None or image.isNull():
                continue
            slot = QRectF(
                track.left() + track.width() * index / count,
                track.top(),
                track.width() / count,
                track.height(),
            )
            scale = max(slot.width() / image.width(), slot.height() / image.height())
            source_w, source_h = slot.width() / scale, slot.height() / scale
            source = QRectF(
                (image.width() - source_w) / 2, (image.height() - source_h) / 2, source_w, source_h
            )
            painter.drawImage(slot, image, source)

        left, right = self._x(self._start), self._x(self._end)
        shade = QColor(0, 0, 0, 170)
        top, height = track.top(), track.height()
        painter.fillRect(QRectF(track.left(), top, left - track.left(), height), shade)
        painter.fillRect(QRectF(right, top, track.right() - right, height), shade)

        painter.setPen(QPen(QColor(255, 200, 0), 2))
        painter.drawRect(QRectF(left, track.top(), right - left, track.height()))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 200, 0))
        painter.drawRect(QRectF(left - SIDE / 2, 2, SIDE / 2 + 2, self.height() - 4))
        painter.drawRect(QRectF(right - 2, 2, SIDE / 2 + 2, self.height() - 4))

        painter.setPen(QPen(QColor("white"), 2))
        x = self._x(self._position)
        painter.drawLine(int(x), 0, int(x), self.height())

    # --- мышь --------------------------------------------------------------------------------

    def _handle_at(self, x: float) -> str | None:
        if abs(x - self._x(self._start)) <= HANDLE_GRAB:
            return "start"
        if abs(x - self._x(self._end)) <= HANDLE_GRAB:
            return "end"
        return None

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self._duration <= 0:
            return
        self._drag = self._handle_at(event.position().x()) or "seek"
        self._drag_to(event.position().x())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        x = event.position().x()
        if self._drag is None:
            handle = self._handle_at(x)
            self.setCursor(
                Qt.CursorShape.SizeHorCursor if handle else Qt.CursorShape.PointingHandCursor
            )
            return
        self._drag_to(x)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag in ("start", "end"):
            self.trimCommitted.emit(self._start, self._end)
        self._drag = None

    def _drag_to(self, x: float) -> None:
        seconds = self._time_at(x)
        if self._drag == "start":
            self._start = min(seconds, self._end - MIN_CLIP_SECONDS)
            self.trimming.emit(self._start, self._end)
            self.seekRequested.emit(self._start)
        elif self._drag == "end":
            self._end = max(seconds, self._start + MIN_CLIP_SECONDS)
            self.trimming.emit(self._start, self._end)
            self.seekRequested.emit(self._end)
        elif self._drag == "seek":
            self.seekRequested.emit(seconds)
        self.update()
