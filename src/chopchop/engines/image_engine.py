"""Применение операций к фото через Pillow: и для превью на прокси, и для экспорта."""

import math
from collections.abc import Callable, Iterable
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps, ImageStat

from chopchop.core.operations import (
    Adjust,
    Annotate,
    Crop,
    Filter,
    Flip,
    Operation,
    Redact,
    Resize,
    Rotate,
    Stroke,
    Text,
    scale_operation,
)
from chopchop.engines.fonts import find_font
from chopchop.services.metadata import exif_for_export
from chopchop.services.output import render_name, unique_path
from chopchop.services.profiling import stage

PROXY_SIDE = 2048
MARKER_ALPHA = 110
ARROW_HEAD_ANGLE = math.radians(28)

FORMATS = {"png": (".png", "PNG"), "jpeg": (".jpg", "JPEG"), "webp": (".webp", "WEBP")}


# --- загрузка ----------------------------------------------------------------------------------


def open_image(path: Path) -> tuple[Image.Image, Image.Exif]:
    """Открывает фото, применяет поворот из EXIF; возвращает картинку и её EXIF."""
    import pillow_heif

    pillow_heif.register_heif_opener()
    with stage("photo.open_full"), Image.open(path) as opened:
        exif = opened.getexif()
        image = ImageOps.exif_transpose(opened)
        has_alpha = "A" in image.getbands() or "transparency" in image.info
        return image.convert("RGBA" if has_alpha else "RGB"), exif


def load_preview(
    path: Path, max_side: int = PROXY_SIDE
) -> tuple[Image.Image, float, tuple[int, int]]:
    """Уменьшенная копия для редактирования без декодирования файла целиком.

    JPEG при открытии декодируется сразу в уменьшенном виде (draft): 24 Мп читаются в несколько
    раз быстрее. Возвращает превью, его масштаб относительно оригинала и размер оригинала.
    """
    import pillow_heif

    pillow_heif.register_heif_opener()
    with stage("photo.load_preview"), Image.open(path) as opened:
        width, height = opened.size
        if opened.getexif().get(0x0112, 1) in (5, 6, 7, 8):  # снимок повёрнут на 90°
            width, height = height, width
        if opened.format == "JPEG":
            # размер надо просить с пропорциями кадра, иначе декодер не уменьшает в 2 и более раз
            factor = max_side / max(opened.size)
            opened.draft("RGB", (round(opened.width * factor), round(opened.height * factor)))
        image = ImageOps.exif_transpose(opened)
        has_alpha = "A" in image.getbands() or "transparency" in image.info
        image = image.convert("RGBA" if has_alpha else "RGB")
        image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return image, image.width / width, (width, height)


def make_proxy(image: Image.Image, max_side: int = PROXY_SIDE) -> tuple[Image.Image, float]:
    """Уменьшенная копия для быстрого превью и её масштаб относительно оригинала."""
    with stage("photo.make_proxy"):
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
    with stage(f"op.{type(op).__name__}"):
        return _apply_operation(image, op)


def _apply_operation(image: Image.Image, op: Operation) -> Image.Image:
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
        case Stroke():
            return _stroke(image, op)
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
    """Яркость, контраст, насыщенность, гамма.

    Яркость и контраст — таблицы значений (point), в 5–7 раз быстрее ImageEnhance при том же
    результате с точностью до единицы; насыщенность через ImageEnhance, ей таблицы не подходят.
    """
    if op.is_identity:
        return image
    rgb = image if image.mode == "RGB" else image.convert("RGB")
    if op.brightness != 1.0:
        rgb = rgb.point(_table(lambda x: x * op.brightness) * 3)
    if op.contrast != 1.0:
        mean = int(ImageStat.Stat(rgb.convert("L")).mean[0] + 0.5)
        rgb = rgb.point(_table(lambda x: mean + (x - mean) * op.contrast) * 3)
    if op.saturation != 1.0:
        rgb = ImageEnhance.Color(rgb).enhance(op.saturation)
    if op.gamma != 1.0:
        rgb = rgb.point(_table(lambda x: 255 * (x / 255) ** (1 / op.gamma)) * 3)
    if image.mode == "RGBA":
        rgb.putalpha(image.getchannel("A"))
    return rgb


def _table(curve: Callable[[float], float]) -> list[int]:
    return [min(max(round(curve(i)), 0), 255) for i in range(256)]


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


def _stroke(image: Image.Image, op: Stroke) -> Image.Image:
    """Линия от руки со скруглёнными концами; полупрозрачная не темнеет в местах пересечений.

    Рисуется и склеивается только в границах штриха: на больших кадрах это в разы быстрее.
    """
    if not op.points:
        return image
    width = max(1, round(op.width))
    alpha = round(min(max(op.opacity, 0.0), 1.0) * 255)
    points = [(float(x), float(y)) for x, y in op.points]
    pad = math.ceil(width / 2) + 2
    left = max(math.floor(min(x for x, _ in points)) - pad, 0)
    top = max(math.floor(min(y for _, y in points)) - pad, 0)
    right = min(math.ceil(max(x for x, _ in points)) + pad, image.width)
    bottom = min(math.ceil(max(y for _, y in points)) + pad, image.height)
    if right <= left or bottom <= top:
        return image
    box = (left, top, right, bottom)
    region = image.crop(box).convert("RGBA")
    layer = Image.new("RGBA", region.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    fill = (*op.color, alpha)
    local = [(x - left, y - top) for x, y in points]
    if len(local) > 1:
        draw.line(local, fill=fill, width=width, joint="curve")
    radius = width / 2
    for x, y in local[:: max(1, len(local) // 400)] + [local[0], local[-1]]:
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill)
    merged = Image.alpha_composite(region, layer)
    result = image.copy()
    result.paste(merged if image.mode == "RGBA" else merged.convert("RGB"), (left, top))
    return result


def _text(image: Image.Image, op: Text) -> Image.Image:
    if not op.text:
        return image
    result = image.copy()
    font = find_font(max(6, round(op.size)))
    ImageDraw.Draw(result).multiline_text((op.x, op.y), op.text, font=font, fill=op.color)
    return result


# --- экспорт -----------------------------------------------------------------------------------


def default_output_path(
    source: Path | None,
    fmt: str,
    folder: Path | None = None,
    template: str = "{name}_edited",
) -> Path:
    """Путь вида photo_edited.jpg рядом с исходником; существующие файлы не перезаписываются."""
    extension = FORMATS[fmt][0]
    directory = folder or (source.parent if source else Path.home() / "Pictures")
    stem = render_name(template, source.stem if source else "image")
    return unique_path(directory, stem, extension)


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
