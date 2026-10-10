"""Эффекты видео: кадр, скрытие области, текст, цвет и фильтры, поворот.

Класс не рисуется сам: он держит инструменты поверх видео, состояние «что выбрано» и собирает
панели параметров для контекстной панели оболочки (по одной на пункт рейки).
"""

from dataclasses import replace

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QSpinBox, QWidget

from chopchop.core.operations import Crop, Operation, Redact, Text
from chopchop.core.tr_marks import QT_TRANSLATE_NOOP
from chopchop.editor.video_session import VideoSession
from chopchop.ui.color_button import ColorButton
from chopchop.ui.crop_ratio import RatioChips
from chopchop.ui.theme import tokens
from chopchop.ui.time_window import TimeWindow
from chopchop.ui.tools.base import Tool
from chopchop.ui.tools.crop_tool import CropTool
from chopchop.ui.tools.redact_tool import RedactTool
from chopchop.ui.tools.text_tool import TextTool
from chopchop.ui.video_color_panel import ColorPanel
from chopchop.ui.video_overlay import VideoOverlay
from chopchop.ui.widgets import Segmented, button, tip

# пункты рейки: ключ, значок, название, клавиша (пустая — клавиши нет)
RAIL_ITEMS = (
    ("crop", "crop", QT_TRANSLATE_NOOP("VideoEffectsPanel", "Кадрировать"), "C"),
    ("redact", "redact", QT_TRANSLATE_NOOP("VideoEffectsPanel", "Скрыть область"), "B"),
    ("text", "text", QT_TRANSLATE_NOOP("VideoEffectsPanel", "Текст"), "T"),
    ("adjust", "sliders", QT_TRANSLATE_NOOP("VideoEffectsPanel", "Цвет и фильтры"), ""),
    ("rotate", "rotate", QT_TRANSLATE_NOOP("VideoEffectsPanel", "Поворот и отражение"), "R"),
    ("audio", "volume", QT_TRANSLATE_NOOP("VideoEffectsPanel", "Звук"), ""),
)
HINTS = {
    "crop": QT_TRANSLATE_NOOP(
        "VideoEffectsPanel", "Перетащите рамку на видео, Enter — применить, Esc — отмена"
    ),
    "redact": QT_TRANSLATE_NOOP(
        "VideoEffectsPanel", "Выделите область на видео, Enter — применить, Esc — отмена"
    ),
    "text": QT_TRANSLATE_NOOP(
        "VideoEffectsPanel",
        "Введите текст и кликните на видео, где его поставить, Enter — применить, Esc — отмена",
    ),
    "adjust": QT_TRANSLATE_NOOP(
        "VideoEffectsPanel", "Изменения видны сразу, в файл попадут при экспорте"
    ),
    "rotate": QT_TRANSLATE_NOOP("VideoEffectsPanel", "Поворот и отражение применятся при экспорте"),
    "audio": QT_TRANSLATE_NOOP(
        "VideoEffectsPanel", "Громкость, замена и отключение звука применятся при экспорте"
    ),
}
IDLE_HINT = QT_TRANSLATE_NOOP(
    "VideoEffectsPanel", "Выберите инструмент слева. Пробел — пауза, I и O — границы фрагмента"
)


