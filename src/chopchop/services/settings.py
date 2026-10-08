"""Настройки приложения поверх QSettings: последние файлы и параметры плеера."""

import re
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSettings

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
    return QSettings("CHOPCHOP", "CHOPCHOP")


# режимы аппаратного декодирования видео: с копированием кадров (надёжнее), без копирования
# (быстрее, но на некоторых видеокартах и файлах даёт мусор в картинке), программное
HWDEC_MODES = ("auto-copy-safe", "auto-safe", "no")


@dataclass
class PlayerPrefs:
    audio_langs: str = ""  # предпочитаемые языки аудио через запятую: "rus,eng"
    sub_langs: str = ""
    sub_font_size: int = 55
    sub_margin: int = 22
    hwdec: str = "auto-copy-safe"


def clean_langs(text: str) -> str:
    """Оставляет только коды языков через запятую (они уходят в параметры mpv)."""
    codes = (re.sub(r"[^A-Za-z-]", "", part) for part in text.split(","))
    return ",".join(code for code in codes if code)


def load_player_prefs(settings: QSettings) -> PlayerPrefs:
    defaults = PlayerPrefs()
    return PlayerPrefs(
        audio_langs=clean_langs(str(settings.value("player/audio_langs", defaults.audio_langs))),
        sub_langs=clean_langs(str(settings.value("player/sub_langs", defaults.sub_langs))),
        sub_font_size=_int(settings.value("player/sub_font_size"), defaults.sub_font_size),
        sub_margin=_int(settings.value("player/sub_margin"), defaults.sub_margin),
        hwdec=_hwdec(settings.value("player/hwdec", defaults.hwdec), defaults.hwdec),
    )


def save_player_prefs(settings: QSettings, prefs: PlayerPrefs) -> None:
    settings.setValue("player/audio_langs", clean_langs(prefs.audio_langs))
    settings.setValue("player/sub_langs", clean_langs(prefs.sub_langs))
    settings.setValue("player/sub_font_size", prefs.sub_font_size)
    settings.setValue("player/sub_margin", prefs.sub_margin)
    settings.setValue("player/hwdec", _hwdec(prefs.hwdec, PlayerPrefs().hwdec))


def _hwdec(value: object, default: str) -> str:
    """Допустимый режим декодирования; неизвестное значение (из старой версии) — по умолчанию."""
    return str(value) if str(value) in HWDEC_MODES else default


def _int(value: object, default: int) -> int:
    try:
        return int(str(value))
    except ValueError:
        return default
