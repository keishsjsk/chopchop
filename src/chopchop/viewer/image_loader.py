"""Декодирование фото в QImage. Безопасно вызывать из фонового потока."""

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage, QImageIOHandler, QImageReader

from chopchop.services.profiling import stage


def load_image(path: Path) -> QImage | None:
    """Читает фото с учётом поворота из EXIF; None, если файл не удалось прочитать."""
    with stage("photo.load_full"):
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        image = reader.read()
        if not image.isNull():
            return image
        return _load_with_pillow(path)


def load_reduced(path: Path, max_side: int) -> QImage | None:
    """Уменьшенная копия для мгновенного первого показа; None, если быстрого пути нет.

    JPEG декодируется сразу в нужном масштабе (в разы быстрее полного чтения). Если формат так не
    умеет или картинка и так не больше max_side, возвращается None: показывать нечего заранее.
    """
    with stage("photo.load_reduced"):
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        if not reader.supportsOption(QImageIOHandler.ImageOption.ScaledSize):
            return None
        size = reader.size()
        if not size.isValid() or max(size.width(), size.height()) <= max_side:
            return None
        reader.setScaledSize(
            QSize(size).scaled(max_side, max_side, Qt.AspectRatioMode.KeepAspectRatio)
        )
        image = reader.read()
        return None if image.isNull() else image


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
