"""Список последних файлов (QSettings) и параметры плеера, собранные из настроек приложения."""

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSettings

from chopchop.services.app_settings import AppSettings

MAX_RECENT = 10
_RECENT_KEY = "recent_files"


class RecentFiles:
    def __init__(self, settings: QSettings) -> None:
        self._settings = settings

    def items(self) -> list[Path]:
        raw = self._settings.value(_RECENT_KEY, [])
        if isinstance(raw, str):  # QSettings возвращает строку, если элемент один
            raw = [raw]
        if not isinstance(raw, list):
            return []
        return [Path(str(p)) for p in raw]

    def add(self, path: Path) -> None:
        entry = str(path)
        paths = [str(p) for p in self.items() if str(p) != entry]
        self._settings.setValue(_RECENT_KEY, [entry, *paths][:MAX_RECENT])


def default_settings() -> QSettings:
    """Служебное хранилище состояния (последние файлы, позиции просмотра); не настройки."""
    return QSettings("CHOPCHOP", "CHOPCHOP")


@dataclass
class PlayerPrefs:
    """То, что нужно mpv. hwdec — режим mpv: auto-copy-safe (по умолчанию), auto-safe или no."""

    audio_langs: str = ""  # предпочитаемые языки аудио через запятую: "rus,eng"
    sub_langs: str = ""
    sub_font_size: int = 55
    sub_margin: int = 22
    hwdec: str = "auto-copy-safe"
    volume: float = 100.0  # громкость для файлов, у которых своя не запомнена


def player_prefs(settings: AppSettings) -> PlayerPrefs:
    return PlayerPrefs(
        audio_langs=settings.get_str("playback.audio_langs"),
        sub_langs=settings.get_str("playback.sub_langs"),
        sub_font_size=settings.get_int("subtitles.font_size"),
        sub_margin=settings.get_int("subtitles.margin"),
        hwdec=settings.mpv_hwdec(),
        volume=float(settings.get_int("playback.volume_default")),
    )
