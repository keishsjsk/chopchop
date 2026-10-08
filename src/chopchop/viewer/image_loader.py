"""Декодирование фото в QImage. Безопасно вызывать из фонового потока."""

from pathlib import Path

from PySide6.QtGui import QImage, QImageReader


def load_image(path: Path) -> QImage | None:
    """Читает фото с учётом поворота из EXIF; None, если файл не удалось прочитать."""
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    image = reader.read()
    if not image.isNull():
        return image
    return _load_with_pillow(path)


def _load_with_pillow(path: Path) -> QImage | None:
    """Запасной путь для форматов, которых нет в Qt (HEIC с айфонов)."""
    try:
        import pillow_heif
        from PIL import Image, ImageOps

        pillow_heif.register_heif_opener()
        with Image.open(path) as opened:
            rgba = ImageOps.exif_transpose(opened).convert("RGBA")
        width, height = rgba.size
        # copy(): QImage иначе ссылается на буфер, который освободится после возврата
        image = QImage(rgba.tobytes(), width, height, width * 4, QImage.Format.Format_RGBA8888)
        return image.copy()
    except Exception:
        return None
