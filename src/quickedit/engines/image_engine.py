"""Применение операций к фото через Pillow: и для превью на прокси, и для экспорта."""

import math
from collections.abc import Iterable
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from quickedit.core.operations import (
    Adjust,
    Annotate,
    Crop,
    Filter,
    Flip,
    Operation,
    Redact,
    Resize,
    Rotate,
    Text,
    scale_operation,
)
from quickedit.engines.fonts import find_font
from quickedit.services.metadata import exif_for_export

PROXY_SIDE = 2048
MARKER_ALPHA = 110
ARROW_HEAD_ANGLE = math.radians(28)

FORMATS = {"png": (".png", "PNG"), "jpeg": (".jpg", "JPEG"), "webp": (".webp", "WEBP")}


# --- загрузка ----------------------------------------------------------------------------------


def open_image(path: Path) -> tuple[Image.Image, Image.Exif]:
    """Открывает фото, применяет поворот из EXIF; возвращает картинку и её EXIF."""
    import pillow_heif

    pillow_heif.register_heif_opener()
    with Image.open(path) as opened:
        exif = opened.getexif()
        image = ImageOps.exif_transpose(opened)
        has_alpha = "A" in image.getbands() or "transparency" in image.info
        return image.convert("RGBA" if has_alpha else "RGB"), exif


def make_proxy(image: Image.Image, max_side: int = PROXY_SIDE) -> tuple[Image.Image, float]:
    """Уменьшенная копия для быстрого превью и её масштаб относительно оригинала."""
    proxy = image.copy()
    proxy.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return proxy, proxy.width / image.width


# --- операции ----------------------------------------------------------------------------------


def apply_operations(
    image: Image.Image, ops: Iterable[Operation], scale: float = 1.0
) -> Image.Image:
    """Применяет операции по порядку; scale — масштаб картинки относительно координат операций."""
    for op in ops:
        image = apply_operation(image, scale_operation(op, scale) if scale != 1.0 else op)
    return image


def apply_operation(image: Image.Image, op: Operation) -> Image.Image:
    match op:
        case Crop(rect):
            box = rect.to_box(*image.size)
            return image.crop(box) if box else image
        case Rotate(degrees):
            method = {
                90: Image.Transpose.ROTATE_270,
                180: Image.Transpose.ROTATE_180,
                270: Image.Transpose.ROTATE_90,
            }[degrees]
            return image.transpose(method)
        case Flip(horizontal):
            return image.transpose(
                Image.Transpose.FLIP_LEFT_RIGHT if horizontal else Image.Transpose.FLIP_TOP_BOTTOM
            )
        case Redact():
            return _redact(image, op)
        case Adjust():
            return _adjust(image, op)
        case Filter(name):
            return _filter(image, name)
        case Annotate():
            return _annotate(image, op)
        case Text():
            return _text(image, op)
        case Resize(width, height):
            return image.resize((max(1, width), max(1, height)), Image.Resampling.LANCZOS)


