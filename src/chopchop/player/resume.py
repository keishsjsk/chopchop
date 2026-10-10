"""Запоминание позиции, громкости и выбранных дорожек для каждого файла."""

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from PySide6.QtCore import QSettings

_KEY = "resume/entries"
MAX_ENTRIES = 200
MIN_RESUME_SECONDS = 5.0  # начало не запоминаем
END_MARGIN_SECONDS = 10.0  # досмотренное до конца начинаем заново


@dataclass
class ResumeState:
    position: float = 0.0
    volume: float | None = None
    aid: int | None = None
    sid: int | None = None
    secondary_sid: int | None = None
    sub_delay: float = 0.0
    secondary_sub_delay: float = 0.0


class ResumeStore:
    def __init__(self, settings: QSettings) -> None:
        self._settings = settings

    def _read(self) -> dict[str, dict[str, object]]:
        raw = self._settings.value(_KEY, "")
        try:
            data = json.loads(str(raw)) if raw else {}
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    def load(self, path: Path) -> ResumeState | None:
        entry = self._read().get(str(path))
        if not entry:
            return None
        known = ResumeState.__dataclass_fields__
        try:
            return ResumeState(**{k: v for k, v in entry.items() if k in known})  # type: ignore[arg-type]
        except TypeError:
            return None

    def rename(self, old: Path, new: Path) -> None:
        """Файл переименован: запомненная позиция и дорожки переходят к новому имени."""
        entries = self._read()
        entry = entries.pop(str(old), None)
        if entry is not None:
            entries[str(new)] = entry
            self._settings.setValue(_KEY, json.dumps(entries))

    def forget(self, path: Path) -> None:
        entries = self._read()
        if entries.pop(str(path), None) is not None:
            self._settings.setValue(_KEY, json.dumps(entries))

    def save(self, path: Path, state: ResumeState, duration: float | None) -> None:
        entries = self._read()
        key = str(path)
        finished = duration is not None and state.position > duration - END_MARGIN_SECONDS
        if state.position < MIN_RESUME_SECONDS or finished:
            state = ResumeState(**{**asdict(state), "position": 0.0})
        entries.pop(key, None)  # заново вставляем в конец: самые свежие последними
        entries[key] = {**asdict(state), "ts": time.time()}
        while len(entries) > MAX_ENTRIES:
            entries.pop(next(iter(entries)))
        self._settings.setValue(_KEY, json.dumps(entries))
