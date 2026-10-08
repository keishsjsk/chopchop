"""Панель эффектов видео: кадр, скрытие области, текст, цвет и фильтры, поворот."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from chopchop.core.operations import Crop, Operation, Redact, RedactMode, Text
from chopchop.editor.video_session import VideoSession
from chopchop.ui.color_button import ColorButton
from chopchop.ui.crop_ratio import CropRatioBar
from chopchop.ui.tools.base import Tool
from chopchop.ui.tools.crop_tool import CropTool
from chopchop.ui.tools.redact_tool import RedactTool
from chopchop.ui.tools.text_tool import TextTool
from chopchop.ui.video_color_dialog import VideoColorDialog
from chopchop.ui.video_overlay import VideoOverlay

TOOL_LABELS = {"crop": "Кадр", "redact": "Скрыть", "text": "Текст"}
TOOL_KEYS = {"crop": "C", "redact": "B", "text": "T"}


class VideoEffectsPanel(QWidget):
    message = Signal(str)
    colorPreview = Signal(object, object)  # Adjust, имя фильтра: пока открыт диалог цвета
    colorPreviewEnded = Signal()

    def __init__(
        self, session: VideoSession, overlay: VideoOverlay, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.overlay = overlay
        crop = CropTool(self)
        redact = RedactTool(self)
        text = TextTool(self)
        text.draw_preview = True
        self.tools: dict[str, Tool] = {"crop": crop, "redact": redact, "text": text}
        self._active: str | None = None
        self._build_ui()
        for tool in self.tools.values():
            tool.changed.connect(self.overlay.update)
        self.refresh()

    # --- интерфейс ---------------------------------------------------------------------------

    def _build_ui(self) -> None:
        self._buttons: dict[str, QToolButton] = {}
        row = QHBoxLayout()
        row.addWidget(QLabel(self.tr("Эффекты:")))
        for name, label in TOOL_LABELS.items():
            button = QToolButton()
            button.setText(f"{self.tr(label)} [{TOOL_KEYS[name]}]")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, n=name: self.select_tool(n))
            self._buttons[name] = button
            row.addWidget(button)
        color = QPushButton(self.tr("Цвет и фильтры…"))
        color.clicked.connect(self.open_color_dialog)
        row.addWidget(color)
        rotate = QToolButton()
        rotate.setText(self.tr("Поворот ▾"))
        rotate.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(rotate)
        menu.addAction(self.tr("Влево на 90°"), lambda: self.session.rotate(270))
        menu.addAction(self.tr("Вправо на 90°"), lambda: self.session.rotate(90))
        menu.addAction(self.tr("Отразить по горизонтали"), lambda: self.session.flip(True))
        menu.addAction(self.tr("Отразить по вертикали"), lambda: self.session.flip(False))
        rotate.setMenu(menu)
        row.addWidget(rotate)
        self._reset = QPushButton(self.tr("Сбросить эффекты"))
        self._reset.clicked.connect(self.session.clear_effects)
        row.addWidget(self._reset)
        row.addStretch(1)
        self._summary = QLabel()
        row.addWidget(self._summary)

        self._options = QStackedWidget()
        self._options.addWidget(QWidget())
        self._option_index = {
            "crop": self._options.addWidget(self._crop_options()),
            "redact": self._options.addWidget(self._redact_options()),
            "text": self._options.addWidget(self._text_options()),
        }
        self._options.setFixedHeight(self._options.sizeHint().height())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(row)
        layout.addWidget(self._options)

    def _apply_button(self) -> QPushButton:
        button = QPushButton(self.tr("Применить (Enter)"))
        button.clicked.connect(self.apply_pending)
        return button

    def _crop_options(self) -> QWidget:
        panel = QWidget()
        row = QHBoxLayout(panel)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel(self.tr("Пропорции:")))
        self._ratio_bar = CropRatioBar()
        self._ratio_bar.ratioChanged.connect(self._on_ratio_changed)
        row.addWidget(self._ratio_bar)
        row.addWidget(QLabel(self.tr("Рамка по всему кадру, тяните края.")))
        row.addWidget(self._apply_button())
        remove = QPushButton(self.tr("Убрать кадр"))
        remove.clicked.connect(self.remove_crop)
        row.addWidget(remove)
        row.addStretch(1)
        return panel

    def _redact_options(self) -> QWidget:
        panel = QWidget()
        row = QHBoxLayout(panel)
        row.setContentsMargins(0, 0, 0, 0)
        self._redact_mode = QComboBox()
        self._redact_mode.addItem(self.tr("Заливка (надёжно)"), "fill")
        self._redact_mode.addItem(self.tr("Пикселизация"), "pixelate")
        self._redact_mode.addItem(self.tr("Размытие"), "blur")
        self._redact_mode.currentIndexChanged.connect(self._on_redact_mode)
        self._redact_hint = QLabel(
            self.tr("Размытый или пикселизированный текст можно частично восстановить.")
        )
        self._redact_hint.hide()
        row.addWidget(self._redact_mode)
        row.addWidget(self._apply_button())
        row.addWidget(self._redact_hint)
        row.addStretch(1)
        return panel

    def _on_ratio_changed(self, ratio: object) -> None:
        crop = self.tools["crop"]
        assert isinstance(crop, CropTool)
        crop.set_ratio(ratio)  # type: ignore[arg-type]

    def _on_redact_mode(self) -> None:
        mode: RedactMode = self._redact_mode.currentData()
        tool = self.tools["redact"]
        assert isinstance(tool, RedactTool)
        tool.set_mode(mode)
        self._redact_hint.setVisible(mode != "fill")

    def _text_options(self) -> QWidget:
        panel = QWidget()
        row = QHBoxLayout(panel)
        row.setContentsMargins(0, 0, 0, 0)
        self._text = QLineEdit()
        self._text.setPlaceholderText(self.tr("Текст (на всё видео)"))
        self._text_size = QSpinBox()
        self._text_size.setRange(1, 50)
        self._text_size.setValue(6)
        self._text_size.setPrefix(self.tr("Размер, % высоты: "))
        self._text_color = ColorButton((255, 255, 255))
        self._text_color.setFixedWidth(40)
        for signal in (
            self._text.textChanged,
            self._text_size.valueChanged,
            self._text_color.colorChanged,
        ):
            signal.connect(self._on_text_options)
        row.addWidget(self._text, 1)
        row.addWidget(self._text_size)
        row.addWidget(self._text_color)
        row.addWidget(QLabel(self.tr("Кликните на видео, где поставить")))
        row.addWidget(self._apply_button())
        return panel

    def _on_text_options(self) -> None:
        tool = self.tools["text"]
        assert isinstance(tool, TextTool)
        tool.set_options(self._text.text(), float(self._text_size.value()), self._text_color.color)

    # --- инструменты -------------------------------------------------------------------------

    @property
    def active(self) -> str | None:
        return self._active

    def _active_tool(self) -> Tool | None:
        return self.tools[self._active] if self._active else None

    def select_tool(self, name: str) -> None:
        if name not in self.tools:
            return
        previous = self._active_tool()
        if previous is not None:
            previous.reset()
        self._active = None if name == self._active else name
        for key, button in self._buttons.items():
            button.setChecked(key == self._active)
        tool = self._active_tool()
        self._options.setCurrentIndex(self._option_index[self._active] if self._active else 0)
        self._frame_selection()
        self.overlay.set_tool(tool)

    def _frame_selection(self) -> None:
        """Рамка кадрирования: прежний кадр (его можно подправить) или весь кадр."""
        tool = self._active_tool()
        if not isinstance(tool, CropTool) or tool.selection.rect is not None:
            return
        existing = self.session.project.effects.crop
        if existing is not None:
            tool.selection.rect = existing
            tool.changed.emit()
        else:
            tool.select_all()

    def remove_crop(self) -> None:
        """Убрать кадр: рамка снова охватывает весь кадр видео."""
        self.session.set_crop(None)
        tool = self._active_tool()
        if isinstance(tool, CropTool):
            tool.select_all()

    def _deselect(self) -> None:
        if self._active is not None:
            self.select_tool(self._active)

    def _pending(self, tool: Tool | None) -> Operation | None:
        """Незавершённое действие; рамка, равная уже применённому кадру, не считается."""
        if tool is None:
            return None
        op = tool.pending_operation()
        if isinstance(op, Crop) and op.rect == self.session.project.effects.crop:
            return None
        return op

    def has_pending(self) -> bool:
        return self._pending(self._active_tool()) is not None

    def apply_pending(self) -> None:
        tool = self._active_tool()
        if tool is None:
            return
        op = self._pending(tool)
        if op is None:
            self.message.emit(self.tr("Сначала выделите область или введите текст"))
            return
        tool.reset()
        if isinstance(op, Crop):
            self.session.set_crop(op.rect)
        elif isinstance(op, Redact):
            self.session.add_redact(op)
        elif isinstance(op, Text):
            self.session.add_text(op)

    def escape(self) -> bool:
        """Esc: отменить незавершённое действие или снять инструмент; False — делать нечего."""
        tool = self._active_tool()
        if tool is None:
            return False
        if self._pending(tool) is not None:
            tool.reset()
        else:
            self._deselect()
        return True

    # --- цвет --------------------------------------------------------------------------------

    def open_color_dialog(self) -> None:
        effects = self.session.project.effects
        dialog = VideoColorDialog(effects.adjust, effects.filter, self)
        dialog.previewChanged.connect(self.colorPreview)
        accepted = dialog.exec()
        if accepted:
            self.session.set_adjust(dialog.adjust())
            self.session.set_filter(dialog.filter_name())
        self.colorPreviewEnded.emit()

    # --- обновление --------------------------------------------------------------------------

    def refresh(self) -> None:
        project = self.session.project
        effects = project.effects
        size = project.frame_size
        for tool in self.tools.values():
            tool.set_bounds(float(size[0]), float(size[1]))
        self.overlay.set_frame_size(size)
        self.overlay.set_crop(effects.crop)
        note = ""
        if effects.rotation or effects.flip_h or effects.flip_v:
            note = self.tr("Поворот и отражение применятся при экспорте")
        self.overlay.set_rotation_note(note)
        parts = effects.describe()
        self._summary.setText(", ".join(parts) if parts else self.tr("без эффектов"))
        self._reset.setEnabled(not effects.is_default)
        self._frame_selection()  # после применения рамка снова охватывает кадр
