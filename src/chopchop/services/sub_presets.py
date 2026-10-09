"""Именованные пресеты оформления субтитров: файл рядом с настройками, импорт и экспорт JSON."""

import contextlib
import os
import tempfile
from pathlib import Path

from chopchop.core import subtitle_style as ss
from chopchop.core.subtitle_style import PresetFileError, SubtitleStyle

FILE_NAME = "subtitle_presets.json"


class PresetStore:
    """Пользовательские пресеты. Встроенные («Стандарт», «Кино» …) лежат в коде и не меняются."""

    def __init__(self, path: Path | None) -> None:
        self._path = path
        self.user: dict[str, SubtitleStyle] = {}
        self.error: str = ""
        self.load()

    def load(self) -> None:
        self.user = {}
        self.error = ""
        if self._path is None or not self._path.is_file():
            return
        try:
            self.user = ss.presets_from_json(self._path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, PresetFileError) as error:
            self.error = str(error)  # повреждённый файл не мешает работе: пресетов просто нет

    def _save(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        text = ss.presets_to_json(self.user)
        handle, temp = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(text)
            os.replace(temp, self._path)
        except OSError:
            with contextlib.suppress(OSError):
                os.unlink(temp)
            raise

    # --- состав ------------------------------------------------------------------------------

    def names(self) -> list[str]:
        """Сначала встроенные, затем пользовательские."""
        return [*ss.BUILTIN, *self.user]

    def is_builtin(self, name: str) -> bool:
        return name in ss.BUILTIN

    def get(self, name: str) -> SubtitleStyle | None:
        return ss.BUILTIN.get(name) or self.user.get(name)

    def name_of(self, style: SubtitleStyle) -> str | None:
        """Имя пресета, которому в точности равно оформление; None — оформление своё."""
        for name in self.names():
            if self.get(name) == style:
                return name
        return None

    # --- изменения ---------------------------------------------------------------------------

    def save_as(self, name: str, style: SubtitleStyle) -> str:
        """Сохранить оформление под именем; встроенные имена не перезаписываются."""
        clean = name.strip()
        if not clean:
            raise ValueError("пустое имя пресета")
        if clean in ss.BUILTIN:
            clean = f"{clean} (мой)"
        self.user[clean] = style
        self._save()
        return clean

    def remove(self, name: str) -> bool:
        if name in self.user:
            del self.user[name]
            self._save()
            return True
        return False

    # --- файлы -------------------------------------------------------------------------------

    def export_to(self, path: Path, extra: dict[str, SubtitleStyle] | None = None) -> None:
        """Записать свои пресеты (и, если нужно, ещё что-то, например текущее оформление)."""
        presets = {**self.user, **(extra or {})}
        if not presets:
            raise ValueError("нечего экспортировать")
        path.write_text(ss.presets_to_json(presets), encoding="utf-8")

    def import_from(self, path: Path) -> list[str]:
        """Добавить пресеты из файла; совпавшие имена получают пометку, свои не затираются."""
        loaded = ss.presets_from_json(path.read_text(encoding="utf-8"))
        added: list[str] = []
        for name, style in loaded.items():
            if ss.BUILTIN.get(name) == style:
                continue  # такой встроенный пресет уже есть
            final = name
            while final in ss.BUILTIN or (final in self.user and self.user[final] != style):
                final = f"{final} (импорт)"
            self.user[final] = style
            added.append(final)
        if added:
            self._save()
        return added
