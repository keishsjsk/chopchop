"""Страница редактора фото: панель инструментов, холст, отмена и повтор, сохранение."""

from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
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
from chopchop.ui.canvas import Canvas
from chopchop.ui.color_button import ColorButton
from chopchop.ui.crop_ratio import CropRatioBar
from chopchop.ui.export_dialog import ExportDialog
from chopchop.ui.pil_qt import pil_to_qimage
from chopchop.ui.tools.adjust_tool import AdjustTool
from chopchop.ui.tools.base import Tool
from chopchop.ui.tools.crop_tool import CropTool
from chopchop.ui.tools.draw_tool import DrawShape, DrawTool
from chopchop.ui.tools.redact_tool import RedactTool
from chopchop.ui.tools.text_tool import TextTool

PANEL_WIDTH = 240
REFRESH_MS = 15


class EditorPage(QWidget):
    exitRequested = Signal()
    message = Signal(str)

    def __init__(self, session: EditSession, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
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
        self._rendered_key: tuple[int, Operation | None] | None = None
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
        self._on_draw_options()  # инструмент берёт то, что выбрано в панели
        session.changed.connect(self.refresh)
        session.exported.connect(self._on_exported)
        session.exportFailed.connect(lambda err: self.message.emit(self.tr("Ошибка: ") + err))
        self.refresh()

    # --- построение интерфейса ---------------------------------------------------------------

    def _build_ui(self) -> None:
        back = QPushButton(self.tr("← К просмотру"))
        back.clicked.connect(self.request_exit)
        self._undo_button = QPushButton(self.tr("Отменить"))
        self._undo_button.clicked.connect(self.undo)
        self._redo_button = QPushButton(self.tr("Повторить"))
        self._redo_button.clicked.connect(self.redo)
        copy = QPushButton(self.tr("Копировать"))
        copy.clicked.connect(self.copy_result)
        save = QPushButton(self.tr("Сохранить"))
        save.clicked.connect(self.save_quick)
        save_as = QPushButton(self.tr("Сохранить как…"))
        save_as.clicked.connect(self.save_as)
        self._info = QLabel()

        top = QHBoxLayout()
        for widget in (back, self._undo_button, self._redo_button, copy, save, save_as):
            top.addWidget(widget)
        top.addStretch(1)
        top.addWidget(self._info)

        tool_column = QVBoxLayout()
        self._stack = QStackedWidget()
        self._stack.setFixedWidth(PANEL_WIDTH)
        group = QButtonGroup(self)
        group.setExclusive(False)
        self._buttons: dict[str, QToolButton] = {}
        entries = [
            ("crop", self.tr("Кадрировать"), "C", self._panel_crop()),
            ("rotate", self.tr("Повернуть"), "R", self._panel_rotate()),
            ("redact", self.tr("Скрыть"), "B", self._panel_redact()),
            ("draw", self.tr("Рисовать"), "D", self._panel_draw()),
            ("text", self.tr("Текст"), "T", self._panel_text()),
            ("adjust", self.tr("Цвет и фильтры"), "", self._panel_adjust()),
            ("resize", self.tr("Размер"), "", self._panel_resize()),
        ]
        self._stack.addWidget(QWidget())  # индекс 0: инструмент не выбран
        self._panel_index: dict[str, int] = {}
        for key, label, letter, panel in entries:
            button = QToolButton()
            button.setText(f"{label}  [{letter}]" if letter else label)
            button.setCheckable(True)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            button.setFixedWidth(PANEL_WIDTH)
            button.clicked.connect(lambda _checked=False, k=key: self.select_tool(k))
            group.addButton(button)
            tool_column.addWidget(button)
            self._buttons[key] = button
            self._panel_index[key] = self._stack.addWidget(panel)
        tool_column.addSpacing(8)
        tool_column.addWidget(self._stack)
        tool_column.addStretch(1)

        body = QHBoxLayout()
        body.addLayout(tool_column)
        body.addWidget(self.canvas, 1)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addLayout(body, 1)

    def _apply_button(self) -> QPushButton:
        button = QPushButton(self.tr("Применить (Enter)"))
        button.clicked.connect(self.apply_pending)
        return button

    def _panel(self, *widgets: QWidget) -> QWidget:
        panel = QWidget()
        column = QVBoxLayout(panel)
        column.setContentsMargins(0, 0, 0, 0)
        for widget in widgets:
            column.addWidget(widget)
        column.addStretch(1)
        return panel

    def _hint(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
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
        self._draw_color = ColorButton((255, 0, 0))
        self._thickness = QSpinBox()
        self._thickness.setRange(1, 20)
        self._thickness.setValue(4)
        self._thickness.setPrefix(self.tr("Толщина: "))
        for signal in (
            self._shape.currentIndexChanged,
            self._draw_color.colorChanged,
            self._thickness.valueChanged,
        ):
            signal.connect(self._on_draw_options)
        hint = self._hint(
            self.tr("Кисть и маркер рисуют сразу, пока держите кнопку. Фигуры — проведите и Enter.")
        )
        return self._panel(
            self._shape, self._draw_color, self._thickness, hint, self._apply_button()
        )

    def _on_draw_options(self) -> None:
        draw = self.tools["draw"]
        assert isinstance(draw, DrawTool)
        shape: DrawShape = self._shape.currentData()
        draw.set_options(shape, self._draw_color.color, self._thickness.value())

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
        return self._panel(*rows, reset, self._apply_button(), QLabel(self.tr("Фильтры")), *filters)

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
        # у цветокоррекции мыши нет, только ползунки
        mouse_tool = self._active_tool() if key != "adjust" else None
        self.canvas.set_tool(mouse_tool)
        self._select_whole_frame()
        self._rendered_key = None
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
        tool.reset()
        if isinstance(tool, AdjustTool):
            self._reset_sliders()
        self.session.add(op)

    def escape(self) -> None:
        """Esc: сначала отменяет незавершённое действие, затем выходит из редактора."""
        tool = self._active_tool()
        if tool is not None and tool.pending_operation() is not None:
            tool.reset()
            if isinstance(tool, AdjustTool):
                self._reset_sliders()
            return
        self.request_exit()

    def undo(self) -> None:
        self.session.undo()

    def redo(self) -> None:
        self.session.redo()

    # --- отображение -------------------------------------------------------------------------

    def refresh(self) -> None:
        preview = self.session.preview()
        for tool in self.tools.values():
            tool.set_bounds(preview.width, preview.height)
        self._select_whole_frame()  # после обрезки рамка снова охватывает новый кадр
        self._rendered_key = None
        self._update_canvas()
        self._undo_button.setEnabled(self.session.history.can_undo)
        self._redo_button.setEnabled(self.session.history.can_redo)
        width, height = self.session.output_size()
        self._syncing = True
        self._width.setValue(width)
        self._height.setValue(height)
        self._syncing = False
        marker = " *" if self.session.modified else ""
        self._info.setText(f"{width}×{height}{marker}")

    def _on_tool_changed(self) -> None:
        self._timer.start()
        self.canvas.update()

    def _update_canvas(self) -> None:
        preview = self.session.preview()
        tool = self._active_tool()
        pending = tool.pending_operation() if tool is not None and tool.live else None
        key = (id(preview), pending)
        if key == self._rendered_key:
            return
        self._rendered_key = key
        image = self.session.render_with(pending) if pending is not None else preview
        self.canvas.set_image(pil_to_qimage(image))

    # --- сохранение и буфер обмена -----------------------------------------------------------

    def save_quick(self) -> None:
        fmt = format_for_source(self.session.source)
        dest = default_output_path(self.session.source, fmt)
        self.message.emit(self.tr("Сохранение…"))
        self.session.export(dest, fmt)

    def save_as(self) -> None:
        source = self.session.source
        dialog = ExportDialog(source, format_for_source(source), self)
        if not dialog.exec():
            return
        choice = dialog.choice()
        path = choice.path
        if source is not None and path.resolve() == source.resolve():
            path = default_output_path(source, choice.fmt)  # исходник не перезаписывается
            self.message.emit(
                self.tr("Исходный файл не перезаписывается, сохраняю как ") + path.name
            )
        self.session.export(path, choice.fmt, choice.quality, choice.keep_metadata)

    def _on_exported(self, path: Path) -> None:
        self.message.emit(self.tr("Сохранено: ") + str(path))
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
