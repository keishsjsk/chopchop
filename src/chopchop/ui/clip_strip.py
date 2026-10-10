"""Полоса клипов: чипы с названием и длительностью, перестановка перетаскиванием.

С одним клипом полоса компактная (одна строка высотой 40). Клипов больше — чипы переносятся на
следующие строки, полоса растёт до предела и прокручивается. При малой высоте окна остаётся одна
строка с горизонтальной прокруткой. Над выбранным чипом при наведении появляется мини-панель
(раньше, позже, удалить), то же есть в контекстном меню.
"""

from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QContextMenuEvent,
    QFontMetrics,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QResizeEvent,
)
from PySide6.QtWidgets import QFrame, QHBoxLayout, QMenu, QScrollArea, QWidget

from chopchop.ui import anim
from chopchop.ui.theme import current, tokens
from chopchop.ui.widgets import icon_button, refresh_icons

CHIP_H = tokens.CLIP_STRIP_H
CHIP_MIN_W = 14 * tokens.SPACE_2  # 112: чип не уже, даже у короткого имени
CHIP_MAX_W = 14 * tokens.SPACE_4  # 224: длинное имя сокращается в середине
GAP = tokens.SPACE_2
MINI_BUTTON = tokens.RAIL_BUTTON - tokens.SPACE_2  # 32: значок 32 px, как у рейки
DRAG_THRESHOLD = tokens.SPACE_2


@dataclass(frozen=True)
class ClipInfo:
    name: str
    duration: str  # уже оформленная длительность «0:06»
    tooltip: str = ""


class ClipChip(QWidget):
    """Один клип. Рисуется сам, чтобы совпадать по стилю с остальными панелями."""

    def __init__(self, index: int, info: ClipInfo, parent: QWidget) -> None:
        super().__init__(parent)
        self.index = index
        self.info = info
        self.selected = False
        self.dragging = False
        self.setFixedSize(self.fitted_width(), CHIP_H)
        self.setToolTip(info.tooltip)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def fitted_width(self) -> int:
        """Ширина по содержимому (номер, имя, длительность) в пределах минимума и максимума."""
        metrics = QFontMetrics(self.font())
        label = f"{self.index + 1}  {self.info.name}"
        wanted = (
            metrics.horizontalAdvance(label)
            + metrics.horizontalAdvance(self.info.duration)
            + 4 * tokens.SPACE_2
            + 2 * tokens.BORDER_WIDTH
        )
        return min(max(wanted, CHIP_MIN_W), CHIP_MAX_W)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        p = current.palette()
        hot = self.underMouse() and not self.selected
        border = p.accent if self.selected else (p.text if hot else p.border_strong)
        fill = p.surface_raised if self.selected or hot else p.surface
        painter.fillRect(self.rect(), QColor(border))
        inner = self.rect().adjusted(
            tokens.BORDER_WIDTH, tokens.BORDER_WIDTH, -tokens.BORDER_WIDTH, -tokens.BORDER_WIDTH
        )
        painter.fillRect(inner, QColor(fill))
        text_left = inner.left() + tokens.SPACE_2
        metrics = QFontMetrics(painter.font())
        duration_w = metrics.horizontalAdvance(self.info.duration)
        duration_rect = QRectF(
            inner.right() - duration_w - tokens.SPACE_2, inner.top(), duration_w, inner.height()
        )
        painter.setPen(QColor(p.text_muted))
        painter.drawText(duration_rect, int(Qt.AlignmentFlag.AlignVCenter), self.info.duration)
        label = f"{self.index + 1}  {self.info.name}"
        room = int(duration_rect.left() - text_left - tokens.SPACE_2)
        painter.setPen(QColor(p.text))
        painter.drawText(
            QRectF(text_left, inner.top(), room, inner.height()),
            int(Qt.AlignmentFlag.AlignVCenter),
            metrics.elidedText(label, Qt.TextElideMode.ElideMiddle, room),
        )
        if self.hasFocus():
            painter.setPen(QPen(QColor(p.focus_ring), tokens.BORDER_WIDTH))
            painter.drawRect(self.rect().adjusted(1, 1, -1, -1))


