"""Элементы окна настроек в стиле темы: тумблер, сегменты, список, ползунок, число, поля, цвет.

Каждый элемент — `SettingControl`: умеет показать значение (`set_value`, без сигнала) и сообщает об
изменении пользователем сигналом `edited`. Окно настроек строит их по описанию настройки
(`Spec`) функцией `make_control`, состояния (обычное, наведение, нажатие, фокус, выключено) рисует
таблица стилей темы или сам элемент токенами темы.
"""

from collections.abc import Callable
from functools import partial

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFontMetrics,
    QIcon,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStyle,
    QStyleOptionButton,
    QStylePainter,
    QVBoxLayout,
    QWidget,
)

from chopchop.core.settings_schema import Spec
from chopchop.ui.click_slider import ClickSlider
from chopchop.ui.color_button import ColorButton, color_to_hex, hex_to_color
from chopchop.ui.theme import current, icons, tokens
from chopchop.ui.theme.pixel import paint_frame
from chopchop.ui.themed_menu import ThemedMenu
from chopchop.ui.widgets import PixelToggle, Segmented

SEGMENT_MAX_CHOICES = 3
SEGMENT_MAX_CHARS = 16  # шрифт крупный: длинные варианты сегментами не уместятся
SLIDER_MAX_STEPS = 100
SLIDER_WIDTH = 150
FIELD_WIDTH = 190
SELECT_WIDTH = 230
VALUE_LABEL_WIDTH = 44
ROW_MIN_H = 48
ROW_PADDING = tokens.SPACE_3
NAV_W = 220
NAV_ITEM_H = 40
ACCENT_BAR = 4
SWATCH = 16  # квадратик-образец цвета
SEARCH_DELAY_MS = 120


class SettingControl(QWidget):
    """Общий вид элемента: значение внутрь без сигнала, изменение наружу сигналом."""

    edited = Signal(object)

    def set_value(self, value: object) -> None:
        raise NotImplementedError

    def value(self) -> object:
        raise NotImplementedError

    def focus_target(self) -> QWidget:
        return self


def _hbox(parent: QWidget, spacing: int = tokens.SPACE_2) -> QHBoxLayout:
    row = QHBoxLayout(parent)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(spacing)
    return row


class ToggleControl(SettingControl):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.toggle = PixelToggle()
        _hbox(self).addWidget(self.toggle)
        self.toggle.toggled.connect(lambda on: self.edited.emit(bool(on)))

    def set_value(self, value: object) -> None:
        self.toggle.blockSignals(True)
        self.toggle.setChecked(bool(value))
        self.toggle.blockSignals(False)

    def value(self) -> object:
        return self.toggle.isChecked()

    def focus_target(self) -> QWidget:
        return self.toggle


