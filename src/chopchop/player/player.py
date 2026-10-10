"""Управление воспроизведением: mpv живёт в своём потоке, наружу идут сигналы Qt."""

import contextlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal

from chopchop.core.subtitle_style import SubtitleStyle, to_mpv
from chopchop.core.tracks import Track, next_track_id, of_kind, parse_tracks
from chopchop.player.resume import ResumeState
from chopchop.player.throttle import Throttle
from chopchop.services.settings import PlayerPrefs

VOLUME_MAX = 130.0
SPEED_MIN = 0.25
SPEED_MAX = 4.0
SUB_DELAY_STEP = 0.1
SEEK_INTERVAL_MS = 30  # перемотка при перетаскивании: не чаще 33 раз в секунду
POSITION_INTERVAL_MS = 33  # позиция для интерфейса: до 30 раз в секунду, а не на каждый кадр


def _track_id(value: object) -> int | None:
    """mpv отдаёт id дорожки числом, а «выключено» — строкой или False."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _opt_id(track_id: int | None) -> object:
    return track_id if track_id else "no"


class Player(QObject):
    positionChanged = Signal(float)
    durationChanged = Signal(float)
    pausedChanged = Signal(bool)
    volumeChanged = Signal(float)
    speedChanged = Signal(float)
    muteChanged = Signal(bool)
    tracksChanged = Signal()
    ended = Signal()
    fileLoaded = Signal()
    errorOccurred = Signal(str)
    _positionRaw = Signal(float)  # из потока mpv; наружу уходит через ограничитель

    def __init__(self, mpv: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._mpv = mpv
        self._closed = False
        self._current: Path | None = None
        self._copy_decoding = False
        self._paused: bool | None = None
        # дорожки из наблюдателей: опрос ядра во время загрузки файла держит интерфейс сотни мс
        self._track_cache: dict[str, object] = {}
        self._default_volume = 100.0
        self.unsupported_style: set[str] = set()
        self._applied_codepage = "auto"
        # обработчики вызываются из потока mpv; сигналы Qt сами ставят доставку в очередь
        self._seeks: Throttle[float] = Throttle(SEEK_INTERVAL_MS, self._seek_keyframes, self)
        self._positions: Throttle[float] = Throttle(
            POSITION_INTERVAL_MS, self.positionChanged.emit, self
        )
        self._positionRaw.connect(self._positions.push)
        mpv.observe_property("time-pos", lambda _n, v: self._emit_float(self._positionRaw, v))
        mpv.observe_property("duration", lambda _n, v: self._emit_float(self.durationChanged, v))
        mpv.observe_property("volume", lambda _n, v: self._emit_float(self.volumeChanged, v))
        mpv.observe_property("speed", lambda _n, v: self._emit_float(self.speedChanged, v))
        mpv.observe_property("pause", self._on_pause)
        mpv.observe_property("mute", lambda _n, v: self.muteChanged.emit(bool(v)))
        mpv.observe_property("eof-reached", self._on_eof)
        for name in ("track-list", "aid", "sid", "secondary-sid"):
            mpv.observe_property(name, self._on_track_property)
        mpv.event_callback("end-file")(self._on_end_file)
        mpv.event_callback("file-loaded")(lambda _event: self.fileLoaded.emit())

    def _emit_float(self, signal: Any, value: object) -> None:
        if isinstance(value, int | float) and not isinstance(value, bool):
            signal.emit(float(value))

    def _on_track_property(self, name: str, value: object) -> None:
        if value is not None:
            self._track_cache[name] = value
        self.tracksChanged.emit()

    def _tracks_value(self, name: str, read: Callable[[], object]) -> object:
        if name in self._track_cache:
            return self._track_cache[name]
        return read()

    def _on_pause(self, _name: str, value: object) -> None:
        self._paused = bool(value)  # запоминаем: опрос ядра во время перемотки блокирует интерфейс
        self.pausedChanged.emit(self._paused)

    def _on_eof(self, _name: str, value: object) -> None:
        if value is True:
            self.ended.emit()

    def _on_end_file(self, event: Any) -> None:
        data = event.as_dict() if hasattr(event, "as_dict") else {}
        reason = data.get("reason", b"")
        if isinstance(reason, bytes):
            reason = reason.decode("utf-8", "replace")
        if reason == "error":
            self.errorOccurred.emit(str(data.get("file_error", "")))

    # --- загрузка --------------------------------------------------------------------------

    def load(self, path: Path, resume: ResumeState | None = None) -> None:
        self._current = path
        options: dict[str, object] = {"pause": "no"}
        if resume is not None:
            if resume.position > 0:
                options["start"] = f"{resume.position:.3f}"
            if resume.aid is not None:
                options["aid"] = _opt_id(resume.aid)
            if resume.sid is not None:
                options["sid"] = _opt_id(resume.sid)
            if resume.secondary_sid is not None:
                options["secondary-sid"] = _opt_id(resume.secondary_sid)
            options["sub-delay"] = resume.sub_delay
            if self.supports_secondary_delay:
                options["secondary-sub-delay"] = resume.secondary_sub_delay
        # у файла нет своей громкости: берём ту, что выбрана в настройках
        if resume is not None and resume.volume is not None:
            self.set_volume(resume.volume)
        else:
            self.set_volume(self._default_volume)
        self._loadfile(str(path), options)

    def load_source(
        self, source: str, current: Path, position: float = 0.0, paused: bool = False
    ) -> None:
        """Загрузка того, что не является одним файлом (EDL предпросмотра монтажа).

        `current` — файл, который считается открытым; позиция и пауза сохраняются между
        перезагрузками, когда блоки поменялись.
        """
        self._current = current
        options: dict[str, object] = {"pause": "yes" if paused else "no"}
        if position > 0:
            options["start"] = f"{position:.3f}"
        self._loadfile(source, options)

    def _loadfile(self, target: str, options: dict[str, object]) -> None:
        """Загрузка без ожидания ядра mpv.

        Обычный `loadfile` ждёт ответа ядра, а оно может быть занято разбором прошлой загрузки или
        перемоткой: интерфейс при этом стоит. Асинхронная команда уходит сразу, а о готовности
        сообщает событие загрузки файла. Пауза передаётся параметром загрузки, а не отдельной
        записью свойства (она тоже ждала бы ядро).
        """
        mpv = self._mpv
        if not hasattr(mpv, "command_async") or not hasattr(mpv, "mpv_version_tuple"):
            mpv.loadfile(target, **options)
            return
        args: list[object] = [target, "replace"]
        if mpv.mpv_version_tuple >= (0, 38, 0):
            args.append(-1)
        args.append(",".join(f"{key}={value}" for key, value in options.items()))
        mpv.command_async("loadfile", *args)

    def stop(self) -> None:
        if not self._closed:
            self._mpv.command("stop")

    def shutdown(self) -> None:
        if not self._closed:
            self._closed = True
            self._mpv.terminate()

    # --- состояние -------------------------------------------------------------------------

    @property
    def position(self) -> float:
        return float(self._mpv.time_pos or 0.0)

    @property
    def duration(self) -> float | None:
        value = self._mpv.duration
        return float(value) if value else None

    @property
    def paused(self) -> bool:
        """Из наблюдателя mpv, без опроса ядра (опрос занят перемоткой и держит интерфейс)."""
        return self._paused if self._paused is not None else bool(self._mpv.pause)

    @property
    def volume(self) -> float:
        return float(self._mpv.volume or 0.0)

    @property
    def supports_secondary_delay(self) -> bool:
        """В старых версиях mpv (например, в Ubuntu 24.04) у второй строки нет своего сдвига."""
        try:
            self._mpv.secondary_sub_delay  # noqa: B018
        except AttributeError:
            return False
        return True

    def _secondary_delay(self) -> float:
        if not self.supports_secondary_delay:
            return 0.0
        return float(self._mpv.secondary_sub_delay or 0.0)

    def tracks(self) -> list[Track]:
        listing = self._tracks_value("track-list", lambda: self._mpv.track_list)
        return parse_tracks(listing or [])  # type: ignore[arg-type]

    def audio_id(self) -> int | None:
        return _track_id(self._tracks_value("aid", lambda: self._mpv.aid))

    def sub_id(self) -> int | None:
        return _track_id(self._tracks_value("sid", lambda: self._mpv.sid))

    def sub2_id(self) -> int | None:
        return _track_id(self._tracks_value("secondary-sid", lambda: self._mpv.secondary_sid))

    def state(self) -> ResumeState:
        return ResumeState(
            position=self.position,
            volume=self.volume,
            aid=self.audio_id() or 0,
            sid=self.sub_id() or 0,
            secondary_sid=self.sub2_id() or 0,
            sub_delay=float(self._mpv.sub_delay or 0.0),
            secondary_sub_delay=self._secondary_delay(),
        )

    # --- управление ------------------------------------------------------------------------

    def toggle_pause(self) -> None:
        self._mpv.pause = not self.paused

    def seek(self, delta: float) -> None:
        self._send_seek(delta, "relative", "keyframes")

    def _send_seek(self, amount: float, reference: str, precision: str) -> None:
        """Перемотка не ждёт ядро mpv: синхронный вызов держал интерфейс десятки миллисекунд."""
        self._mpv.command_async("seek", amount, reference, precision)

    def _seek_keyframes(self, seconds: float) -> None:
        self._send_seek(seconds, "absolute", "keyframes")

    def seek_to(self, seconds: float, exact: bool = False) -> None:
        """Перемотка: по ключевым кадрам (для перетаскивания, не чаще 33 раз в секунду) или точно.

        Точная отменяет отложенную и уходит сразу: она последняя, когда ползунок отпустили.
        """
        seconds = max(seconds, 0.0)
        if exact:
            self._seeks.cancel()
            self._send_seek(seconds, "absolute", "exact")
        else:
            self._seeks.push(seconds)

    def step_frame(self, direction: int) -> None:
        """Шаг на один кадр вперёд (direction > 0) или назад; воспроизведение встаёт на паузу."""
        self._mpv.command("frame-step" if direction > 0 else "frame-back-step")

    def set_volume(self, value: float) -> None:
        self._mpv.volume = min(max(value, 0.0), VOLUME_MAX)

    @property
    def current(self) -> Path | None:
        return self._current

    @property
    def muted(self) -> bool:
        return bool(self._mpv.mute)

    def toggle_mute(self) -> None:
        self._mpv.mute = not self._mpv.mute

    @property
    def speed(self) -> float:
        return float(self._mpv.speed or 1.0)

    def set_speed(self, value: float) -> None:
        self._mpv.speed = round(min(max(value, SPEED_MIN), SPEED_MAX), 3)

    def add_speed(self, delta: float) -> None:
        self.set_speed(self.speed + delta)

    def add_volume(self, delta: float) -> None:
        self.set_volume(self.volume + delta)

    def set_audio(self, track_id: int | None) -> None:
        self._mpv.aid = _opt_id(track_id)

    def set_sub(self, track_id: int | None) -> None:
        self._mpv.sid = _opt_id(track_id)

    def set_sub2(self, track_id: int | None) -> None:
        self._mpv.secondary_sid = _opt_id(track_id)

    def cycle_audio(self) -> None:
        self.set_audio(next_track_id(of_kind(self.tracks(), "audio"), self.audio_id(), False))

    def cycle_sub(self) -> None:
        self.set_sub(self._next_sub(self.sub_id(), busy=self.sub2_id()))

    def cycle_sub2(self) -> None:
        self.set_sub2(self._next_sub(self.sub2_id(), busy=self.sub_id()))

    def _next_sub(self, current: int | None, busy: int | None) -> int | None:
        """Следующие субтитры по кругу; дорожка другой строки пропускается (mpv не даёт обе)."""
        free = [t for t in of_kind(self.tracks(), "sub") if t.id != busy]
        return next_track_id(free, current, True)

    def shift_sub(self, steps: int) -> None:
        self._mpv.sub_delay = round(float(self._mpv.sub_delay or 0.0) + steps * SUB_DELAY_STEP, 3)

    def shift_sub2(self, steps: int) -> None:
        if self.supports_secondary_delay:
            current = self._secondary_delay()
            self._mpv.secondary_sub_delay = round(current + steps * SUB_DELAY_STEP, 3)

    def restore_video(self) -> None:
        """Вернуть картинку после пересоздания контекста рендера.

        Когда Qt создаёт для виджета новый GL-контекст (виджет перенесли в другое окно),
        mpv теряет видеовыход. Если он не настроен, файл загружается заново с той же позиции
        и в том же состоянии паузы; иначе достаточно заново показать текущий кадр.
        """
        if self._closed or self._current is None:
            return
        position = self._mpv.time_pos
        if position is None:
            self._reload(0.0, False)
        elif self._mpv.vo_configured:
            self._send_seek(0, "relative", "exact")
        else:
            self._reload(float(position), bool(self._mpv.pause))

    def _reload(self, position: float, paused: bool) -> None:
        assert self._current is not None
        options: dict[str, object] = {
            "start": f"{position:.3f}",
            "pause": "yes" if paused else "no",
        }
        self._loadfile(str(self._current), options)

    def set_video_filter(self, graph: str | None) -> bool:
        """Показывать видео через граф фильтров ffmpeg (метки vid1 и vo); None снимает фильтр."""
        if self._closed:
            return False
        if graph:
            self._decode_with_copy()
        try:
            if graph:
                self._mpv.command("vf", "set", f"lavfi=[{graph}]")
            else:
                self._mpv.command("vf", "clear", "")
        except Exception:
            return False
        return True

    def _decode_with_copy(self) -> None:
        """Фильтры ffmpeg не работают с кадрами, оставшимися в памяти видеокарты (nvdec, d3d11va).

        Включаем аппаратное декодирование с копированием кадров (оно по-прежнему на видеокарте)
        и один раз перезапускаем декодер, если он уже работал без копирования.
        """
        if self._copy_decoding:
            return
        self._copy_decoding = True
        if str(self._mpv.hwdec) != "auto-safe":
            return  # уже копирующее или программное декодирование: фильтрам этого достаточно
        self._mpv.hwdec = "auto-copy-safe"
        current = str(self._mpv.hwdec_current or "")
        zero_copy = current not in ("", "no") and not current.endswith("-copy")
        position = self._mpv.time_pos
        if zero_copy and self._current is not None and position is not None:
            self._reload(float(position), bool(self._mpv.pause))

    def set_loop(self, start: float | None, end: float | None) -> None:
        """Зациклить фрагмент [start, end] (предпросмотр обрезки); None снимает цикл."""
        # асинхронно: при загрузке файла ядро занято, а синхронная запись держала окно 200 мс
        self._mpv.command_async("set", "ab-loop-a", "no" if start is None else start)
        self._mpv.command_async("set", "ab-loop-b", "no" if end is None else end)

    @property
    def looping(self) -> bool:
        """Повтор текущего файла (loop-file)."""
        return str(self._mpv.loop_file).lower() not in ("no", "false", "none", "")

    def set_looping(self, value: bool) -> None:
        self._mpv.loop_file = "inf" if value else "no"

    def screenshot(self, with_subtitles: bool = False) -> Any | None:
        """Кадр картинкой Pillow через screenshot-raw; субтитры в нём только по просьбе."""
        if self._closed:
            return None
        try:
            return self._mpv.screenshot_raw("subtitles" if with_subtitles else "video")
        except Exception:  # noqa: BLE001 - нет кадра (ничего не открыто) или формат не тот
            return None

    def add_subtitle(self, path: Path, second: bool = False) -> None:
        """Загрузить файл субтитров; second — показать его второй строкой, первую не трогая."""
        previous = self.sub_id()
        self._mpv.sub_add(str(path))
        if not second:
            return
        external = [t for t in of_kind(self.tracks(), "sub") if t.external]
        if external:
            self.set_sub(previous)  # mpv делает новую дорожку первой: возвращаем прежнюю
            self.set_sub2(external[-1].id)

    def apply_style(self, style: SubtitleStyle, codepage: str = "auto", pos2: int = 0) -> None:
        """Оформление субтитров в mpv на лету. Свойства, которых нет в этой версии libmpv,
        пропускаются и запоминаются в `unsupported_style`, чтобы интерфейс мог об этом сказать."""
        missing: set[str] = set()
        for name, value in to_mpv(style).items():
            if not self._set_property(name, value):
                missing.add(name)
        for name, value in (("sub_codepage", codepage), ("secondary_sub_pos", pos2)):
            if not self._set_property(name, value):
                missing.add(name)
        self.unsupported_style = missing
        if codepage != self._applied_codepage:
            self._applied_codepage = codepage
            if self._current is not None:
                with contextlib.suppress(Exception):  # старый libmpv без sub-reload: со след. файла
                    self._mpv.command("sub-reload")

    def _set_property(self, name: str, value: object) -> bool:
        if self._closed:
            return True
        try:
            setattr(self._mpv, name, value)
        except AttributeError:
            return False  # такого свойства в этой версии libmpv нет
        except Exception:  # noqa: BLE001 - mpv сообщает о неверном значении своими ошибками
            return False
        return True

    def apply_prefs(self, prefs: PlayerPrefs) -> None:
        """Применить настройки без перезапуска: вид субтитров сразу, языки со следующего файла."""
        self._default_volume = prefs.volume
        self.apply_style(prefs.style, prefs.codepage, prefs.sub_pos2)
        self._mpv.alang = prefs.audio_langs
        self._mpv.slang = prefs.sub_langs
        if str(self._mpv.hwdec) != prefs.hwdec:
            self._mpv.hwdec = prefs.hwdec
            self._copy_decoding = False  # следующий фильтр заново проверит режим
            position = self._mpv.time_pos
            if self._current is not None and position is not None:
                self._reload(float(position), bool(self._mpv.pause))  # декодер перезапускается
