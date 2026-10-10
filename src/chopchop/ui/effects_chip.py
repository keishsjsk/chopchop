"""Чип эффектов в строке состояния: «без эффектов» или «Эффекты: 3» со списком по клику.

Список показывает каждый применённый эффект с кнопкой удаления, внизу — «Сбросить все».
"""

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QToolButton, QWidget

from chopchop.core.tr_marks import QT_TRANSLATE_NOOP
from chopchop.core.video import EffectEntry, VideoEffects, effect_entries
from chopchop.ui.context_gate import menu_allowed
from chopchop.ui.floating import FloatingPanel
from chopchop.ui.theme import tokens
from chopchop.ui.widgets import button, icon_button

LABELS = {
    "crop": QT_TRANSLATE_NOOP("EffectsChip", "Кадр"),
    "redact": QT_TRANSLATE_NOOP("EffectsChip", "Скрытие области"),
    "text": QT_TRANSLATE_NOOP("EffectsChip", "Текст"),
    "adjust": QT_TRANSLATE_NOOP("EffectsChip", "Цветокоррекция"),
    "filter": QT_TRANSLATE_NOOP("EffectsChip", "Фильтр"),
    "rotation": QT_TRANSLATE_NOOP("EffectsChip", "Поворот"),
    "flip": QT_TRANSLATE_NOOP("EffectsChip", "Отражение"),
}
PREVIEW_CHARS = 18


class EffectsPopup(FloatingPanel):
    """Список применённых эффектов; закрывается кликом вне окна."""

    removeRequested = Signal(object)
    clearRequested = Signal()
    rowMenuRequested = Signal(object, QPoint)  # правая кнопка на строке списка

    def __init__(self, labels: list[tuple[EffectEntry, str]], parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        column = self.vertical()
        column.setSpacing(tokens.SPACE_1)
        self.rows: list[tuple[EffectEntry, QLabel, QToolButton]] = []
        for entry, text in labels:
            label = QLabel(text)
            label.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            label.customContextMenuRequested.connect(
                lambda point, e=entry, lab=label: self.rowMenuRequested.emit(
                    e, lab.mapToGlobal(point)
                )
            )
            remove = icon_button("trash", self.tr("Убрать эффект"), small=True)
            remove.clicked.connect(lambda _c=False, e=entry: self._remove(e))
            row = QHBoxLayout()
            row.addWidget(label, 1)
            row.addWidget(remove)
            column.addLayout(row)
            self.rows.append((entry, label, remove))
        self.reset_all = button(self.tr("Сбросить все"), slot=self._clear)
        column.addWidget(self.reset_all)
        self.setMinimumWidth(12 * tokens.SPACE_4)

    def _remove(self, entry: EffectEntry) -> None:
        self.removeRequested.emit(entry)
        self.close()

    def _clear(self) -> None:
        self.clearRequested.emit()
        self.close()


class EffectsChip(QPushButton):
    removeRequested = Signal(object)
    clearRequested = Signal()
    menuRequested = Signal(list, QPoint)  # записи эффектов и точка на экране

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("variant", "chip")
        self.setProperty("dense", True)  # в строке состояния высотой 24 обычный чип не помещается
        self._effects = VideoEffects()
        self._popup: EffectsPopup | None = None
        self.clicked.connect(self.open_list)
        self.set_effects(VideoEffects())

    def entries(self) -> list[EffectEntry]:
        return effect_entries(self._effects)

    def label_for(self, entry: EffectEntry) -> str:
        text = self.tr(LABELS[entry.kind])
        if entry.kind in ("redact", "text"):
            text += f" {entry.index + 1}"
        if entry.kind == "text":
            shown = self._effects.texts[entry.index].text
            if len(shown) > PREVIEW_CHARS:
                shown = shown[: PREVIEW_CHARS - 1] + "…"
            text += f": {shown}"
        return text

    def set_effects(self, effects: VideoEffects) -> None:
        self._effects = effects
        entries = self.entries()
        if entries:
            self.setText(self.tr("Эффекты: {0}").format(len(entries)))
            self.setToolTip(self.tr("Применённые эффекты: убрать любой или сбросить все"))
        else:
            self.setText(self.tr("Без эффектов"))
            self.setToolTip("")
        self.setEnabled(bool(entries))

    def open_list(self) -> None:
        entries = self.entries()
        if not entries:
            return
        popup = EffectsPopup([(e, self.label_for(e)) for e in entries], self)
        popup.removeRequested.connect(self.removeRequested)
        popup.clearRequested.connect(self.clearRequested)
        popup.rowMenuRequested.connect(lambda entry, pos: self.menuRequested.emit([entry], pos))
        popup.adjustSize()
        origin = self.mapToGlobal(QPoint(self.width() - popup.width(), -popup.height()))
        popup.move(origin)
        self._popup = popup
        popup.show()

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802
        entries = self.entries()
        if entries and menu_allowed():
            self.menuRequested.emit(entries, event.globalPos())

    def close_list(self) -> None:
        if self._popup is not None:
            self._popup.close()
            self._popup = None
