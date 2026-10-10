"""Четыре варианта значка приложения на сетке 32x32 и лист сравнения.

Значки собраны только из квадратов (SVG с `crispEdges`), палитра Ember без фиолетового.
Лист сравнения: каждый вариант на светлом и тёмном фоне в размерах 256, 64, 32 и 16 px,
масштабирование без сглаживания. В приложение значки пока не подключены.

Запуск: `QT_QPA_PLATFORM=offscreen python docs/design/make_app_icons.py`
"""

import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, QRect, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

OUT = Path(__file__).resolve().parent / "icons"
BG, INK, ACCENT, ON_ACCENT = "#F8EDE3", "#4B2A21", "#B04F33", "#FFF8F0"
ACCENT_DARK = "#E8804A"
PAGE_LIGHT, PAGE_DARK = "#EFE2D2", "#241713"
TEXT_LIGHT, TEXT_DARK = "#4B2A21", "#F6E6CB"

Rect = tuple[int, int, int, int, str]


def tile() -> list[Rect]:
    """Плитка 32x32 со ступенчатыми углами."""
    return [(2, 0, 28, 32, BG), (0, 2, 32, 28, BG), (1, 1, 30, 30, BG)]


def frame(x: int, y: int, w: int, h: int) -> list[Rect]:
    """Кадр: контур 2 px и заливка акцентом."""
    return [(x, y, w, h, INK), (x + 2, y + 2, w - 4, h - 4, ACCENT)]


def play(cx: int, cy: int, height: int) -> list[Rect]:
    """Ступенчатый треугольник «играть» из столбиков по 2 px."""
    out: list[Rect] = []
    for i in range(height // 2):
        h = height - 2 * i
        out.append((cx - height // 2 + 2 * i, cy - h // 2, 2, h, ON_ACCENT))
    return out


def variant_a() -> list[Rect]:
    rects = tile() + frame(3, 7, 26, 18) + play(16, 16, 10)
    for x in range(5, 27, 4):  # перфорация плёнки
        rects += [(x, 9, 2, 2, ON_ACCENT), (x, 21, 2, 2, ON_ACCENT)]
    return rects


def variant_b() -> list[Rect]:
    rects = tile() + frame(3, 17, 26, 12)
    for i in range(6):  # лезвия ножниц, пересекаются в центре
        rects += [(10 + 2 * i, 3 + 2 * i, 2, 2, INK), (22 - 2 * i, 3 + 2 * i, 2, 2, INK)]
    for x in (5, 23):  # кольца-ручки
        rects += [(x, 2, 6, 6, INK), (x + 2, 4, 2, 2, BG)]
    rects += play(16, 23, 6)
    return rects


def variant_c() -> list[Rect]:
    rects = tile() + frame(3, 16, 26, 13)
    for k in range(6):  # пиксельный клин «chop»
        width = 24 - 4 * k
        rects.append((16 - width // 2, 2 + 2 * k, width, 2, INK))
        if width > 8:
            rects.append((16 - width // 2 + 2, 2 + 2 * k, width - 4, 2, ACCENT))
    rects += [(14, 14, 4, 2, BG)]  # зарубка в рамке под клином
    rects += play(16, 23, 6)
    return rects


def variant_d() -> list[Rect]:
    rects = tile() + frame(3, 6, 26, 20)
    rects += [(8, 10, 6, 2, ON_ACCENT), (8, 15, 16, 2, ON_ACCENT), (12, 20, 8, 2, ON_ACCENT)]
    return rects


VARIANTS = {"a": variant_a, "b": variant_b, "c": variant_c, "d": variant_d}


def svg_text(rects: list[Rect], dark: bool = False) -> str:
    swap = {BG: "#2E1F19", INK: "#F6E6CB", ACCENT: ACCENT_DARK, ON_ACCENT: "#2B0F1A"}
    body = "\n".join(
        f'  <rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{swap.get(c, c) if dark else c}"/>'
        for x, y, w, h, c in rects
    )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="32" height="32"'
        ' shape-rendering="crispEdges">\n' + body + "\n</svg>\n"
    )


def render(svg: str, size: int) -> QImage:
    """Рисует значок в 32x32 и увеличивает/уменьшает ближайшим соседом."""
    base = QImage(32, 32, QImage.Format.Format_ARGB32)
    base.fill(Qt.GlobalColor.transparent)
    painter = QPainter(base)
    QSvgRenderer(QByteArray(svg.encode())).render(painter)
    painter.end()
    return base.scaled(
        size,
        size,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.FastTransformation,
    )


def main() -> None:
    QGuiApplication.instance() or QGuiApplication(sys.argv)
    OUT.mkdir(exist_ok=True)
    for name, make in VARIANTS.items():
        (OUT / f"app-{name}.svg").write_text(svg_text(make()), encoding="utf-8")

    sizes = (256, 64, 32, 16)
    pad, label_h = 24, 36
    cell_w = sum(sizes) + pad * (len(sizes) + 1)
    cell_h = 256 + pad * 2
    width, height = cell_w * 2, label_h + (cell_h + label_h) * len(VARIANTS)
    sheet = QImage(width, height, QImage.Format.Format_ARGB32)
    painter = QPainter(sheet)
    ttf = Path(__file__).resolve().parents[2] / "resources" / "fonts" / "Monocraft.ttf"
    family = QFontDatabase.applicationFontFamilies(QFontDatabase.addApplicationFont(str(ttf)))[0]
    font = QFont(family)
    font.setPixelSize(18)
    font.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
    painter.setFont(font)
    for col, (page, ink, dark) in enumerate(
        ((PAGE_LIGHT, TEXT_LIGHT, False), (PAGE_DARK, TEXT_DARK, True))
    ):
        painter.fillRect(col * cell_w, 0, cell_w, height, QColor(page))
        painter.setPen(QColor(ink))
        title = "светлый фон" if not dark else "тёмный фон"
        painter.drawText(
            QRect(col * cell_w + pad, 0, cell_w, label_h), Qt.AlignmentFlag.AlignVCenter, title
        )
        for row, (name, make) in enumerate(VARIANTS.items()):
            y0 = label_h + row * (cell_h + label_h)
            painter.drawText(
                QRect(col * cell_w + pad, y0, cell_w, label_h),
                Qt.AlignmentFlag.AlignVCenter,
                f"вариант {name}",
            )
            x = col * cell_w + pad
            svg = svg_text(make(), dark)
            for size in sizes:
                painter.drawImage(x, y0 + label_h + pad + (256 - size), render(svg, size))
                x += size + pad
    painter.end()
    sheet.save(str(OUT / "app-compare.png"))
    print("готово:", OUT)


if __name__ == "__main__":
    main()
