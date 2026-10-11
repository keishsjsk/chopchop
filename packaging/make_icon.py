"""Значок приложения из SVG варианта «a»: python packaging/make_icon.py → resources/icons/.

Исходник `docs/design/icons/app-a.svg` собран из квадратов на сетке 32×32 (кадр плёнки с
«плеем», палитра Ember). Скрипт читает прямоугольники и рисует их в Pillow:
  - размеры, кратные 32 (64, 128, 256, 512), увеличиваются «по ближайшему», клетки остаются резкими;
  - 16, 24 и 48 px собираются усреднением из увеличенной копии, поэтому нет рваных клеток.
Результат: `chopchop.svg`, `chopchop.ico` (16, 24, 32, 48, 64, 128, 256), `chopchop-<размер>.png`
(16–512) и `chopchop.png` (256, как раньше).
"""

import re
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "design" / "icons" / "app-a.svg"
OUT = ROOT / "resources" / "icons"
GRID = 32
PNG_SIZES = (16, 24, 32, 48, 64, 128, 256, 512)
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
RECT = re.compile(
    r'<rect x="(\d+)" y="(\d+)" width="(\d+)" height="(\d+)" fill="(#[0-9A-Fa-f]{6})"/>'
)


def read_rects(svg: str) -> list[tuple[int, int, int, int, str]]:
    return [(int(x), int(y), int(w), int(h), colour) for x, y, w, h, colour in RECT.findall(svg)]


def base_image(svg: str) -> Image.Image:
    """Значок 32×32: клетки как в SVG, углы плитки прозрачные."""
    image = Image.new("RGBA", (GRID, GRID), (0, 0, 0, 0))
    for x, y, w, h, colour in read_rects(svg):
        image.paste(Image.new("RGBA", (w, h), colour), (x, y))
    return image


def render(base: Image.Image, size: int) -> Image.Image:
    """Значок нужного размера: целые кратные «по ближайшему», остальные усреднением."""
    if size % GRID == 0:
        return base.resize((size, size), Image.Resampling.NEAREST)
    big = base.resize((GRID * 8, GRID * 8), Image.Resampling.NEAREST)
    return big.resize((size, size), Image.Resampling.BOX)


def main() -> None:
    svg = SOURCE.read_text(encoding="utf-8")
    base = base_image(svg)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "chopchop.svg").write_text(svg, encoding="utf-8")
    images = {size: render(base, size) for size in PNG_SIZES}
    for size, image in images.items():
        image.save(OUT / f"chopchop-{size}.png", optimize=True)
    images[256].save(OUT / "chopchop.png", optimize=True)
    largest = images[256]
    largest.save(
        OUT / "chopchop.ico",
        format="ICO",
        sizes=[(s, s) for s in ICO_SIZES],
        append_images=[images[s] for s in ICO_SIZES if s != 256],
        bitmap_format="png",
    )
    print("saved", OUT)


if __name__ == "__main__":
    main()
