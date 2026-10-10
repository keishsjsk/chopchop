"""Общая оболочка редакторов: верхняя панель, рейка инструментов, контекстная панель, статус.

Оболочка не знает ни про фото, ни про видео: страница редактора кладёт своё содержимое в
`set_content` и наполняет рейку, контекстные панели и строку состояния. Видеоредактор уже
собран на ней, фото-редактор может перейти позже без изменений оболочки.

    ┌──────────────────────────────────────────────┐ 48  верхняя панель
    ├────┬─────────────────────────────────────────┤ 48  контекстная панель (по инструменту)
    │ 56 │             содержимое                  │
    ├────┴─────────────────────────────────────────┤ 24  строка состояния
"""

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QContextMenuEvent, QPainter, QPaintEvent, QResizeEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from chopchop.ui import anim
from chopchop.ui.context_gate import menu_allowed
from chopchop.ui.export_strip import ExportStrip
from chopchop.ui.theme import current, tokens
from chopchop.ui.widgets import refresh_icons, set_icon, tip

FLASH_MS = 6000
MARK = 6  # размер точки-метки «у инструмента есть применённый эффект»


class RailButton(QToolButton):
    """Кнопка рейки 40×40; точка в углу показывает, что у инструмента есть эффект."""

    contextRequested = Signal(str, QPoint)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = ""
        self._marked = False
        self.setProperty("rail", True)  # размер 40×40 без лишних отступов (см. qss.py)

    @property
    def marked(self) -> bool:
        return self._marked

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802
        if self._marked and menu_allowed():
            self.contextRequested.emit(self.key, event.globalPos())

    def set_marked(self, value: bool) -> None:
        if value != self._marked:
            self._marked = value
            self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        super().paintEvent(event)
        if not self._marked:
            return
        painter = QPainter(self)
        p = current.palette()
        x = self.width() - MARK - tokens.SPACE_2
        y = tokens.SPACE_2
        painter.fillRect(
            QRectF(x - 1, y - 1, MARK + 2, MARK + 2), QColor(p.surface_raised)
        )  # ободок, чтобы точка читалась на любой плашке
        painter.fillRect(QRectF(x, y, MARK, MARK), QColor(p.secondary))


class ToolRail(QWidget):
    """Вертикальная рейка инструментов: 56 px шириной, кнопки 40×40 с пиксельными иконками."""

    toolClicked = Signal(str)
    contextRequested = Signal(str, QPoint)  # правая кнопка на инструменте с эффектом

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._buttons: dict[str, RailButton] = {}
        self._column = QVBoxLayout(self)
        self._column.setContentsMargins(
            (tokens.RAIL_W - tokens.RAIL_BUTTON) // 2, tokens.SPACE_2, 0, tokens.SPACE_2
        )
        self._column.setSpacing(tokens.SPACE_1)
        self._column.addStretch(1)
        self.setFixedWidth(tokens.RAIL_W)

    def add_tool(self, key: str, icon: str, name: str, hotkey: str = "") -> RailButton:
        item = RailButton()
        item.key = key
        item.contextRequested.connect(self.contextRequested)
        item.setCheckable(True)
        item.setFixedSize(tokens.RAIL_BUTTON, tokens.RAIL_BUTTON)
        item.setToolTip(tip(name, hotkey))
        item.setAccessibleName(name)
        item.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        set_icon(item, icon, 32)
        item.clicked.connect(lambda _checked=False, k=key: self.toolClicked.emit(k))
        self._column.insertWidget(self._column.count() - 1, item)
        self._buttons[key] = item
        return item

    def button(self, key: str) -> RailButton:
        return self._buttons[key]

    def names(self) -> list[str]:
        return list(self._buttons)

    def set_checked(self, key: str | None) -> None:
        for name, item in self._buttons.items():
            item.setChecked(name == key)

    def set_marked(self, key: str, value: bool) -> None:
        if key in self._buttons:
            self._buttons[key].set_marked(value)

    def marked(self, key: str) -> bool:
        return self._buttons[key].marked

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        p = current.palette()
        painter.fillRect(self.rect(), QColor(p.surface))
        painter.fillRect(
            QRectF(self.width() - tokens.BORDER_WIDTH, 0, tokens.BORDER_WIDTH, self.height()),
            QColor(p.border),
        )


