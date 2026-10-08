"""Преобразование между картинками Pillow и Qt."""

from PIL import Image
from PySide6.QtGui import QImage


def pil_to_qimage(image: Image.Image) -> QImage:
    rgba = image.convert("RGBA")
    width, height = rgba.size
    # copy(): QImage ссылается на буфер bytes, который освободится после возврата
    return QImage(rgba.tobytes(), width, height, width * 4, QImage.Format.Format_RGBA8888).copy()


def qimage_to_pil(image: QImage) -> Image.Image:
    converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
    # строки RGBA8888 выровнены по 4 байтам, поэтому отступов в конце строки нет
    return Image.frombytes(
        "RGBA", (converted.width(), converted.height()), bytes(converted.constBits())
    )
