"""Оформление субтитров: шрифт, цвета, положение, пресеты и образец на заглушке.

Один виджет в двух видах: полный (раздел «Субтитры» в настройках) и компактный (быстрая панель
в плеере). Любое изменение сразу пишется в настройки, а оттуда на лету уходит в mpv, поэтому
результат виден поверх идущего видео.
"""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QRectF, QSignalBlocker, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from chopchop.core import subtitle_style as ss
from chopchop.core.subtitle_style import SubtitleStyle
from chopchop.services.app_settings import AppSettings
from chopchop.services.settings import save_subtitle_style, subtitle_style
from chopchop.services.sub_presets import PresetStore
from chopchop.ui.click_slider import ClickSlider
from chopchop.ui.color_button import ColorButton, color_to_hex, hex_to_color
from chopchop.ui.theme import current, fonts, tokens
from chopchop.ui.widgets import PixelToggle, Segmented, button

SAMPLE_TEXT = "Съешь ещё этих мягких французских булок"
SAMPLE_SECOND = "The quick brown fox jumps over the lazy dog"
PREVIEW_HEIGHT = 150
CUSTOM = "\0custom"  # служебный пункт списка пресетов: оформление изменено вручную
PRIVATE_FAMILIES = {fonts.PIXEL_FAMILY}  # шрифты самой программы libass не видит


def _tr(text: str) -> str:
    return QCoreApplication.translate("SubtitleStyle", text)


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], amount: float) -> QColor:
    return QColor(*(round(x + (y - x) * amount) for x, y in zip(a, b, strict=True)))


def system_families() -> list[str]:
    """Шрифты, которые найдёт и libass: системные, без шрифтов интерфейса программы."""
    return [
        f for f in QFontDatabase.families() if f not in PRIVATE_FAMILIES and not f.startswith("@")
    ]


def covers_cyrillic(family: str) -> bool:
    return QFontDatabase.WritingSystem.Cyrillic in QFontDatabase.writingSystems(family)