class TopRow(QWidget):
    """Верхняя панель 40 px: слева навигация и отмена, справа главное действие."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("toprow")
        self.setFixedHeight(tokens.TOP_BAR_H)
        self.left = QHBoxLayout()
        self.left.setSpacing(tokens.SPACE_1)
        self.right = QHBoxLayout()
        self.right.setSpacing(tokens.SPACE_2)
        row = QHBoxLayout(self)
        row.setContentsMargins(tokens.SPACE_3, 0, tokens.SPACE_3, 0)
        row.addLayout(self.left)
        row.addStretch(1)
        row.addLayout(self.right)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        p = current.palette()
        painter.fillRect(self.rect(), QColor(p.surface))
        painter.fillRect(
            QRectF(0, self.height() - tokens.BORDER_WIDTH, self.width(), tokens.BORDER_WIDTH),
            QColor(p.border),
        )


class ContextBar(QWidget):
    """Панель параметров выбранного инструмента: плавно раскрывается и сворачивается.

    Без выбранного инструмента её нет вовсе (высота 0), и содержимое получает всё место.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("contextbar")
        self._stack = QStackedWidget(self)
        self._empty = QWidget()
        self._stack.addWidget(self._empty)
        self._index: dict[str, int] = {}
        self._current: str | None = None
        self._height = 0
        self._animation = QVariantAnimation(self)
        self._animation.setEasingCurve(anim.ease_out())
        self._animation.valueChanged.connect(lambda value: self._step(float(value)))
        self.setFixedHeight(0)
        self.hide()

    @property
    def current(self) -> str | None:
        return self._current

    @property
    def expanded(self) -> bool:
        return self._current is not None

    def add_panel(self, key: str, widget: QWidget) -> None:
        """Строка параметров: отступы по краям, высота панели 36."""
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(tokens.SPACE_3, 0, tokens.SPACE_3, 0)
        row.setSpacing(tokens.SPACE_3)
        row.addWidget(widget, 1)
        self._index[key] = self._stack.addWidget(holder)

    def panel_keys(self) -> list[str]:
        return list(self._index)

    def show_panel(self, key: str | None) -> None:
        if key is not None and key not in self._index:
            key = None
        self._current = key
        if key is not None:
            self._stack.setCurrentIndex(self._index[key])
            self._set_height(self._height, tokens.CONTEXT_H)
        else:
            self._set_height(self._height, 0)

    def _set_height(self, start: int, end: int) -> None:
        if end > 0:
            self.show()
        self._animation.stop()
        span = anim.duration(tokens.PANEL_MS)
        if span == 0 or start == end:
            self._step(float(end))
            return
        self._animation.setDuration(span)
        self._animation.setStartValue(float(start))
        self._animation.setEndValue(float(end))
        self._animation.start()

    def _step(self, value: float) -> None:
        self._height = round(value)
        self.setFixedHeight(self._height)
        if self._height <= 0 and self._current is None:
            self.hide()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._stack.setGeometry(0, 0, self.width(), tokens.CONTEXT_H)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, self._height)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        p = current.palette()
        painter.fillRect(self.rect(), QColor(p.surface_raised))
        painter.fillRect(
            QRectF(0, self.height() - tokens.BORDER_WIDTH, self.width(), tokens.BORDER_WIDTH),
            QColor(p.border),
        )


class StatusLine(QWidget):
    """Строка состояния 24 px: слева подсказка по инструменту, справа итог и чип эффектов."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(tokens.STATUS_H)
        self._hint = QLabel()
        self._hint.setProperty("muted", True)
        self._resting_hint = ""
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._end_flash)
        self._summary = QLabel()
        self._summary.setProperty("muted", True)
        self.right = QHBoxLayout()
        self.right.setSpacing(tokens.SPACE_3)
        self.right.addWidget(self._summary)
        row = QHBoxLayout(self)
        row.setContentsMargins(tokens.SPACE_3, 0, tokens.SPACE_3, 0)
        row.addWidget(self._hint, 1)
        row.addLayout(self.right)

    @property
    def summary_label(self) -> QLabel:
        return self._summary

    def set_hint(self, text: str) -> None:
        self._resting_hint = text
        if not self._flash_timer.isActive():
            self._hint.setText(text)

    def hint(self) -> str:
        return self._resting_hint

    def shown_text(self) -> str:
        return self._hint.text()

    def flash(self, text: str, ms: int = FLASH_MS) -> None:
        """Короткое сообщение вместо подсказки: «Клип добавлен», «Экспорт отменён»."""
        self._hint.setText(text)
        self._flash_timer.start(ms)

    def _end_flash(self) -> None:
        self._hint.setText(self._resting_hint)

    def set_summary(self, text: str) -> None:
        self._summary.setText(text)

    def summary(self) -> str:
        return self._summary.text()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        p = current.palette()
        painter.fillRect(self.rect(), QColor(p.surface))
        painter.fillRect(
            QRectF(0, 0, self.width(), tokens.BORDER_WIDTH),
            QColor(p.border),
        )


class EditorShell(QWidget):
    """Собирает части в колонку: верх, полоса экспорта, контекст, (рейка + содержимое), статус."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.top = TopRow()
        self.export_strip = ExportStrip()
        self.context = ContextBar()
        self.rail = ToolRail()
        self.status = StatusLine()
        self._content: QWidget | None = None
        self._body = QHBoxLayout()
        self._body.setContentsMargins(0, 0, 0, 0)
        self._body.setSpacing(0)
        self._body.addWidget(self.rail)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self.top)
        column.addWidget(self.export_strip)
        column.addWidget(self.context)
        column.addLayout(self._body, 1)
        column.addWidget(self.status)

    def set_content(self, widget: QWidget) -> None:
        self._content = widget
        self._body.addWidget(widget, 1)

    def select(self, key: str | None) -> None:
        """Выбран инструмент (или снят): рейка подсвечивает, панель параметров раскрывается."""
        self.rail.set_checked(key)
        self.context.show_panel(key)

    def refresh_theme(self) -> None:
        refresh_icons(self)
        self.update()
