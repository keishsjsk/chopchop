"""Соседние файлы в папке: порядок как в проводнике, листание по кругу."""

import os
import re
from collections.abc import Iterable
from pathlib import Path

from quickedit.core.document import IMAGE_EXTENSIONS


def natural_key(name: str) -> list[int | str]:
    """Ключ «естественной» сортировки: img2 идёт раньше img10."""
    parts = re.split(r"(\d+)", name.casefold())
    return [int(p) if i % 2 else p for i, p in enumerate(parts)]


def list_folder(current: Path, extensions: Iterable[str] = IMAGE_EXTENSIONS) -> list[Path]:
    allowed = frozenset(extensions)
    files: list[Path] = []
    try:
        with os.scandir(current.parent) as entries:
            files = [
                Path(e.path)
                for e in entries
                if Path(e.name).suffix.lower() in allowed and e.is_file()
            ]
    except OSError:
        pass
    if current not in files:
        files.append(current)
    return sorted(files, key=lambda p: natural_key(p.name))


class FolderNav:
    def __init__(self, current: Path, extensions: Iterable[str] = IMAGE_EXTENSIONS) -> None:
        self.files = list_folder(current, extensions)
        self.index = self.files.index(current)

    @property
    def current(self) -> Path:
        return self.files[self.index]

    def step(self, delta: int) -> Path:
        self.index = (self.index + delta) % len(self.files)
        return self.current

    def neighbors(self, ahead: int = 2, behind: int = 1) -> list[Path]:
        """Файлы для предзагрузки: сначала ближайшие вперёд, затем назад."""
        count = len(self.files)
        offsets = [*range(1, ahead + 1), *(-i for i in range(1, behind + 1))]
        result: list[Path] = []
        for offset in offsets:
            path = self.files[(self.index + offset) % count]
            if path != self.current and path not in result:
                result.append(path)
        return result
