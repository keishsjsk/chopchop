"""Значок приложения (вариант «a»): файлы, размеры, палитра и подключение к окну."""

import colorsys
from pathlib import Path

import pytest
from PIL import Image

from chopchop.app import app_icon
from chopchop.services.paths import resource_dir

ICONS = resource_dir() / "icons"
SIZES = (16, 24, 32, 48, 64, 128, 256, 512)
ICO_SIZES = {(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)}


def test_ico_has_every_windows_size() -> None:
    with Image.open(ICONS / "chopchop.ico") as ico:
        assert set(ico.info["sizes"]) == ICO_SIZES


def test_png_files_exist_with_the_right_sizes() -> None:
    for size in SIZES:
        with Image.open(ICONS / f"chopchop-{size}.png") as image:
            assert image.size == (size, size)
    with Image.open(ICONS / "chopchop.png") as image:
        assert image.size == (256, 256)


def test_svg_is_variant_a_from_the_design_folder() -> None:
    root = Path(__file__).resolve().parents[2]
    assert (ICONS / "chopchop.svg").read_text(encoding="utf-8") == (
        root / "docs" / "design" / "icons" / "app-a.svg"
    ).read_text(encoding="utf-8")


def test_big_sizes_are_crisp_multiples_of_the_32_grid() -> None:
    with Image.open(ICONS / "chopchop-256.png") as image:
        colours = {image.getpixel((x, y)) for x in range(256) for y in range(256)}
    # только цвета SVG и прозрачность углов: без сглаживания нет промежуточных оттенков
    assert len(colours) <= 6


def test_no_purple_in_the_icon() -> None:
    with Image.open(ICONS / "chopchop-256.png") as image:
        pixels = {image.getpixel((x, y)) for x in range(256) for y in range(256)}
    for pixel in pixels:
        assert isinstance(pixel, tuple)
        red, green, blue, alpha = pixel
        if alpha == 0:
            continue
        hue, _lightness, saturation = colorsys.rgb_to_hls(red / 255, green / 255, blue / 255)
        assert not (0.70 < hue < 0.88 and saturation > 0.15), (red, green, blue)


def test_window_icon_has_all_sizes(qapp: object) -> None:
    icon = app_icon()
    assert not icon.isNull()
    available = {(s.width(), s.height()) for s in icon.availableSizes()}
    assert {(16, 16), (32, 32), (256, 256), (512, 512)} <= available


@pytest.mark.skipif(not (ICONS / "chopchop.ico").exists(), reason="нет значка")
def test_pyinstaller_spec_and_installer_use_the_ico() -> None:
    root = Path(__file__).resolve().parents[2]
    assert "chopchop.ico" in (root / "packaging" / "chopchop.spec").read_text(encoding="utf-8")
    assert "chopchop.ico" in (root / "packaging" / "chopchop.iss").read_text(encoding="utf-8")
