"""Страница редактора фото: панель инструментов, холст, отмена и повтор, сохранение."""

from collections.abc import Callable
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QContextMenuEvent, QImage
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from chopchop.core.operations import (
    Adjust,
    Filter,
    Flip,
    Operation,
    RedactMode,
    Resize,
    Rotate,
)
from chopchop.editor.session import EditSession
from chopchop.engines.image_engine import default_output_path, format_for_source
from chopchop.services.app_settings import AppSettings
from chopchop.services.reveal import reveal_in_folder
from chopchop.ui.canvas import Canvas
from chopchop.ui.color_button import ColorButton, hex_to_color
from chopchop.ui.context_gate import menu_allowed
from chopchop.ui.crop_ratio import CropRatioBar
from chopchop.ui.export_dialog import ExportDialog
from chopchop.ui.export_strip import ExportStrip
from chopchop.ui.pil_qt import pil_to_qimage
from chopchop.ui.theme import current, icons, tokens
from chopchop.ui.toast import Toast
from chopchop.ui.tools.adjust_tool import AdjustTool
from chopchop.ui.tools.base import RectSelectTool, Tool
from chopchop.ui.tools.crop_tool import CropTool, ratio_from_setting
from chopchop.ui.tools.draw_tool import DrawShape, DrawTool
from chopchop.ui.tools.redact_tool import RedactTool
from chopchop.ui.tools.text_tool import TextTool

REFRESH_MS = 15


