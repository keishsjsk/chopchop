"""Имена выходных файлов: результат всегда новый файл, исходник не перезаписывается."""

import re
import time
from pathlib import Path


def unique_path(directory: Path, stem: str, extension: str) -> Path:
    """directory/stem.ext, а если занято — directory/stem (2).ext и так далее."""
    candidate = directory / f"{stem}{extension}"
    counter = 2
    while candidate.exists():
        candidate = directory / f"{stem} ({counter}){extension}"
        counter += 1
    return candidate


_FORBIDDEN = '<>:"/\\|?*'
MAX_STEM = 150


_FIELD = re.compile(r"\{(name|date|time)\}")


def render_name(template: str, source_stem: str, now: time.struct_time | None = None) -> str:
    """Имя результата по шаблону ({name}, {date}, {time}) без недопустимых в именах символов.

    Подстановка идёт только для трёх известных полей, а не через str.format: атрибуты объектов
    из шаблона (`{name.__class__}`) не читаются.
    """
    moment = now or time.localtime()
    values = {
        "name": source_stem,
        "date": time.strftime("%Y-%m-%d", moment),
        "time": time.strftime("%H-%M-%S", moment),
    }
    if "{" in _FIELD.sub("", template) or "}" in _FIELD.sub("", template):
        text = f"{source_stem}_edited"  # испорченный шаблон не должен ломать сохранение
    else:
        text = _FIELD.sub(lambda match: values[match.group(1)], template)
    cleaned = "".join("_" if c in _FORBIDDEN or ord(c) < 32 else c for c in text)
    cleaned = cleaned.strip(" .")[:MAX_STEM].rstrip(" .")
    return cleaned or "output"
