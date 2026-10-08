"""Подделка mpv для тестов без libmpv."""

from collections.abc import Callable
from typing import Any, cast

from PySide6.QtWidgets import QWidget

from quickedit.player.player import Player
from quickedit.ui.video_page import VideoPage


class FakeMpv:
    def __init__(self) -> None:
        self.pause = False
        self.vo_configured = True
        self.hwdec: Any = "auto-safe"
        self.hwdec_current: Any = "no"
        self.volume = 100.0
        self.time_pos: float | None = 0.0
        self.duration: float | None = None
        self.track_list: list[dict[str, Any]] = []
        self.aid: Any = "no"
        self.sid: Any = "no"
        self.secondary_sid: Any = "no"
        self.sub_delay = 0.0
        self.secondary_sub_delay = 0.0
        self.sub_font_size = 55
        self.sub_margin_y = 22
        self.alang = ""
        self.ab_loop_a: Any = "no"
        self.ab_loop_b: Any = "no"
        self.slang = ""
        self.observers: dict[str, list[Callable[[str, object], None]]] = {}
        self.event_handlers: list[Callable[[Any], None]] = []
        self.loaded: list[tuple[str, dict[str, object]]] = []
        self.seeks: list[tuple[object, ...]] = []
        self.commands: list[tuple[object, ...]] = []
        self.subtitles: list[str] = []
        self.terminated = False

    def observe_property(self, name: str, handler: Callable[[str, object], None]) -> None:
        self.observers.setdefault(name, []).append(handler)

    def event_callback(
        self, *_types: str
    ) -> Callable[[Callable[[Any], None]], Callable[[Any], None]]:
        def register(handler: Callable[[Any], None]) -> Callable[[Any], None]:
            self.event_handlers.append(handler)
            return handler

        return register

    def fire(self, name: str, value: object) -> None:
        for handler in self.observers.get(name, []):
            handler(name, value)

    def loadfile(self, path: str, **options: object) -> None:
        self.loaded.append((path, options))

    def seek(self, *args: object) -> None:
        self.seeks.append(args)

    def command(self, *args: object) -> None:
        self.commands.append(args)

    def sub_add(self, path: str) -> None:
        self.subtitles.append(path)

    def terminate(self) -> None:
        self.terminated = True


class FakeEndFileEvent:
    def __init__(self, reason: bytes) -> None:
        self._reason = reason

    def as_dict(self) -> dict[str, object]:
        return {"event": b"end-file", "reason": self._reason}


class FakeOldMpv(FakeMpv):
    """mpv без свойства secondary-sub-delay (как libmpv в Ubuntu 24.04)."""

    def __init__(self) -> None:
        super().__init__()
        del self.secondary_sub_delay


class FakeVideoPage(QWidget):
    """Замена VideoPage без OpenGL и libmpv: плеер поверх FakeMpv."""

    def __init__(self) -> None:
        super().__init__()
        self.mpv = FakeMpv()
        self.player = Player(self.mpv, self)
        self.controls = QWidget(self)

    def as_video_page(self) -> VideoPage:
        return cast(VideoPage, self)

    def release(self) -> None:
        self.player.shutdown()