def _redact(image: Image.Image, op: Redact) -> Image.Image:
    box = op.rect.to_box(*image.size)
    if box is None:
        return image
    result = image.copy()
    if op.mode == "fill":
        ImageDraw.Draw(result).rectangle((box[0], box[1], box[2] - 1, box[3] - 1), fill=op.color)
        return result
    region = result.crop(box)
    if op.mode == "blur":
        region = region.filter(ImageFilter.GaussianBlur(max(op.strength, 1.0)))
    else:
        block = max(2, round(op.strength))
        small = region.resize(
            (max(1, region.width // block), max(1, region.height // block)), Image.Resampling.BOX
        )
        region = small.resize(region.size, Image.Resampling.NEAREST)
    result.paste(region, box[:2])
    return result


def _adjust(image: Image.Image, op: Adjust) -> Image.Image:
    if op.is_identity:
        return image
    rgb = image.convert("RGB")
    if op.brightness != 1.0:
        rgb = ImageEnhance.Brightness(rgb).enhance(op.brightness)
    if op.contrast != 1.0:
        rgb = ImageEnhance.Contrast(rgb).enhance(op.contrast)
    if op.saturation != 1.0:
        rgb = ImageEnhance.Color(rgb).enhance(op.saturation)
    if op.gamma != 1.0:
        table = [round(255 * (i / 255) ** (1 / op.gamma)) for i in range(256)]
        rgb = rgb.point(table * 3)
    if image.mode == "RGBA":
        rgb.putalpha(image.getchannel("A"))
    return rgb


def _filter(image: Image.Image, name: str) -> Image.Image:
    # радиусы заданы долей размера кадра, чтобы превью и полный размер выглядели одинаково
    side = max(image.size)
    alpha = image.getchannel("A") if image.mode == "RGBA" else None
    rgb = image.convert("RGB")
    match name:
        case "grayscale":
            rgb = ImageOps.grayscale(rgb).convert("RGB")
        case "sepia":
            gray = ImageOps.grayscale(rgb)
            rgb = ImageOps.colorize(
                gray, black=(30, 18, 6), mid=(150, 110, 70), white=(255, 240, 214)
            )
        case "sharpen":
            radius = max(1.0, side * 0.002)
            rgb = rgb.filter(ImageFilter.UnsharpMask(radius=radius, percent=160, threshold=2))
        case "blur":
            rgb = rgb.filter(ImageFilter.GaussianBlur(max(1.0, side * 0.004)))
    if alpha is not None:
        rgb.putalpha(alpha)
    return rgb


def _annotate(image: Image.Image, op: Annotate) -> Image.Image:
    width = max(1, round(op.width))
    (x0, y0), (x1, y1) = op.start, op.end
    if op.shape == "marker":
        base = image.convert("RGBA")
        overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
        ImageDraw.Draw(overlay).rectangle(
            (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)), fill=(*op.color, MARKER_ALPHA)
        )
        merged = Image.alpha_composite(base, overlay)
        return merged if image.mode == "RGBA" else merged.convert("RGB")

    result = image.copy()
    draw = ImageDraw.Draw(result)
    if op.shape == "rect":
        draw.rectangle(
            (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)), outline=op.color, width=width
        )
        return result

    length = math.hypot(x1 - x0, y1 - y0)
    if length < 1:
        return result
    head = min(max(width * 4.0, 12.0), length)
    angle = math.atan2(y1 - y0, x1 - x0)
    left = (
        x1 - head * math.cos(angle - ARROW_HEAD_ANGLE),
        y1 - head * math.sin(angle - ARROW_HEAD_ANGLE),
    )
    right = (
        x1 - head * math.cos(angle + ARROW_HEAD_ANGLE),
        y1 - head * math.sin(angle + ARROW_HEAD_ANGLE),
    )
    base_x, base_y = (left[0] + right[0]) / 2, (left[1] + right[1]) / 2
    draw.line((x0, y0, base_x, base_y), fill=op.color, width=width)
    draw.polygon((op.end, left, right), fill=op.color)
    return result


def _text(image: Image.Image, op: Text) -> Image.Image:
    if not op.text:
        return image
    result = image.copy()
    font = find_font(max(6, round(op.size)))
    ImageDraw.Draw(result).multiline_text((op.x, op.y), op.text, font=font, fill=op.color)
    return result


# --- экспорт -----------------------------------------------------------------------------------


def default_output_path(source: Path | None, fmt: str, folder: Path | None = None) -> Path:
    """Путь вида photo_edited.jpg рядом с исходником; существующие файлы не перезаписываются."""
    extension = FORMATS[fmt][0]
    directory = folder or (source.parent if source else Path.home() / "Pictures")
    stem = f"{source.stem}_edited" if source else "image_edited"
    candidate = directory / f"{stem}{extension}"
    counter = 2
    while candidate.exists():
        candidate = directory / f"{stem} ({counter}){extension}"
        counter += 1
    return candidate


def format_for_source(source: Path | None) -> str:
    """Формат быстрого сохранения: тот же, что у исходника, если Pillow умеет его писать."""
    suffix = source.suffix.lower() if source else ""
    if suffix in (".jpg", ".jpeg", ".heic", ".heif"):
        return "jpeg"
    if suffix == ".webp":
        return "webp"
    return "png"


def save_image(
    image: Image.Image,
    dest: Path,
    fmt: str,
    quality: int = 92,
    exif: Image.Exif | None = None,
    keep_metadata: bool = False,
) -> Path:
    """Сохраняет в новый файл. Метаданные пишутся только если явно попросили."""
    _, pil_format = FORMATS[fmt]
    options: dict[str, object] = {}
    if pil_format == "JPEG":
        if image.mode == "RGBA":
            background = Image.new("RGB", image.size, "white")
            background.paste(image, mask=image.getchannel("A"))
            image = background
        options.update(quality=quality, optimize=True)
    elif pil_format == "WEBP":
        options.update(quality=quality)
    else:
        options.update(optimize=True)
    exif_bytes = exif_for_export(exif, keep_metadata)
    if exif_bytes is not None and pil_format != "PNG":
        options["exif"] = exif_bytes
    dest.parent.mkdir(parents=True, exist_ok=True)
    image.save(dest, pil_format, **options)
    return dest
