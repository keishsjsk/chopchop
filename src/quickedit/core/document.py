"""Тип медиафайла. Чистый Python, без Qt."""

from enum import Enum
from pathlib import Path


class MediaKind(Enum):
    IMAGE = "image"
    VIDEO = "video"


IMAGE_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".heic", ".heif"}
)
VIDEO_EXTENSIONS = frozenset(
    {".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v", ".wmv", ".flv", ".mpg", ".mpeg", ".ts"}
)


def detect_kind(path: Path) -> MediaKind | None:
    """Определяет тип файла по расширению; None, если формат не поддерживается."""
    ext = path.suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return MediaKind.IMAGE
    if ext in VIDEO_EXTENSIONS:
        return MediaKind.VIDEO
    return None
