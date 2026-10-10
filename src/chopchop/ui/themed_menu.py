"""Контекстное меню в стиле темы: ступенчатая рамка, жёсткая тень, пиксельные значки.

Меню — отдельное всплывающее окно, поэтому ему не мешают ни OpenGL-виджет плеера, ни плавающие
панели. Фон окна прозрачный (рамку и тень рисуем сами), появление — плавное, не дольше 100 мс,
и отключается настройкой «Анимации». Список пунктов собирается при открытии из текущего
состояния, а не хранится.
"""

from collections.abc import Callable

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRectF, Qt
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QKeySequence,
    QPainter,
    QPaintEvent,
    QShowEvent,
)
from PySide6.QtWidgets import QMenu, QWidget

from chopchop.ui import anim
from chopchop.ui.theme import current, icons, tokens
from chopchop.ui.theme.pixel import paint_frame

APPEAR_MS = 90  # не больше 100
ICON_SIZE = 32


class ThemedMenu(QMenu):
    """Меню с рамкой темы; подменю того же вида."""

    def __init__(self, parent: QWidget | None = None, title: str = "") -> None:
        super().__init__(title, parent)
        self.setProperty("themed", True)
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setSeparatorsCollapsible(True)
        self._fade: QPropertyAnimation | None = None

    # --- вид ---------------------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        p = current.palette()
        reserve = tokens.SHADOW_OFFSET
        rect = QRectF(0, 0, self.width() - reserve, self.height() - reserve)
        paint_frame(
            painter, rect, fill=p.surface_raised, border=p.border_strong, shadow=p.shadow, levels=1
        )
        painter.end()
        super().paintEvent(event)  # пункты рисуются поверх рамки

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        span = anim.duration(APPEAR_MS)
        if span == 0:
            self.setWindowOpacity(1.0)
            return
        self.setWindowOpacity(0.0)
        fade = QPropertyAnimation(self, b"windowOpacity", self)
        fade.setDuration(span)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve(QEasingCurve.Type.OutCubic))
        fade.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._fade = fade

    # --- наполнение --------------------------------------------------------------------------

    def submenu(self, title: str, icon: str | None = None) -> "ThemedMenu":
        menu = ThemedMenu(self, title)
        if icon:
            menu.setIcon(icons.qicon(icon, current.palette(), logical=ICON_SIZE))
        self.addMenu(menu)
        return menu

    def add_action(
        self,
        action: QAction,
        *,
        enabled: bool = True,
        checked: bool | None = None,
        text: str | None = None,
    ) -> QAction:
        """Пункт для действия из реестра: то же имя, значок, клавиша и тот же обработчик.

        В меню кладётся «двойник»: он запускает исходное действие, а доступность и отметка у
        него свои. Исходное действие (и его горячая клавиша) от этого не меняется.
        """
        shown = text or action.text()
        keys = action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
        proxy = QAction(f"{shown}	{keys}" if keys else shown, self)
        proxy.setObjectName(action.objectName())
        proxy.setIcon(action.icon())
        proxy.setEnabled(enabled and action.isEnabled())
        if checked is not None:
            proxy.setCheckable(True)
            proxy.setChecked(checked)
        proxy.triggered.connect(lambda _checked=False: action.trigger())
        self.addAction(proxy)
        return proxy

    def add_item(
        self,
        text: str,
        slot: Callable[[], object] | None = None,
        *,
        icon: str | None = None,
        checked: bool | None = None,
        enabled: bool = True,
        shortcut: str = "",
        group: QActionGroup | None = None,
    ) -> QAction:
        """Пункт без реестра (дорожки, скорости, эффекты): значок и отметка по желанию."""
        action = QAction(text, self)
        if icon:
            action.setIcon(icons.qicon(icon, current.palette(), logical=ICON_SIZE))
        if checked is not None:
            action.setCheckable(True)
            action.setChecked(checked)
        if shortcut:
            action.setShortcut(shortcut)
        action.setEnabled(enabled)
        if group is not None:
            group.addAction(action)
        if slot is not None:
            action.triggered.connect(lambda _checked=False: slot())
        self.addAction(action)
        return action

    def popup_at(self, global_pos: QPoint) -> None:
        """Показать меню у точки; не выходит за край экрана (это делает Qt)."""
        self.popup(global_pos)
