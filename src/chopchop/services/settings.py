"""Список последних файлов (QSettings) и параметры плеера, собранные из настроек приложения."""

from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QSettings

from chopchop.core.subtitle_style import SubtitleStyle, style_from_dict
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

    def remove(self, path: Path) -> None:
        self._settings.setValue(_RECENT_KEY, [str(p) for p in self.items() if p != path])

    def replace(self, old: Path, new: Path) -> None:
        """Файл переименован: в списке последних он остаётся на своём месте."""
        items = [str(new) if p == old else str(p) for p in self.items()]
        self._settings.setValue(_RECENT_KEY, items)


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
    style: SubtitleStyle = field(default_factory=SubtitleStyle)
    codepage: str = "auto"
    sub_pos2: int = 0  # положение второй строки субтитров, % от верха


def subtitle_style(settings: AppSettings) -> SubtitleStyle:
    """Оформление субтитров из настроек (значения проходят проверку пределов)."""
    return style_from_dict(
        {
            "font": settings.get_str("subtitles.font"),
            "font_size": settings.get_int("subtitles.font_size"),
            "bold": settings.get_bool("subtitles.bold"),
            "italic": settings.get_bool("subtitles.italic"),
            "color": settings.get_str("subtitles.color"),
            "outline_color": settings.get_str("subtitles.outline_color"),
            "outline_size": settings.get_float("subtitles.outline_size"),
            "shadow_color": settings.get_str("subtitles.shadow_color"),
            "shadow_offset": settings.get_float("subtitles.shadow_offset"),
            "back_enabled": settings.get_bool("subtitles.back_enabled"),
            "back_color": settings.get_str("subtitles.back_color"),
            "back_opacity": settings.get_int("subtitles.back_opacity"),
            "line_spacing": settings.get_int("subtitles.line_spacing"),
            "margin_y": settings.get_int("subtitles.margin"),
            "margin_x": settings.get_int("subtitles.margin_x"),
            "align_x": settings.get_str("subtitles.align_x"),
            "align_y": settings.get_str("subtitles.align_y"),
            "pos": settings.get_int("subtitles.pos"),
            "scale": settings.get_float("subtitles.scale"),
            "ass_mode": settings.get_str("subtitles.ass_mode"),
        }
    )


STYLE_KEYS = {
    "font": "subtitles.font",
    "font_size": "subtitles.font_size",
    "bold": "subtitles.bold",
    "italic": "subtitles.italic",
    "color": "subtitles.color",
    "outline_color": "subtitles.outline_color",
    "outline_size": "subtitles.outline_size",
    "shadow_color": "subtitles.shadow_color",
    "shadow_offset": "subtitles.shadow_offset",
    "back_enabled": "subtitles.back_enabled",
    "back_color": "subtitles.back_color",
    "back_opacity": "subtitles.back_opacity",
    "line_spacing": "subtitles.line_spacing",
    "margin_y": "subtitles.margin",
    "margin_x": "subtitles.margin_x",
    "align_x": "subtitles.align_x",
    "align_y": "subtitles.align_y",
    "pos": "subtitles.pos",
    "scale": "subtitles.scale",
    "ass_mode": "subtitles.ass_mode",
}  # поле SubtitleStyle -> ключ настройки


def save_subtitle_style(settings: AppSettings, style: SubtitleStyle) -> None:
    """Записать оформление в настройки целиком (применяется к mpv на лету)."""
    for field_name, key in STYLE_KEYS.items():
        settings.set(key, getattr(style, field_name))


def player_prefs(settings: AppSettings) -> PlayerPrefs:
    return PlayerPrefs(
        audio_langs=settings.get_str("playback.audio_langs"),
        sub_langs=settings.get_str("playback.sub_langs"),
        sub_font_size=settings.get_int("subtitles.font_size"),
        sub_margin=settings.get_int("subtitles.margin"),
        style=subtitle_style(settings),
        codepage=settings.get_str("subtitles.codepage"),
        sub_pos2=settings.get_int("subtitles.pos2"),
        hwdec=settings.mpv_hwdec(),
        volume=float(settings.get_int("playback.volume_default")),
    )
