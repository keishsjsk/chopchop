# ruff: noqa: E501
"""Сборка таблицы стилей Qt из токенов темы.

Все цвета и размеры берутся из `Palette` и констант `tokens`; ни одного числа или цвета «от
руки» здесь нет. Картинки для флажков, переключателей и стрелок рисуются из тех же токенов
в папку assets и подключаются через `url()`.
"""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter

from chopchop.ui.theme import tokens
from chopchop.ui.theme.tokens import Palette

# рисунки внутри флажка (8×8) и переключателя (10×10): «#» — цвет значка
_CHECK = (
    "........",
    "......##",
    ".....##.",
    "##..##..",
    ".####...",
    "..##....",
    "........",
    "........",
)
_RADIO = (
    "..####..",
    ".######.",
    "########",
    "########",
    "########",
    "########",
    ".######.",
    "..####..",
)
_CHEVRON_DOWN = (
    "........",
    "##....##",
    ".##..##.",
    "..####..",
    "...##...",
    "........",
    "........",
    "........",
)
_CHEVRON_UP = tuple(reversed(_CHEVRON_DOWN))

ASSET_UNIT = 2  # размер «пикселя» значков в стилях, пиксели экрана


def _paint_bitmap(
    image: QImage, rows: tuple[str, ...], color: str, ox: int, oy: int, unit: int
) -> None:
    painter = QPainter(image)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    for y, row in enumerate(rows):
        for x, char in enumerate(row):
            if char == "#":
                painter.drawRect(ox + x * unit, oy + y * unit, unit, unit)
    painter.end()