class SubtitlePreview(QWidget):
    """Образец на заглушке: приближённо показывает оформление, пока видео нет или оно закрыто."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._style = SubtitleStyle()
        self.setFixedHeight(PREVIEW_HEIGHT)
        self.setMinimumWidth(240)
        self.setAccessibleName(QCoreApplication.translate("SubtitleStyle", "Образец субтитров"))

    def set_style(self, style: SubtitleStyle) -> None:
        self._style = style
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._paint_backdrop(painter)
        self._paint_text(painter)

    def _paint_backdrop(self, painter: QPainter) -> None:
        """Заглушка вместо кадра: светлая и тёмная половины, на которых проверяют читаемость."""
        rect = QRectF(self.rect())
        half = rect.width() / 2
        dark = QLinearGradient(0, 0, 0, rect.height())
        dark.setColorAt(0, QColor(*tokens.OVERLAY_DARK))
        dark.setColorAt(1, _mix(tokens.OVERLAY_DARK, tokens.OVERLAY_LIGHT, 0.25))
        light = QLinearGradient(0, 0, 0, rect.height())
        light.setColorAt(0, QColor(*tokens.OVERLAY_LIGHT))
        light.setColorAt(1, _mix(tokens.OVERLAY_DARK, tokens.OVERLAY_LIGHT, 0.75))
        painter.fillRect(QRectF(0, 0, half, rect.height()), dark)
        painter.fillRect(QRectF(half, 0, half, rect.height()), light)
        painter.setPen(QPen(QColor(current.palette().border_strong), tokens.BORDER_WIDTH))
        painter.drawRect(rect.adjusted(1, 1, -1, -1))

    def _paint_text(self, painter: QPainter) -> None:
        s = self._style
        rect = QRectF(self.rect())
        pixel = max(s.font_size * rect.height() / 720 * s.scale, 6.0)
        font = QFont(s.font or "sans-serif")
        font.setPixelSize(round(pixel))
        font.setBold(s.bold)
        font.setItalic(s.italic)
        metrics = QFontMetricsF(font)
        gap = s.line_spacing * rect.height() / 720
        lines = (SAMPLE_TEXT, SAMPLE_SECOND)
        line_h = metrics.height() + gap
        block_h = line_h * len(lines)
        margin_y = s.margin_y * rect.height() / 720
        margin_x = s.margin_x * rect.width() / 1280
        if s.align_y == "top":
            top = margin_y
        elif s.align_y == "center":
            top = (rect.height() - block_h) / 2
        else:
            top = rect.height() - margin_y - block_h
        scale_k = rect.height() / 720
        for index, text in enumerate(lines):
            width = metrics.horizontalAdvance(text)
            if s.align_x == "left":
                x = margin_x
            elif s.align_x == "right":
                x = rect.width() - margin_x - width
            else:
                x = (rect.width() - width) / 2
            baseline = top + index * line_h + metrics.ascent()
            self._line(painter, text, font, x, baseline, width, metrics, scale_k)

    def _line(
        self,
        painter: QPainter,
        text: str,
        font: QFont,
        x: float,
        baseline: float,
        width: float,
        metrics: QFontMetricsF,
        k: float,
    ) -> None:
        s = self._style
        if s.back_enabled:
            pad = max(s.outline_size * k, 2.0)
            box = QRectF(
                x - pad,
                baseline - metrics.ascent() - pad / 2,
                width + 2 * pad,
                metrics.height() + pad,
            )
            back = QColor(s.back_color)
            back.setAlphaF(s.back_opacity / 100)
            painter.fillRect(box, back)
        path = QPainterPath()
        path.addText(x, baseline, font, text)
        if s.shadow_offset > 0:
            shadow = QColor(s.shadow_color)
            painter.fillPath(path.translated(s.shadow_offset * k, s.shadow_offset * k), shadow)
        if s.outline_size > 0 and not s.back_enabled:
            pen = QPen(QColor(s.outline_color), s.outline_size * k * 2)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.strokePath(path, pen)
        painter.fillPath(path, QColor(s.color))


class SubtitleStyleEditor(QWidget):
    """Все настройки оформления. `compact` — быстрая панель в плеере: только самое нужное."""

    openAllRequested = Signal()  # из быстрой панели: показать полный раздел настроек

    def __init__(
        self,
        settings: AppSettings,
        presets: PresetStore | None = None,
        *,
        compact: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._presets = presets or PresetStore(None)
        self._compact = compact
        self._syncing = False
        self._image_only = False
        self._unsupported: set[str] = set()

        self.preview = SubtitlePreview()
        self._build()
        settings.changed.connect(self._on_setting)
        settings.reloaded.connect(self.sync)
        self.sync()

    # --- построение --------------------------------------------------------------------------

    def _build(self) -> None:
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(tokens.SPACE_3)
        column.addWidget(self.preview)
        self._notice = QLabel()
        self._notice.setWordWrap(True)
        self._notice.setProperty("muted", True)
        self._notice.hide()
        column.addWidget(self._notice)
        column.addLayout(self._preset_row())

        self._form = QFormLayout()
        self._form.setSpacing(tokens.SPACE_2)
        self._form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self._text_controls: list[QWidget] = []  # то, что неприменимо к картинкам
        self._add_font_rows()
        self._add_color_rows()
        self._add_layout_rows()
        self._add_mode_rows()
        column.addLayout(self._form)
        if self._compact:
            more = button(
                self.tr("Все настройки субтитров…"), "ghost", slot=self.openAllRequested.emit
            )
            column.addWidget(more)

    def _row(self, label: str, widget: QWidget, text_only: bool = True) -> QWidget:
        self._form.addRow(label, widget)
        if text_only:
            self._text_controls.append(widget)
        return widget

    def _preset_row(self) -> QHBoxLayout:
        self._preset = QComboBox()
        self._preset.setAccessibleName(self.tr("Пресет оформления"))
        self._preset.activated.connect(self._on_preset_chosen)
        self._save = button(self.tr("Сохранить…"), tooltip=self.tr("Сохранить как пресет"))
        self._save.clicked.connect(self.save_preset)
        self._delete = button(self.tr("Удалить"), tooltip=self.tr("Удалить свой пресет"))
        self._delete.clicked.connect(self.delete_preset)
        row = QHBoxLayout()
        row.setSpacing(tokens.SPACE_2)
        row.addWidget(self._preset, 1)
        row.addWidget(self._save)
        row.addWidget(self._delete)
        if not self._compact:
            self._import = button(self.tr("Импорт…"), slot=self.import_presets)
            self._export = button(self.tr("Экспорт…"), slot=self.export_presets)
            row.addWidget(self._import)
            row.addWidget(self._export)
        return row

    def _add_font_rows(self) -> None:
        self._font = QComboBox()
        self._font.setEditable(True)
        self._font.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._font.addItem(self.tr("По умолчанию"), "")
        for family in system_families():
            self._font.addItem(family, family)
        completer = QCompleter(self._font.model(), self._font)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)  # поиск по части названия
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._font.setCompleter(completer)
        self._font.activated.connect(lambda _i: self._font_chosen())
        self._font.lineEdit().editingFinished.connect(self._font_typed)  # type: ignore[union-attr]
        self._font_note = QLabel()
        self._font_note.setWordWrap(True)
        self._font_note.setProperty("error", True)
        self._font_note.hide()
        box = QWidget()
        inner = QVBoxLayout(box)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(tokens.SPACE_1)
        inner.addWidget(self._font)
        inner.addWidget(self._font_note)
        self._row(self.tr("Шрифт"), box)

        self._size = QSpinBox()
        self._size.setRange(*ss.SIZE_RANGE)
        self._size.setToolTip(
            self.tr("Относительно высоты видео: 55 ≈ 7,6 % высоты кадра, растёт вместе с окном")
        )
        self._size.valueChanged.connect(lambda v: self._set("subtitles.font_size", v))
        self._bold = PixelToggle(self.tr("Жирный"))
        self._bold.toggled.connect(lambda v: self._set("subtitles.bold", v))
        self._italic = PixelToggle(self.tr("Курсив"))
        self._italic.toggled.connect(lambda v: self._set("subtitles.italic", v))
        line = QWidget()
        row = QHBoxLayout(line)
        row.setContentsMargins(0, 0, 0, 0)
        for widget in (self._size, self._bold, self._italic):
            row.addWidget(widget)
        row.addStretch(1)
        self._row(self.tr("Размер"), line)

    def _color(self, key: str) -> ColorButton:
        picker = ColorButton((255, 255, 255))
        picker.setFixedWidth(tokens.BUTTON_HEIGHT * 2)
        picker.colorChanged.connect(lambda c: self._set(key, color_to_hex(c)))
        return picker

    def _spin(self, key: str, low: float, high: float, step: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(low, high)
        spin.setSingleStep(step)
        spin.setDecimals(1)
        spin.valueChanged.connect(lambda v: self._set(key, float(v)))
        return spin

    def _int_spin(self, key: str, low: int, high: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(low, high)
        spin.valueChanged.connect(lambda v: self._set(key, int(v)))
        return spin

    def _pair(self, *widgets: QWidget) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(tokens.SPACE_2)
        for widget in widgets:
            row.addWidget(widget)
        row.addStretch(1)
        return box

    def _add_color_rows(self) -> None:
        self._color_text = self._color("subtitles.color")
        self._row(self.tr("Цвет текста"), self._pair(self._color_text))
        self._color_outline = self._color("subtitles.outline_color")
        self._outline = self._spin("subtitles.outline_size", *ss.OUTLINE_RANGE, 0.5)
        self._row(self.tr("Контур: цвет и толщина"), self._pair(self._color_outline, self._outline))
        if self._compact:
            return
        self._color_shadow = self._color("subtitles.shadow_color")
        self._shadow = self._spin("subtitles.shadow_offset", *ss.SHADOW_RANGE, 0.5)
        self._row(self.tr("Тень: цвет и смещение"), self._pair(self._color_shadow, self._shadow))
        self._back = PixelToggle(self.tr("Включить"))
        self._back.toggled.connect(lambda v: self._set("subtitles.back_enabled", v))
        self._color_back = self._color("subtitles.back_color")
        self._back_opacity = ClickSlider(Qt.Orientation.Horizontal)
        self._back_opacity.setRange(0, 100)
        self._back_opacity.setFixedWidth(10 * tokens.SPACE_4)
        self._back_opacity.setToolTip(self.tr("Непрозрачность подложки"))
        self._back_opacity.valueChanged.connect(lambda v: self._set("subtitles.back_opacity", v))
        self._row(self.tr("Подложка"), self._pair(self._back, self._color_back, self._back_opacity))

    def _segmented(self, key: str, items: list[tuple[str, str]]) -> Segmented:
        segments = Segmented()
        for value, text in items:
            segments.add(text, value)
        segments.changed.connect(lambda v: self._set(key, v))
        return segments

    def _add_layout_rows(self) -> None:
        self._margin_y = self._int_spin("subtitles.margin", *ss.MARGIN_RANGE)
        self._pos = self._int_spin("subtitles.pos", *ss.POS_RANGE)
        self._pos.setSuffix(" %")
        self._pos.setToolTip(self.tr("0 — вверху кадра, 100 — внизу; действует и на картинки"))
        self._row(self.tr("Положение по высоте"), self._pair(self._pos), text_only=False)
        self._scale = self._spin("subtitles.scale", *ss.SCALE_RANGE, 0.05)
        self._scale.setDecimals(2)
        self._row(self.tr("Масштаб"), self._pair(self._scale), text_only=False)
        self._row(self.tr("Вертикальный отступ"), self._pair(self._margin_y))
        if self._compact:
            return
        self._margin_x = self._int_spin("subtitles.margin_x", *ss.MARGIN_RANGE)
        self._row(self.tr("Горизонтальный отступ"), self._pair(self._margin_x))
        self._spacing = self._int_spin("subtitles.line_spacing", *ss.SPACING_RANGE)
        self._row(self.tr("Межстрочный интервал"), self._pair(self._spacing))
        self._align_x = self._segmented(
            "subtitles.align_x",
            [
                ("left", self.tr("Слева")),
                ("center", self.tr("По центру")),
                ("right", self.tr("Справа")),
            ],
        )
        self._row(self.tr("Выравнивание"), self._align_x)
        self._align_y = self._segmented(
            "subtitles.align_y",
            [
                ("top", self.tr("Сверху")),
                ("center", self.tr("По центру")),
                ("bottom", self.tr("Снизу")),
            ],
        )
        self._row(self.tr("По вертикали"), self._align_y)
        self._pos2 = self._int_spin("subtitles.pos2", *ss.POS_RANGE)
        self._pos2.setSuffix(" %")
        self._pos2.setToolTip(self.tr("Положение второй строки субтитров, 0 — вверху"))
        self._row(self.tr("Вторая строка: положение"), self._pair(self._pos2), text_only=False)

    def _add_mode_rows(self) -> None:
        self._mode = Segmented()
        for key, _code, label in ss.ASS_MODES:
            self._mode.add(_tr(label), key)
        self._mode.changed.connect(lambda v: self._set("subtitles.ass_mode", v))
        self._mode.setToolTip(
            self.tr(
                "Для файлов .ass и .ssa: взять оформление из файла или навязать своё. "
                "Простые .srt всегда оформляются по этим настройкам."
            )
        )
        self._row(self.tr("Оформление из файла или моё"), self._mode)
        self._codepage = QComboBox()
        for code, label in ss.CODEPAGES:
            self._codepage.addItem(_tr(label), code)
        self._codepage.setToolTip(
            self.tr("Если вместо русских букв «кракозябры», выберите CP1251 или KOI8-R")
        )
        self._codepage.activated.connect(
            lambda _i: self._set("subtitles.codepage", self._codepage.currentData())
        )
        self._row(self.tr("Кодировка текстовых субтитров"), self._codepage, text_only=False)

    # --- запись и чтение настроек ------------------------------------------------------------

    def _set(self, key: str, value: object) -> None:
        if self._syncing:
            return
        self._settings.set(key, value)
        self._settings.set("subtitles.preset", "")

    def _on_setting(self, key: str, _value: object) -> None:
        if key.startswith("subtitles."):
            self.sync()

    def current_style(self) -> SubtitleStyle:
        return subtitle_style(self._settings)

    def sync(self) -> None:
        """Показать то, что в настройках; сигналы виджетов на это время выключены."""
        style = self.current_style()
        self._syncing = True
        try:
            self._show_style(style)
        finally:
            self._syncing = False
        self.preview.set_style(style)
        self._sync_presets(style)
        self._sync_font_note(style.font)

    def _show_style(self, style: SubtitleStyle) -> None:
        def put(widget: QWidget, setter: Callable[[], None]) -> None:
            with QSignalBlocker(widget):
                setter()

        index = max(self._font.findData(style.font), 0)
        put(self._font, lambda: self._font.setCurrentIndex(index))
        if style.font and self._font.findData(style.font) < 0:
            put(self._font, lambda: self._font.setEditText(style.font))
        put(self._size, lambda: self._size.setValue(style.font_size))
        put(self._bold, lambda: self._bold.setChecked(style.bold))
        put(self._italic, lambda: self._italic.setChecked(style.italic))
        self._color_text.set_color(hex_to_color(style.color))
        self._color_outline.set_color(hex_to_color(style.outline_color))
        put(self._outline, lambda: self._outline.setValue(style.outline_size))
        put(self._margin_y, lambda: self._margin_y.setValue(style.margin_y))
        put(self._pos, lambda: self._pos.setValue(style.pos))
        put(self._scale, lambda: self._scale.setValue(style.scale))
        self._mode.set_value(style.ass_mode)
        codepage = self._settings.get_str("subtitles.codepage")
        put(
            self._codepage,
            lambda: self._codepage.setCurrentIndex(max(self._codepage.findData(codepage), 0)),
        )
        if self._compact:
            return
        self._color_shadow.set_color(hex_to_color(style.shadow_color))
        put(self._shadow, lambda: self._shadow.setValue(style.shadow_offset))
        put(self._back, lambda: self._back.setChecked(style.back_enabled))
        self._color_back.set_color(hex_to_color(style.back_color))
        put(self._back_opacity, lambda: self._back_opacity.setValue(style.back_opacity))
        put(self._margin_x, lambda: self._margin_x.setValue(style.margin_x))
        put(self._spacing, lambda: self._spacing.setValue(style.line_spacing))
        self._align_x.set_value(style.align_x)
        self._align_y.set_value(style.align_y)
        put(self._pos2, lambda: self._pos2.setValue(self._settings.get_int("subtitles.pos2")))

    def _sync_font_note(self, family: str) -> None:
        if family and not covers_cyrillic(family) and family in QFontDatabase.families():
            self._font_note.setText(
                self.tr("В этом шрифте нет кириллицы: русские буквы возьмутся из другого шрифта.")
            )
            self._font_note.show()
        elif family and family not in QFontDatabase.families():
            self._font_note.setText(
                self.tr("Такого шрифта в системе нет, будет использован шрифт по умолчанию.")
            )
            self._font_note.show()
        else:
            self._font_note.hide()

    # --- шрифт -------------------------------------------------------------------------------

    def _font_chosen(self) -> None:
        self._set("subtitles.font", self._font.currentData() or "")

    def _font_typed(self) -> None:
        typed = self._font.currentText().strip()
        index = self._font.findText(typed, Qt.MatchFlag.MatchFixedString)
        if index >= 0:
            self._set("subtitles.font", self._font.itemData(index) or "")
        elif typed == self.tr("По умолчанию") or not typed:
            self._set("subtitles.font", "")
        else:
            self._set("subtitles.font", typed)  # имя, которого нет в списке, но libass может знать

    # --- пресеты -----------------------------------------------------------------------------

    def _preset_title(self, name: str) -> str:
        return _tr(name) if self._presets.is_builtin(name) else name

    def _sync_presets(self, style: SubtitleStyle) -> None:
        with QSignalBlocker(self._preset):
            self._preset.clear()
            current_name = self._presets.name_of(style)
            if current_name is None:
                self._preset.addItem(self.tr("Свои настройки"), CUSTOM)
            for name in self._presets.names():
                self._preset.addItem(self._preset_title(name), name)
            self._preset.setCurrentIndex(
                max(self._preset.findData(current_name if current_name else CUSTOM), 0)
            )
        selected = self._preset.currentData()
        self._delete.setEnabled(selected in self._presets.user)

    def _on_preset_chosen(self, _index: int) -> None:
        name = self._preset.currentData()
        style = self._presets.get(name) if isinstance(name, str) else None
        if style is None:
            return
        save_subtitle_style(self._settings, style)
        self._settings.set("subtitles.preset", name)

    def save_preset(self) -> None:
        name, accepted = QInputDialog.getText(self, self.tr("Пресет"), self.tr("Название пресета:"))
        if not accepted or not name.strip():
            return
        saved = self._presets.save_as(name, self.current_style())
        self._settings.set("subtitles.preset", saved)
        self.sync()

    def delete_preset(self) -> None:
        name = self._preset.currentData()
        if isinstance(name, str) and self._presets.remove(name):
            self.sync()

    def import_presets(self) -> None:
        name, _ = QFileDialog.getOpenFileName(
            self, self.tr("Импорт пресетов"), "", self.tr("Пресеты (*.json)")
        )
        if not name:
            return
        try:
            added = self._presets.import_from(Path(name))
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, self.tr("Импорт пресетов"), str(error))
            return
        if added:
            style = self._presets.get(added[0])
            if style is not None:
                save_subtitle_style(self._settings, style)
        self.sync()

    def export_presets(self) -> None:
        name, _ = QFileDialog.getSaveFileName(
            self, self.tr("Экспорт пресетов"), "subtitle_presets.json", self.tr("Пресеты (*.json)")
        )
        if not name:
            return
        style = self.current_style()
        extra = {} if self._presets.name_of(style) else {self.tr("Текущее"): style}
        try:
            self._presets.export_to(Path(name), extra)
        except ValueError:
            extra = {self.tr("Текущее"): style}  # своих пресетов нет: пишем хотя бы текущее
            self._presets.export_to(Path(name), extra)
        except OSError as error:
            QMessageBox.warning(self, self.tr("Экспорт пресетов"), str(error))

    # --- картиночные субтитры и старые версии libmpv -----------------------------------------

    def set_track_kind(self, image_only: bool) -> None:
        """Выбраны картиночные субтитры (PGS, VobSub): оформление к ним неприменимо."""
        self._image_only = image_only
        for widget in self._text_controls:
            widget.setEnabled(not image_only)
        if image_only:
            self._notice.setText(
                self.tr(
                    "Выбраны картиночные субтитры (PGS, VobSub): шрифт и цвета к ним неприменимы, "
                    "доступны только положение и масштаб."
                )
            )
        self._refresh_notice()

    def set_unsupported(self, names: set[str]) -> None:
        """Свойства, которых нет в установленной версии libmpv: объясняем, а не молчим."""
        self._unsupported = names
        self._refresh_notice()

    def _refresh_notice(self) -> None:
        if self._image_only:
            self._notice.show()
            return
        if self._unsupported:
            self._notice.setText(
                self.tr("Эта версия libmpv не поддерживает: {0}. Остальное работает.").format(
                    ", ".join(sorted(n.replace("_", "-") for n in self._unsupported))
                )
            )
            self._notice.show()
        else:
            self._notice.hide()
