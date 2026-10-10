"""Полоса монтажа: ролик как блоки подряд, у каждого миниатюры и длительность.

Блоки идут один за другим со швами (зазор 2 px). Выбранный блок в акцентной рамке. Блок можно:
выбрать щелчком, перетащить на другое место (индикатор вставки, прокрутка у краёв), растянуть или
укоротить за край (в пределах исходного файла). Перемотка колёсиком времени вверху (линейка).
Статичный слой (блоки, миниатюры) рисуется один раз в готовый pixmap; при воспроизведении
перерисовывается только линия позиции.
"""

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, QSize, Qt, QTimer, Signal
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
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from chopchop.core.video import MIN_CLIP_SECONDS
from chopchop.ui.context_gate import menu_allowed
from chopchop.ui.theme import current, tokens

GAP = 2  # шов между блоками, px
SIDE = 8.0  # поле слева и справа
RULER_H = 18  # линейка со временем
EDGE_GRAB = 6.0  # зона захвата края блока, px
DRAG_THRESHOLD = 5.0  # со скольких px движения нажатие на блоке превращается в перенос
MIN_MARK_SECONDS = 0.04
ZOOM_STEP = 1.5
MAX_ZOOM = 64.0
LABEL_PAD = 4
KEY_TICK = 4
SCROLL_EDGE = 28.0  # у края окна при переносе включается прокрутка
SCROLL_SPEED = 0.03  # доля видимой ширины за один шаг прокрутки
TICK_STEPS = (0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1800, 3600)
MIN_TICK_PX = 56  # подписи на линейке не чаще


def format_precise(seconds: float) -> str:
    """1:05.3 — минуты, секунды и десятые."""
    seconds = max(seconds, 0.0)
    minutes, rest = divmod(seconds, 60)
    return f"{int(minutes)}:{rest:04.1f}"


def format_clock(seconds: float) -> str:
    total = max(int(seconds), 0)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02}:{secs:02}" if hours else f"{minutes}:{secs:02}"


def range_label(start: float, end: float) -> str:
    """«0:00.0 – 0:06.9 · 0:06.9»: границы фрагмента и его длина."""
    return f"{format_precise(start)} – {format_precise(end)} · {format_precise(end - start)}"


@dataclass(frozen=True)
class TimelineBlock:
    """Что нужно полосе знать о блоке: файл, границы в нём и привязка к ключевому кадру."""

    path: Path
    duration: float  # длина исходного файла
    start: float
    stop: float
    precise: bool = False  # начало не на ключевом кадре: быстрая резка сдвинет его
    shift: float = 0.0

    @property
    def length(self) -> float:
        return self.stop - self.start


