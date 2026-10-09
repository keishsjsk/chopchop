"""Семейство кнопок: главная, вторичная, призрачная, сегментная, чип и тумблер.

Главная (`variant="primary"`, акцентная заливка) — одна на экран: «Экспорт», «Применить».
Вторичная — обычная кнопка с рамкой. Призрачная (`ghost`) — значок или текст без рамки, но с
состояниями наведения и нажатия. Сегментная и чип — выбор из нескольких. У всех есть состояния
«обычная», «наведение», «нажатие», «фокус» (видимое кольцо) и «выключена»; стили лежат в
`ui/theme/qss.py`, а тумблер рисуется сам, потому что в Qt его нет.
"""

from collections.abc import Callable, Iterable

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QKeyEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QHBoxLayout,
    QPushButton,
    QToolButton,
    QWidget,
)

from chopchop.ui.theme import current, icons, tokens
from chopchop.ui.theme.pixel import paint_frame

ICON_NAME = "icon_name"
ICON_SIZE = "icon_size"
ICON_ROLE = "icon_role"


def tip(name: str, key: str = "") -> str:
    """Подсказка «Название (клавиша)»: показывается через 400 мс, без скобок в подписях."""
    return f"{name} ({key})" if key else name


def set_icon(button: QAbstractButton, name: str, logical: int = 16, role: str = "text") -> None:
    """Значок кнопки в цветах темы; запоминается, чтобы перекраситься при смене темы."""
    button.setProperty(ICON_NAME, name)
    button.setProperty(ICON_SIZE, logical)
    button.setProperty(ICON_ROLE, role)
    button.setIcon(icons.qicon(name, current.palette(), logical=logical, role=role))
    button.setIconSize(QSize(logical, logical))


def refresh_icons(root: QWidget) -> None:
    """Тема сменилась: перекрасить значки всех кнопок внутри root."""
    for button in root.findChildren(QAbstractButton):
        name = button.property(ICON_NAME)
        if isinstance(name, str):
            set_icon(
                button,
                name,
                int(button.property(ICON_SIZE) or 16),
                str(button.property(ICON_ROLE) or "text"),
            )


def button(
    text: str,
    variant: str | None = None,
    *,
    icon: str | None = None,
    tooltip: str = "",
    slot: Callable[[], object] | None = None,
) -> QPushButton:
    """Текстовая кнопка нужного вида: primary, ghost или None (вторичная)."""
    result = QPushButton(text)
    if variant:
        result.setProperty("variant", variant)
    if icon:
        set_icon(result, icon, 16, "on_accent" if variant == "primary" else "text")
    if tooltip:
        result.setToolTip(tooltip)
    if slot is not None:
        result.clicked.connect(lambda _checked=False: slot())
    return result


def icon_button(
    icon: str,
    tooltip: str,
    slot: Callable[[], object] | None = None,
    *,
    text: str = "",
    checkable: bool = False,
    logical: int = 16,
) -> QToolButton:
    """Призрачная кнопка со значком (и необязательной подписью рядом)."""
    result = QToolButton()
    result.setProperty("variant", "ghost")
    result.setToolTip(tooltip)
    result.setAccessibleName(text or tooltip)
    result.setCheckable(checkable)
    result.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    if text:
        result.setText(text)
        result.setProperty("labelled", True)
        result.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    set_icon(result, icon, logical)
    if slot is not None:
        result.clicked.connect(lambda _checked=False: slot())
    return result


class Segmented(QWidget):
    """Ряд связанных кнопок «одна из многих»: режим скрытия, пропорции, поворот."""

    changed = Signal(object)

    def __init__(
        self, *, variant: str = "segment", exclusive: bool = True, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._variant = variant
        self._group = QButtonGroup(self)
        self._group.setExclusive(exclusive)
        self._values: dict[QAbstractButton, object] = {}
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        # сегменты примыкают и делят общую границу, чипы стоят отдельно
        self._row.setSpacing(-tokens.BORDER_WIDTH if variant == "segment" else tokens.SPACE_1)
        self._group.buttonClicked.connect(lambda b: self.changed.emit(self._values[b]))

    def add(
        self,
        text: str,
        value: object,
        tooltip: str = "",
        icon: str | None = None,
        *,
        momentary: bool = False,
    ) -> QPushButton:
        item = QPushButton(text)
        item.setProperty("variant", self._variant)
        item.setCheckable(not momentary)
        if icon:
            set_icon(item, icon, 16, "text")
        if tooltip:
            item.setToolTip(tooltip)
        if momentary:
            item.clicked.connect(lambda _checked=False, v=value: self.changed.emit(v))
        else:
            self._group.addButton(item)
        self._values[item] = value
        self._row.addWidget(item)
        return item

    def buttons(self) -> list[QAbstractButton]:
        return list(self._values)

    def value(self) -> object:
        checked = self._group.checkedButton()
        return self._values[checked] if checked is not None else None

    def set_value(self, value: object, *, emit: bool = False) -> None:
        for item, item_value in self._values.items():
            if item_value == value and item.isCheckable():
                item.setChecked(True)
                if emit:
                    self.changed.emit(value)
                return

    def clear_value(self) -> None:
        """Снять выбор со всех кнопок (значения, которого нет среди кнопок)."""
        self._group.setExclusive(False)
        for item in self._values:
            item.setChecked(False)
        self._group.setExclusive(True)

    def set_items(self, items: Iterable[tuple[str, object]]) -> None:
        for text, value in items:
            self.add(text, value)


class PixelToggle(QAbstractButton):
    """Тумблер в стиле интерфейса: ступенчатая дорожка и бегунок; Space и клик переключают."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText(text)
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.toggled.connect(lambda _checked: self.update())

    def sizeHint(self) -> QSize:  # noqa: N802
        label = QFontMetrics(self.font()).horizontalAdvance(self.text()) if self.text() else 0
        gap = tokens.SPACE_2 if label else 0
        return QSize(tokens.TOGGLE_W + gap + label + 2 * tokens.FOCUS_GAP, tokens.MIN_HIT)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.toggle()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        p = current.palette()
        on = self.isChecked()
        enabled = self.isEnabled()
        top = (self.height() - tokens.TOGGLE_H) / 2
        left = tokens.FOCUS_GAP
        track = QRectF(left, top, tokens.TOGGLE_W, tokens.TOGGLE_H)
        hot = self.underMouse() and enabled
        if not enabled:
            fill, border, knob = p.bg, p.border, p.border
        elif on:
            fill = p.accent_pressed if self.isDown() else (p.accent_hover if hot else p.accent)
            border, knob = fill, p.on_accent
        else:
            fill = p.border if self.isDown() else p.surface_raised
            border = p.text if hot else p.border_strong
            knob = p.text if hot else p.border_strong
        paint_frame(painter, track, fill=fill, border=border)
        inset = tokens.BORDER_WIDTH + tokens.PIXEL_STEP
        size = tokens.TOGGLE_H - 2 * inset
        x = track.right() - inset - size if on else track.left() + inset
        painter.fillRect(QRectF(x, top + inset, size, size), knob)
        if self.hasFocus():
            painter.setPen(QPen(QColor(p.focus_ring), tokens.BORDER_WIDTH))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(track.adjusted(-1, -1, 1, 1))
        if self.text():
            painter.setPen(QColor(p.text if enabled else p.text_muted))
            text_rect = QRectF(
                track.right() + tokens.SPACE_2, 0, self.width() - track.right(), self.height()
            )
            painter.drawText(
                text_rect,
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                self.text(),
            )