class VideoEffectsPanel(QObject):
    message = Signal(str)
    colorPreview = Signal(object, object)  # Adjust, имя фильтра: пока двигают ползунки
    colorPreviewEnded = Signal()
    selectionChanged = Signal(object)  # ключ выбранного пункта или None
    hintChanged = Signal(str)

    def __init__(
        self, session: VideoSession, overlay: VideoOverlay, parent: QObject | None = None
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
        self.panels: dict[str, QWidget] = {}
        self._build()
        for tool in self.tools.values():
            tool.changed.connect(self.overlay.update)
        self.refresh()

    # --- панели параметров -------------------------------------------------------------------

    def _build(self) -> None:
        self.panels["crop"] = self._crop_panel()
        self.panels["redact"] = self._redact_panel()
        self.panels["text"] = self._text_panel()
        self.panels["adjust"] = self._color_panel()
        self.panels["rotate"] = self._rotate_panel()

    def _row(self, *widgets: QWidget) -> QWidget:
        panel = QWidget()
        row = QHBoxLayout(panel)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(tokens.SPACE_3)
        for widget in widgets:
            row.addWidget(widget)
        row.addStretch(1)
        return panel

    def _apply_button(self) -> QWidget:
        return button(
            self.tr("Применить"),
            "primary",
            tooltip=tip(self.tr("Применить"), "Enter"),
            slot=self.apply_pending,
        )

    def _cancel_button(self) -> QWidget:
        return button(self.tr("Отмена"), tooltip=tip(self.tr("Отмена"), "Esc"), slot=self.escape)

    def _crop_panel(self) -> QWidget:
        self._ratio = RatioChips()
        self._ratio.ratioChanged.connect(self._on_ratio_changed)
        remove = button(self.tr("Убрать кадр"), slot=self.remove_crop)
        return self._row(self._ratio, self._apply_button(), remove)

    def _on_ratio_changed(self, ratio: object) -> None:
        crop = self.tools["crop"]
        assert isinstance(crop, CropTool)
        crop.set_ratio(ratio)  # type: ignore[arg-type]

    def _redact_panel(self) -> QWidget:
        self._modes = Segmented()
        self._modes.add(
            self.tr("Заливка"), "fill", self.tr("Заливка: надёжно скрывает любой текст")
        )
        self._modes.add(self.tr("Размытие"), "blur")
        self._modes.add(self.tr("Пикселизация"), "pixelate")
        self._modes.set_value("fill")
        self._modes.changed.connect(self._on_redact_mode)
        self._redact_hint = QLabel()
        self._redact_hint.setProperty("muted", True)
        self._on_redact_mode("fill")
        self.redact_time = TimeWindow()
        return self._row(
            self._modes,
            self._redact_hint,
            self.redact_time,
            self._apply_button(),
            self._cancel_button(),
        )

    def _on_redact_mode(self, mode: object) -> None:
        tool = self.tools["redact"]
        assert isinstance(tool, RedactTool)
        tool.set_mode(mode)  # type: ignore[arg-type]
        if mode == "fill":
            self._redact_hint.setText(self.tr("Заливку не восстановить: берите её для паролей"))
        else:
            self._redact_hint.setText(self.tr("Размытый текст можно частично восстановить"))

    def _text_panel(self) -> QWidget:
        self._text = QLineEdit()
        self._text.setPlaceholderText(self.tr("Текст (на всё видео)"))
        self._text.setMinimumWidth(11 * tokens.SPACE_4)
        self._text.setAccessibleName(self.tr("Текст"))
        self._text_size = QSpinBox()
        self._text_size.setRange(1, 50)
        self._text_size.setValue(6)
        self._text_size.setSuffix(" %")
        self._text_size.setToolTip(self.tr("Размер, % высоты кадра"))
        self._text_color = ColorButton((255, 255, 255))
        self._text_color.setFixedWidth(tokens.BUTTON_HEIGHT)
        self._text_color.setToolTip(self.tr("Цвет текста"))
        for signal in (
            self._text.textChanged,
            self._text_size.valueChanged,
            self._text_color.colorChanged,
        ):
            signal.connect(self._on_text_options)
        size_label = QLabel(self.tr("Размер"))
        size_label.setProperty("muted", True)
        self.text_time = TimeWindow()
        return self._row(
            self._text,
            size_label,
            self._text_size,
            self._text_color,
            self.text_time,
            self._apply_button(),
            self._cancel_button(),
        )

    def _on_text_options(self) -> None:
        tool = self.tools["text"]
        assert isinstance(tool, TextTool)
        tool.set_options(self._text.text(), float(self._text_size.value()), self._text_color.color)

    def _color_panel(self) -> QWidget:
        effects = self.session.project.effects
        self.color = ColorPanel(effects.adjust, effects.filter)
        self.color.previewChanged.connect(self.colorPreview)
        self.color.committed.connect(self._commit_color)
        return self.color

    def _commit_color(self, adjust: object, filter_name: object) -> None:
        self.session.set_adjust(adjust)  # type: ignore[arg-type]
        self.session.set_filter(filter_name)  # type: ignore[arg-type]
        self.colorPreviewEnded.emit()

    def _rotate_panel(self) -> QWidget:
        segments = Segmented()
        for text, value, icon in (
            (self.tr("90° влево"), "left", "rotate"),
            (self.tr("90° вправо"), "right", "rotate"),
            (self.tr("Отразить по горизонтали"), "flip_h", "flip"),
            (self.tr("Отразить по вертикали"), "flip_v", "flip"),
        ):
            segments.add(text, value, icon=icon, momentary=True)
        segments.changed.connect(self._on_rotate)
        self.rotate_segments = segments
        return self._row(segments)

    def _on_rotate(self, value: object) -> None:
        if value == "left":
            self.session.rotate(270)
        elif value == "right":
            self.session.rotate(90)
        elif value == "flip_h":
            self.session.flip(True)
        elif value == "flip_v":
            self.session.flip(False)

    # --- выбор -------------------------------------------------------------------------------

    @property
    def active(self) -> str | None:
        return self._active

    def _active_tool(self) -> Tool | None:
        return self.tools.get(self._active) if self._active else None

    def hint(self) -> str:
        return self.tr(HINTS[self._active]) if self._active in HINTS else self.tr(IDLE_HINT)

    def select_tool(self, name: str) -> None:
        """Выбрать пункт рейки; повторный выбор того же снимает его."""
        known = {key for key, *_ in RAIL_ITEMS}
        if name not in known:
            return
        previous = self._active_tool()
        if previous is not None:
            previous.reset()
        self._active = None if name == self._active else name
        self._frame_selection()
        self.overlay.set_tool(self._active_tool())
        self.selectionChanged.emit(self._active)
        self.hintChanged.emit(self.hint())

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
            start, stop = self.redact_time.values()
            self.session.add_redact(replace(op, show_from=start, show_to=stop))
            self.redact_time.reset()
        elif isinstance(op, Text):
            start, stop = self.text_time.values()
            self.session.add_text(replace(op, show_from=start, show_to=stop))
            self.text_time.reset()

    def escape(self) -> bool:
        """Esc: отменить незавершённое действие или снять инструмент; False — делать нечего."""
        if self._active is None:
            return False
        tool = self._active_tool()
        if tool is not None and self._pending(tool) is not None:
            tool.reset()
        else:
            self._deselect()
        return True

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
        self.color.set_values(effects.adjust, effects.filter)
        self.text_time.set_duration(project.duration)
        self.redact_time.set_duration(project.duration)
        self._frame_selection()  # после применения рамка снова охватывает кадр