class Timeline(QWidget):
    seekRequested = Signal(float)  # время итога; пока тянут линию позиции
    seekFinished = Signal(float)  # отпустили: точная перемотка
    blockSelected = Signal(int)
    selectionCleared = Signal()
    trimming = Signal(int, float, float)  # номер блока и его края, пока тянут
    trimCommitted = Signal(int, float, float)
    moveRequested = Signal(int, int)  # откуда и куда (индекс после удаления из старого места)
    zoomChanged = Signal(float)
    rangeMarked = Signal(float, float)  # Shift + протягивание: выделенный участок итога
    menuRequested = Signal(QPoint, object)  # точка на экране и (блок, время итога) или None

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._blocks: list[TimelineBlock] = []
        self._thumbs: dict[Path, list[QImage | None]] = {}
        self._selected: int | None = None
        self._position = 0.0
        self._view_start = 0.0
        self._view_span = 0.0  # 0 — вся длина
        self._hover_edge: tuple[int, str] | None = None
        self._hover_block: int | None = None
        # состояние перетаскивания: вид и данные
        self._press: tuple[str, int, float] | None = None  # вид, блок, x нажатия
        self._drag: str | None = None  # scrub, edge, move
        self._edge: tuple[int, str] | None = None
        self._marks: tuple[float, float] | None = None  # выделенный участок (время итога)
        self._mark_anchor = 0.0
        self._edge_scale = 0.0  # секунд на пиксель в момент нажатия на край
        self._was_fit = False
        self._edge_override: dict[int, tuple[float, float]] = {}  # живые края при растяжении
        self._move_x = 0.0
        self._drop_slot: int | None = None
        self._cache: QPixmap | None = None
        self._cache_key: tuple[object, ...] | None = None
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setInterval(16)
        self._scroll_timer.timeout.connect(self._auto_scroll)
        self.setMinimumHeight(tokens.TRIM_MIN_H)
        self.setMinimumWidth(240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setMouseTracking(True)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(480, tokens.TRIM_DEFAULT_H)

    # --- данные ------------------------------------------------------------------------------

    @property
    def blocks(self) -> list[TimelineBlock]:
        return list(self._blocks)

    @property
    def selected(self) -> int | None:
        return self._selected

    @property
    def duration(self) -> float:
        return sum(self._shown(i)[1] - self._shown(i)[0] for i in range(len(self._blocks)))

    def set_blocks(self, blocks: list[TimelineBlock], selected: int | None = None) -> None:
        if self._drag in ("edge", "move"):
            return  # во время перетаскивания раскладка не меняется
        keep_zoom = self.zoom_level > 1.0
        self._blocks = list(blocks)
        self._selected = (
            None if selected is None or not blocks else min(max(selected, 0), len(blocks) - 1)
        )
        self._edge_override.clear()
        self._invalidate()
        if not keep_zoom or self.duration <= 0:
            self._view_start, self._view_span = 0.0, 0.0
        else:
            self._view_span = min(self._view_span, self.duration)
            self._clamp_view()
        self.update()

    @property
    def marks(self) -> tuple[float, float] | None:
        return self._marks

    def set_marks(self, marks: tuple[float, float] | None) -> None:
        self._marks = marks
        self.update()

    def set_selected(self, index: int | None) -> None:
        if index != self._selected:
            self._selected = index
            self._invalidate()
            self.update()

    def set_thumbs(self, path: Path, thumbs: list[QImage | None]) -> None:
        self._thumbs[path] = thumbs
        self._invalidate()
        self.update()

    def set_thumbnail(self, path: Path, index: int, image: QImage) -> None:
        thumbs = self._thumbs.get(path)
        if thumbs is not None and 0 <= index < len(thumbs):
            thumbs[index] = image
            self._invalidate()
            self.update()

    def set_position(self, seconds: float) -> None:
        self._position = seconds
        if self.zoom_level > 1.0 and not self._visible(seconds) and self._drag is None:
            self._center_on(seconds)
            self._invalidate()
        self.update()

    def _shown(self, index: int) -> tuple[float, float]:
        """Края блока с учётом растяжения, которое ещё не зафиксировано."""
        block = self._blocks[index]
        return self._edge_override.get(index, (block.start, block.stop))

    def _offsets(self) -> list[float]:
        result, total = [], 0.0
        for i in range(len(self._blocks)):
            result.append(total)
            a, b = self._shown(i)
            total += b - a
        return result

    # --- масштаб по времени ------------------------------------------------------------------

    @property
    def zoom_level(self) -> float:
        total = self.duration
        if total <= 0 or self._view_span <= 0:
            return 1.0
        return total / self._view_span

    def _span(self) -> float:
        return self._view_span if self._view_span > 0 else self.duration

    def _visible(self, seconds: float) -> bool:
        return self._view_start <= seconds <= self._view_start + self._span()

    def _clamp_view(self) -> None:
        self._view_start = min(max(self._view_start, 0.0), max(self.duration - self._span(), 0.0))

    def _center_on(self, seconds: float) -> None:
        self._view_start = seconds - self._span() / 2
        self._clamp_view()

    def zoom_by(self, factor: float, anchor: float | None = None) -> None:
        total = self.duration
        if total <= 0:
            return
        level = min(max(self.zoom_level * factor, 1.0), MAX_ZOOM)
        focus = self._position if anchor is None else anchor
        old_span = self._span()
        share = (focus - self._view_start) / old_span if old_span > 0 else 0.5
        share = min(max(share, 0.0), 1.0)
        self._view_span = 0.0 if level <= 1.0 else total / level
        self._view_start = focus - share * self._span()
        self._clamp_view()
        self._invalidate()
        self.zoomChanged.emit(self.zoom_level)
        self.update()

    def zoom_in(self) -> None:
        self.zoom_by(ZOOM_STEP)

    def zoom_out(self) -> None:
        self.zoom_by(1 / ZOOM_STEP)

    def fit(self) -> None:
        self._view_start, self._view_span = 0.0, 0.0
        self._invalidate()
        self.zoomChanged.emit(1.0)
        self.update()

    # --- координаты --------------------------------------------------------------------------

    def _track(self) -> QRectF:
        top = RULER_H + 4
        return QRectF(SIDE, top, max(self.width() - 2 * SIDE, 1.0), self.height() - top - 6)

    def x_of(self, seconds: float) -> float:
        track = self._track()
        span = self._span()
        if span <= 0:
            return track.left()
        return track.left() + (seconds - self._view_start) / span * track.width()

    def time_at(self, x: float) -> float:
        track = self._track()
        fraction = (x - track.left()) / track.width()
        seconds = self._view_start + fraction * self._span()
        return min(max(seconds, 0.0), self.duration)

    def _seconds_per_pixel(self) -> float:
        return self._span() / self._track().width() if self._track().width() > 0 else 0.0

    def block_rect(self, index: int) -> QRectF:
        """Прямоугольник блока на экране без шва: между соседями остаётся зазор GAP."""
        track = self._track()
        offsets = self._offsets()
        a, b = self._shown(index)
        left = self.x_of(offsets[index])
        right = self.x_of(offsets[index] + (b - a))
        return QRectF(left + GAP / 2, track.top(), max(right - left - GAP, 1.0), track.height())

    def block_at(self, x: float) -> int | None:
        offsets = self._offsets()
        for index in range(len(self._blocks)):
            a, b = self._shown(index)
            if (
                self.x_of(offsets[index]) - GAP / 2
                <= x
                <= self.x_of(offsets[index] + b - a) + GAP / 2
            ):
                return index
        return None

    def _edge_at(self, x: float) -> tuple[int, str] | None:
        """Ближайший к указателю край блока: левый тянет начало, правый конец."""
        best: tuple[float, int, str] | None = None
        for index in range(len(self._blocks)):
            rect = self.block_rect(index)
            if rect.width() <= 2 * EDGE_GRAB:
                continue  # узкий блок: края не отдельные цели, иначе его не взять за середину
            for side, edge in (("start", rect.left()), ("end", rect.right())):
                distance = abs(x - edge)
                if distance <= EDGE_GRAB and (best is None or distance < best[0]):
                    best = (distance, index, side)
        return None if best is None else (best[1], best[2])

    # --- рисование ---------------------------------------------------------------------------

    def _invalidate(self) -> None:
        self._cache = None

    def invalidate(self) -> None:
        """Перерисовать с нуля (сменилась тема)."""
        self._cache = None
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        p = current.palette()
        ratio = self.devicePixelRatioF()
        key = (
            self.size(),
            ratio,
            self._view_start,
            self._view_span,
            self._selected,
            self._drag,
            tuple(self._edge_override.items()),
            self._drop_slot,
            tuple((b.path, b.start, b.stop, b.precise) for b in self._blocks),
            p.surface,
            p.accent,
        )
        if self._cache is None or self._cache_key != key:
            pixmap = QPixmap(int(self.width() * ratio), int(self.height() * ratio))
            pixmap.setDevicePixelRatio(ratio)
            pixmap.fill(QColor(p.surface))
            inner = QPainter(pixmap)
            self._paint_static(inner)
            inner.end()
            self._cache, self._cache_key = pixmap, key
        painter.drawPixmap(0, 0, self._cache)
        self._paint_dynamic(painter)

    def _paint_static(self, painter: QPainter) -> None:
        p = current.palette()
        self._paint_ruler(painter)
        track = self._track()
        painter.fillRect(track, QColor(p.border))
        painter.save()
        painter.setClipRect(track)
        for index in range(len(self._blocks)):
            self._paint_block(painter, index)
        painter.restore()
        if self._drag == "move" and self._drop_slot is not None:
            self._paint_insertion(painter)

    def _paint_ruler(self, painter: QPainter) -> None:
        p = current.palette()
        track = self._track()
        painter.fillRect(QRectF(0, 0, self.width(), RULER_H), QColor(p.surface_raised))
        span = self._span()
        if span <= 0 or track.width() <= 0:
            return
        per_second = track.width() / span
        step = next((s for s in TICK_STEPS if s * per_second >= MIN_TICK_PX), TICK_STEPS[-1])
        painter.setPen(QPen(QColor(p.text_muted), 1))
        metrics = QFontMetrics(painter.font())
        first = int(self._view_start // step)
        tick = first * step
        while tick <= self._view_start + span + step:
            x = self.x_of(tick)
            if track.left() - 1 <= x <= track.right() + 1:
                painter.drawLine(int(x), RULER_H - 6, int(x), RULER_H)
                painter.drawText(int(x) + 3, RULER_H - 6, format_clock(tick))
            tick += step
        _ = metrics

    def _paint_block(self, painter: QPainter, index: int) -> None:
        p = current.palette()
        block = self._blocks[index]
        rect = self.block_rect(index)
        if rect.right() < 0 or rect.left() > self.width():
            return
        start, stop = self._shown(index)
        painter.save()
        painter.setClipRect(rect)
        painter.fillRect(rect, QColor(p.surface_raised))
        self._paint_tiles(painter, block, rect, start, stop)
        dimmed = self._drag == "move" and self._press is not None and self._press[1] == index
        if dimmed:
            painter.fillRect(rect, QColor(*p.scrim))
        if index == self._selected:
            tint = QColor(p.accent)
            tint.setAlpha(46)
            painter.fillRect(rect, tint)
        painter.restore()
        self._paint_block_labels(painter, block, rect, start, stop)
        if index == self._selected:
            painter.setPen(QPen(QColor(p.accent), tokens.BORDER_WIDTH))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect.adjusted(1, 1, -1, -1))
        if block.precise:
            # начало не на ключевом кадре: заметный уголок на левом шве
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(p.danger))
            x, y = rect.left(), rect.top()
            painter.drawPolygon([QPointF(x, y), QPointF(x + 9, y), QPointF(x, y + 9)])

    def _paint_tiles(
        self, painter: QPainter, block: TimelineBlock, rect: QRectF, start: float, stop: float
    ) -> None:
        thumbs = self._thumbs.get(block.path) or []
        palette = current.palette()
        count = len(thumbs)
        tile_w = max(rect.height() * 16 / 9, 24.0)
        length = max(stop - start, 1e-6)
        x = rect.left()
        n = 0
        while x < rect.right():
            width = min(tile_w, rect.right() - x)
            slot = QRectF(x, rect.top(), width, rect.height())
            middle = start + (x + width / 2 - rect.left()) / rect.width() * length
            image = None
            if count and block.duration > 0:
                image = thumbs[min(int(middle / block.duration * count), count - 1)]
            if image is None or image.isNull():
                tone = palette.surface_raised if n % 2 == 0 else palette.border
                painter.fillRect(slot, QColor(tone))
            else:
                scale = max(tile_w / image.width(), slot.height() / image.height())
                source_w, source_h = tile_w / scale, slot.height() / scale
                source = QRectF(
                    (image.width() - source_w) / 2,
                    (image.height() - source_h) / 2,
                    source_w * width / tile_w,
                    source_h,
                )
                painter.drawImage(slot, image, source)
            x += tile_w
            n += 1

    def _paint_block_labels(
        self, painter: QPainter, block: TimelineBlock, rect: QRectF, start: float, stop: float
    ) -> None:
        """Длительность блока в углу; на узких блоках подписи нет."""
        metrics = QFontMetrics(painter.font())
        text = format_precise(stop - start)
        width = metrics.horizontalAdvance(text) + 2 * LABEL_PAD
        if rect.width() < width + 16:
            return
        box = QRectF(
            rect.left() + 3,
            rect.bottom() - metrics.height() - LABEL_PAD - 1,
            width,
            metrics.height() + LABEL_PAD - 1,
        )
        painter.fillRect(box, QColor(*current.palette().scrim))
        painter.setPen(QColor(*tokens.OVERLAY_LIGHT))
        painter.drawText(box, int(Qt.AlignmentFlag.AlignCenter), text)

    def _paint_insertion(self, painter: QPainter) -> None:
        """Индикатор вставки: линия на шве, куда встанет переносимый блок."""
        slot = self._drop_slot
        if slot is None:
            return
        offsets = self._offsets()
        seconds = self.duration if slot >= len(offsets) else offsets[slot]
        x = self.x_of(seconds)
        track = self._track()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(current.palette().accent))
        painter.drawRect(QRectF(x - 2, track.top() - 3, 4, track.height() + 6))

    def _paint_dynamic(self, painter: QPainter) -> None:
        p = current.palette()
        track = self._track()
        if self._visible(self._position) and self._blocks:
            head = int(self.x_of(self._position))
            painter.setPen(QPen(QColor(p.text), tokens.BORDER_WIDTH))
            painter.drawLine(head, 0, head, self.height())
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(p.text))
            painter.drawRect(QRectF(head - 4, 0, 8, 6))
        if self._marks is not None:
            tint = QColor(p.accent)
            tint.setAlpha(110)
            a, b = self._marks
            painter.fillRect(
                QRectF(self.x_of(a), track.top(), self.x_of(b) - self.x_of(a), track.height()), tint
            )
        if self._drag == "move" and self._press is not None:
            index = self._press[1]
            rect = self.block_rect(index)
            ghost = QRectF(
                self._move_x - rect.width() / 2, track.top(), rect.width(), track.height()
            )
            fill = QColor(p.accent)
            fill.setAlpha(120)
            painter.fillRect(ghost, fill)
            painter.setPen(QPen(QColor(p.accent), tokens.BORDER_WIDTH))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(ghost)
        elif self._hover_edge is not None or self._edge is not None:
            index, side = self._edge or self._hover_edge or (0, "start")
            rect = self.block_rect(index)
            x = rect.left() if side == "start" else rect.right()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(p.accent))
            painter.drawRect(QRectF(x - 2, track.top(), 4, track.height()))
            self._paint_edge_time(painter, index, side, rect)
        if self.hasFocus():
            painter.setPen(QPen(QColor(p.focus_ring), tokens.BORDER_WIDTH))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.rect().adjusted(1, 1, -1, -1))
        _ = QBrush

    def _paint_edge_time(self, painter: QPainter, index: int, side: str, rect: QRectF) -> None:
        """Время края блока в исходном файле рядом с ручкой."""
        start, stop = self._shown(index)
        text = format_precise(start if side == "start" else stop)
        metrics = QFontMetrics(painter.font())
        width = metrics.horizontalAdvance(text) + 2 * LABEL_PAD
        height = metrics.height() + LABEL_PAD
        anchor = rect.left() if side == "start" else rect.right()
        x = anchor + LABEL_PAD if side == "start" else anchor - width - LABEL_PAD
        x = min(max(x, 0.0), self.width() - width)
        box = QRectF(x, self._track().top() + LABEL_PAD, width, height)
        painter.fillRect(box, QColor(*current.palette().scrim))
        painter.setPen(QColor(*tokens.OVERLAY_LIGHT))
        painter.drawText(box, int(Qt.AlignmentFlag.AlignCenter), text)

    # --- мышь --------------------------------------------------------------------------------

    def _in_ruler(self, y: float) -> bool:
        return y < RULER_H + 2

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or not self._blocks:
            return
        x, y = event.position().x(), event.position().y()
        self._press = None
        if self._in_ruler(y):
            self._drag = "scrub"
            self._scrub(x)
            return
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier and self.block_at(x) is not None:
            self._drag = "mark"  # Shift + протягивание выделяет участок, который можно вырезать
            self._mark_anchor = self.time_at(x)
            self.set_marks(None)
            return
        if self._marks is not None:
            self.set_marks(None)
        edge = self._edge_at(x)
        if edge is not None:
            index, side = edge
            self._drag = "edge"
            self._edge = edge
            self._press = ("edge", index, x)
            # масштаб на время растяжения неподвижен: соседи сдвигаются, а не сжимаются
            self._edge_scale = self._seconds_per_pixel()
            self._was_fit = self._view_span <= 0
            if self._was_fit:
                self._view_span = self.duration
            self._edge_override[index] = self._shown(index)
            self._select(index)
            return
        hit = self.block_at(x)
        if hit is None:
            self._select(None)
            return
        self._press = ("body", hit, x)
        self._select(hit)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        x, y = event.position().x(), event.position().y()
        if self._drag == "scrub":
            self._scrub(x)
        elif self._drag == "mark":
            seconds = self.time_at(x)
            self.set_marks((min(self._mark_anchor, seconds), max(self._mark_anchor, seconds)))
        elif self._drag == "edge" and self._press is not None and self._edge is not None:
            self._drag_edge(x)
        elif self._press is not None and self._press[0] == "body":
            if self._drag == "move":
                self._move_to(x)
            elif abs(x - self._press[2]) >= DRAG_THRESHOLD:
                self._drag = "move"
                self._move_to(x)
                self._scroll_timer.start()
        else:
            self._hover(x, y)

    def _hover(self, x: float, y: float) -> None:
        edge = None if self._in_ruler(y) else self._edge_at(x)
        block = None if self._in_ruler(y) else self.block_at(x)
        if edge != self._hover_edge or block != self._hover_block:
            self._hover_edge, self._hover_block = edge, block
            self.update()
        if self._in_ruler(y):
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        elif edge is not None:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif block is not None:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.unsetCursor()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        drag, press = self._drag, self._press
        self._scroll_timer.stop()
        self._drag, self._press = None, None
        x = event.position().x()
        if drag == "mark":
            marks = self._marks
            if marks is not None and marks[1] - marks[0] >= MIN_MARK_SECONDS:
                self.rangeMarked.emit(*marks)
            else:
                self.set_marks(None)
        elif drag == "scrub":
            self.seekFinished.emit(self.time_at(x))
        elif drag == "edge" and self._edge is not None:
            index, _side = self._edge
            start, stop = self._shown(index)
            self._edge = None
            if self._was_fit:
                self._view_span = 0.0
                self._view_start = 0.0
            self.trimCommitted.emit(index, start, stop)
            # раскладка обновится по сигналу сессии; если правка не прошла, край вернётся
            self._edge_override.clear()
            self._invalidate()
        elif drag == "move" and press is not None:
            slot = self._drop_slot
            self._drop_slot = None
            index = press[1]
            if slot is not None:
                target = slot if slot < index else slot - 1
                if target != index:
                    self.moveRequested.emit(index, target)
            self._invalidate()
        elif press is not None and press[0] == "body":
            seconds = self.time_at(x)
            self.seekRequested.emit(seconds)
            self.seekFinished.emit(seconds)
        self.update()

    def _select(self, index: int | None) -> None:
        if index != self._selected:
            self._selected = index
            self._invalidate()
            if index is None:
                self.selectionCleared.emit()
            else:
                self.blockSelected.emit(index)
        self.update()

    def _scrub(self, x: float) -> None:
        seconds = self.time_at(x)
        self._position = seconds
        self.seekRequested.emit(seconds)
        self.update()

    def _drag_edge(self, x: float) -> None:
        """Тянем край: меняется исходное время блока; соседи сдвигаются вслед."""
        assert self._press is not None and self._edge is not None
        index, side = self._edge
        block = self._blocks[index]
        delta = (x - self._press[2]) * self._edge_scale
        start, stop = block.start, block.stop
        if side == "start":
            start = min(max(start + delta, 0.0), stop - MIN_CLIP_SECONDS)
        else:
            stop = max(min(stop + delta, block.duration), start + MIN_CLIP_SECONDS)
        self._edge_override[index] = (start, stop)
        self._invalidate()
        self.trimming.emit(index, start, stop)
        self.update()

    def _move_to(self, x: float) -> None:
        """Переносимый блок следует за указателем; слот вставки — ближайший шов."""
        self._move_x = x
        offsets = self._offsets()
        edges = [*offsets, self.duration]
        seconds = self.time_at(x)
        slot = min(range(len(edges)), key=lambda i: abs(edges[i] - seconds))
        index = self._press[1] if self._press is not None else -1
        if slot in (index, index + 1):
            slot_value: int | None = None  # на прежнее место: индикатор не показываем
        else:
            slot_value = slot
        if slot_value != self._drop_slot:
            self._drop_slot = slot_value
            self._invalidate()
        self.update()

    def _auto_scroll(self) -> None:
        """Прокрутка у краёв при переносе блока."""
        if self._drag != "move" or self.zoom_level <= 1.0:
            return
        step = self._span() * SCROLL_SPEED
        if self._move_x < SCROLL_EDGE:
            self._view_start -= step
        elif self._move_x > self.width() - SCROLL_EDGE:
            self._view_start += step
        else:
            return
        self._clamp_view()
        self._move_to(self._move_x)
        self._invalidate()
        self.update()

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802
        """ПКМ или клавиша Menu: блок под указателем выбирается, затем меню."""
        if not menu_allowed() or not self._blocks:
            return
        payload: tuple[int | None, float | None] | None = None
        if event.reason() != QContextMenuEvent.Reason.Keyboard:
            index = self.block_at(event.pos().x())
            if index is not None:
                self._select(index)
            payload = (index, self.time_at(event.pos().x()))
        self.menuRequested.emit(event.globalPos(), payload)

    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802
        self._hover_edge = None
        self._hover_block = None
        self.update()
        super().leaveEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        """Ctrl + колесо — масштаб под курсором, просто колесо — сдвиг при увеличении."""
        steps = event.angleDelta().y() / 120
        if steps == 0 or not self._blocks:
            return
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom_by(ZOOM_STEP**steps, self.time_at(event.position().x()))
        elif self.zoom_level > 1.0:
            self._view_start -= steps * self._span() * 0.1
            self._clamp_view()
            self._invalidate()
            self.update()
        event.accept()

    def resizeEvent(self, event: object) -> None:  # noqa: N802
        self._invalidate()
        super().resizeEvent(event)  # type: ignore[arg-type]