class EditorPage(QWidget):
    exitRequested = Signal()
    message = Signal(str)
    menuRequested = Signal(QPoint)  # правая кнопка над холстом

    def __init__(
        self,
        session: EditSession,
        settings: AppSettings | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self._app = settings or AppSettings(None)
        self.canvas = Canvas()
        self.tools: dict[str, Tool] = {
            "crop": CropTool(self),
            "redact": RedactTool(self),
            "draw": DrawTool(self),
            "text": TextTool(self),
            "adjust": AdjustTool(),
        }
        self._active: str | None = None  # инструмент для мыши
        self._selected: str | None = None  # выбранная кнопка (инструмент или панель)
        self._exit_after_save = False
        self._shown_key: tuple[str, int] | None = None  # какая картинка сейчас на холсте
        self._base_qimage: tuple[int, QImage] | None = None  # превью без операции с экрана
        self._pending: tuple[Operation, Image.Image] | None = None  # живой предпросмотр
        self._committing = False  # операция передана в историю, превью ещё считается
        self._syncing = False

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self._update_canvas)

        self._build_ui()

        for tool in self.tools.values():
            tool.changed.connect(self._on_tool_changed)
        draw_tool = self.tools["draw"]
        assert isinstance(draw_tool, DrawTool)
        draw_tool.strokeFinished.connect(self.apply_pending)
        redact = self.tools["redact"]
        assert isinstance(redact, RedactTool)
        redact.set_overlay_fill(True)  # заливка рисуется на холсте, без расчёта картинки
        self._on_draw_options()  # инструмент берёт то, что выбрано в панели
        self._ratio_bar.set_value(ratio_from_setting(self._app.get_str("editor.crop_ratio")))
        session.changed.connect(self.refresh)
        session.previewReady.connect(self._on_preview_ready)
        session.pendingReady.connect(self._on_pending_ready)
        session.frame_converter = pil_to_qimage  # QImage собирается в фоне, не в потоке интерфейса
        session.previewFailed.connect(self._on_preview_failed)
        session.exported.connect(self._on_exported)
        session.exportFailed.connect(self._on_export_failed)
        session.exportCancelled.connect(self._on_export_cancelled)
        self.refresh()

    # --- построение интерфейса ---------------------------------------------------------------

    def _icon_button(
        self, name: str, tip: str, slot: Callable[[], object] | None = None, rail: bool = False
    ) -> QToolButton:
        """Кнопка рейки (40 px, значок 32) или верхнего ряда (32 px, значок около 18)."""
        button = QToolButton()
        button.setToolTip(tip)
        side = tokens.RAIL_BUTTON if rail else tokens.ICON_BUTTON
        logical = 32 if rail else icons.ui_icon_size()
        button.setFixedSize(side, side)
        button.setIconSize(QSize(logical, logical))
        self._icon_buttons.append((button, name))
        button.setIcon(icons.qicon(name, current.palette(), logical=logical))
        if slot is not None:
            button.clicked.connect(lambda _checked=False: slot())
        return button

    def refresh_theme(self) -> None:
        """Тема сменилась: значки перекрашиваются."""
        for button, name in self._icon_buttons:
            size = button.iconSize().width()
            role = "on_accent" if name == "save" else "text"
            button.setIcon(icons.qicon(name, current.palette(), logical=size, role=role))
        self.update()

    def _build_ui(self) -> None:
        self._icon_buttons: list[tuple[QToolButton | QPushButton, str]] = []
        back = QToolButton()
        back.setText(self.tr("К просмотру"))
        back.setToolTip(self.tr("Вернуться к просмотру  Esc"))
        back.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        side = icons.ui_icon_size()
        back.setIconSize(QSize(side, side))
        back.setMinimumHeight(tokens.ICON_BUTTON)
        back.setIcon(icons.qicon("back_to_view", current.palette(), logical=side))
        self._icon_buttons.append((back, "back_to_view"))
        back.clicked.connect(self.request_exit)
        self._undo_button = self._icon_button("undo", self.tr("Отменить  Ctrl+Z"), self.undo)
        self._redo_button = self._icon_button("redo", self.tr("Повторить  Ctrl+Y"), self.redo)
        copy = self._icon_button("copy", self.tr("Копировать результат  Ctrl+C"), self.copy_result)
        save_as = self._icon_button(
            "save_as", self.tr("Сохранить как…  Ctrl+Shift+S"), self.save_as
        )
        save = QPushButton(self.tr("Сохранить"))
        save.setProperty("variant", "primary")
        save.setToolTip(self.tr("Сохранить  Ctrl+S"))
        save.setIcon(icons.qicon("save", current.palette(), logical=16, role="on_accent"))
        save.setIconSize(QSize(16, 16))
        self._icon_buttons.append((save, "save"))
        save.clicked.connect(self.save_quick)
        self._info = QLabel()
        self._info.setProperty("muted", True)

        top = QHBoxLayout()
        top.setSpacing(tokens.SPACE_2)
        top.addWidget(back)
        top.addWidget(self._undo_button)
        top.addWidget(self._redo_button)
        top.addStretch(1)
        top.addWidget(self._info)
        top.addWidget(copy)
        top.addWidget(save_as)
        top.addWidget(save)

        self.export_strip = ExportStrip()
        self.export_strip.cancelRequested.connect(self._cancel_export)

        rail = QVBoxLayout()
        rail.setSpacing(tokens.SPACE_1)
        self._stack = QStackedWidget()
        self._stack.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        group = QButtonGroup(self)
        group.setExclusive(False)
        self._buttons: dict[str, QToolButton] = {}
        entries = [
            ("crop", "crop", self.tr("Кадрировать"), "C", self._panel_crop()),
            ("rotate", "rotate", self.tr("Повернуть"), "R", self._panel_rotate()),
            ("redact", "redact", self.tr("Скрыть"), "B", self._panel_redact()),
            ("draw", "brush", self.tr("Рисовать"), "D", self._panel_draw()),
            ("text", "text", self.tr("Текст"), "T", self._panel_text()),
            ("adjust", "adjust", self.tr("Цвет и фильтры"), "", self._panel_adjust()),
            ("resize", "fit", self.tr("Размер"), "", self._panel_resize()),
        ]
        self._stack.addWidget(QWidget())  # индекс 0: инструмент не выбран
        self._panel_index: dict[str, int] = {}
        for key, icon_name, label, letter, panel in entries:
            tip = f"{label}  {letter}" if letter else label
            button = self._icon_button(icon_name, tip, rail=True)
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, k=key: self.select_tool(k))
            group.addButton(button)
            rail.addWidget(button)
            self._buttons[key] = button
            self._panel_index[key] = self._stack.addWidget(panel)
        rail.addStretch(1)
        self._stack.hide()

        column = QVBoxLayout()
        column.setSpacing(tokens.SPACE_2)
        column.addWidget(self._stack)
        column.addWidget(self.canvas, 1)
        body = QHBoxLayout()
        body.setSpacing(tokens.SPACE_2)
        body.addLayout(rail)
        body.addLayout(column, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(tokens.SPACE_3, tokens.SPACE_3, tokens.SPACE_3, tokens.SPACE_3)
        layout.setSpacing(tokens.SPACE_2)
        layout.addLayout(top)
        layout.addWidget(self.export_strip)
        layout.addLayout(body, 1)
        self.toast = Toast(self)

    def _apply_button(self) -> QPushButton:
        button = QPushButton(self.tr("Применить  Enter"))
        button.setProperty("variant", "primary")
        button.clicked.connect(self.apply_pending)
        return button

    def _panel(self, *widgets: QWidget) -> QWidget:
        """Панель параметров инструмента: одна строка над холстом."""
        panel = QWidget()
        row = QHBoxLayout(panel)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(tokens.SPACE_2)
        for widget in widgets:
            row.addWidget(widget)
        row.addStretch(1)
        return panel

    def _hint(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setMaximumWidth(420)
        label.setProperty("muted", True)
        return label

    def _panel_crop(self) -> QWidget:
        self._ratio_bar = CropRatioBar()
        self._ratio_bar.ratioChanged.connect(self._on_ratio_changed)
        hint = self._hint(
            self.tr("Тяните края и углы рамки, внутри — переносите. Enter — обрезать.")
        )
        return self._panel(
            QLabel(self.tr("Пропорции")), self._ratio_bar, hint, self._apply_button()
        )

    def _on_ratio_changed(self, ratio: object) -> None:
        crop = self.tools["crop"]
        assert isinstance(crop, CropTool)
        crop.set_ratio(ratio)  # type: ignore[arg-type]

    def _panel_rotate(self) -> QWidget:
        buttons: list[QWidget] = []
        for text, op in (
            (self.tr("⟲ Влево на 90°"), Rotate(270)),
            (self.tr("⟳ Вправо на 90°"), Rotate(90)),
            (self.tr("↔ Отразить по горизонтали"), Flip(True)),
            (self.tr("↕ Отразить по вертикали"), Flip(False)),
        ):
            button = QPushButton(text)
            button.clicked.connect(lambda _checked=False, o=op: self.session.add_full(o))
            buttons.append(button)
        return self._panel(*buttons)

    def _panel_redact(self) -> QWidget:
        self._redact_mode = QComboBox()
        self._redact_mode.addItem(self.tr("Заливка (надёжно)"), "fill")
        self._redact_mode.addItem(self.tr("Пикселизация"), "pixelate")
        self._redact_mode.addItem(self.tr("Размытие"), "blur")
        self._redact_mode.currentIndexChanged.connect(self._on_redact_mode)
        self._redact_hint = self._hint(
            self.tr(
                "Размытие и пикселизацию текста можно частично восстановить. "
                "Для паролей, номеров и переписки выбирайте заливку."
            )
        )
        self._redact_hint.hide()
        return self._panel(self._redact_mode, self._redact_hint, self._apply_button())

    def _on_redact_mode(self) -> None:
        mode: RedactMode = self._redact_mode.currentData()
        redact = self.tools["redact"]
        assert isinstance(redact, RedactTool)
        redact.set_mode(mode)
        self._redact_hint.setVisible(mode != "fill")

    def _panel_draw(self) -> QWidget:
        self._shape = QComboBox()
        self._shape.addItem(self.tr("Кисть (рисовать мышью)"), "pen")
        self._shape.addItem(self.tr("Маркер (рисовать мышью)"), "highlighter")
        self._shape.addItem(self.tr("Стрелка"), "arrow")
        self._shape.addItem(self.tr("Рамка"), "rect")
        self._shape.addItem(self.tr("Выделение области"), "marker")
        self._draw_color = ColorButton(hex_to_color(self._app.get_str("editor.brush_color")))
        self._thickness = QSpinBox()
        self._thickness.setRange(1, 20)
        self._thickness.setValue(self._app.get_int("editor.brush_width"))
        self._thickness.setPrefix(self.tr("Толщина: "))
        self._opacity = QSpinBox()
        self._opacity.setRange(10, 100)
        self._opacity.setSuffix("%")
        self._opacity.setValue(100)
        self._opacity.setPrefix(self.tr("Непрозрачность: "))
        for signal in (
            self._shape.currentIndexChanged,
            self._draw_color.colorChanged,
            self._thickness.valueChanged,
            self._opacity.valueChanged,
        ):
            signal.connect(self._on_draw_options)
        self._shape.currentIndexChanged.connect(self._reset_opacity_for_shape)
        hint = self._hint(
            self.tr("Кисть и маркер рисуют сразу, пока держите кнопку. Фигуры — проведите и Enter.")
        )
        return self._panel(
            self._shape,
            self._draw_color,
            self._thickness,
            self._opacity,
            hint,
            self._apply_button(),
        )

    def _on_draw_options(self) -> None:
        draw = self.tools["draw"]
        assert isinstance(draw, DrawTool)
        shape: DrawShape = self._shape.currentData()
        draw.set_options(
            shape,
            self._draw_color.color,
            self._thickness.value(),
            self._opacity.value() / 100,
        )

    def _reset_opacity_for_shape(self) -> None:
        """Маркер по умолчанию полупрозрачный, кисть и фигуры — сплошные."""
        self._opacity.setValue(40 if self._shape.currentData() == "highlighter" else 100)

    def _panel_text(self) -> QWidget:
        self._text = QLineEdit()
        self._text.setPlaceholderText(self.tr("Текст"))
        self._text_size = QSpinBox()
        self._text_size.setRange(1, 50)
        self._text_size.setValue(6)
        self._text_size.setPrefix(self.tr("Размер, % высоты: "))
        self._text_color = ColorButton((255, 255, 255))
        for signal in (
            self._text.textChanged,
            self._text_size.valueChanged,
            self._text_color.colorChanged,
        ):
            signal.connect(self._on_text_options)
        hint = self._hint(self.tr("Введите текст, кликните на фото, где он должен стоять, Enter."))
        return self._panel(
            self._text, self._text_size, self._text_color, hint, self._apply_button()
        )

    def _on_text_options(self) -> None:
        text_tool = self.tools["text"]
        assert isinstance(text_tool, TextTool)
        text_tool.set_options(
            self._text.text(), float(self._text_size.value()), self._text_color.color
        )

    def _panel_adjust(self) -> QWidget:
        self._sliders: dict[str, QSlider] = {}
        rows: list[QWidget] = []
        for key, label in (
            ("brightness", self.tr("Яркость")),
            ("contrast", self.tr("Контраст")),
            ("saturation", self.tr("Насыщенность")),
            ("gamma", self.tr("Гамма")),
        ):
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(-100, 100)
            slider.valueChanged.connect(self._on_adjust_sliders)
            self._sliders[key] = slider
            rows.extend((QLabel(label), slider))
        reset = QPushButton(self.tr("Сбросить ползунки"))
        reset.clicked.connect(self._reset_sliders)
        reset.clicked.connect(self._on_adjust_sliders)
        filters: list[QWidget] = []
        for text, name in (
            (self.tr("Чёрно-белое"), "grayscale"),
            (self.tr("Сепия"), "sepia"),
            (self.tr("Резкость"), "sharpen"),
            (self.tr("Размытие всего кадра"), "blur"),
        ):
            button = QPushButton(text)
            button.clicked.connect(lambda _checked=False, n=name: self.session.add_full(Filter(n)))
            filters.append(button)
        grid = QWidget()
        cells = QGridLayout(grid)
        cells.setContentsMargins(0, 0, 0, 0)
        cells.setHorizontalSpacing(tokens.SPACE_4)
        for index in range(0, len(rows), 2):
            column = index // 2
            cells.addWidget(rows[index], 0, column)
            cells.addWidget(rows[index + 1], 1, column)
        cells.addWidget(reset, 1, 4)
        cells.addWidget(self._apply_button(), 0, 4)
        strip = QWidget()
        buttons = QHBoxLayout(strip)
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.addWidget(QLabel(self.tr("Фильтры")))
        for chip in filters:
            buttons.addWidget(chip)
        buttons.addStretch(1)
        wrapper = QWidget()
        stack = QVBoxLayout(wrapper)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.addWidget(grid)
        stack.addWidget(strip)
        return wrapper

    def _on_adjust_sliders(self) -> None:
        if self._syncing:
            return
        values = {key: slider.value() for key, slider in self._sliders.items()}
        adjust = self.tools["adjust"]
        assert isinstance(adjust, AdjustTool)
        adjust.set_values(
            Adjust(
                brightness=1 + values["brightness"] / 100,
                contrast=1 + values["contrast"] / 100,
                saturation=1 + values["saturation"] / 100,
                gamma=2 ** (values["gamma"] / 50),
            )
        )

    def _reset_sliders(self) -> None:
        self._syncing = True
        for slider in self._sliders.values():
            slider.setValue(0)
        self._syncing = False

    def _panel_resize(self) -> QWidget:
        self._width = QSpinBox()
        self._height = QSpinBox()
        for box, prefix in (
            (self._width, self.tr("Ширина: ")),
            (self._height, self.tr("Высота: ")),
        ):
            box.setRange(1, 20000)
            box.setPrefix(prefix)
        self._keep_ratio = QCheckBox(self.tr("Сохранять пропорции"))
        self._keep_ratio.setChecked(True)
        self._width.valueChanged.connect(lambda v: self._on_size_edit(True, v))
        self._height.valueChanged.connect(lambda v: self._on_size_edit(False, v))
        apply = QPushButton(self.tr("Изменить размер"))
        apply.clicked.connect(self._apply_resize)
        return self._panel(self._width, self._height, self._keep_ratio, apply)

    def _on_size_edit(self, width_changed: bool, value: int) -> None:
        if self._syncing or not self._keep_ratio.isChecked():
            return
        current_w, current_h = self.session.output_size()
        self._syncing = True
        if width_changed:
            self._height.setValue(max(1, round(value * current_h / current_w)))
        else:
            self._width.setValue(max(1, round(value * current_w / current_h)))
        self._syncing = False

    def _apply_resize(self) -> None:
        self.session.add_full(Resize(self._width.value(), self._height.value()))

    # --- выбор инструмента -------------------------------------------------------------------

    def select_tool(self, key: str | None) -> None:
        previous = self._active_tool()
        if previous is not None:
            previous.reset()
        if key == self._selected:
            key = None  # повторный клик снимает инструмент
        self._selected = key
        self._active = key if key in self.tools else None
        for name, button in self._buttons.items():
            button.setChecked(name == key)
        self._stack.setCurrentIndex(self._panel_index[key] if key else 0)
        self._stack.setVisible(key is not None)
        # у цветокоррекции мыши нет, только ползунки
        mouse_tool = self._active_tool() if key != "adjust" else None
        self.canvas.set_tool(mouse_tool)
        self._select_whole_frame()
        self._drop_pending()
        self._update_canvas()

    def _select_whole_frame(self) -> None:
        """Кадрирование начинается с рамки по всему кадру, а не с пустого холста."""
        tool = self._active_tool()
        if isinstance(tool, CropTool) and tool.selection.rect is None:
            tool.select_all()

    def _active_tool(self) -> Tool | None:
        return self.tools[self._active] if self._active else None

    # --- применение --------------------------------------------------------------------------

    def apply_pending(self) -> None:
        tool = self._active_tool()
        if tool is None:
            return
        op = tool.pending_operation()
        if op is None:
            if isinstance(tool, CropTool):
                self.message.emit(
                    self.tr("Рамка совпадает с кадром: потяните край, чтобы обрезать")
                )
            else:
                self.message.emit(self.tr("Сначала выделите область или задайте параметры"))
            return
        # если операция уже посчитана для предпросмотра, повторно движок её не гоняет
        rendered = self._pending[1] if self._pending and self._pending[0] == op else None
        tool.commit()
        if isinstance(tool, AdjustTool):
            self._reset_sliders()
        self._committing = True
        self.session.cancel_pending()
        self.session.add(op, rendered)

    def escape(self) -> None:
        """Esc: сначала отменяет незавершённое действие, затем выходит из редактора."""
        tool = self._active_tool()
        if tool is not None and tool.pending_operation() is not None:
            tool.reset()
            if isinstance(tool, AdjustTool):
                self._reset_sliders()
            return
        self.request_exit()

    def has_pending(self) -> bool:
        """Есть ли активное выделение или незавершённое действие инструмента."""
        tool = self._active_tool()
        return tool is not None and tool.pending_operation() is not None

    def reset_selection(self) -> None:
        tool = self._active_tool()
        if tool is not None:
            tool.reset()
            if isinstance(tool, AdjustTool):
                self._reset_sliders()

    def session_can_undo(self) -> bool:
        return self.session.history.can_undo

    def session_can_redo(self) -> bool:
        return self.session.history.can_redo

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802
        if menu_allowed():
            self.menuRequested.emit(event.globalPos())
            event.accept()

    def undo(self) -> None:
        self.session.undo()

    def redo(self) -> None:
        self.session.redo()

    # --- отображение -------------------------------------------------------------------------

    def is_busy(self) -> bool:
        """Идёт ли расчёт картинки (для тестов и бенчмарков)."""
        return self._timer.isActive() or self.session.is_busy or self._committing

    def refresh(self) -> None:
        """Список операций изменился: сразу обновляем кнопки, картинку считает фон."""
        self._undo_button.setEnabled(self.session.history.can_undo)
        self._redo_button.setEnabled(self.session.history.can_redo)
        width, height = self.session.output_size()
        self._syncing = True
        self._width.setValue(width)
        self._height.setValue(height)
        self._syncing = False
        marker = " *" if self.session.modified else ""
        self._info.setText(f"{width}×{height}{marker}")
        self.session.request_preview()

    def _on_preview_ready(self) -> None:
        self._committing = False
        preview = self.session.preview()
        scale = self.session.preview_scale()
        for tool in self.tools.values():
            tool.set_bounds(preview.width, preview.height)
            if isinstance(tool, RectSelectTool):
                tool.size_scale = scale  # плашка размера показывает размер результата
            tool.end_commit()
        self._select_whole_frame()  # после обрезки рамка снова охватывает новый кадр
        self._drop_pending()
        self._update_canvas()

    def _on_preview_failed(self, error: str) -> None:
        self._committing = False
        self.message.emit(self.tr("Ошибка: ") + error)

    def _drop_pending(self) -> None:
        self.session.cancel_pending()
        self._pending = None
        self._shown_key = None

    def _on_tool_changed(self) -> None:
        self._timer.start()  # холст сам перерисует нужную область; тяжёлое — после паузы

    def _update_canvas(self) -> None:
        if self._committing:
            return  # на экране остаётся прежняя картинка и след инструмента
        tool = self._active_tool()
        pending = tool.pending_operation() if tool is not None and tool.live else None
        if pending is None:
            if self._pending is not None:
                self._drop_pending()
            self._show_base()
        elif self._pending is None or self._pending[0] != pending:
            self.session.request_pending(pending)

    def _show_base(self) -> None:
        preview = self.session.preview()
        key = ("base", id(preview))
        if key == self._shown_key:
            return
        self._shown_key = key
        if self._base_qimage is None or self._base_qimage[0] != id(preview):
            self._base_qimage = (id(preview), pil_to_qimage(preview))
        self.canvas.set_image(self._base_qimage[1])

    def _on_pending_ready(self, op: Operation, image: Image.Image, frame: object) -> None:
        tool = self._active_tool()
        if tool is None or not tool.live or tool.pending_operation() != op:
            return  # пока считали, параметры изменились: придёт более свежий ответ
        self._pending = (op, image)
        self._shown_key = ("pending", id(image))
        self.canvas.set_image(frame if isinstance(frame, QImage) else pil_to_qimage(image))

    # --- сохранение и буфер обмена -----------------------------------------------------------

    def _quality_for(self, fmt: str) -> int:
        key = {"jpeg": "editor.jpeg_quality", "webp": "editor.webp_quality"}.get(fmt)
        return self._app.get_int(key) if key else 92

    def _default_path(self, fmt: str) -> Path:
        folder = self._app.get_str("editor.output_dir")
        return default_output_path(
            self.session.source,
            fmt,
            Path(folder) if folder else None,
            self._app.get_str("editor.output_template"),
        )

    def save_quick(self) -> None:
        fmt = format_for_source(self.session.source)
        self.message.emit(self.tr("Сохранение…"))
        self.export_strip.start(self.tr("Сохранение…"), indeterminate=True)
        self.session.export(
            self._default_path(fmt),
            fmt,
            self._quality_for(fmt),
            keep_metadata=not self._app.get_bool("editor.strip_metadata"),
        )

    def save_as(self) -> None:
        source = self.session.source
        dialog = ExportDialog(source, format_for_source(source), self, self._app)
        if not dialog.exec():
            return
        choice = dialog.choice()
        path = choice.path
        if source is not None and path.resolve() == source.resolve():
            path = self._default_path(choice.fmt)  # исходник не перезаписывается
            self.message.emit(
                self.tr("Исходный файл не перезаписывается, сохраняю как ") + path.name
            )
        self.export_strip.start(self.tr("Сохранение…"), indeterminate=True)
        self.session.export(path, choice.fmt, choice.quality, choice.keep_metadata)

    def _cancel_export(self) -> None:
        self.export_strip.cancelling()
        self.session.cancel_export()

    def _on_export_cancelled(self) -> None:
        self.export_strip.finish()
        self.message.emit(self.tr("Сохранение отменено"))
        self.toast.show_message(self.tr("Сохранение отменено"), "info")
        self._exit_after_save = False

    def _on_export_failed(self, error: str) -> None:
        self.export_strip.finish()
        self._exit_after_save = False
        self.message.emit(self.tr("Ошибка: ") + error)
        self.toast.show_message(self.tr("Не удалось сохранить: ") + error, "error")

    def _on_exported(self, path: Path) -> None:
        self.export_strip.finish()
        self.message.emit(self.tr("Сохранено: ") + str(path))
        self.toast.show_message(
            self.tr("Сохранено: ") + path.name,
            "success",
            self.tr("Показать в папке"),
            lambda: reveal_in_folder(path),
        )
        self.refresh()
        if self._exit_after_save:
            self._exit_after_save = False
            self.exitRequested.emit()

    def copy_result(self) -> None:
        self.message.emit(self.tr("Копирование…"))
        self.session.render_full(self._on_full_rendered)

    def _on_full_rendered(self, image: Image.Image) -> None:
        clipboard: QImage = pil_to_qimage(image)
        QApplication.clipboard().setImage(clipboard)
        self.message.emit(self.tr("Скопировано в буфер обмена"))

    # --- выход -------------------------------------------------------------------------------

    def request_exit(self) -> None:
        if not self.session.modified:
            self.exitRequested.emit()
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(self.tr("Несохранённые правки"))
        box.setText(self.tr("Сохранить изменения перед выходом из редактора?"))
        save = box.addButton(self.tr("Сохранить"), QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton(self.tr("Не сохранять"), QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(self.tr("Отмена"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is save:
            self._exit_after_save = True
            self.save_quick()
        elif box.clickedButton() is discard:
            self.exitRequested.emit()
