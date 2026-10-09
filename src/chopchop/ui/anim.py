"""Анимации интерфейса: плавное появление и исчезновение, сдвиг, наведение.

Все длительности из токенов, кривая ease-out. Настройка «Анимации» (reduce motion) выключает их
целиком: изменения происходят сразу. Анимации идут на стороне Qt и не трогают видео.
"""

from collections.abc import Callable

from PySide6.QtCore import QEasingCurve, QObject, QPoint, QPropertyAnimation, QVariantAnimation
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

from chopchop.ui.theme import tokens

_enabled = True


def enabled() -> bool:
    return _enabled


def set_enabled(value: bool) -> None:
    global _enabled
    _enabled = value


def duration(ms: int) -> int:
    return ms if _enabled else 0


def ease_out() -> QEasingCurve:
    return QEasingCurve(QEasingCurve.Type.OutCubic)


class Fader(QObject):
    """Плавная прозрачность виджета (вместе с дочерними): fade_in и fade_out."""

    def __init__(self, widget: QWidget) -> None:
        super().__init__(widget)
        self._widget = widget
        self._effect = QGraphicsOpacityEffect(widget)
        self._effect.setOpacity(1.0)
        widget.setGraphicsEffect(self._effect)
        self._animation = QPropertyAnimation(self._effect, b"opacity", self)
        self._animation.setEasingCurve(ease_out())
        self._done: Callable[[], None] | None = None
        self._animation.finished.connect(self._finished)

    @property
    def opacity(self) -> float:
        return float(self._effect.opacity())

    def fade_to(
        self, target: float, ms: int = tokens.FADE_MS, done: Callable[[], None] | None = None
    ) -> None:
        self._animation.stop()
        self._done = done
        span = duration(ms)
        if span == 0:
            self._effect.setOpacity(target)
            self._finished()
            return
        self._animation.setDuration(span)
        self._animation.setStartValue(self._effect.opacity())
        self._animation.setEndValue(target)
        self._animation.start()

    def _finished(self) -> None:
        done, self._done = self._done, None
        if done is not None:
            done()


def slide(
    widget: QWidget, start: QPoint, end: QPoint, ms: int = tokens.PANEL_MS
) -> QPropertyAnimation:
    """Сдвиг виджета из start в end (позиции в родителе)."""
    animation = QPropertyAnimation(widget, b"pos", widget)
    animation.setEasingCurve(ease_out())
    animation.setDuration(duration(ms))
    animation.setStartValue(start)
    animation.setEndValue(end)
    animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
    return animation


def tween(
    start: float,
    end: float,
    ms: int,
    step: Callable[[float], None],
    parent: QObject | None = None,
) -> QVariantAnimation:
    """Плавное изменение числа (толщина линии, ширина ползунка): step вызывается на каждом кадре."""
    animation = QVariantAnimation(parent)
    animation.setEasingCurve(ease_out())
    animation.setDuration(duration(ms))
    animation.setStartValue(float(start))
    animation.setEndValue(float(end))
    animation.valueChanged.connect(lambda value: step(float(value)))
    if duration(ms) == 0:
        step(float(end))
    else:
        animation.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)
    return animation
