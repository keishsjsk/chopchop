"""Иконки, шрифт, рамки, стили и смена темы на лету."""

import re
from pathlib import Path

import pytest
from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import QColor, QIcon, QImage, QPainter
from PySide6.QtWidgets import QApplication, QPushButton
from pytestqt.qtbot import QtBot

from chopchop.services.paths import resource_dir
from chopchop.ui.theme import fonts, icon_data, icons, pixel, qss, tokens
from chopchop.ui.theme.manager import ThemeManager
from chopchop.ui.theme.tokens import DARK, LIGHT, make_palette

# --- иконки ------------------------------------------------------------------------------------


@pytest.mark.parametrize("size", [16, 24])
def test_icon_bitmaps_are_well_formed(size: int) -> None:
    grids = icon_data.ICONS_16 if size == 16 else icon_data.ICONS_24
    assert grids
    for name, rows in grids.items():
        assert len(rows) == size, name
        assert all(len(row) == size for row in rows), name
        assert {char for row in rows for char in row} <= set("#a."), name
        pixels = sum(row.count("#") + row.count("a") for row in rows)
        assert pixels >= size, f"{name}: почти пустая иконка"
        assert pixels <= size * size * 0.7, f"{name}: иконка залита почти целиком"
        # последние ряд и столбец зарезервированы под тень
        assert set(rows[-1]) == {"."}, name
        assert all(row[-1] == "." for row in rows), name


def test_all_required_icons_exist() -> None:
    missing = [name for name in icons.REQUIRED if name not in icons.names(16)]
    assert missing == []
    assert len(icons.REQUIRED) == 58


def test_large_icons_have_a_24_grid() -> None:
    assert set(icon_data.ICONS_24) == {"play", "pause", "folder", "edit"}
    assert icons.grid_size("play", 24) == 24
    assert icons.grid_size("trash", 24) == 16  # крупного варианта нет: берётся 16×16


def test_no_duplicate_pictures() -> None:
    seen: dict[tuple[str, ...], str] = {}
    for name, rows in icon_data.ICONS_16.items():
        assert rows not in seen, f"{name} совпадает с {seen.get(rows)}"
        seen[rows] = name


@pytest.mark.parametrize("scale", [1, 2, 3, 4])
def test_render_uses_integer_nearest_neighbour_scaling(scale: int) -> None:
    image = icons.render("play", scale=scale, color="#112233")
    assert image.size().width() == 16 * scale
    colors = {
        image.pixelColor(x, y).name() for x in range(image.width()) for y in range(image.height())
    }
    assert colors <= {"#112233", "#000000"}  # ни одного промежуточного цвета: без сглаживания
    # пиксель сетки (3, 2) — левый верх треугольника — стал блоком scale×scale
    block = {
        image.pixelColor(3 * scale + dx, 2 * scale + dy).name()
        for dx in range(scale)
        for dy in range(scale)
    }
    assert block == {"#112233"}


def test_icon_is_recoloured_by_tokens_with_shadow() -> None:
    palette = make_palette("light")
    image = icons.render(
        "pause", scale=1, color=palette.text, accent=palette.accent, shadow=palette.border
    )
    assert image.pixelColor(3, 2).name() == palette.text.lower()  # основной цвет
    assert image.pixelColor(7, 14).name() == palette.border.lower()  # тень под левой палкой
    assert image.pixelColor(8, 8).alpha() == 0  # между палками пусто
    dark = icons.render("pause", scale=1, color=DARK.text, shadow=DARK.border)
    assert dark.pixelColor(3, 2).name() == DARK.text.lower()
    assert dark.pixelColor(3, 2).name() != image.pixelColor(3, 2).name()