class MiniActions(QFrame):
    """Мини-панель над выбранным чипом: раньше, позже, удалить."""

    moveBy = Signal(int)
    removeRequested = Signal()
    pointerLeft = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._fader = anim.Fader(self)
        self.left = icon_button("chevron_left", self.tr("Сдвинуть клип раньше"))
        self.right = icon_button("chevron_right", self.tr("Сдвинуть клип позже"))
        self.remove = icon_button("trash", self.tr("Удалить клип"))
        for item in (self.left, self.right, self.remove):
            item.setFixedSize(MINI_BUTTON, MINI_BUTTON)
        self.left.clicked.connect(lambda: self.moveBy.emit(-1))
        self.right.clicked.connect(lambda: self.moveBy.emit(1))
        self.remove.clicked.connect(self.removeRequested)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        for item in (self.left, self.right, self.remove):
            row.addWidget(item)
        self.setFixedSize(3 * MINI_BUTTON, MINI_BUTTON)
        self.hide()

    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802
        self.pointerLeft.emit()
        super().leaveEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(current.palette().surface_raised))

    @property
    def opacity(self) -> float:
        return self._fader.opacity

    def appear(self) -> None:
        if self.isVisible() and self._fader.opacity >= 1.0:
            return
        if not self.isVisible():
            self._fader.fade_to(0.0, 0)
            self.show()
        self._fader.fade_to(1.0, tokens.PANEL_MS)

    def disappear(self) -> None:
        if self.isVisible():
            self._fader.fade_to(0.0, tokens.PANEL_MS, self.hide)


