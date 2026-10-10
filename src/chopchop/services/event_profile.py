"""Время обработчиков событий Qt (CHOPCHOP_PROFILE=1): кто и сколько занимает поток интерфейса.

`ProfiledApplication` замеряет каждую доставку события (`notify`): тип события, класс виджета,
длительность. Дольше порога кадра (16 мс) пишется предупреждение, остальное копится в таблице,
которую можно вывести при выходе или забрать из бенчмарка.
"""

import logging
import time
from dataclasses import dataclass, field

from PySide6.QtCore import QCoreApplication, QEvent, QObject
from PySide6.QtWidgets import QApplication

log = logging.getLogger("chopchop.profile")

FRAME_MS = 16.0
SLOW_MS = 50.0

_NAMES = {
    int(QEvent.Type.Paint): "Paint",
    int(QEvent.Type.UpdateRequest): "UpdateRequest",
    int(QEvent.Type.MouseMove): "MouseMove",
    int(QEvent.Type.MouseButtonPress): "MousePress",
    int(QEvent.Type.MouseButtonRelease): "MouseRelease",
    int(QEvent.Type.Timer): "Timer",
    int(QEvent.Type.MetaCall): "MetaCall",
    int(QEvent.Type.HoverMove): "HoverMove",
    int(QEvent.Type.Enter): "Enter",
    int(QEvent.Type.Leave): "Leave",
    int(QEvent.Type.Resize): "Resize",
    int(QEvent.Type.StyleChange): "StyleChange",
    int(QEvent.Type.Polish): "Polish",
}


@dataclass
class Stat:
    count: int = 0
    total: float = 0.0
    longest: float = 0.0
    over_frame: int = 0  # сколько раз дольше 16 мс
    samples: list[float] = field(default_factory=list)

    def add(self, milliseconds: float) -> None:
        self.count += 1
        self.total += milliseconds
        self.longest = max(self.longest, milliseconds)
        if milliseconds > FRAME_MS:
            self.over_frame += 1
        if len(self.samples) < 20000:
            self.samples.append(milliseconds)

    def percentile(self, fraction: float) -> float:
        if not self.samples:
            return 0.0
        ordered = sorted(self.samples)
        return ordered[min(int(len(ordered) * fraction), len(ordered) - 1)]


class ProfiledApplication(QApplication):
    """QApplication, который замеряет время обработки каждого события."""

    def __init__(self, argv: list[str]) -> None:
        super().__init__(argv)
        self.stats: dict[tuple[str, str], Stat] = {}
        self.lost_events = 0
        self.recording = True

    def notify(self, receiver: QObject, event: QEvent) -> bool:  # noqa: N802
        if not self.recording:
            return super().notify(receiver, event)
        started = time.perf_counter()
        try:
            return super().notify(receiver, event)
        except TypeError:
            # PySide иногда передаёт вместо получателя событие (внутренний объект Qt без обёртки);
            # это только в режиме профилирования, потеря такого события безвредна
            self.lost_events += 1
            return False
        finally:
            elapsed = (time.perf_counter() - started) * 1000
            kind = _NAMES.get(int(event.type()), "")
            if kind:
                key = (kind, type(receiver).__name__)
                stat = self.stats.get(key)
                if stat is None:
                    stat = self.stats[key] = Stat()
                stat.add(elapsed)
                if elapsed > FRAME_MS:
                    log.warning("%s on %s took %.1f ms", kind, key[1], elapsed)

    def reset(self) -> None:
        self.stats.clear()


def report(app: QCoreApplication | None = None, top: int = 12) -> str:
    """Таблица самых тяжёлых обработчиков: событие, виджет, число, медиана, p95, максимум."""
    if not isinstance(app, ProfiledApplication):
        return ""
    rows = sorted(app.stats.items(), key=lambda item: -item[1].total)[:top]
    lines = [f"{'событие':14}{'виджет':24}{'шт':>7}{'p50':>8}{'p95':>8}{'max':>8}{'>16':>6}"]
    for (kind, widget), stat in rows:
        lines.append(
            f"{kind:14}{widget:24}{stat.count:7}{stat.percentile(0.5):8.2f}"
            f"{stat.percentile(0.95):8.2f}{stat.longest:8.2f}{stat.over_frame:6}"
        )
    return "\n".join(lines)