def test_accent_pixels_use_the_accent_colour(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = list(icon_data.ICONS_16["pause"])
    rows[2] = "...a###..####..."
    monkeypatch.setitem(icon_data.ICONS_16, "pause", tuple(rows))
    icons.clear_cache()
    image = icons.render("pause", scale=1, color="#111111", accent="#ff8800")
    assert image.pixelColor(3, 2).name() == "#ff8800"
    assert image.pixelColor(4, 2).name() == "#111111"
    plain = icons.render("pause", scale=1, color="#111111")  # без акцента «a» красится основным
    assert plain.pixelColor(3, 2).name() == "#111111"
    icons.clear_cache()


def test_integer_scale_follows_device_pixel_ratio() -> None:
    assert icons.integer_scale(16, 1.0) == 1
    assert icons.integer_scale(16, 1.25) == 1
    assert icons.integer_scale(16, 1.5) == 2
    assert icons.integer_scale(16, 2.0) == 2
    assert icons.integer_scale(32, 1.0) == 2
    assert icons.integer_scale(16, 0.5) == 1  # не меньше единицы


def test_pixmap_keeps_logical_size_with_device_pixels(qtbot: QtBot) -> None:
    palette = make_palette("dark")
    pm = icons.pixmap("play", palette, logical=16, ratio=2.0)
    assert pm.width() == 32 and pm.devicePixelRatio() == pytest.approx(2.0)
    pm = icons.pixmap(
        "play", palette, logical=16, ratio=1.5
    )  # 1,5 округляется до 2: чёткие пиксели
    assert pm.width() == 32 and pm.devicePixelRatio() == pytest.approx(2.0)
    big = icons.pixmap("play", palette, logical=24, ratio=1.0, size=24)
    assert big.width() == 24


def test_qicon_has_states(qtbot: QtBot) -> None:
    palette = make_palette("light")
    icon = icons.qicon("pause", palette)
    size = QSize(16, 16)
    normal = icon.pixmap(size, 1.0).toImage()
    disabled = icon.pixmap(size, 1.0, QIcon.Mode.Disabled).toImage()
    checked = icon.pixmap(size, 1.0, QIcon.Mode.Normal, QIcon.State.On).toImage()
    assert normal.pixelColor(3, 2).name() == palette.text.lower()
    assert disabled.pixelColor(3, 2).name() == palette.text_muted.lower()
    assert checked.pixelColor(3, 2).name() == palette.on_accent.lower()


# --- шрифт -------------------------------------------------------------------------------------


def test_pixel_font_ships_with_license() -> None:
    folder = resource_dir() / "fonts"
    assert (folder / "Tiny5.ttf").is_file()
    assert "SIL OPEN FONT LICENSE" in (folder / "OFL-Tiny5.txt").read_text(encoding="utf-8")


def test_pixel_font_loads_and_covers_cyrillic(qtbot: QtBot) -> None:
    assert fonts.load_fonts()
    font = fonts.pixel_font(2, 1.0)
    assert font.family() == fonts.PIXEL_FAMILY
    assert font.pixelSize() == 16
    assert fonts.pixel_font(3, 1.0).pixelSize() == 24
    text = "Привет, мир! Настройки · Воспроизведение · Редактор · Сохранить как… ЁёЙйЪъЫыЭэЮюЯя"
    assert fonts.covers(font, text)


def test_pixel_sizes_stay_multiples_of_eight_device_pixels() -> None:
    for scale in (2, 3, 4):
        for ratio in (1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0):
            device = fonts.snapped_pixel_size(scale, ratio) * ratio
            assert device % 8 == pytest.approx(0, abs=1e-6)
            assert device >= 8


def test_font_coverage_with_fonttools() -> None:
    ttlib = pytest.importorskip("fontTools.ttLib")
    font = ttlib.TTFont(resource_dir() / "fonts" / "Tiny5.ttf")
    cmap = font.getBestCmap()
    cyrillic = [chr(code) for code in [*range(0x410, 0x450), 0x401, 0x451]]
    assert [char for char in cyrillic if ord(char) not in cmap] == []
    assert all(ord(char) in cmap for char in "0123456789%:()[]/×.,!?-—…·")


# --- ступенчатые рамки -------------------------------------------------------------------------


def test_stepped_polygon_cuts_corners() -> None:
    rect = QRectF(0, 0, 20, 10)
    one = pixel.stepped_polygon(rect, 2, 1)
    assert one.count() == 8
    assert (one.at(0).x(), one.at(0).y()) == (2, 0)  # левый верхний угол срезан
    two = pixel.stepped_polygon(rect, 2, 2)
    assert two.count() == 20
    points = {(two.at(i).x(), two.at(i).y()) for i in range(two.count())}
    assert (0, 0) not in points and (20, 10) not in points


def _render_frame(shadow: str | None) -> QImage:
    image = QImage(40, 30, QImage.Format.Format_ARGB32)
    image.fill(QColor("#000000"))
    painter = QPainter(image)
    pixel.paint_frame(
        painter,
        QRectF(2, 2, 24, 16),
        fill="#ffffff",
        border="#ff0000",
        shadow=shadow,
    )
    painter.end()
    return image


def test_frame_has_hard_shadow_border_and_fill() -> None:
    image = _render_frame("#00ff00")
    assert image.pixelColor(14, 10).name() == "#ffffff"  # заливка
    assert (
        image.pixelColor(14, 2).name() == "#ff0000" or image.pixelColor(14, 3).name() == "#ff0000"
    )
    assert image.pixelColor(2, 2).name() == "#000000"  # угол срезан ступенькой
    assert image.pixelColor(28, 19).name() == "#00ff00"  # тень смещена на 4 пикселя
    assert image.pixelColor(28, 3).name() == "#000000"  # выше тени пусто
    assert image.pixelColor(28, 8).name() == "#00ff00"  # тень видна справа от рамки
    colors = {image.pixelColor(x, y).name() for x in range(40) for y in range(30)}
    assert colors == {"#000000", "#ffffff", "#ff0000", "#00ff00"}  # без размытия и сглаживания


def test_frame_without_shadow_draws_nothing_outside() -> None:
    image = _render_frame(None)
    assert image.pixelColor(28, 19).name() == "#000000"


def test_pixel_frame_widget_follows_theme(qtbot: QtBot) -> None:
    frame = pixel.PixelFrame(LIGHT)
    qtbot.addWidget(frame)
    frame.resize(60, 40)
    frame.show()
    light = frame.grab().toImage().pixelColor(30, 20).name()
    frame.set_tokens(DARK)
    dark = frame.grab().toImage().pixelColor(30, 20).name()
    assert light == LIGHT.surface.lower() and dark == DARK.surface.lower()


# --- стили -------------------------------------------------------------------------------------


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_stylesheet_uses_only_token_colours(tmp_path: Path, theme: str, qtbot: QtBot) -> None:
    palette = make_palette(theme, "violet")
    sheet = qss.build(palette, qss.write_assets(palette, tmp_path))
    allowed = {
        value.lower()
        for field, value in vars(palette).items()
        if isinstance(value, str) and value.startswith("#")
    }
    literals = {match.lower() for match in re.findall(r"#[0-9a-fA-F]{3,8}\b", sheet)}
    assert literals <= allowed, literals - allowed
    assert palette.accent.lower() in literals and palette.text.lower() in literals


def test_stylesheet_sizes_come_from_tokens(tmp_path: Path, qtbot: QtBot) -> None:
    palette = make_palette("light")
    sheet = qss.build(palette, qss.write_assets(palette, tmp_path))
    assert f"min-height: {tokens.BUTTON_HEIGHT - 2 * tokens.BORDER_WIDTH}px" in sheet  # кнопка 40
    assert f"min-width: {tokens.RAIL_BUTTON - 2 * tokens.BORDER_WIDTH}px" in sheet  # рейка 40
    for state in (":hover", ":pressed", ":disabled", ":focus", ":checked"):
        assert state in sheet
    assert palette.focus_ring in sheet


def test_assets_are_written_for_each_theme(tmp_path: Path, qtbot: QtBot) -> None:
    light = qss.write_assets(make_palette("light"), tmp_path)
    dark = qss.write_assets(make_palette("dark"), tmp_path)
    assert set(light) == {
        "check-off",
        "check-on",
        "radio-off",
        "radio-on",
        "chevron-down",
        "chevron-up",
        "chevron-right",
    }
    for path in [*light.values(), *dark.values()]:
        assert path.is_file()
    assert light["check-on"] != dark["check-on"]
    checked = QImage(str(light["check-on"]))
    assert checked.pixelColor(2, 12).name() == make_palette("light").accent.lower()


# --- менеджер темы -----------------------------------------------------------------------------


def test_theme_switches_on_the_fly(qtbot: QtBot) -> None:
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    previous = app.styleSheet()
    manager = ThemeManager(app)
    try:
        changes: list[str] = []
        manager.changed.connect(lambda palette: changes.append(palette.name))
        manager.set_theme("light", "orange")
        light_sheet = app.styleSheet()
        manager.set_theme("dark")
        dark_sheet = app.styleSheet()
        assert changes == ["light", "dark"]
        assert light_sheet != dark_sheet
        assert DARK.bg.lower() in dark_sheet.lower() and LIGHT.bg.lower() in light_sheet.lower()
        manager.set_theme("dark", "coral")
        assert manager.palette.accent == make_palette("dark", "coral").accent
        manager.set_theme("nonsense")
        assert manager.choice == "system"
    finally:
        manager.shutdown()
        app.setStyleSheet(previous)


def test_buttons_get_styles_and_variants(qtbot: QtBot) -> None:
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    previous = app.styleSheet()
    manager = ThemeManager(app)
    try:
        manager.set_theme("light")
        plain, primary = QPushButton("Отмена"), QPushButton("Сохранить")
        primary.setProperty("variant", "primary")
        for button in (plain, primary):
            qtbot.addWidget(button)
            button.show()
        assert plain.sizeHint().height() >= tokens.BUTTON_HEIGHT
        assert primary.grab().toImage().pixelColor(8, 8).name() == LIGHT.accent.lower()
        assert plain.grab().toImage().pixelColor(8, 8).name() == LIGHT.surface.lower()
        manager.set_theme("dark")
        primary.style().unpolish(primary)
        primary.style().polish(primary)
        assert primary.grab().toImage().pixelColor(8, 8).name() == DARK.accent.lower()
    finally:
        manager.shutdown()
        app.setStyleSheet(previous)