class ClipStrip(QScrollArea):
    currentChanged = Signal(int)
    moveRequested = Signal(int, int)  # откуда, куда
    removeRequested = Signal(int)
    addRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._holder = QWidget()
        self._chips: list[ClipChip] = []
        self._current = 0
        self._compact = False
        self._press: tuple[ClipChip, QPoint] | None = None
        self._drag_target = -1
        self.setWidget(self._holder)
        self.setWidgetResizable(False)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.viewport().setAutoFillBackground(False)
        self._holder.setAutoFillBackground(False)
        self.add_button = icon_button("add_clip", self.tr("Добавить клип…"), self.addRequested.emit)
        self.add_button.setParent(self._holder)
        self.add_button.setFixedSize(tokens.MIN_HIT, CHIP_H)
        self.mini = MiniActions(self._holder)
        self.mini.moveBy.connect(self._move_selected)
        self.mini.removeRequested.connect(lambda: self.removeRequested.emit(self._current))
        self.mini.pointerLeft.connect(self.mini.disappear)
        self.setFixedHeight(tokens.CLIP_STRIP_H)

    # --- данные ------------------------------------------------------------------------------

    def set_clips(self, infos: list[ClipInfo], current_index: int) -> None:
        for chip in self._chips:
            chip.removeEventFilter(self)
            chip.deleteLater()
        self._chips = []
        for index, info in enumerate(infos):
            chip = ClipChip(index, info, self._holder)
            chip.installEventFilter(self)
            chip.show()
            self._chips.append(chip)
        self._current = min(max(current_index, 0), max(len(infos) - 1, 0))
        self._mark_selected()
        self._relayout()

    def count(self) -> int:
        return len(self._chips)

    @property
    def current(self) -> int:
        return self._current

    def set_current(self, index: int) -> None:
        if 0 <= index < len(self._chips) and index != self._current:
            self._current = index
            self._mark_selected()

    def chips(self) -> list[ClipChip]:
        return list(self._chips)

    def set_compact(self, value: bool) -> None:
        """Малая высота окна: чипы в одну строку с горизонтальной прокруткой."""
        if value != self._compact:
            self._compact = value
            self._relayout()

    def _mark_selected(self) -> None:
        for chip in self._chips:
            chip.selected = chip.index == self._current
            chip.update()
        self.mini.disappear()

    def refresh_theme(self) -> None:
        refresh_icons(self)
        for chip in self._chips:
            chip.update()

    # --- раскладка ---------------------------------------------------------------------------

    def rows(self) -> int:
        if not self._chips:
            return 1
        return max(chip.y() for chip in self._chips) // (CHIP_H + GAP) + 1

    def _relayout(self) -> None:
        width = max(self.viewport().width(), CHIP_MAX_W + tokens.MIN_HIT)
        x = y = 0
        for chip in self._chips:
            if not self._compact and x > 0 and x + chip.width() > width:
                x, y = 0, y + CHIP_H + GAP
            chip.move(x, y)
            x += chip.width() + GAP
        if not self._compact and x + tokens.MIN_HIT > width and x > 0:
            x, y = 0, y + CHIP_H + GAP
        self.add_button.move(x, y)
        total_w = max(x + tokens.MIN_HIT, width) if self._compact else width
        total_h = y + CHIP_H
        self._holder.resize(total_w, total_h)
        wanted = min(max(total_h, tokens.CLIP_STRIP_H), tokens.CLIP_STRIP_MAX)
        scroll = self.horizontalScrollBar().sizeHint().height() if self._compact else 0
        height = wanted + (scroll if self._compact and len(self._chips) > 2 else 0)
        self.setFixedHeight(height)
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
            if not self._compact
            else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
            if self._compact
            else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._relayout()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, self.height())

    # --- мышь: выбор, перетаскивание, мини-панель --------------------------------------------

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if not isinstance(watched, ClipChip):
            return False
        kind = event.type()
        if kind == QEvent.Type.MouseButtonPress and isinstance(event, QMouseEvent):
            if event.button() == Qt.MouseButton.LeftButton:
                self._press = (watched, event.globalPosition().toPoint())
                self._select(watched.index)
        elif kind == QEvent.Type.MouseMove and isinstance(event, QMouseEvent):
            self._on_move(watched, event)
        elif kind == QEvent.Type.MouseButtonRelease:
            self._finish_drag(watched)
        elif kind == QEvent.Type.Enter and watched.selected and not self._press:
            self._show_mini(watched)
        elif kind == QEvent.Type.Leave and not self._mini_under_pointer():
            self.mini.disappear()
        elif kind == QEvent.Type.ContextMenu and isinstance(event, QContextMenuEvent):
            self._select(watched.index)
            self._menu(event.globalPos())
            return True
        return False

    def _select(self, index: int) -> None:
        if index != self._current:
            self._current = index
            self._mark_selected()
            self.currentChanged.emit(index)

    def _mini_under_pointer(self) -> bool:
        return self.mini.isVisible() and self.mini.underMouse()

    def _show_mini(self, chip: ClipChip) -> None:
        self.mini.setParent(self._holder)
        count = len(self._chips)
        self.mini.left.setEnabled(chip.index > 0)
        self.mini.right.setEnabled(chip.index < count - 1)
        self.mini.remove.setEnabled(count > 1)
        self.mini.move(
            chip.x() + chip.width() - self.mini.width() - tokens.BORDER_WIDTH, chip.y() + 4
        )
        self.mini.raise_()
        self.mini.appear()

    def _on_move(self, chip: ClipChip, event: QMouseEvent) -> None:
        if self._press is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        origin = self._press[1]
        here = event.globalPosition().toPoint()
        if not chip.dragging and (here - origin).manhattanLength() < DRAG_THRESHOLD:
            return
        chip.dragging = True
        self.mini.disappear()
        local = self._holder.mapFromGlobal(here)
        chip.move(local.x() - chip.width() // 2, local.y() - chip.height() // 2)
        chip.raise_()
        self._drag_target = self._slot_at(local)

    def _slot_at(self, point: QPoint) -> int:
        """Номер места под точкой: по ближайшему центру среди остальных чипов."""
        others = [c for c in self._chips if not c.dragging]
        best, best_distance = 0, 10**9
        for position in range(len(others) + 1):
            x, y = self._slot_position(position)
            half = others[min(position, len(others) - 1)].width() // 2 if others else 0
            distance = (point.x() - (x + half)) ** 2 + (point.y() - (y + CHIP_H // 2)) ** 2
            if distance < best_distance:
                best, best_distance = position, distance
        return min(best, len(self._chips) - 1)

    def _slot_position(self, position: int) -> tuple[int, int]:
        """Где окажется чип, вставленный на место position среди остальных."""
        width = max(self.viewport().width(), CHIP_MAX_W + tokens.MIN_HIT)
        others = [c for c in self._chips if not c.dragging]
        x = y = 0
        for index in range(position):
            x += others[index].width() + GAP
            following = others[index + 1].width() if index + 1 < len(others) else CHIP_MIN_W
            if not self._compact and x + following > width:
                x, y = 0, y + CHIP_H + GAP
        return x, y

    def _finish_drag(self, chip: ClipChip) -> None:
        self._press = None
        if not chip.dragging:
            return
        chip.dragging = False
        target = self._drag_target
        self._drag_target = -1
        if target >= 0 and target != chip.index:
            self.moveRequested.emit(chip.index, target)
        else:
            self._relayout()

    def _move_selected(self, delta: int) -> None:
        target = self._current + delta
        if 0 <= target < len(self._chips):
            self.moveRequested.emit(self._current, target)

    def _menu(self, global_pos: QPoint) -> None:
        menu = QMenu(self)
        count = len(self._chips)
        earlier = menu.addAction(self.tr("Сдвинуть раньше"))
        earlier.setEnabled(self._current > 0)
        earlier.triggered.connect(lambda: self._move_selected(-1))
        later = menu.addAction(self.tr("Сдвинуть позже"))
        later.setEnabled(self._current < count - 1)
        later.triggered.connect(lambda: self._move_selected(1))
        remove = menu.addAction(self.tr("Удалить клип"))
        remove.setEnabled(count > 1)
        remove.triggered.connect(lambda: self.removeRequested.emit(self._current))
        menu.addSeparator()
        menu.addAction(self.tr("Добавить клип…"), self.addRequested.emit)
        menu.exec(global_pos)
