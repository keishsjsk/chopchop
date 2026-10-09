"""Лист превью дизайн-системы: docs/design/preview.png.

Запуск (нужны шрифты ОС, поэтому не offscreen):
    python docs/design/make_preview.py [путь/к/preview.png]

Лист показывает палитры обеих тем с контрастом, типографику с кириллицей, все иконки в масштабе
×4, кнопки в состояниях, ступенчатую рамку с жёсткой тенью и макет панели инструментов
редактора. Всё нарисовано настоящими виджетами и модулями `chopchop.ui.theme`.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
if sys.platform == "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "windows")

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QColor,
    QFont,
    QImage,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QButtonGroup,
    QHBoxLayout,
    QPushButton,
    QStyle,
    QStyleOptionButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from chopchop.ui.theme import fonts, icons, tokens  # noqa: E402
from chopchop.ui.theme.manager import ThemeManager  # noqa: E402
from chopchop.ui.theme.pixel import paint_frame  # noqa: E402
from chopchop.ui.theme.tokens import Palette, contrast  # noqa: E402

WIDTH = 1800
MARGIN = 32
COLUMN = (WIDTH - 3 * MARGIN) // 2
THEMES = ("light", "dark")
SAMPLE = "Настройки · Воспроизведение · Сохранить как… 0123456789"
SAMPLE_BY_SCALE = {
    4: "Настройки · Фото",
    3: "Настройки · Воспроизведение",
    2: SAMPLE,
}
SAMPLE_LONG = "Привет, мир! Ёё Йй Ъъ Ыы Ээ Юю Яя — съешь ещё этих мягких французских булок"

TOKEN_ROWS = (
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
    "shadow",
)
CONTRAST_ROWS = (
    ("text", "bg", 4.5),
    ("text", "surface", 4.5),
    ("text_muted", "surface", 4.5),
    ("on_accent", "accent", 4.5),
    ("accent", "surface", 3.0),
    ("border_strong", "surface", 3.0),
    ("secondary", "surface", 4.5),
    ("danger", "surface", 4.5),
    ("focus_ring", "surface", 3.0),
)
TOOLS = (
    ("crop", "Кадрировать  C"),
    ("rotate", "Повернуть  R"),
    ("redact", "Скрыть  B"),
    ("brush", "Кисть  D"),
    ("text", "Текст  T"),
    ("adjust", "Цвет и фильтры"),
    ("fit", "Размер"),
)


def text_font(px: int, bold: bool = False) -> QFont:
    font = QApplication.font()
    font.setPixelSize(px)
    font.setBold(bold)
    return font


class Canvas:
    """Лист, на который по очереди рисуются блоки."""

    def __init__(self, height: int) -> None:
        self.image = QImage(WIDTH, height, QImage.Format.Format_RGB32)
        self.image.fill(QColor("#7A7A7A"))
        self.painter = QPainter(self.image)

    def panel(self, rect: QRect, palette: Palette) -> None:
        self.painter.fillRect(rect, QColor(palette.bg))

    def text(self, x: int, y: int, text: str, color: str, font: QFont, pixel: bool = False) -> None:
        self.painter.setPen(QColor(color))
        self.painter.setFont(font)
        metrics = self.painter.fontMetrics()
        self.painter.drawText(x, y + metrics.ascent(), text)


def theme_columns(palette_light: Palette, palette_dark: Palette) -> list[tuple[int, Palette]]:
    return [(MARGIN, palette_light), (2 * MARGIN + COLUMN, palette_dark)]


def draw_palette_block(c: Canvas, x: int, y: int, p: Palette) -> int:
    title = fonts.pixel_font(3, 1.0)
    c.text(x, y, f"{'Cozy Cream' if p.name == 'light' else 'Cozy Night'}", p.text, title)
    y += 40
    cell_w, cell_h = 98, 70
    per_row = COLUMN // cell_w
    for index, name in enumerate(TOKEN_ROWS):
        cx = x + (index % per_row) * cell_w
        cy = y + (index // per_row) * (cell_h + 34)
        color = getattr(p, name)
        c.painter.fillRect(QRect(cx, cy, cell_w - 8, cell_h), QColor(color))
        c.painter.setPen(QColor(p.border_strong))
        c.painter.drawRect(QRect(cx, cy, cell_w - 8, cell_h))
        c.text(cx, cy + cell_h + 2, name.replace("_", "-"), p.text, text_font(11))
        c.text(cx, cy + cell_h + 16, color.upper(), p.text_muted, text_font(10))
    y += ((len(TOKEN_ROWS) + per_row - 1) // per_row) * (cell_h + 34) + 8
    c.text(x, y, "Контраст (WCAG)", p.text, text_font(13, True))
    y += 22
    for foreground, background, need in CONTRAST_ROWS:
        ratio = contrast(getattr(p, foreground), getattr(p, background))
        mark = "✓" if ratio >= need else "✗"
        line = f"{foreground} на {background}: {ratio:.1f} : 1  (нужно ≥ {need:g})  {mark}"
        c.text(x, y, line, p.text, text_font(12))
        y += 18
    return y


def draw_typography(c: Canvas, x: int, y: int, p: Palette) -> int:
    c.text(x, y, "Типографика", p.text_muted, text_font(12, True))
    y += 22
    for scale in (4, 3, 2):
        font = fonts.pixel_font(scale, 1.0)
        c.text(x, y, SAMPLE_BY_SCALE[scale], p.text, font, pixel=True)
        y += 8 * scale + 14
    c.text(x, y, "Заголовки — пиксельный Tiny5, размеры кратны 8 px", p.text_muted, text_font(12))
    y += 28
    c.text(x, y, SAMPLE_LONG, p.text, text_font(15))
    y += 24
    c.text(
        x, y, "Основной текст — системный шрифт, читаемый на любом размере", p.text, text_font(13)
    )
    y += 20
    c.text(
        x, y, "Приглушённый текст для подсказок и вторичных подписей", p.text_muted, text_font(12)
    )
    y += 20
    c.text(x, y, "Ошибка: файл не удалось открыть", p.danger, text_font(13))
    c.text(x + 290, y, "Сохранено", p.success, text_font(13))
    c.text(x + 380, y, "Ссылка", p.secondary, text_font(13))
    return y + 28


def draw_icons(c: Canvas, x: int, y: int, p: Palette) -> int:
    c.text(x, y, "Иконки ×4 (16×16 → 64×64, ближайший сосед)", p.text_muted, text_font(12, True))
    y += 24
    names = list(icons.REQUIRED)
    cell_w, cell_h = 76, 96
    per_row = COLUMN // cell_w
    for index, name in enumerate(names):
        cx = x + (index % per_row) * cell_w
        cy = y + (index // per_row) * cell_h
        image = icons.render(name, scale=4, color=p.text, accent=p.accent, shadow=p.border)
        c.painter.drawImage(cx, cy, image)
        c.text(cx, cy + 68, name, p.text_muted, text_font(9))
    rows = (len(names) + per_row - 1) // per_row
    y += rows * cell_h
    c.text(x, y, "Крупные 24×24 ×2 и акцентные цвета", p.text_muted, text_font(12, True))
    y += 22
    cx = x
    for name in ("play", "pause", "folder", "edit"):
        c.painter.drawImage(
            cx, y, icons.render(name, scale=2, size=24, color=p.text, shadow=p.border)
        )
        cx += 70
    for role, name in (
        ("accent", "check"),
        ("danger", "warning"),
        ("success", "check"),
        ("secondary", "info"),
    ):
        c.painter.drawImage(
            cx,
            y,
            icons.render(name, scale=3, color=getattr(p, role), shadow=p.border),
        )
        cx += 66
    return y + 70


BUTTON_STATES = ("Обычная", "Наведение", "Нажатие", "Выключена", "Фокус")


def button_state_image(button: QPushButton, state: str) -> QPixmap:
    """Рисует кнопку в нужном состоянии средствами стиля (стили Qt учитывают флаги состояния)."""
    size = button.sizeHint()
    pixmap = QPixmap(size)
    pixmap.fill(Qt.GlobalColor.transparent)
    option = QStyleOptionButton()
    option.initFrom(button)
    option.rect = QRect(QPoint(0, 0), size)
    option.text = button.text()
    flags = QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_Active
    if state == "Наведение":
        flags |= QStyle.StateFlag.State_MouseOver
    elif state == "Нажатие":
        flags |= QStyle.StateFlag.State_Sunken | QStyle.StateFlag.State_MouseOver
    elif state == "Выключена":
        flags = QStyle.StateFlag.State_Active
    elif state == "Фокус":
        flags |= QStyle.StateFlag.State_HasFocus
    option.state = flags
    painter = QPainter(pixmap)
    button.style().drawControl(QStyle.ControlElement.CE_PushButton, option, painter, button)
    painter.end()
    return pixmap


def draw_buttons(c: Canvas, x: int, y: int, p: Palette) -> int:
    c.text(
        x,
        y,
        "Кнопки: обычная, наведение, нажатие, выключена, фокус",
        p.text_muted,
        text_font(12, True),
    )
    y += 44
    variants = (("Сохранить", "primary"), ("Отмена", ""), ("Удалить", "danger"), ("Назад", "flat"))
    for label, variant in variants:
        button = QPushButton(label)
        if variant:
            button.setProperty("variant", variant)
        button.ensurePolished()
        cx = x
        for state in BUTTON_STATES:
            if label == "Сохранить":
                c.text(cx, y - 16, state, p.text_muted, text_font(10))
            image = button_state_image(button, state)
            c.painter.drawPixmap(cx, y, image)
            cx += image.width() + 12
        y += button.sizeHint().height() + 12
    return y + 8


def draw_accents(c: Canvas, x: int, y: int, p: Palette) -> int:
    c.text(
        x,
        y,
        "Акценты на выбор (в каждой теме свой вариант с проверенным контрастом)",
        p.text_muted,
        text_font(12, True),
    )
    y += 26
    cx = x
    for family in tokens.ACCENTS:
        q = tokens.make_palette(p.name, family)
        rect = QRectF(cx, y, 190, 44)
        paint_frame(c.painter, rect, fill=q.accent, border=q.accent_pressed, shadow=p.shadow)
        c.text(cx + 14, y + 6, family, q.on_accent, fonts.pixel_font(2, 1.0))
        c.text(
            cx + 14,
            y + 26,
            f"{contrast(q.on_accent, q.accent):.1f} : 1",
            q.on_accent,
            text_font(11),
        )
        cx += 210
    return y + 70


def draw_frame_sample(c: Canvas, x: int, y: int, p: Palette) -> int:
    c.text(x, y, "Ступенчатая рамка и жёсткая тень", p.text_muted, text_font(12, True))
    y += 24
    for index, (levels, raised) in enumerate(((1, False), (2, True))):
        rect = QRectF(x + index * 270, y, 240, 120)
        paint_frame(
            c.painter,
            rect,
            fill=p.surface_raised if raised else p.surface,
            border=p.border_strong,
            shadow=p.shadow,
            levels=levels,
        )
        c.text(int(rect.x()) + 16, int(rect.y()) + 14, "Карточка", p.text, fonts.pixel_font(3, 1.0))
        c.text(
            int(rect.x()) + 16,
            int(rect.y()) + 52,
            f"ступенек в углу: {levels}",
            p.text_muted,
            text_font(12),
        )
        c.text(
            int(rect.x()) + 16,
            int(rect.y()) + 74,
            "тень 4 px без размытия",
            p.text_muted,
            text_font(12),
        )
    return y + 150


class Mock(QWidget):
    """Макет окна редактора: верхняя строка, левая рейка, панель параметров и холст."""

    def __init__(self, p: Palette) -> None:
        super().__init__()
        self.p = p
        self.setFixedSize(COLUMN, 430)
        root = QVBoxLayout(self)
        root.setContentsMargins(tokens.SPACE_3, tokens.SPACE_3, tokens.SPACE_3, tokens.SPACE_3)
        root.setSpacing(tokens.SPACE_2)
        top = QHBoxLayout()
        for name in ("back_to_view", "undo", "redo"):
            top.addWidget(self._tool(name, checkable=False))
        top.addStretch(1)
        for name in ("copy", "save_as"):
            top.addWidget(self._tool(name, checkable=False))
        save = QPushButton("  Сохранить")
        save.setProperty("variant", "primary")
        save.setIcon(icons.qicon("save", p, role="on_accent", checked_role="on_accent"))
        save.setIconSize(QSize(16, 16))
        top.addWidget(save)
        root.addLayout(top)
        body = QHBoxLayout()
        rail = QVBoxLayout()
        rail.setSpacing(tokens.SPACE_1)
        group = QButtonGroup(self)
        for index, (name, _label) in enumerate(TOOLS):
            button = self._tool(name, checkable=True)
            group.addButton(button)
            button.setChecked(index == 0)
            rail.addWidget(button)
        rail.addStretch(1)
        body.addLayout(rail)
        column = QVBoxLayout()
        chips = QHBoxLayout()
        chips.setSpacing(tokens.SPACE_2)
        for index, text in enumerate(("Свободно", "Исходное", "1:1", "4:3", "16:9", "9:16")):
            chip = QPushButton(text)
            chip.setCheckable(True)
            chip.setChecked(index == 4)
            chip.setProperty("variant", "primary" if index == 4 else "")
            chip.setMinimumWidth(0)
            chips.addWidget(chip)
        chips.addStretch(1)
        column.addLayout(chips)
        self.canvas = QWidget()
        self.canvas.setMinimumHeight(250)
        self.canvas.paintEvent = self._paint_canvas  # type: ignore[method-assign]
        column.addWidget(self.canvas, 1)
        body.addLayout(column, 1)
        root.addLayout(body, 1)

    def _tool(self, name: str, checkable: bool) -> QToolButton:
        button = QToolButton()
        button.setIcon(icons.qicon(name, self.p, logical=32))
        button.setIconSize(QSize(32, 32))
        button.setCheckable(checkable)
        button.setToolTip(name)
        return button

    def paintEvent(self, event: object) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(self.p.bg))

    def _paint_canvas(self, event: object) -> None:
        p = self.p
        painter = QPainter(self.canvas)
        area = self.canvas.rect()
        painter.fillRect(area, QColor(p.surface))
        photo = QRect(area.x() + 8, area.y() + 8, area.width() - 16, area.height() - 16)
        sky = QColor(p.secondary)
        painter.fillRect(photo, sky)
        painter.fillRect(
            QRect(
                photo.x(),
                photo.y() + photo.height() * 2 // 3,
                photo.width(),
                photo.height() // 3 + 1,
            ),
            QColor(p.success),
        )
        painter.setBrush(QColor(p.accent))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(photo.x() + photo.width() * 3 // 4, photo.y() + 22, 44, 44)
        crop = QRect(photo.x() + 70, photo.y() + 34, photo.width() - 190, photo.height() - 84)
        shade = QColor(0, 0, 0, 153)  # затемнение вне рамки 60%
        for rect in (
            QRect(photo.x(), photo.y(), photo.width(), crop.y() - photo.y()),
            QRect(photo.x(), crop.bottom() + 1, photo.width(), photo.bottom() - crop.bottom()),
            QRect(photo.x(), crop.y(), crop.x() - photo.x(), crop.height()),
            QRect(crop.right() + 1, crop.y(), photo.right() - crop.right(), crop.height()),
        ):
            painter.fillRect(rect, shade)
        painter.setPen(QColor(255, 255, 255, 110))
        for i in (1, 2):  # сетка третей
            painter.drawLine(
                crop.x() + crop.width() * i // 3,
                crop.y(),
                crop.x() + crop.width() * i // 3,
                crop.bottom(),
            )
            painter.drawLine(
                crop.x(),
                crop.y() + crop.height() * i // 3,
                crop.right(),
                crop.y() + crop.height() * i // 3,
            )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(p.accent))
        painter.drawRect(crop.adjusted(-1, -1, 1, -crop.height() + 1))
        painter.drawRect(crop.adjusted(-1, crop.height() - 2, 1, 1))
        painter.drawRect(crop.adjusted(-1, -1, -crop.width() + 1, 1))
        painter.drawRect(crop.adjusted(crop.width() - 2, -1, 1, 1))
        for hx in (crop.left(), crop.center().x(), crop.right()):
            for hy in (crop.top(), crop.center().y(), crop.bottom()):
                if (hx, hy) != (crop.center().x(), crop.center().y()):
                    painter.setBrush(QColor(p.surface_raised))
                    painter.setPen(QColor(p.accent))
                    painter.drawRect(hx - 4, hy - 4, 8, 8)
        badge = QRect(crop.center().x() - 50, crop.bottom() - 34, 100, 24)
        paint_frame(painter, QRectF(badge), fill=p.surface_raised, border=p.accent, shadow=None)
        painter.setPen(QColor(p.text))
        painter.setFont(text_font(12, True))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, "1920×1080")


def draw_mock(c: Canvas, x: int, y: int, p: Palette, manager: ThemeManager) -> int:
    c.text(x, y, "Макет панели инструментов редактора", p.text_muted, text_font(12, True))
    y += 24
    mock = Mock(p)
    mock.ensurePolished()
    mock.show()
    pixmap = mock.grab()
    c.painter.drawPixmap(x, y, pixmap)
    mock.close()
    return y + pixmap.height() + 8


def candidates_strip(c: Canvas, x: int, y: int, p: Palette) -> int:
    path = ROOT / "docs" / "design" / "font-candidates.png"
    c.text(
        x,
        y,
        "Кандидаты на пиксельный шрифт (OFL, проверено fontTools)",
        p.text_muted,
        text_font(12, True),
    )
    y += 22
    if path.is_file():
        image = QImage(str(path))
        c.painter.drawImage(x, y, image)
        return y + image.height() + 12
    return y


def main() -> None:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "design" / "preview.png"
    app = QApplication.instance() or QApplication(sys.argv[:1])
    assert isinstance(app, QApplication)
    fonts.load_fonts()
    manager = ThemeManager(app)
    height = 3100
    sheet = Canvas(height)
    palettes = {name: tokens.make_palette(name) for name in THEMES}
    # блоки с настоящими виджетами рисуем при активной стилизации своей темы
    drawers_by_theme = {}
    for name in THEMES:
        manager.set_theme(name)
        app.processEvents()
        drawers_by_theme[name] = {
            "buttons": [],
        }
    top = MARGIN
    for index, name in enumerate(THEMES):
        x = MARGIN + index * (COLUMN + MARGIN)
        p = palettes[name]
        sheet.painter.fillRect(QRect(x - 16, 0, COLUMN + 32, height), QColor(p.bg))
    sheet.painter.fillRect(QRect(0, 0, WIDTH, 56), QColor("#2A1020"))
    sheet.text(
        MARGIN,
        12,
        "CHOPCHOP · дизайн-система 0.2 · «уютный пиксель»",
        "#FFFFFF",
        fonts.pixel_font(3, 1.0),
    )
    ys = []
    for index, name in enumerate(THEMES):
        manager.set_theme(name)
        app.processEvents()
        p = palettes[name]
        x = MARGIN + index * (COLUMN + MARGIN)
        y = top + 48
        y = draw_palette_block(sheet, x, y, p) + 24
        y = draw_typography(sheet, x, y, p) + 8
        y = draw_icons(sheet, x, y, p) + 12
        y = draw_buttons(sheet, x, y, p) + 8
        y = draw_frame_sample(sheet, x, y, p)
        y = draw_accents(sheet, x, y, p)
        y = draw_mock(sheet, x, y, p, manager)
        ys.append(y)
    # кандидаты на шрифт — внизу на всю ширину
    y_left = candidates_strip(sheet, MARGIN, ys[0] + 8, palettes["light"])
    y = max(y_left, ys[1])
    sheet.painter.end()
    final = sheet.image.copy(0, 0, WIDTH, min(height, y + MARGIN))
    output.parent.mkdir(parents=True, exist_ok=True)
    final.save(str(output))
    manager.shutdown()
    print(f"записано: {output} ({final.width()}×{final.height()}), высота по содержимому {y}")


if __name__ == "__main__":
    main()
