"""Лист палитр и окна настроек: docs/design/preview.png и palettes.png.

Запуск (нужен настоящий экран и шрифты ОС):
    python docs/design/make_settings_screens.py     # снимки окна настроек
    python docs/design/make_preview_sheet.py        # лист из них и палитр

На листе обе темы и четыре палитры акцента: образцы цветов с контрастом и настоящие виджеты темы
(кнопки, сегменты, тумблер, ползунок, выбранный инструмент), затем окно настроек в трёх размерах.
`palettes.png` — только часть с палитрами.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
if sys.platform == "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "windows")

from PySide6.QtCore import QRect, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from chopchop.ui.click_slider import ClickSlider  # noqa: E402
from chopchop.ui.theme import fonts, icons  # noqa: E402
from chopchop.ui.theme.manager import ThemeManager  # noqa: E402
from chopchop.ui.theme.tokens import ACCENTS, Palette, contrast  # noqa: E402
from chopchop.ui.widgets import PixelToggle, Segmented, set_icon  # noqa: E402

COLUMN = 880
MARGIN = 24
GAP = 20
FAMILY_H = 290
TITLES = {
    "ember": "Ember · терракота и шалфей",
    "meadow": "Meadow · шалфей и глина",
    "sunset": "Sunset · закат и золото",
    "rose": "Rose · коралл и мята",
}
THEME_NAMES = {"light": "Ember Cream (светлая)", "dark": "Ember Night (тёмная)"}
SWATCHES = (
    "bg",
    "surface",
    "surface_raised",
    "border",
    "border_strong",
    "text",
    "text_muted",
    "accent",
    "accent_hover",
    "accent_pressed",
    "on_accent",
    "secondary",
    "danger",
    "success",
    "focus_ring",
    "accent_tint",
)
CHECKS = (
    ("text", "bg", 4.5),
    ("text_muted", "surface", 4.5),
    ("on_accent", "accent", 4.5),
    ("secondary", "bg", 4.5),
    ("accent", "surface", 3.0),
    ("border_strong", "bg", 3.0),
    ("focus_ring", "surface", 3.0),
)


def text_font(px: int, bold: bool = False) -> QFont:
    font = QApplication.font()
    font.setPixelSize(px)
    font.setBold(bold)
    return font


def sample_widget() -> QWidget:
    """Живые виджеты темы: кнопки, сегменты, тумблер, ползунок и выбранный инструмент."""
    root = QDialog()  # фон окна берётся из таблицы стилей темы
    row = QHBoxLayout()
    row.setSpacing(8)
    primary = QPushButton("Сохранить")
    primary.setProperty("variant", "primary")
    plain = QPushButton("Отмена")
    danger = QPushButton("Сбросить")
    danger.setProperty("variant", "danger-soft")
    for button in (primary, plain, danger):
        row.addWidget(button)
    segments = Segmented()
    segments.add("Светлая", "light")
    segments.add("Тёмная", "dark")
    segments.set_value("light")
    row.addWidget(segments)
    toggles = QHBoxLayout()
    on, off = PixelToggle(), PixelToggle()
    on.setChecked(True)
    toggles.addWidget(on)
    toggles.addWidget(off)
    slider = ClickSlider(Qt.Orientation.Horizontal)
    slider.setRange(0, 100)
    slider.setValue(60)
    slider.setFixedWidth(160)
    tool_row = QHBoxLayout()
    for name, checked in (("crop", True), ("rotate", False), ("text", False)):
        tool = QToolButton()
        tool.setProperty("rail", True)
        tool.setCheckable(True)
        tool.setChecked(checked)
        tool.setFixedSize(40, 40)
        set_icon(tool, name, 32)
        tool_row.addWidget(tool)
    label = QLabel("Описание настройки приглушённым цветом")
    label.setProperty("muted", True)
    column = QVBoxLayout(root)
    column.setContentsMargins(12, 12, 12, 12)
    column.setSpacing(8)
    column.addLayout(row)
    lower = QHBoxLayout()
    lower.addLayout(toggles)
    lower.addWidget(slider)
    lower.addLayout(tool_row)
    lower.addStretch(1)
    column.addLayout(lower)
    column.addWidget(label)
    root.resize(COLUMN, root.sizeHint().height())
    return root


def draw_family(painter: QPainter, x: int, y: int, theme: str, accent: str, p: Palette) -> int:
    painter.fillRect(QRect(x, y, COLUMN, FAMILY_H), QColor(p.bg))
    painter.setPen(QColor(p.text))
    painter.setFont(text_font(15, True))
    painter.drawText(x + 12, y + 24, TITLES[accent])
    cell = (COLUMN - 24) // 16
    top = y + 36
    sample = ACCENTS[accent][theme].sample()
    for index, name in enumerate(SWATCHES):
        painter.fillRect(QRect(x + 12 + index * cell, top, cell - 4, 44), QColor(getattr(p, name)))
        painter.setPen(QColor(p.border_strong))
        painter.drawRect(QRect(x + 12 + index * cell, top, cell - 4, 44))
        painter.setPen(QColor(p.text_muted))
        painter.setFont(text_font(9))
        painter.drawText(x + 12 + index * cell, top + 58, getattr(p, name).upper())
    painter.fillRect(QRect(x + COLUMN - 56, y + 8, 40, 20), QColor(sample))
    painter.setPen(QColor(p.border_strong))
    painter.drawRect(QRect(x + COLUMN - 56, y + 8, 40, 20))
    parts = []
    for a, b, need in CHECKS:
        ratio = contrast(getattr(p, a), getattr(p, b))
        parts.append(f"{a}/{b} {ratio:.1f}{'✓' if ratio >= need else '✗'}")
    line = "   ".join(parts)
    painter.setPen(QColor(p.text))
    painter.setFont(text_font(10))
    painter.drawText(x + 12, top + 82, line)
    return top + 94


def main() -> int:
    app = QApplication([])
    fonts.load_fonts()
    fonts.apply(app, "monocraft")
    manager = ThemeManager(app)
    out = ROOT / "docs" / "design"
    cells: list[tuple[str, str, Palette, QPixmap]] = []
    for theme in ("light", "dark"):
        for accent in ACCENTS:
            manager.set_theme(theme, accent)
            icons.clear_cache()
            widget = sample_widget()
            widget.show()
            app.processEvents()
            from chopchop.ui.theme import current

            cells.append((theme, accent, current.palette(), widget.grab()))
            widget.close()
    family_h = FAMILY_H
    height = MARGIN + 36 + 4 * (family_h + GAP) + MARGIN
    palettes = QImage(2 * COLUMN + 3 * MARGIN, height, QImage.Format.Format_RGB32)
    palettes.fill(QColor("#7A7A7A"))
    painter = QPainter(palettes)
    for theme, accent, p, grab in cells:
        column = 0 if theme == "light" else 1
        row = list(ACCENTS).index(accent)
        x = MARGIN + column * (COLUMN + MARGIN)
        y = MARGIN + 36 + row * (family_h + GAP)
        if row == 0:
            painter.setPen(QColor("#FFFFFF"))
            painter.setFont(text_font(16, True))
            painter.drawText(x, y - 12, THEME_NAMES[theme])
        below = draw_family(painter, x, y, theme, accent, p)
        painter.drawPixmap(x, below, grab)
    painter.end()
    palettes.save(str(out / "palettes.png"))

    # лист целиком: палитры и окно настроек в трёх размерах для обеих тем
    shots: list[QImage] = []
    for theme in ("light", "dark"):
        for size in ("720x480", "860x600", "1200x800"):
            path = out / f"settings-{theme}-{size}.png"
            if path.is_file():
                shots.append(QImage(str(path)))
    width = palettes.width()
    scaled = [
        s.scaledToWidth((width - 4 * MARGIN) // 3, Qt.TransformationMode.FastTransformation)
        for s in shots
    ]
    rows = [scaled[:3], scaled[3:6]]
    extra = sum((max(i.height() for i in r) + MARGIN) if r else 0 for r in rows) + 2 * MARGIN
    sheet = QImage(width, palettes.height() + extra, QImage.Format.Format_RGB32)
    sheet.fill(QColor("#7A7A7A"))
    painter = QPainter(sheet)
    painter.drawImage(0, 0, palettes)
    y = palettes.height() + MARGIN
    painter.setPen(QColor("#FFFFFF"))
    painter.setFont(text_font(16, True))
    painter.drawText(MARGIN, y, "Окно настроек: 720×480, 860×600, 1200×800")
    y += 12
    for r in rows:
        x = MARGIN
        for image in r:
            painter.drawImage(x, y, image)
            x += image.width() + MARGIN
        y += (max(i.height() for i in r) if r else 0) + MARGIN
    painter.end()
    sheet.save(str(out / "preview.png"))
    print("saved", out / "preview.png", sheet.width(), "x", sheet.height())
    return 0


if __name__ == "__main__":
    sys.exit(main())
