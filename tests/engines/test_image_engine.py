from pathlib import Path

import pytest
from PIL import Image

from quickedit.core.geometry import Rect
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
    Stroke,
    Text,
    output_size,
)
from quickedit.engines.image_engine import (
    apply_operation,
    apply_operations,
    default_output_path,
    format_for_source,
    make_proxy,
    open_image,
    save_image,
)


def _two_tone(size: tuple[int, int] = (40, 20)) -> Image.Image:
    """Левая половина красная, правая синяя."""
    image = Image.new("RGB", size, (255, 0, 0))
    image.paste((0, 0, 255), (size[0] // 2, 0, size[0], size[1]))
    return image


def test_crop_and_resize() -> None:
    image = _two_tone()
    cropped = apply_operation(image, Crop(Rect(20, 0, 20, 20)))
    assert cropped.size == (20, 20)
    assert cropped.getpixel((0, 0)) == (0, 0, 255)
    assert apply_operation(image, Resize(10, 5)).size == (10, 5)


def test_crop_outside_image_is_ignored() -> None:
    image = _two_tone()
    assert apply_operation(image, Crop(Rect(500, 500, 10, 10))).size == image.size


def test_rotate_clockwise() -> None:
    image = _two_tone()  # красная слева, синяя справа
    rotated = apply_operation(image, Rotate(90))
    assert rotated.size == (20, 40)
    assert rotated.getpixel((10, 5)) == (255, 0, 0)  # левая половина стала верхней
    assert rotated.getpixel((10, 35)) == (0, 0, 255)
    assert apply_operation(image, Rotate(180)).getpixel((0, 0)) == (0, 0, 255)
    assert apply_operation(image, Rotate(270)).getpixel((10, 5)) == (0, 0, 255)


def test_flip() -> None:
    image = _two_tone()
    assert apply_operation(image, Flip(True)).getpixel((0, 0)) == (0, 0, 255)
    assert apply_operation(image, Flip(False)).getpixel((0, 0)) == (255, 0, 0)


def test_redact_fill_covers_area_only() -> None:
    image = _two_tone()
    result = apply_operation(image, Redact(Rect(5, 5, 10, 10), "fill", color=(0, 255, 0)))
    assert result.getpixel((5, 5)) == (0, 255, 0)
    assert result.getpixel((14, 14)) == (0, 255, 0)
    assert result.getpixel((15, 15)) == (255, 0, 0)
    assert result.getpixel((4, 4)) == (255, 0, 0)
    assert image.getpixel((5, 5)) == (255, 0, 0)  # исходная картинка не изменилась


def test_redact_pixelate_makes_blocks() -> None:
    gradient = Image.linear_gradient("L").resize((64, 64)).convert("RGB")
    result = apply_operation(gradient, Redact(Rect(0, 0, 64, 64), "pixelate", strength=16))
    assert result.getpixel((0, 0)) == result.getpixel((15, 15))
    assert result.getpixel((0, 0)) != result.getpixel((0, 63))
    assert result.getpixel((20, 20)) == result.getpixel((31, 31))


def test_redact_blur_softens_edge() -> None:
    result = apply_operation(_two_tone((60, 20)), Redact(Rect(0, 0, 60, 20), "blur", strength=6))
    mid = result.getpixel((30, 10))
    assert mid[0] not in (0, 255)  # на границе красного и синего появился переход


def test_adjust_brightness_and_identity() -> None:
    image = Image.new("RGB", (4, 4), (100, 100, 100))
    brighter = apply_operation(image, Adjust(brightness=1.5))
    assert brighter.getpixel((0, 0))[0] == 150
    assert apply_operation(image, Adjust()) is image
    darker_gamma = apply_operation(image, Adjust(gamma=0.5))
    assert darker_gamma.getpixel((0, 0))[0] < 100


def test_adjust_keeps_alpha() -> None:
    image = Image.new("RGBA", (4, 4), (100, 100, 100, 77))
    result = apply_operation(image, Adjust(contrast=1.3))
    assert result.mode == "RGBA"
    assert result.getpixel((0, 0))[3] == 77


def test_filters() -> None:
    image = Image.new("RGB", (8, 8), (200, 50, 50))
    gray = apply_operation(image, Filter("grayscale")).getpixel((0, 0))
    assert gray[0] == gray[1] == gray[2]
    r, g, b = apply_operation(image, Filter("sepia")).getpixel((0, 0))
    assert r > g > b
    for name in ("sharpen", "blur"):
        assert apply_operation(image, Filter(name)).size == image.size


def test_annotations_draw_pixels() -> None:
    base = Image.new("RGB", (100, 100), "black")
    arrow = apply_operation(base, Annotate("arrow", (10, 50), (90, 50), (255, 0, 0), 4))
    assert arrow.getpixel((50, 50)) == (255, 0, 0)
    assert arrow.getpixel((50, 10)) == (0, 0, 0)
    rect = apply_operation(base, Annotate("rect", (20, 20), (80, 80), (0, 255, 0), 3))
    assert rect.getpixel((20, 50)) == (0, 255, 0)
    assert rect.getpixel((50, 50)) == (0, 0, 0)
    marker = apply_operation(base, Annotate("marker", (20, 20), (80, 80), (255, 255, 0)))
    r, g, b = marker.getpixel((50, 50))
    assert 0 < r < 255 and r == g and b == 0  # полупрозрачная заливка


def test_zero_length_arrow_is_harmless() -> None:
    base = Image.new("RGB", (20, 20), "black")
    result = apply_operation(base, Annotate("arrow", (5, 5), (5, 5)))
    assert result.getpixel((5, 5)) == (0, 0, 0)


def test_text_draws_pixels_and_supports_cyrillic() -> None:
    base = Image.new("RGB", (200, 60), "black")
    result = apply_operation(base, Text("Привет", 5, 5, size=30, color=(255, 255, 255)))
    assert result.getbbox() is not None
    assert result.tobytes() != base.tobytes()
    assert apply_operation(base, Text("", 5, 5)) is base


def test_operations_apply_in_order() -> None:
    image = _two_tone()
    # сначала поворот, затем кроп верхней половины: остаётся красная часть
    ops: list[Operation] = [Rotate(90), Crop(Rect(0, 0, 20, 20))]
    result = apply_operations(image, ops)
    assert result.size == (20, 20)
    assert result.getpixel((10, 10)) == (255, 0, 0)


def test_output_size_matches_real_result() -> None:
    image = Image.new("RGB", (400, 300), "white")
    ops: list[Operation] = [Crop(Rect(10, 10, 200, 100)), Rotate(90), Resize(30, 60), Flip(True)]
    assert apply_operations(image, ops).size == output_size(ops, image.size)


def test_proxy_scaling_matches_full_size() -> None:
    """Операции в координатах оригинала, применённые к прокси с масштабом, дают тот же кадр."""
    full = Image.new("RGB", (4000, 2000), (255, 0, 0))
    full.paste((0, 0, 255), (2000, 0, 4000, 2000))
    proxy, scale = make_proxy(full)
    assert proxy.width == 2048
    assert scale == pytest.approx(0.512)
    ops: list[Operation] = [Crop(Rect(1000, 500, 2000, 1000)), Redact(Rect(0, 0, 500, 500), "fill")]
    full_result = apply_operations(full, ops)
    proxy_result = apply_operations(proxy, ops, scale)
    assert abs(proxy_result.width / full_result.width - scale) < 0.01
    assert proxy_result.getpixel((proxy_result.width - 5, 5)) == (0, 0, 255)


def test_small_images_are_not_upscaled_by_proxy() -> None:
    proxy, scale = make_proxy(Image.new("RGB", (100, 50)))
    assert proxy.size == (100, 50)
    assert scale == 1.0


def test_open_image_applies_exif_orientation(tmp_path: Path) -> None:
    path = tmp_path / "rot.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6
    Image.new("RGB", (40, 20), "blue").save(path, exif=exif)
    image, original_exif = open_image(path)
    assert image.size == (20, 40)
    assert original_exif[0x0112] == 6


def test_open_image_keeps_alpha(tmp_path: Path) -> None:
    path = tmp_path / "a.png"
    Image.new("RGBA", (10, 10), (1, 2, 3, 100)).save(path)
    image, _ = open_image(path)
    assert image.mode == "RGBA"


def test_default_output_path_never_overwrites(tmp_path: Path) -> None:
    source = tmp_path / "photo.jpg"
    first = default_output_path(source, "jpeg")
    assert first == tmp_path / "photo_edited.jpg"
    first.write_bytes(b"x")
    assert default_output_path(source, "jpeg") == tmp_path / "photo_edited (2).jpg"
    assert default_output_path(source, "png") == tmp_path / "photo_edited.png"


def test_default_output_path_without_source(tmp_path: Path) -> None:
    assert default_output_path(None, "png", tmp_path) == tmp_path / "image_edited.png"


def test_format_for_source() -> None:
    assert format_for_source(Path("a.JPG")) == "jpeg"
    assert format_for_source(Path("a.heic")) == "jpeg"
    assert format_for_source(Path("a.webp")) == "webp"
    assert format_for_source(Path("a.bmp")) == "png"
    assert format_for_source(None) == "png"


def _exif_with_gps() -> Image.Exif:
    exif = Image.Exif()
    exif[0x010F] = "TestCam"  # Make
    exif[0x0112] = 6
    exif.get_ifd(0x8825)[1] = "N"  # GPS
    return exif


def test_save_strips_metadata_by_default(tmp_path: Path) -> None:
    image = Image.new("RGB", (16, 16), "red")
    dest = save_image(image, tmp_path / "out.jpg", "jpeg", exif=_exif_with_gps())
    with Image.open(dest) as saved:
        assert len(saved.getexif()) == 0
        assert saved.format == "JPEG"


def test_save_can_keep_metadata_with_reset_orientation(tmp_path: Path) -> None:
    image = Image.new("RGB", (16, 16), "red")
    dest = save_image(
        image, tmp_path / "out.jpg", "jpeg", exif=_exif_with_gps(), keep_metadata=True
    )
    with Image.open(dest) as saved:
        exif = saved.getexif()
        assert exif[0x010F] == "TestCam"
        assert exif[0x0112] == 1


@pytest.mark.parametrize("fmt", ["png", "jpeg", "webp"])
def test_save_formats_roundtrip(tmp_path: Path, fmt: str) -> None:
    image = Image.new("RGBA", (16, 16), (10, 200, 30, 255))
    dest = save_image(image, tmp_path / f"out.{fmt}", fmt, quality=80)
    with Image.open(dest) as saved:
        assert saved.size == (16, 16)


def test_stroke_draws_along_the_path_with_round_ends() -> None:
    base = Image.new("RGB", (100, 100), "black")
    stroke = Stroke(((10, 50), (50, 50), (90, 20)), (255, 255, 0), 8.0)
    result = apply_operation(base, stroke)
    assert result.getpixel((30, 50)) == (255, 255, 0)  # на линии
    assert result.getpixel((70, 35))[0] > 200  # на втором отрезке
    assert result.getpixel((30, 90)) == (0, 0, 0)  # вдали от линии
    assert result.getpixel((8, 50)) == (255, 255, 0)  # скруглённый конец выступает за точку
    assert base.getpixel((30, 50)) == (0, 0, 0)  # исходная картинка не изменилась


def test_translucent_stroke_does_not_darken_where_it_overlaps_itself() -> None:
    base = Image.new("RGB", (100, 100), "white")
    crossing = Stroke(((10, 10), (90, 90), (90, 10), (10, 90)), (255, 0, 0), 10.0, 0.4)
    result = apply_operation(base, crossing)
    on_line = result.getpixel((20, 20))
    at_crossing = result.getpixel((50, 50))
    assert 0 < on_line[1] < 255  # просвечивает фон
    assert at_crossing == on_line  # линия пересекла сама себя, но цвет тот же


def test_single_point_stroke_is_a_dot() -> None:
    base = Image.new("RGB", (50, 50), "black")
    result = apply_operation(base, Stroke(((25, 25),), (0, 255, 0), 10.0))
    assert result.getpixel((25, 25)) == (0, 255, 0)
    assert result.getpixel((25, 40)) == (0, 0, 0)
    assert apply_operation(base, Stroke(())) is base


def test_stroke_keeps_alpha_images_rgba() -> None:
    base = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    result = apply_operation(base, Stroke(((5, 20), (35, 20)), (255, 0, 0), 6.0))
    assert result.mode == "RGBA"
    assert result.getpixel((20, 20))[3] == 255


def test_stroke_is_scaled_with_the_preview() -> None:
    from quickedit.core.operations import scale_operation

    scaled = scale_operation(Stroke(((10, 20), (30, 40)), (1, 2, 3), 4.0, 0.5), 2.0)
    assert scaled == Stroke(((20, 40), (60, 80)), (1, 2, 3), 8.0, 0.5)
