"""Полоса обрезки: миниатюры кадров, две границы, позиция и масштаб по времени."""

from PySide6.QtCore import QEvent, QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QContextMenuEvent,
    QFontMetrics,
    QImage,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QWheelEvent,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from chopchop.core.video import MIN_CLIP_SECONDS, Range
from chopchop.ui.context_gate import menu_allowed
from chopchop.ui.theme import current, tokens

SIDE = 12.0  # поле слева и справа под ручки
HANDLE_GRAB = 9.0  # зона захвата ручки в пикселях
ZOOM_STEP = 1.5
MAX_ZOOM = 64.0
LABEL_PAD = 4
KEY_TICK = 4  # высота метки ключевого кадра
MIN_TICK_GAP = 6  # ключевые кадры чаще этого расстояния не рисуем
MIN_MARK_SECONDS = 0.04


def format_precise(seconds: float) -> str:
    """1:05.3 — минуты, секунды и десятые."""
    seconds = max(seconds, 0.0)
    minutes, rest = divmod(seconds, 60)
    return f"{int(minutes)}:{rest:04.1f}"


def range_label(start: float, end: float) -> str:
    """«0:00.0 – 0:06.9 · 0:06.9»: границы фрагмента и его длина."""
    return f"{format_precise(start)} – {format_precise(end)} · {format_precise(end - start)}"