class SegmentControl(SettingControl):
    """Выбор из двух-трёх коротких вариантов рядом кнопок."""

    def __init__(self, choices: tuple[tuple[str, str], ...], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.segments = Segmented()
        for value, title in choices:
            self.segments.add(title, value)
        _hbox(self).addWidget(self.segments)
        self.segments.changed.connect(self.edited.emit)

    def set_value(self, value: object) -> None:
        self.segments.blockSignals(True)
        self.segments.set_value(value)
        self.segments.blockSignals(False)

    def value(self) -> object:
        return self.segments.value()

    def focus_target(self) -> QWidget:
        buttons = self.segments.buttons()
        return buttons[0] if buttons else self


class SelectButton(QPushButton):
    """Кнопка выпадающего списка: значение слева, стрелка справа; Up и Down листают значения.

    Если задан цвет образца, слева от значения рисуется квадратик этого цвета.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.swatch: Callable[[], str | None] | None = None  # цвет образца берётся при рисовании
        self.setProperty("variant", "select")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:  # noqa: N802
        metrics = QFontMetrics(self.font())
        return QSize(
            max(metrics.horizontalAdvance(self.text()) + 4 * tokens.SPACE_4, 140),
            tokens.CONTEXT_CONTROL_H,
        )

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QStylePainter(self)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.text = ""
        option.icon = option.icon.__class__()
        painter.drawControl(QStyle.ControlElement.CE_PushButton, option)
        p = current.palette()
        pad = tokens.BORDER_WIDTH + tokens.SPACE_3
        side = icons.ui_icon_size()
        left = pad
        color = self.swatch() if self.swatch else None
        if color:
            box = QRect(pad, (self.height() - SWATCH) // 2, SWATCH, SWATCH)
            painter.fillRect(box, QColor(color))
            painter.setPen(QPen(QColor(p.border_strong), tokens.BORDER_WIDTH))
            painter.drawRect(box)
            left += SWATCH + tokens.SPACE_2
        text_rect = QRectF(left, 0, self.width() - left - pad - side, self.height())
        painter.setPen(QColor(p.text if self.isEnabled() else p.text_muted))
        elided = QFontMetrics(self.font()).elidedText(
            self.text(), Qt.TextElideMode.ElideRight, int(text_rect.width())
        )
        painter.drawText(
            text_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), elided
        )
        role = "text" if self.isEnabled() else "text_muted"
        pix = icons.pixmap(
            "chevron_down", p, logical=side, ratio=self.devicePixelRatioF(), role=role
        )
        painter.drawPixmap(
            QPoint(
                self.width() - tokens.BORDER_WIDTH - tokens.SPACE_2 - side,
                (self.height() - side) // 2,
            ),
            pix,
        )


class SelectControl(SettingControl):
    """Выпадающий список: меню рисует тема, а не система."""

    def __init__(
        self,
        choices: tuple[tuple[str, str], ...],
        parent: QWidget | None = None,
        swatch: Callable[[object], str | None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._choices = choices
        self._swatch = swatch  # цвет-образец варианта (палитры акцента)
        self._value: object = choices[0][0] if choices else ""
        self.button = SelectButton()
        self.button.setFixedWidth(SELECT_WIDTH)
        self.button.clicked.connect(self.open_menu)
        self.button.installEventFilter(self)
        _hbox(self).addWidget(self.button)
        self._refresh()

    def _title(self, value: object) -> str:
        return next((title for key, title in self._choices if key == value), "")

    def _refresh(self) -> None:
        self.button.setText(self._title(self._value))
        if self._swatch is not None:
            self.button.swatch = lambda: self._swatch(self._value) if self._swatch else None
        self.button.update()

    def set_value(self, value: object) -> None:
        self._value = value
        self._refresh()

    def value(self) -> object:
        return self._value

    def focus_target(self) -> QWidget:
        return self.button

    def choose(self, value: object) -> None:
        if value != self._value:
            self._value = value
            self._refresh()
            self.edited.emit(value)

    def open_menu(self) -> ThemedMenu:
        menu = ThemedMenu(self.button)
        for key, title in self._choices:
            action = menu.add_item(title, partial(self.choose, key), checked=key == self._value)
            color = self._swatch(key) if self._swatch else None
            if color:
                action.setIcon(_swatch_icon(color))
        menu.setMinimumWidth(self.button.width())
        menu.popup(self.button.mapToGlobal(QPoint(0, self.button.height())))
        return menu

    def eventFilter(self, watched: object, event: QEvent) -> bool:  # noqa: N802
        if (
            watched is self.button
            and isinstance(event, QKeyEvent)
            and event.type() == QEvent.Type.KeyPress
        ):
            step = {Qt.Key.Key_Down: 1, Qt.Key.Key_Up: -1}.get(Qt.Key(event.key()))
            if step is not None and self._choices:
                keys = [key for key, _title in self._choices]
                index = keys.index(self._value) if self._value in keys else 0
                self.choose(keys[min(max(index + step, 0), len(keys) - 1)])
                return True
        return False


class SliderControl(SettingControl):
    """Ползунок с подписью значения: для чисел в небольшом диапазоне."""

    def __init__(self, spec: Spec, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._low = float(spec.low or 0.0)
        self._step = float(spec.step) or 1.0
        self._integer = spec.kind == "int"
        top = float(spec.high or 0.0)
        self.slider = ClickSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, round((top - self._low) / self._step))
        self.slider.setFixedWidth(SLIDER_WIDTH)
        self.slider.setAccessibleName(spec.label)
        self.label = QLabel()
        self.label.setFixedWidth(VALUE_LABEL_WIDTH)
        self.label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row = _hbox(self)
        row.addWidget(self.slider)
        row.addWidget(self.label)
        self.slider.valueChanged.connect(self._moved)
        self._silent = False

    def _number(self, position: int) -> float | int:
        value = self._low + position * self._step
        return round(value) if self._integer else round(value, 4)

    def _text(self, value: float | int) -> str:
        return f"{value}" if self._integer else f"{value:g}"

    def _moved(self, position: int) -> None:
        value = self._number(position)
        self.label.setText(self._text(value))
        if not self._silent:
            self.edited.emit(value)

    def set_value(self, value: object) -> None:
        number = float(str(value))
        self._silent = True
        self.slider.setValue(round((number - self._low) / self._step))
        self._silent = False
        self.label.setText(self._text(self._number(self.slider.value())))

    def value(self) -> object:
        return self._number(self.slider.value())

    def focus_target(self) -> QWidget:
        return self.slider


class NumberControl(SettingControl):
    """Поле числа с кнопками «−» и «+»: для больших диапазонов. Колесо и стрелки меняют на шаг."""

    def __init__(self, spec: Spec, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._integer = spec.kind == "int"
        self.field = _Spin(self._integer)
        low, high = float(spec.low or 0.0), float(spec.high or 0.0)
        self.field.configure(low, high, float(spec.step))
        self.field.setFixedWidth(VALUE_LABEL_WIDTH + 2 * tokens.SPACE_4)
        self.field.setAccessibleName(spec.label)
        self.minus = self._step_button("-", -1)
        self.plus = self._step_button("+", 1)
        row = _hbox(self, tokens.SPACE_1)
        row.addWidget(self.minus)
        row.addWidget(self.field)
        row.addWidget(self.plus)
        self.field.valueEdited.connect(self.edited.emit)

    def _step_button(self, text: str, direction: int) -> QPushButton:
        button = QPushButton(text)
        button.setProperty("variant", "step")
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        button.setAutoRepeat(True)
        button.clicked.connect(lambda: self.field.nudge(direction))
        return button

    def set_value(self, value: object) -> None:
        self.field.show_value(float(str(value)))

    def value(self) -> object:
        return self.field.number()

    def focus_target(self) -> QWidget:
        return self.field


class _Spin(QSpinBox):
    """Поле без встроенных стрелок: рисуется как обычное поле темы, кнопки рядом."""

    valueEdited = Signal(object)

    def __init__(self, integer: bool) -> None:
        super().__init__()
        self._integer = integer
        self._scale = 1 if integer else 100
        self.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setKeyboardTracking(False)
        self.valueChanged.connect(self._changed)
        self._silent = False

    def configure(self, low: float, high: float, step: float) -> None:
        self.setRange(round(low * self._scale), round(high * self._scale))
        self.setSingleStep(max(round(step * self._scale), 1))

    def textFromValue(self, value: int) -> str:  # noqa: N802
        return str(value) if self._integer else f"{value / self._scale:g}"

    def valueFromText(self, text: str) -> int:  # noqa: N802
        try:
            return round(float(text.replace(",", ".")) * self._scale)
        except ValueError:
            return self.value()

    def number(self) -> float | int:
        return self.value() if self._integer else self.value() / self._scale

    def show_value(self, number: float) -> None:
        self._silent = True
        self.setValue(round(number * self._scale))
        self._silent = False

    def nudge(self, direction: int) -> None:
        self.stepBy(direction)

    def _changed(self, _value: int) -> None:
        if not self._silent:
            self.valueEdited.emit(self.number())

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()  # колесо над полем листает страницу, а не меняет число


class TextControl(SettingControl):
    def __init__(self, placeholder: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.edit = QLineEdit()
        self.edit.setFixedWidth(FIELD_WIDTH)
        if placeholder:
            self.edit.setPlaceholderText(placeholder)
        _hbox(self).addWidget(self.edit)
        self.edit.editingFinished.connect(lambda: self.edited.emit(self.edit.text()))

    def set_value(self, value: object) -> None:
        self.edit.setText(str(value))

    def value(self) -> object:
        return self.edit.text()

    def focus_target(self) -> QWidget:
        return self.edit


class PathControl(SettingControl):
    def __init__(self, title: str, browse_text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._title = title
        self.edit = QLineEdit()
        self.edit.setFixedWidth(FIELD_WIDTH)
        self.browse = QPushButton(browse_text)
        row = _hbox(self)
        row.addWidget(self.edit)
        row.addWidget(self.browse)
        self.edit.editingFinished.connect(lambda: self.edited.emit(self.edit.text()))
        self.browse.clicked.connect(self._choose)

    def _choose(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, self._title, self.edit.text())
        if folder:
            self.edit.setText(folder)
            self.edited.emit(folder)

    def set_value(self, value: object) -> None:
        self.edit.setText(str(value))

    def value(self) -> object:
        return self.edit.text()

    def focus_target(self) -> QWidget:
        return self.edit


class ColorControl(SettingControl):
    def __init__(self, color: tuple[int, int, int], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.button = ColorButton(color)
        self.button.setFixedWidth(VALUE_LABEL_WIDTH + 2 * tokens.SPACE_4)
        _hbox(self).addWidget(self.button)
        self.button.colorChanged.connect(lambda c: self.edited.emit(color_to_hex(c)))

    def set_value(self, value: object) -> None:
        self.button.set_color(hex_to_color(str(value)))

    def value(self) -> object:
        return color_to_hex(self.button.color)

    def focus_target(self) -> QWidget:
        return self.button


def _swatch_icon(color: str) -> QIcon:
    """Квадратик цвета для пункта меню (значок меню 32 px, образец 20 px по центру)."""
    pix = QPixmap(32, 32)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.fillRect(QRect(6, 6, 20, 20), QColor(color))
    painter.setPen(QPen(QColor(current.palette().border_strong), tokens.BORDER_WIDTH))
    painter.drawRect(QRect(6, 6, 20, 20))
    painter.end()
    return QIcon(pix)


def accent_swatch(value: object) -> str | None:
    """Образец палитры акцента в цветах текущей темы."""
    family = tokens.ACCENTS.get(str(value))
    return family[current.palette().name].sample() if family else None


def make_control(spec: Spec, translate: Callable[[str], str], browse_text: str) -> SettingControl:
    """Подходящий элемент по типу настройки."""
    match spec.kind:
        case "bool":
            return ToggleControl()
        case "choice":
            choices = tuple((value, translate(title)) for value, title in spec.choices)
            short = len(choices) <= SEGMENT_MAX_CHOICES and (
                sum(len(title) for _v, title in choices) <= SEGMENT_MAX_CHARS
            )
            if spec.key == "appearance.accent":
                return SelectControl(choices, swatch=accent_swatch)
            return SegmentControl(choices) if short else SelectControl(choices)
        case "int" | "float":
            steps = ((spec.high or 0.0) - (spec.low or 0.0)) / (spec.step or 1.0)
            return SliderControl(spec) if steps <= SLIDER_MAX_STEPS else NumberControl(spec)
        case "color":
            return ColorControl(hex_to_color(str(spec.default)))
        case "path":
            return PathControl(translate(spec.label), browse_text)
        case "langs":
            return TextControl("rus,eng")
        case _:
            return TextControl()


# --- строка, карточка и навигация -------------------------------------------------------------


class SettingRow(QWidget):
    """Строка настройки: слева название и описание, справа элемент; не ниже 48 px."""

    activated = Signal()

    def __init__(
        self,
        spec: Spec | None,
        control: QWidget,
        title: str,
        hint: str,
        restart_text: str = "",
        breadcrumb: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.spec = spec
        self.control = control
        self._last = False
        self._flash = False
        self.setMinimumHeight(ROW_MIN_H)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.title = QLabel(title)
        self.title.setProperty("rowtitle", True)
        self.title.setWordWrap(True)
        self.title.setMinimumWidth(6 * tokens.SPACE_4)
        self.description = QLabel(hint)
        self.description.setWordWrap(True)
        self.description.setProperty("muted", True)
        self.description.setVisible(bool(hint))
        self.description.setMaximumHeight(
            2 * QFontMetrics(self.description.font()).lineSpacing() + 2
        )
        self.description.setToolTip(hint)
        head = QHBoxLayout()
        head.setSpacing(tokens.SPACE_2)
        head.addWidget(self.title, 1)
        chips = QHBoxLayout()  # ярлыки под названием, чтобы не раздвигать строку
        chips.setSpacing(tokens.SPACE_1)
        self.chip: QLabel | None = None
        if restart_text:
            self.chip = QLabel(restart_text)
            self.chip.setProperty("chip", True)
            chips.addWidget(self.chip)
        if breadcrumb:
            crumb = QLabel(breadcrumb)
            crumb.setProperty("chip", "muted")
            chips.addWidget(crumb)
        chips.addStretch(1)
        self.error = QLabel()
        self.error.setProperty("error", True)
        self.error.setWordWrap(True)
        self.error.hide()
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addLayout(head)
        if self.chip is not None or breadcrumb:
            text.addLayout(chips)
        text.addWidget(self.description)
        text.addWidget(self.error)
        row = QHBoxLayout(self)
        row.setContentsMargins(ROW_PADDING, tokens.SPACE_2, ROW_PADDING, tokens.SPACE_2)
        row.setSpacing(tokens.SPACE_4)
        row.addLayout(text, 1)
        row.addWidget(control, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._end_flash)
        self.title.setCursor(
            Qt.CursorShape.PointingHandCursor if breadcrumb else Qt.CursorShape.ArrowCursor
        )
        self._clickable = bool(breadcrumb)

    def set_last(self, last: bool) -> None:
        self._last = last
        self.update()

    def show_error(self, message: str) -> None:
        self.error.setText(message)
        self.error.setVisible(bool(message))

    def flash(self) -> None:
        """Подсветить строку после перехода из поиска."""
        self._flash = True
        self.update()
        self._timer.start(1400)

    def _end_flash(self) -> None:
        self._flash = False
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._clickable and event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        p = current.palette()
        if self._flash:
            painter.fillRect(self.rect(), QColor(p.accent_tint))
        if not self._last:
            painter.fillRect(
                QRectF(ROW_PADDING, self.height() - 1, self.width() - 2 * ROW_PADDING, 1),
                QColor(p.border),
            )


class SettingCard(QWidget):
    """Группа строк в карточке: фон surface, ступенчатая рамка темы. Опасная — рамка danger."""

    def __init__(
        self, title: str = "", danger: bool = False, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._danger = danger
        self.heading = QLabel(title)
        self.heading.setProperty("cardtitle", True)
        self.heading.setVisible(bool(title))
        self._body = QVBoxLayout()
        self._body.setContentsMargins(0, 0, 0, 0)
        self._body.setSpacing(0)
        edge = tokens.BORDER_WIDTH + tokens.SPACE_1
        frame = QVBoxLayout()
        frame.setContentsMargins(edge, edge, edge, edge)
        frame.addLayout(self._body)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(tokens.SPACE_2)
        outer.addWidget(self.heading)
        outer.addLayout(frame)
        self._frame = frame
        self._rows: list[QWidget] = []

    def add(self, widget: QWidget) -> None:
        self._rows.append(widget)
        self._body.addWidget(widget)
        for index, row in enumerate(self._rows):
            if isinstance(row, SettingRow):
                row.set_last(index == len(self._rows) - 1)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        p = current.palette()
        top = self.heading.geometry().bottom() + tokens.SPACE_2 if self.heading.isVisible() else 0
        rect = QRectF(0, top, self.width(), self.height() - top)
        paint_frame(
            painter,
            rect,
            fill=p.surface,
            border=p.danger if self._danger else p.border_strong,
        )


class NavItem(QAbstractButton):
    """Пункт левой панели: значок 16 px и название; выбранный — тонировка и полоса акцента."""

    def __init__(self, section: str, title: str, icon: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.section = section
        self.icon_name = icon
        self.setText(title)
        self.setCheckable(True)
        self.setFixedHeight(NAV_ITEM_H)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setAccessibleName(title)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(NAV_W, NAV_ITEM_H)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        p = current.palette()
        if self.isChecked():
            painter.fillRect(self.rect(), QColor(p.accent_tint))
            painter.fillRect(QRectF(0, 0, ACCENT_BAR, self.height()), QColor(p.accent))
        elif self.underMouse():
            painter.fillRect(self.rect(), QColor(p.surface_raised))
        side = icons.ui_icon_size()
        left = ACCENT_BAR + tokens.SPACE_1
        pix = icons.pixmap(
            self.icon_name, p, logical=side, ratio=self.devicePixelRatioF(), role="text"
        )
        painter.drawPixmap(QPoint(left, (self.height() - side) // 2), pix)
        painter.setPen(QColor(p.text))
        painter.drawText(
            QRectF(left + side + tokens.SPACE_2, 0, self.width(), self.height()),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            self.text(),
        )
        if self.hasFocus():
            painter.setPen(QPen(QColor(p.focus_ring), tokens.BORDER_WIDTH))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.rect().adjusted(2, 2, -2, -2))


class SectionNav(QWidget):
    """Левая панель разделов 220 px без рамки; стрелки вверх и вниз переходят между пунктами."""

    sectionChosen = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(NAV_W)
        self.items: list[NavItem] = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._column = QVBoxLayout(self)
        self._column.setContentsMargins(0, 0, 0, 0)
        self._column.setSpacing(0)
        self._divider_before: set[str] = set()

    def add(self, section: str, title: str, icon: str, divider_before: bool = False) -> NavItem:
        if divider_before:
            line = _Divider()
            self._column.addWidget(line)
        item = NavItem(section, title, icon)
        item.clicked.connect(lambda _c=False, s=section: self.sectionChosen.emit(s))
        item.installEventFilter(self)
        self._group.addButton(item)
        self.items.append(item)
        self._column.addWidget(item)
        return item

    def finish(self) -> None:
        self._column.addStretch(1)

    def select(self, section: str, focus: bool = False) -> None:
        for item in self.items:
            if item.section == section:
                item.setChecked(True)
                if focus:
                    item.setFocus()

    def current_section(self) -> str:
        return next((i.section for i in self.items if i.isChecked()), "")

    def eventFilter(self, watched: object, event: QEvent) -> bool:  # noqa: N802
        if isinstance(event, QKeyEvent) and event.type() == QEvent.Type.KeyPress:
            step = {Qt.Key.Key_Down: 1, Qt.Key.Key_Up: -1}.get(Qt.Key(event.key()))
            if step is not None and watched in self.items:
                index = self.items.index(watched)
                target = self.items[min(max(index + step, 0), len(self.items) - 1)]
                target.setChecked(True)
                target.setFocus()
                self.sectionChosen.emit(target.section)
                return True
        return False


class _Divider(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(tokens.SPACE_3 + 1)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(
            QRectF(tokens.SPACE_3, self.height() // 2, self.width() - 2 * tokens.SPACE_3, 1),
            QColor(current.palette().border),
        )
