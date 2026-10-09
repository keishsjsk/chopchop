"""Преобразование между картинками Pillow и Qt."""

from PIL import Image
from PySide6.QtGui import QImage

from chopchop.services.profiling import stage


def pil_to_qimage(image: Image.Image) -> QImage:
    """Одна конвертация на готовый кадр: RGB и RGBA передаются как есть, без промежуточной копии."""
    with stage("pil_to_qimage"):
        if image.mode == "RGB":
            qt_format, channels = QImage.Format.Format_RGB888, 3
        else:
            if image.mode != "RGBA":
                image = image.convert("RGBA")
            qt_format, channels = QImage.Format.Format_RGBA8888, 4
        width, height = image.size
        # copy(): QImage ссылается на буфер bytes, который освободится после возврата
        return QImage(image.tobytes(), width, height, width * channels, qt_format).copy()


def qimage_to_pil(image: QImage) -> Image.Image:
    converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
    # строки RGBA8888 выровнены по 4 байтам, поэтому отступов в конце строки нет
    return Image.frombytes(
        "RGBA", (converted.width(), converted.height()), bytes(converted.constBits())
    )