def _box(size: int, fill: str, border: str, round_steps: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setPen(Qt.PenStyle.NoPen)
    step = tokens.PIXEL_STEP
    for color, inset in ((border, 0), (fill, tokens.BORDER_WIDTH)):
        painter.setBrush(QColor(color))
        inner = size - 2 * inset
        painter.drawRect(inset, inset + step * round_steps, inner, inner - 2 * step * round_steps)
        painter.drawRect(inset + step * round_steps, inset, inner - 2 * step * round_steps, inner)
    painter.end()
    return image


def write_assets(palette: Palette, folder: Path) -> dict[str, Path]:
    """Рисует значки для стилей; возвращает имя -> путь. Файлы перезаписываются при смене темы."""
    folder.mkdir(parents=True, exist_ok=True)
    unit = ASSET_UNIT
    size = 8 * unit + 2 * tokens.BORDER_WIDTH + 2 * unit  # 16 + 4 + 4 = 24 → кратно сетке
    made: dict[str, Path] = {}

    def save(name: str, image: QImage) -> None:
        path = folder / f"{palette.name}-{name}.png"
        image.save(str(path))
        made[name] = path

    pad = (size - 8 * unit) // 2
    off = _box(size, palette.surface_raised, palette.border_strong, 1)
    save("check-off", off)
    on = _box(size, palette.accent, palette.accent, 1)
    _paint_bitmap(on, _CHECK, palette.on_accent, pad, pad, unit)
    save("check-on", on)
    radio_off = QImage(size, size, QImage.Format.Format_ARGB32)
    radio_off.fill(Qt.GlobalColor.transparent)
    _paint_bitmap(radio_off, _RADIO, palette.border_strong, pad, pad, unit)
    _paint_bitmap(
        radio_off,
        (
            "........",
            "..####..",
            ".######.",
            ".######.",
            ".######.",
            ".######.",
            "..####..",
            "........",
        ),
        palette.surface_raised,
        pad + 0,
        pad + 0,
        unit,
    )
    save("radio-off", radio_off)
    radio_on = QImage(size, size, QImage.Format.Format_ARGB32)
    radio_on.fill(Qt.GlobalColor.transparent)
    _paint_bitmap(radio_on, _RADIO, palette.accent, pad, pad, unit)
    _paint_bitmap(
        radio_on,
        (
            "........",
            "........",
            "..####..",
            "..####..",
            "..####..",
            "..####..",
            "........",
            "........",
        ),
        palette.on_accent,
        pad,
        pad,
        unit,
    )
    save("radio-on", radio_on)
    for name, rows in (("down", _CHEVRON_DOWN), ("up", _CHEVRON_UP)):
        glyph = QImage(8 * unit, 8 * unit, QImage.Format.Format_ARGB32)
        glyph.fill(Qt.GlobalColor.transparent)
        _paint_bitmap(glyph, rows, palette.text, 0, 0, unit)
        save(f"chevron-{name}", glyph)
    return made


def _url(path: Path) -> str:
    return path.as_posix()


def build(palette: Palette, assets: dict[str, Path], compact: bool = False) -> str:
    """Таблица стилей для QApplication.setStyleSheet."""
    p = palette
    t = tokens
    hit = t.MIN_HIT
    button_h = t.MIN_HIT if compact else t.BUTTON_HEIGHT  # компактный режим: кнопки 32
    rail = t.MIN_HIT if compact else t.RAIL_BUTTON
    b = t.BORDER_WIDTH
    s1, s2, s3, s4 = t.SPACE_1, t.SPACE_2, t.SPACE_3, t.SPACE_4
    ring = t.BORDER_WIDTH
    return f"""
QWidget {{
    color: {p.text};
    selection-background-color: {p.accent};
    selection-color: {p.on_accent};
}}
QMainWindow, QDialog {{ background: {p.bg}; }}
QToolTip {{
    background: {p.surface_raised};
    color: {p.text};
    border: {b}px solid {p.border_strong};
    padding: {s1}px {s2}px;
}}
QLabel {{ background: transparent; }}
QLabel:disabled {{ color: {p.text_muted}; }}
QLabel[muted="true"] {{ color: {p.text_muted}; }}
QLabel[error="true"] {{ color: {p.danger}; }}
QLabel[heading="true"] {{ color: {p.text}; }}

/* кнопки: обычная, главная (акцентная), опасная, плоская */
QPushButton {{
    min-height: {button_h - 2 * b}px;
    padding: 0 {s4}px;
    background: {p.surface};
    color: {p.text};
    border: {b}px solid {p.border_strong};
    border-radius: 0;
}}
QPushButton:hover {{ background: {p.surface_raised}; border-color: {p.text}; }}
QPushButton:pressed {{ background: {p.bg}; padding-top: {b}px; }}
QPushButton:disabled {{ color: {p.text_muted}; background: {p.bg}; border-color: {p.border}; }}
QPushButton:focus {{ border: {ring}px solid {p.focus_ring}; }}
QPushButton[variant="primary"] {{
    background: {p.accent}; color: {p.on_accent}; border-color: {p.accent};
}}
QPushButton[variant="primary"]:hover {{ background: {p.accent_hover}; border-color: {p.accent_hover}; }}
QPushButton[variant="primary"]:pressed {{ background: {p.accent_pressed}; border-color: {p.accent_pressed}; }}
QPushButton[variant="primary"]:disabled {{ background: {p.bg}; color: {p.text_muted}; border-color: {p.border}; }}
QPushButton[variant="primary"]:focus {{ border: {ring}px solid {p.focus_ring}; }}
QPushButton[variant="danger"] {{
    background: {p.danger}; color: {p.on_danger}; border-color: {p.danger};
}}
/* призрачная: без рамки, но с состояниями; сегментная и «чип» — выбор из нескольких */
QPushButton[variant="ghost"], QPushButton[variant="flat"] {{ background: transparent; border-color: transparent; }}
QPushButton[variant="ghost"]:hover, QPushButton[variant="flat"]:hover {{ background: {p.surface_raised}; border-color: {p.border}; }}
QPushButton[variant="ghost"]:pressed {{ background: {p.border}; }}
QPushButton[variant="ghost"]:disabled {{ background: transparent; border-color: transparent; }}
QPushButton[variant="ghost"]:focus {{ border: {ring}px solid {p.focus_ring}; }}
QPushButton[variant="segment"], QPushButton[variant="chip"] {{
    min-height: {hit - 2 * b}px; padding: 0 {s3}px; background: {p.surface};
}}
QPushButton[variant="chip"] {{ padding: 0 {s2}px; }}
QPushButton[variant="chip"][dense="true"] {{ min-height: {t.STATUS_H - 4 * b}px; padding: 0 {s2}px; }}
QPushButton[variant="segment"]:checked, QPushButton[variant="chip"]:checked {{
    background: {p.accent_tint}; color: {p.text}; border-color: {p.accent};
}}
QPushButton[variant="segment"]:checked:hover, QPushButton[variant="chip"]:checked:hover {{ border-color: {p.accent_hover}; }}
QPushButton[variant="segment"]:checked:disabled, QPushButton[variant="chip"]:checked:disabled {{ background: {p.bg}; color: {p.text_muted}; border-color: {p.border}; }}
QPushButton[variant="segment"]:focus, QPushButton[variant="chip"]:focus {{ border: {ring}px solid {p.focus_ring}; }}

/* кнопки панелей: рейка инструментов и значки */
QToolButton {{
    min-width: {rail - 2 * b}px; min-height: {rail - 2 * b}px;
    padding: 0 {s2}px;
    background: transparent;
    border: {b}px solid transparent;
    border-radius: 0;
}}
QToolButton:hover {{ background: {p.surface_raised}; border-color: {p.border}; }}
QToolButton:pressed {{ background: {p.border}; }}
QToolButton:checked {{ background: {p.accent}; color: {p.on_accent}; border-color: {p.accent}; }}
QToolButton:disabled {{ color: {p.text_muted}; }}
QToolButton:focus {{ border: {ring}px solid {p.focus_ring}; }}
QToolButton[rail="true"] {{
    min-width: {rail - 2 * b}px; min-height: {rail - 2 * b}px; padding: 0;
}}
QToolButton[variant="ghost"] {{
    min-width: {rail - 2 * b}px; min-height: {rail - 2 * b}px; padding: 0;
}}
QToolButton[variant="ghost"][labelled="true"] {{ padding: 0 {s3}px; }}
QToolButton[variant="ghost"][warn="true"] {{ color: {p.danger}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}

/* поля ввода */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    min-height: {hit - 2 * b}px;
    padding: 0 {s2}px;
    background: {p.surface_raised};
    color: {p.text};
    border: {b}px solid {p.border_strong};
    border-radius: 0;
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus,
QPlainTextEdit:focus, QTextEdit:focus {{ border-color: {p.focus_ring}; }}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
    background: {p.bg}; color: {p.text_muted}; border-color: {p.border};
}}
QComboBox::drop-down {{ border: none; width: {hit - s2}px; }}
QComboBox::down-arrow {{ image: url({_url(assets["chevron-down"])}); }}
QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button {{
    width: {hit - s2}px; border: none; background: transparent;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url({_url(assets["chevron-up"])}); }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url({_url(assets["chevron-down"])}); }}
QComboBox QAbstractItemView {{
    background: {p.surface_raised}; color: {p.text};
    border: {b}px solid {p.border_strong};
    selection-background-color: {p.accent}; selection-color: {p.on_accent};
    outline: none;
}}

/* флажки и переключатели */
QCheckBox, QRadioButton {{ spacing: {s2}px; min-height: {hit - s2}px; background: transparent; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: {2 * s4 - s2}px; height: {2 * s4 - s2}px; }}
QCheckBox::indicator:unchecked {{ image: url({_url(assets["check-off"])}); }}
QCheckBox::indicator:checked {{ image: url({_url(assets["check-on"])}); }}
QRadioButton::indicator:unchecked {{ image: url({_url(assets["radio-off"])}); }}
QRadioButton::indicator:checked {{ image: url({_url(assets["radio-on"])}); }}
QCheckBox:focus, QRadioButton:focus {{ color: {p.text}; }}
QCheckBox:disabled, QRadioButton:disabled {{ color: {p.text_muted}; }}

/* ползунки */
QSlider::groove:horizontal {{ height: {t.PIXEL_STEP * 2}px; background: {p.border_strong}; }}
QSlider::sub-page:horizontal {{ background: {p.accent}; }}
QSlider::handle:horizontal {{
    width: {s4 - b}px; height: {s4 - b}px; margin: -{s1}px 0;
    background: {p.surface_raised}; border: {b}px solid {p.text};
}}
QSlider::handle:horizontal:hover {{ background: {p.accent}; border-color: {p.text}; }}
QSlider::groove:vertical {{ width: {t.PIXEL_STEP * 2}px; background: {p.border_strong}; }}
QSlider::handle:vertical {{
    width: {s4 - b}px; height: {s4 - b}px; margin: 0 -{s1}px;
    background: {p.surface_raised}; border: {b}px solid {p.text};
}}

/* полосы прокрутки */
QScrollBar:vertical {{ background: {p.bg}; width: {s3}px; margin: 0; }}
QScrollBar:horizontal {{ background: {p.bg}; height: {s3}px; margin: 0; }}
QScrollBar::handle {{ background: {p.border_strong}; min-height: {s4 + s2}px; min-width: {s4 + s2}px; }}
QScrollBar::handle:hover {{ background: {p.text_muted}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* списки, меню, вкладки */
QListWidget, QListView, QTreeView, QTableView {{
    background: {p.surface}; border: {b}px solid {p.border_strong}; outline: none;
}}
QListWidget::item, QListView::item {{ min-height: {hit - s2}px; padding: 0 {s2}px; }}
QListWidget::item:hover, QListView::item:hover {{ background: {p.surface_raised}; }}
QListWidget::item:selected, QListView::item:selected {{ background: {p.accent}; color: {p.on_accent}; }}
QMenuBar {{ background: {p.bg}; }}
QMenuBar::item {{ padding: {s1}px {s3}px; background: transparent; }}
QMenuBar::item:selected {{ background: {p.surface_raised}; }}
QMenu {{ background: {p.surface_raised}; border: {b}px solid {p.border_strong}; padding: {s1}px; }}
QMenu::item {{ padding: {s2}px {s4 + s2}px; min-height: {hit - s4}px; }}
QMenu::item:selected {{ background: {p.accent}; color: {p.on_accent}; }}
QMenu::item:disabled {{ color: {p.text_muted}; }}
QMenu::separator {{ height: {b}px; background: {p.border}; margin: {s1}px {s2}px; }}
QStatusBar {{ background: {p.bg}; color: {p.text_muted}; }}
QProgressBar {{
    min-height: {s3}px; background: {p.surface}; border: {b}px solid {p.border_strong}; text-align: center;
}}
QProgressBar::chunk {{ background: {p.accent}; }}
QGroupBox {{ border: {b}px solid {p.border}; margin-top: {s3}px; padding-top: {s3}px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: {s3}px; padding: 0 {s1}px; color: {p.text_muted}; }}
QTabBar::tab {{
    padding: {s2}px {s4}px; background: {p.bg}; border: {b}px solid {p.border}; border-bottom: none;
}}
QTabBar::tab:selected {{ background: {p.surface}; border-color: {p.border_strong}; }}
QDialogButtonBox {{ button-layout: 3; }}
"""


def scrim_color(palette: Palette) -> QColor:
    """Полупрозрачное затемнение под панелями и диалогами."""
    return QColor(*palette.scrim)
