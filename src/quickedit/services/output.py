"""Имена выходных файлов: результат всегда новый файл, исходник не перезаписывается."""

from pathlib import Path


def unique_path(directory: Path, stem: str, extension: str) -> Path:
    """directory/stem.ext, а если занято — directory/stem (2).ext и так далее."""
    candidate = directory / f"{stem}{extension}"
    counter = 2
    while candidate.exists():
        candidate = directory / f"{stem} ({counter}){extension}"
        counter += 1
    return candidate
