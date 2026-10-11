"""Плашка с названием файла вверху плеера: компактная, по ширине текста, слева сверху.

Имя файла Monocraft 18 px, длинные имена сокращаются многоточием посередине, расширение видно
всегда. Вторая строка (разрешение, длительность, размер) показывается только при наведении
на плашку или в паузе. Плашка плоская: фон surface без прозрачности, без тени, слева акцентная
полоса 2 px, как у выбранных пунктов. Двойной щелчок открывает переименование, ПКМ — меню файла.
Значка карандаша нет. Прячется и возвращается вместе с остальными панелями плеера.
"""

import os

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QContextMenuEvent,
    QEnterEvent,
    QFontMetrics,
    QMouseEvent,
    QPainter,
    QPaintEvent,
)
from PySide6.QtWidgets import QWidget

from chopchop.ui.floating import FloatingPanel
from chopchop.ui.theme import current, fonts, tokens

STRIPE = 2  # акцентная полоса слева
TAIL = 4  # сколько последних букв имени остаётся перед расширением при сокращении
MAX_SHARE = 0.4  # доля ширины окна, больше которой плашка не растёт
PAD_X = tokens.SPACE_2
LINE_GAP = 1


def elide_keep_extension(text: str, metrics: QFontMetrics, width: int) -> str:
    """«Очень длинное…2024.mkv»: сокращается середина имени, конец и расширение остаются."""
    if metrics.horizontalAdvance(text) <= width:
        return text
    stem, extension = os.path.splitext(text)
    if not extension or len(extension) > 8:
        return metrics.elidedText(text, Qt.TextElideMode.ElideMiddle, width)
    tail = stem[-TAIL:] if len(stem) > TAIL else ""
    head = stem[: len(stem) - len(tail)]
    while head:
        candidate = f"{head}…{tail}{extension}"
        if metrics.horizontalAdvance(candidate) <= width:
            return candidate
        head = head[:-1]
    return f"…{tail}{extension}" if tail else f"…{extension}"


class TopBar(FloatingPanel):
    renameRequested = Signal()
    menuRequested = Signal(QPoint)  # глобальная точка

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, shadow=False)
        # поверх OpenGL панели без прозрачного фона: плашка закрашивает себя целиком сама
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self._full_name = ""
        self._info = ""
        self._paused = False
        self._hover = False
        self._max_width = 480
        self.setFixedHeight(tokens.PLAYER_TOP_H)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    # --- данные ------------------------------------------------------------------------------

    def set_name(self, name: str) -> None:
        self._full_name = name
        self.setToolTip(name)
        self.update()

    def text(self) -> str:
        return self._full_name

    def set_info(self, text: str) -> None:
        """Вторая строка: «1920×1080 · 1:42:10 · 2,1 ГБ»."""
        self._info = text
        self.update()

    def info(self) -> str:
        return self._info

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        self.update()

    def info_visible(self) -> bool:
        return bool(self._info) and (self._hover or self._paused)

    def displayed_name(self) -> str:
        """Имя так, как оно сейчас нарисовано (с многоточием, если не помещается)."""
        return elide_keep_extension(self._full_name, self._name_metrics(), self._room())

    # --- размеры -----------------------------------------------------------------------------

    def _name_metrics(self) -> QFontMetrics:
        return QFontMetrics(fonts.ui_font(fonts.BODY))

    def _info_metrics(self) -> QFontMetrics:
        return QFontMetrics(fonts.ui_font(fonts.SMALL))

    def _room(self) -> int:
        """Ширина под текст внутри плашки при заданной предельной ширине."""
        return max(self._max_width - STRIPE - 2 * PAD_X - 2 * tokens.BORDER_WIDTH, 40)

    def plate_width(self, window_width: int) -> int:
        """Ширина по тексту, но не больше 40% окна."""
        self._max_width = max(int(window_width * MAX_SHARE), 120)
        name = self._name_metrics().horizontalAdvance(
            elide_keep_extension(self._full_name, self._name_metrics(), self._room())
        )
        info = 0
        if self._info:
            info = self._info_metrics().horizontalAdvance(self._info)  # ширина не прыгает от показа
        text = max(name, min(info, self._room()))
        return STRIPE + 2 * PAD_X + 2 * tokens.BORDER_WIDTH + text

    # --- события -----------------------------------------------------------------------------

    def enterEvent(self, event: QEnterEvent) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: object) -> None:  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(event)  # type: ignore[arg-type]

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.renameRequested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802
        self.menuRequested.emit(event.globalPos())
        event.accept()

    def refresh_theme(self) -> None:
        """Шрифт и цвета обновляются вместе с темой."""
        self.update()

    # --- рисование ---------------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        p = current.palette()
        width, height = self.width(), self.height()
        border = tokens.BORDER_WIDTH
        painter.fillRect(self.rect(), QColor(p.border))
        painter.fillRect(
            QRectF(border, border, width - 2 * border, height - 2 * border), QColor(p.surface)
        )
        painter.fillRect(QRectF(border, border, STRIPE, height - 2 * border), QColor(p.accent))
        left = border + STRIPE + PAD_X
        room = width - left - PAD_X - border
        name_font, info_font = fonts.ui_font(fonts.BODY), fonts.ui_font(fonts.SMALL)
        name_metrics, info_metrics = QFontMetrics(name_font), QFontMetrics(info_font)
        name = elide_keep_extension(self._full_name, name_metrics, room)
        show_info = self.info_visible()
        block = name_metrics.height() + (LINE_GAP + info_metrics.height() if show_info else 0)
        top = (height - block) // 2
        painter.setFont(name_font)
        painter.setPen(QColor(p.text))
        painter.drawText(left, top + name_metrics.ascent(), name)
        if show_info:
            painter.setFont(info_font)
            painter.setPen(QColor(p.text_muted))
            info = info_metrics.elidedText(self._info, Qt.TextElideMode.ElideRight, room)
            y = top + name_metrics.height() + LINE_GAP + info_metrics.ascent()
            painter.drawText(left, y, info)
