"""Управление воспроизведением: mpv живёт в своём потоке, наружу идут сигналы Qt."""

from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal

from chopchop.core.tracks import Track, next_track_id, of_kind, parse_tracks
from chopchop.player.resume import ResumeState
from chopchop.services.settings import PlayerPrefs

VOLUME_MAX = 130.0
SPEED_MIN = 0.25
SPEED_MAX = 4.0
SUB_DELAY_STEP = 0.1


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
    tracksChanged = Signal()
    ended = Signal()
    fileLoaded = Signal()
    errorOccurred = Signal(str)

    def __init__(self, mpv: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._mpv = mpv
        self._closed = False
        self._current: Path | None = None
        self._copy_decoding = False
        self._default_volume = 100.0
        # обработчики вызываются из потока mpv; сигналы Qt сами ставят доставку в очередь
        mpv.observe_property("time-pos", lambda _n, v: self._emit_float(self.positionChanged, v))
        mpv.observe_property("duration", lambda _n, v: self._emit_float(self.durationChanged, v))
        mpv.observe_property("volume", lambda _n, v: self._emit_float(self.volumeChanged, v))
        mpv.observe_property("speed", lambda _n, v: self._emit_float(self.speedChanged, v))
        mpv.observe_property("pause", lambda _n, v: self.pausedChanged.emit(bool(v)))
        mpv.observe_property("eof-reached", self._on_eof)
        for name in ("track-list", "aid", "sid", "secondary-sid"):
            mpv.observe_property(name, lambda _n, _v: self.tracksChanged.emit())
        mpv.event_callback("end-file")(self._on_end_file)
        mpv.event_callback("file-loaded")(lambda _event: self.fileLoaded.emit())

    def _emit_float(self, signal: Any, value: object) -> None:
        if isinstance(value, int | float) and not isinstance(value, bool):
            signal.emit(float(value))

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
        options: dict[str, object] = {}
        self._mpv.pause = False
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
        self._mpv.loadfile(str(path), **options)

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
        return bool(self._mpv.pause)

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
        return parse_tracks(self._mpv.track_list or [])

    def audio_id(self) -> int | None:
        return _track_id(self._mpv.aid)

    def sub_id(self) -> int | None:
        return _track_id(self._mpv.sid)

    def sub2_id(self) -> int | None:
        return _track_id(self._mpv.secondary_sid)

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
        self._mpv.pause = not self._mpv.pause

    def seek(self, delta: float) -> None:
        self._mpv.seek(delta, "relative", "keyframes")

    def seek_to(self, seconds: float, exact: bool = False) -> None:
        """Перемотка: по ключевым кадрам (быстро, для перетаскивания) или точно на кадр."""
        self._mpv.seek(max(seconds, 0.0), "absolute", "exact" if exact else "keyframes")

    def set_volume(self, value: float) -> None:
        self._mpv.volume = min(max(value, 0.0), VOLUME_MAX)

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
            self._mpv.seek(0, "relative", "exact")
        else:
            self._reload(float(position), bool(self._mpv.pause))

    def _reload(self, position: float, paused: bool) -> None:
        assert self._current is not None
        options = {"start": f"{position:.3f}", "pause": "yes" if paused else "no"}
        self._mpv.loadfile(str(self._current), **options)

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
        self._mpv.ab_loop_a = "no" if start is None else start
        self._mpv.ab_loop_b = "no" if end is None else end

    def add_subtitle(self, path: Path) -> None:
        self._mpv.sub_add(str(path))

    def apply_prefs(self, prefs: PlayerPrefs) -> None:
        """Применить настройки без перезапуска: вид субтитров сразу, языки со следующего файла."""
        self._default_volume = prefs.volume
        self._mpv.sub_font_size = prefs.sub_font_size
        self._mpv.sub_margin_y = prefs.sub_margin
        self._mpv.alang = prefs.audio_langs
        self._mpv.slang = prefs.sub_langs
        if str(self._mpv.hwdec) != prefs.hwdec:
            self._mpv.hwdec = prefs.hwdec
            self._copy_decoding = False  # следующий фильтр заново проверит режим
            position = self._mpv.time_pos
            if self._current is not None and position is not None:
                self._reload(float(position), bool(self._mpv.pause))  # декодер перезапускается
