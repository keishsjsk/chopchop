"""Рисует значок приложения: python packaging/make_icon.py → resources/icons/."""

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

SIZE = 1024
TOP = (30, 58, 138)
BOTTOM = (14, 165, 233)
WHITE = (255, 255, 255, 255)
OUT = Path(__file__).resolve().parents[1] / "resources" / "icons"
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def _gradient() -> Image.Image:
    """Диагональный градиент от тёмно-синего (слева сверху) к голубому (справа снизу)."""
    vertical = Image.linear_gradient("L").resize((SIZE, SIZE))
    horizontal = vertical.transpose(Image.Transpose.ROTATE_90).transpose(
        Image.Transpose.FLIP_LEFT_RIGHT
    )
    mask = ImageChops.add(vertical, horizontal, scale=2)
    return Image.composite(
        Image.new("RGB", (SIZE, SIZE), BOTTOM), Image.new("RGB", (SIZE, SIZE), TOP), mask
    )


def draw_icon() -> Image.Image:
    canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    radius = SIZE // 5
    shape = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(shape).rounded_rectangle((0, 0, SIZE - 1, SIZE - 1), radius, fill=255)
    canvas.paste(_gradient(), mask=shape)

    draw = ImageDraw.Draw(canvas)
    # треугольник «плей» чуть левее центра: плеер
    cx, cy, half = SIZE * 0.47, SIZE * 0.5, SIZE * 0.2
    draw.polygon(
        [(cx - half * 0.8, cy - half), (cx - half * 0.8, cy + half), (cx + half * 1.2, cy)],
        fill=WHITE,
    )
    # уголки рамки кадрирования: редактор
    margin, arm, width = SIZE * 0.16, SIZE * 0.17, SIZE * 0.045
    far = SIZE - margin
    for (x, y), (dx, dy) in (((margin, margin), (1, 1)), ((far, far), (-1, -1))):
        draw.line([(x, y), (x + dx * arm, y)], fill=WHITE, width=int(width))
        draw.line([(x, y), (x, y + dy * arm)], fill=WHITE, width=int(width))
        draw.ellipse((x - width / 2, y - width / 2, x + width / 2, y + width / 2), fill=WHITE)
    return canvas


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    icon = draw_icon()
    icon.resize((256, 256), Image.Resampling.LANCZOS).save(OUT / "chopchop.png", optimize=True)
    icon.resize((256, 256), Image.Resampling.LANCZOS).save(OUT / "chopchop.ico", sizes=ICO_SIZES)
    print("saved", OUT)


if __name__ == "__main__":
    main()