class TrimBar(QWidget):
    seekRequested = Signal(float)
    trimming = Signal(float, float)  # во время перетаскивания границы
    trimCommitted = Signal(float, float)  # граница отпущена
    seekFinished = Signal(float)  # отпустили мышь: точная перемотка в последнюю позицию
    zoomChanged = Signal(float)
    ghostClicked = Signal(float, float)  # клик по удалённому участку: вернуть его
    segmentPicked = Signal(float, float)  # клик по сегменту: выбрать для удаления
    selectionCleared = Signal()  # клик мимо сегментов и выделения
    rangeMarked = Signal(float, float)  # Shift + протягивание: выделенный диапазон
    menuRequested = Signal(QPoint, object)  # точка на экране и секунда под ней (None — с клавиши)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._duration = 0.0
        self._start = 0.0
        self._end = 0.0
        self._position = 0.0
        self._view_start = 0.0
        self._view_span = 0.0  # 0 — вся длина
        self._thumbs: list[QImage | None] = []
        self._drag: str | None = None
        self._hover: str | None = None  # ручка под указателем: у неё показывается время
        self._ghosts: tuple[Range, ...] | None = None  # удалённые участки; None — только края
        self._splits: tuple[float, ...] = ()
        self._segments: tuple[Range, ...] | None = None
        self._segment: Range | None = None  # выбранный сегмент
        self._marks: Range | None = None  # выделенный диапазон (Shift + протягивание)
        self._keyframes: tuple[float, ...] = ()
        self._junctions: tuple[tuple[float, float, bool], ...] = ()
        self._press: tuple[str, float, float] | None = None  # вид нажатия и его данные
        self.setMinimumHeight(tokens.TRIM_MIN_H)
        self.setMinimumWidth(240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setMouseTracking(True)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(480, tokens.TRIM_DEFAULT_H)

    # --- данные ------------------------------------------------------------------------------

    @property
    def start(self) -> float:
        return self._start

    @property
    def end(self) -> float:
        return self._end

    def label_text(self) -> str:
        return range_label(self._start, self._end)

    def set_clip(
        self, duration: float, start: float, end: float, thumbs: list[QImage | None]
    ) -> None:
        self._duration = duration
        self._start, self._end = start, end
        self._thumbs = list(thumbs)
        self.fit()

    def set_range(self, start: float, end: float) -> None:
        if self._drag is None:
            self._start, self._end = start, end
            self.update()

    def set_cuts(
        self,
        ghosts: tuple[Range, ...],
        splits: tuple[float, ...],
        segments: tuple[Range, ...] | None = None,
    ) -> None:
        """Удалённые участки (призраки), метки разрезов и сегменты клипа."""
        self._ghosts = ghosts
        self._splits = splits
        self._segments = segments
        self.update()

    def set_segment(self, segment: Range | None) -> None:
        self._segment = segment
        self.update()

    def set_marks(self, marks: Range | None) -> None:
        self._marks = marks
        self.update()

    @property
    def marks(self) -> Range | None:
        return self._marks

    def set_keyframes(self, keyframes: tuple[float, ...]) -> None:
        self._keyframes = keyframes
        self.update()

    def set_junctions(self, junctions: tuple[tuple[float, float, bool], ...]) -> None:
        """Начала диапазонов: (где начало, к какому ключевому кадру привяжется, нужна ли точная)."""
        self._junctions = junctions
        self.update()

    def ghost_spans(self) -> tuple[Range, ...]:
        if self._ghosts is not None:
            return self._ghosts
        edges = [(0.0, self._start), (self._end, self._duration)]
        return tuple((a, b) for a, b in edges if b - a > 0.0005)

    def set_thumbnail(self, index: int, image: QImage) -> None:
        if 0 <= index < len(self._thumbs):
            self._thumbs[index] = image
            self.update()

    def set_position(self, seconds: float) -> None:
        self._position = seconds
        if self.zoom_level > 1.0 and not self._visible(seconds) and self._drag is None:
            self._center_on(seconds)
        self.update()

    # --- масштаб по времени ------------------------------------------------------------------

    @property
    def zoom_level(self) -> float:
        """Во сколько раз видимая часть короче всей длины (1 — видно всё)."""
        if self._duration <= 0 or self._view_span <= 0:
            return 1.0
        return self._duration / self._view_span

    def _span(self) -> float:
        return self._view_span if self._view_span > 0 else self._duration

    def _visible(self, seconds: float) -> bool:
        return self._view_start <= seconds <= self._view_start + self._span()

    def _clamp_view(self) -> None:
        span = self._span()
        self._view_start = min(max(self._view_start, 0.0), max(self._duration - span, 0.0))

    def _center_on(self, seconds: float) -> None:
        self._view_start = seconds - self._span() / 2
        self._clamp_view()

    def zoom_by(self, factor: float, anchor: float | None = None) -> None:
        """Приблизить (factor > 1) или отдалить полосу вокруг указанной секунды или позиции."""
        if self._duration <= 0:
            return
        level = min(max(self.zoom_level * factor, 1.0), MAX_ZOOM)
        focus = self._position if anchor is None else anchor
        old_span = self._span()
        share = (focus - self._view_start) / old_span if old_span > 0 else 0.5
        share = min(max(share, 0.0), 1.0)
        self._view_span = 0.0 if level <= 1.0 else self._duration / level
        self._view_start = focus - share * self._span()
        self._clamp_view()
        self.zoomChanged.emit(self.zoom_level)
        self.update()

    def zoom_in(self) -> None:
        self.zoom_by(ZOOM_STEP)

    def zoom_out(self) -> None:
        self.zoom_by(1 / ZOOM_STEP)

    def fit(self) -> None:
        """Вписать: снова видна вся длина клипа."""
        self._view_start, self._view_span = 0.0, 0.0
        self.zoomChanged.emit(1.0)
        self.update()

    # --- координаты --------------------------------------------------------------------------

    def _track(self) -> QRectF:
        return QRectF(SIDE, 6, max(self.width() - 2 * SIDE, 1.0), self.height() - 12)

    def _x(self, seconds: float) -> float:
        track = self._track()
        span = self._span()
        if span <= 0:
            return track.left()
        return track.left() + (seconds - self._view_start) / span * track.width()

    def _time_at(self, x: float) -> float:
        track = self._track()
        fraction = (x - track.left()) / track.width()
        seconds = self._view_start + fraction * self._span()
        return min(max(seconds, 0.0), self._duration)

    # --- рисование ---------------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        p = current.palette()
        painter.fillRect(self.rect(), QColor(p.surface))
        track = self._track()
        painter.fillRect(track, QColor(p.border))
        painter.save()
        painter.setClipRect(track)
        self._paint_thumbs(painter, track)
        painter.restore()

        left, right = self._x(self._start), self._x(self._end)
        painter.save()
        painter.setClipRect(track)
        self._paint_ghosts(painter, track)
        self._paint_marks(painter, track)
        self._paint_keyframes(painter, track)
        painter.restore()

        painter.setPen(QPen(QColor(p.accent), tokens.BORDER_WIDTH))
        painter.drawRect(QRectF(left, track.top(), right - left, track.height()))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(p.accent))
        painter.drawRect(QRectF(left - SIDE / 2, 2, SIDE / 2 + 2, self.height() - 4))
        painter.drawRect(QRectF(right - 2, 2, SIDE / 2 + 2, self.height() - 4))

        if self._visible(self._position):
            painter.setPen(QPen(QColor(p.text), tokens.BORDER_WIDTH))
            x = self._x(self._position)
            painter.drawLine(int(x), 0, int(x), self.height())
        self._paint_handle_time(painter, track)
        if self.hasFocus():
            painter.setPen(QPen(QColor(p.focus_ring), tokens.BORDER_WIDTH))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.rect().adjusted(1, 1, -1, -1))

    def _paint_thumbs(self, painter: QPainter, track: QRectF) -> None:
        count = len(self._thumbs)
        if count == 0 or self._duration <= 0:
            return
        palette = current.palette()
        for index, image in enumerate(self._thumbs):
            x0 = self._x(self._duration * index / count)
            x1 = self._x(self._duration * (index + 1) / count)
            if x1 < track.left() or x0 > track.right():
                continue
            if image is None or image.isNull():
                # заглушка кадра, пока миниатюра грузится: полоса не выглядит пустой
                tone = palette.surface_raised if index % 2 == 0 else palette.border
                painter.fillRect(
                    QRectF(x0, track.top(), max(x1 - x0, 1.0), track.height()), QColor(tone)
                )
                continue
            slot = QRectF(x0, track.top(), max(x1 - x0, 1.0), track.height())
            scale = max(slot.width() / image.width(), slot.height() / image.height())
            source_w, source_h = slot.width() / scale, slot.height() / scale
            source = QRectF(
                (image.width() - source_w) / 2, (image.height() - source_h) / 2, source_w, source_h
            )
            painter.drawImage(slot, image, source)

    def _paint_ghosts(self, painter: QPainter, track: QRectF) -> None:
        """Удалённые участки: затемнение со штриховкой, чтобы они читались как «призраки»."""
        p = current.palette()
        shade = QColor(*p.scrim)
        hatch = QBrush(QColor(p.text_muted), Qt.BrushStyle.BDiagPattern)
        for a, b in self.ghost_spans():
            box = QRectF(self._x(a), track.top(), self._x(b) - self._x(a), track.height())
            painter.fillRect(box, shade)
            painter.fillRect(box, hatch)
        painter.setPen(QPen(QColor(p.text), tokens.BORDER_WIDTH))
        for s in self._splits:  # метки разрезов
            x = self._x(s)
            painter.drawLine(int(x), int(track.top()), int(x), int(track.bottom()))
        if self._segment is not None:  # выбранный сегмент
            a, b = self._segment
            painter.setPen(QPen(QColor(p.accent), tokens.BORDER_WIDTH))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(
                QRectF(self._x(a), track.top() + 1, self._x(b) - self._x(a), track.height() - 2)
            )

    def _paint_marks(self, painter: QPainter, track: QRectF) -> None:
        if self._marks is None:
            return
        a, b = self._marks
        tint = QColor(current.palette().accent)
        tint.setAlpha(110)
        painter.fillRect(
            QRectF(self._x(a), track.top(), self._x(b) - self._x(a), track.height()), tint
        )

    def _paint_keyframes(self, painter: QPainter, track: QRectF) -> None:
        """Ключевые кадры: короткие метки внизу; места привязки быстрой резки — крупнее."""
        p = current.palette()
        painter.setPen(QPen(QColor(p.text_muted), 1))
        last = float(-MIN_TICK_GAP)
        for seconds in self._keyframes:
            x = self._x(seconds)
            if x < track.left() or x > track.right() or x - last < MIN_TICK_GAP:
                continue
            last = x
            painter.drawLine(int(x), int(track.bottom()) - KEY_TICK, int(x), int(track.bottom()))
        for start, snapped, precise in self._junctions:
            color = QColor(p.danger if precise else p.accent)
            painter.setPen(QPen(color, tokens.BORDER_WIDTH))
            x0, x1 = self._x(snapped), self._x(start)
            bottom = int(track.bottom())
            painter.drawLine(int(x0), bottom - 2 * KEY_TICK, int(x0), bottom)
            if precise:  # привязка сдвигает начало: показываем на сколько
                painter.drawLine(int(x0), bottom - 1, int(x1), bottom - 1)

    def _paint_handle_time(self, painter: QPainter, track: QRectF) -> None:
        """Время границы рядом с ручкой, только пока на неё наведён указатель (или её тянут)."""
        handle = self._drag if self._drag in ("start", "end") else self._hover
        if handle is None or self._duration <= 0:
            return
        seconds = self._start if handle == "start" else self._end
        metrics = QFontMetrics(painter.font())
        text = format_precise(seconds)
        width = metrics.horizontalAdvance(text) + 2 * LABEL_PAD
        box_height = metrics.height() + LABEL_PAD
        anchor = self._x(seconds)
        # у левой ручки плашка справа от неё, у правой — слева, чтобы не выходить за край
        x = anchor + SIDE / 2 + LABEL_PAD if handle == "start" else anchor - width - LABEL_PAD
        x = min(max(x, track.left()), track.right() - width)
        box = QRectF(x, track.top() + LABEL_PAD, width, box_height)
        painter.fillRect(box, QColor(*current.palette().scrim))
        painter.setPen(QColor(*tokens.OVERLAY_LIGHT))
        painter.drawText(box, int(Qt.AlignmentFlag.AlignCenter), text)

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
        x = event.position().x()
        handle = self._handle_at(x)
        self._press = None
        if handle is None and event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self._drag = "mark"
            anchor = self._time_at(x)
            self._press = ("mark", anchor, anchor)
            self.set_marks(None)
            return
        seconds = self._time_at(x)
        if handle is None:
            ghost = next((g for g in self.ghost_spans() if g[0] <= seconds <= g[1]), None)
            if ghost is not None:
                self._drag = "ghost"
                self._press = ("ghost", ghost[0], ghost[1])
                return
        self._drag = handle or "seek"
        if self._drag == "seek":
            self._pick_segment(seconds)
        self._drag_to(x)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        x = event.position().x()
        if self._drag is None:
            handle = self._handle_at(x)
            if handle != self._hover:
                self._hover = handle
                self.update()
            seconds = self._time_at(x)
            on_ghost = handle is None and any(a <= seconds <= b for a, b in self.ghost_spans())
            self.setToolTip(self.tr("Нажмите, чтобы вернуть удалённый участок") if on_ghost else "")
            self.setCursor(
                Qt.CursorShape.SizeHorCursor if handle else Qt.CursorShape.PointingHandCursor
            )
            return
        self._drag_to(x)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        drag, self._drag = self._drag, None
        if drag in ("start", "end"):
            self.trimCommitted.emit(self._start, self._end)
            self.seekFinished.emit(self._start if drag == "start" else self._end)
        elif drag == "seek":
            self.seekFinished.emit(self._time_at(event.position().x()))
        elif drag == "ghost" and self._press is not None:
            _kind, a, b = self._press
            if a <= self._time_at(event.position().x()) <= b:
                self.ghostClicked.emit(a, b)
        elif drag == "mark" and self._press is not None:
            _kind, a, b = self._press
            low, high = min(a, b), max(a, b)
            if high - low >= MIN_MARK_SECONDS:
                self.set_marks((low, high))
                self.rangeMarked.emit(low, high)
            else:
                self.set_marks(None)
        self._press = None

    def _pick_segment(self, seconds: float) -> None:
        """Клик по оставленному: этот сегмент выбран; мимо сегментов — выбор снят."""
        self.set_marks(None)
        if self._segments is not None:
            hit = next((s for s in self._segments if s[0] <= seconds < s[1]), None)
            if hit is not None:
                self.set_segment(hit)
                self.segmentPicked.emit(*hit)
                return
        self.set_segment(None)
        self.selectionCleared.emit()

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802
        """ПКМ или клавиша Menu: сегмент под указателем выбирается, затем меню."""
        if not menu_allowed() or self._duration <= 0:
            return
        seconds: float | None = None
        if event.reason() != QContextMenuEvent.Reason.Keyboard:
            seconds = self._time_at(event.pos().x())
            if not any(a <= seconds <= b for a, b in self.ghost_spans()):
                self._pick_segment(seconds)
        self.menuRequested.emit(event.globalPos(), seconds)

    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802
        self._hover = None
        self.update()
        super().leaveEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        """Ctrl + колесо — масштаб под курсором, просто колесо — сдвиг при увеличении."""
        steps = event.angleDelta().y() / 120
        if steps == 0 or self._duration <= 0:
            return
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom_by(ZOOM_STEP**steps, self._time_at(event.position().x()))
        elif self.zoom_level > 1.0:
            self._view_start -= steps * self._span() * 0.1
            self._clamp_view()
            self.update()
        event.accept()

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
        elif self._drag == "mark" and self._press is not None:
            _kind, anchor, _last = self._press
            self._press = ("mark", anchor, seconds)
            self.set_marks((min(anchor, seconds), max(anchor, seconds)))
        self.update()
