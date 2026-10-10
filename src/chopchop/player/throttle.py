"""Ограничитель частоты: первое значение уходит сразу, дальше не чаще раза в интервал.

Ползунок отдаёт значение на каждое движение мыши (до 1000 раз в секунду), а перемотка и громкость
mpv не нужны чаще 30-60 Гц. Пока интервал не прошёл, запоминается последнее значение: оно уйдёт
по таймеру, так что итоговое положение всегда доходит до получателя.
"""

from collections.abc import Callable
from typing import Generic, TypeVar

from PySide6.QtCore import QObject, QTimer

T = TypeVar("T")


class Throttle(QObject, Generic[T]):  # noqa: UP046  # PySide и PEP 695 вместе не проверены
    def __init__(
        self, interval_ms: int, callback: Callable[[T], None], parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._callback = callback
        self._interval = interval_ms
        self._pending: list[T] = []  # пусто или одно последнее значение
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timer)

    def push(self, value: T) -> None:
        if self._timer.isActive():
            self._pending[:] = [value]
            return
        self._callback(value)
        self._timer.start(self._interval)

    def cancel(self) -> None:
        """Забыть отложенное значение (например, перед окончательной точной перемоткой)."""
        self._pending.clear()
        self._timer.stop()

    def _on_timer(self) -> None:
        if self._pending:
            value = self._pending.pop()
            self._callback(value)
            self._timer.start(self._interval)
