"""Настройки приложения поверх QSettings: пока только список последних файлов."""

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
    return QSettings("QuickEdit", "QuickEdit")
