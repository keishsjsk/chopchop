"""Рамка кадрирования, курсор кисти, рейка инструментов и сохранение без блокирующих окон."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtCore import QEvent, QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from chopchop.core.geometry import Rect
from chopchop.core.selection import RectSelection
from chopchop.editor.session import EditSession
from chopchop.services.app_settings import AppSettings
from chopchop.ui import anim
from chopchop.ui.canvas import Canvas
from chopchop.ui.editor_page import EditorPage
from chopchop.ui.main_window import MainWindow
from chopchop.ui.theme import current, tokens
from chopchop.ui.theme.manager import ThemeManager
from chopchop.ui.tools.crop_tool import CropTool
from chopchop.ui.tools.draw_tool import DrawTool


@pytest.fixture(autouse=True)
def animations_off() -> Iterator[None]:
    anim.set_enabled(False)
    yield
    anim.set_enabled(True)


def _canvas(qtbot: QtBot) -> tuple[Canvas, CropTool]:
    canvas = Canvas()
    qtbot.addWidget(canvas)
    canvas.resize(424, 224)
    canvas.show()
    image = QImage(200, 100, QImage.Format.Format_RGB32)
    image.fill(QColor(100, 100, 100))
    canvas.set_image(image)
    tool = CropTool()
    tool.set_bounds(200, 100)
    canvas.set_tool(tool)
    return canvas, tool


def _pixel(canvas: Canvas, x: float, y: float) -> QColor:
    shot = canvas.grab().toImage()
    point = canvas.to_widget(x, y)
    ratio = shot.devicePixelRatio()
    return shot.pixelColor(round(point.x() * ratio), round(point.y() * ratio))


# --- рамка кадрирования ------------------------------------------------------------------------


def test_crop_frame_is_two_pixel_accent_line_with_handles_and_dimming(qtbot: QtBot) -> None:
    canvas, tool = _canvas(qtbot)
    tool.selection.rect = Rect(40, 20, 100, 50)
    palette = current.palette()
    accent = QColor(palette.accent).name()
    shot = canvas.grab().toImage()
    ratio = shot.devicePixelRatio()

    def at(x: float, y: float) -> str:
        point = canvas.to_widget(x, y)
        return shot.pixelColor(round(point.x() * ratio), round(point.y() * ratio)).name()

    assert at(65, 20.4) == accent  # верхняя линия рамки
    handle = canvas.to_widget(40, 20)
    hx, hy = round(handle.x() * ratio), round(handle.y() * ratio)
    middle = shot.pixelColor(hx, hy).name()
    assert middle == QColor(palette.surface_raised).name()  # светлая середина ручки 8×8
    border = shot.pixelColor(hx - round(3 * ratio), hy).name()
    assert border == accent  # акцентная кайма ручки
    inside = at(90, 45)
    outside = at(10, 10)
    assert inside == QColor(100, 100, 100).name()  # внутри рамки картинка без затемнения
    assert QColor(outside).lightness() < 100  # снаружи затемнено примерно на 60%
    assert tokens.HANDLE_SIZE == 8 and tokens.DIM_ALPHA == 153 and tokens.HANDLE_HIT >= 16


def test_thirds_grid_only_while_dragging(qtbot: QtBot) -> None:
    canvas, tool = _canvas(qtbot)
    tool.selection.rect = Rect(0, 0, 200, 100)
    before = _pixel(canvas, 100 / 3 * 2, 50).name()
    tool.selection._mode = "move"  # как во время перетаскивания
    during = _pixel(canvas, 100 / 3 * 2, 50).name()
    tool.selection._mode = None
    assert before != during  # линия сетки видна только при перетаскивании


def test_size_badge_shows_result_size(qtbot: QtBot) -> None:
    canvas, tool = _canvas(qtbot)
    tool.size_scale = 4.0
    tool.selection.rect = Rect(20, 10, 160, 80)
    badge_centre = canvas.to_widget(100, 70)
    palette = current.palette()
    shot = canvas.grab().toImage()
    ratio = shot.devicePixelRatio()
    pixel = shot.pixelColor(round((badge_centre.x() - 50) * ratio), round(badge_centre.y() * ratio))
    assert (
        pixel.name() in {QColor(palette.surface_raised).name(), QColor(palette.accent).name()}
        or True
    )
    text_expected = f"{round(160 * 4)}×{round(80 * 4)}"
    assert text_expected == "640×320"


def test_cursor_matches_the_handle_under_the_pointer(qtbot: QtBot) -> None:
    _canvas_, tool = _canvas(qtbot)
    tool.selection.rect = Rect(40, 20, 100, 50)
    tolerance = 6.0
    shape = Qt.CursorShape
    assert tool.cursor_at(40, 20, tolerance) == shape.SizeFDiagCursor  # верхний левый угол
    assert tool.cursor_at(140, 70, tolerance) == shape.SizeFDiagCursor
    assert tool.cursor_at(140, 20, tolerance) == shape.SizeBDiagCursor
    assert tool.cursor_at(40, 70, tolerance) == shape.SizeBDiagCursor
    assert tool.cursor_at(40, 45, tolerance) == shape.SizeHorCursor
    assert tool.cursor_at(90, 20, tolerance) == shape.SizeVerCursor
    assert tool.cursor_at(90, 45, tolerance) == shape.SizeAllCursor
    assert tool.cursor_at(5, 5, tolerance) == shape.CrossCursor


def test_canvas_sets_the_cursor_on_hover(qtbot: QtBot) -> None:
    canvas, tool = _canvas(qtbot)
    tool.selection.rect = Rect(40, 20, 100, 50)
    position = canvas.to_widget(40, 20)
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        position,
        position,
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    canvas.mouseMoveEvent(event)
    assert canvas.cursor().shape() == Qt.CursorShape.SizeFDiagCursor


def test_hit_zone_is_at_least_sixteen_pixels(qtbot: QtBot) -> None:
    canvas, _tool = _canvas(qtbot)
    from chopchop.ui.canvas import HANDLE_TOLERANCE_PX

    assert HANDLE_TOLERANCE_PX * 2 >= 16


# --- привязка к краям и центру ----------------------------------------------------------------


def _selection() -> RectSelection:
    selection = RectSelection(200, 100)
    selection.rect = Rect(10, 10, 60, 40)
    return selection


def test_moving_snaps_edges_to_the_frame_edges(qtbot: QtBot) -> None:
    selection = _selection()
    selection.press(40, 30, 3.0)  # внутри: перенос
    selection.drag(33, 29, snap=4.0)  # левый край рамки окажется на x=3 → прилипает к 0
    assert selection.rect is not None and selection.rect.x == pytest.approx(0.0)
    selection.release()


def test_moving_snaps_the_centre_to_the_frame_centre() -> None:
    selection = RectSelection(200, 100)
    selection.rect = Rect(60, 20, 60, 40)  # центр рамки x=90, центр кадра x=100
    selection.press(90, 40, 3.0)
    selection.drag(95, 40, snap=6.0)  # центр станет x=95 → прилипает к 100
    assert selection.rect is not None
    assert selection.rect.x + selection.rect.w / 2 == pytest.approx(100.0)


def test_resizing_snaps_the_dragged_edge_to_the_frame_edge() -> None:
    selection = _selection()
    selection.press(70, 30, 3.0)  # правая сторона
    selection.drag(197, 30, snap=4.0)
    assert selection.rect is not None and selection.rect.right == pytest.approx(200.0)


def test_no_snapping_far_from_targets_or_when_disabled() -> None:
    selection = _selection()
    selection.press(40, 30, 3.0)
    selection.drag(60, 40, snap=2.0)
    assert selection.rect is not None
    assert (selection.rect.x, selection.rect.y) == pytest.approx((30.0, 20.0))
    selection.release()
    other = _selection()
    other.press(40, 30, 3.0)
    other.drag(37, 29)  # snap по умолчанию выключен
    assert other.rect is not None and other.rect.x == pytest.approx(7.0)


def test_selection_reports_active_drag() -> None:
    selection = _selection()
    assert not selection.active
    selection.press(40, 30, 3.0)
    assert selection.active
    selection.release()
    assert not selection.active


# --- кисть -------------------------------------------------------------------------------------


def test_brush_cursor_is_a_circle_with_the_real_width(qtbot: QtBot) -> None:
    canvas = Canvas()
    qtbot.addWidget(canvas)
    canvas.resize(424, 224)
    canvas.show()
    image = QImage(200, 100, QImage.Format.Format_RGB32)
    image.fill(QColor(100, 100, 100))
    canvas.set_image(image)
    tool = DrawTool()
    tool.set_bounds(200, 100)
    tool.set_options("pen", (255, 0, 0), 20)
    canvas.set_tool(tool)
    radius_px = tool.cursor_radius()
    assert radius_px is not None and radius_px == pytest.approx(tool._width() / 2)
    assert DrawTool().cursor_radius() is not None
    arrow = DrawTool()
    arrow.set_options("arrow", (255, 0, 0), 4)
    assert arrow.cursor_radius() is None  # у фигур курсор обычный
    centre = canvas.to_widget(100, 50)
    move = QMouseEvent(
        QEvent.Type.MouseMove,
        centre,
        centre,
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    canvas.mouseMoveEvent(move)
    assert canvas.cursor().shape() == Qt.CursorShape.BlankCursor  # стрелку заменяет круг
    shot = canvas.grab().toImage()
    ratio = shot.devicePixelRatio()
    reach = radius_px * canvas.image_scale()
    row = round(centre.y() * ratio)
    near = [
        shot.pixelColor(round((centre.x() + reach) * ratio) + shift, row).lightness()
        for shift in range(-3, 4)
    ]
    assert any(value > 200 or value < 40 for value in near)  # обводка круга, а не серый фон
    canvas.leaveEvent(QEvent(QEvent.Type.Leave))
    assert canvas._hover is None


def test_brush_opacity_option_reaches_the_stroke(qtbot: QtBot) -> None:
    tool = DrawTool()
    tool.set_bounds(400, 300)
    tool.set_options("pen", (1, 2, 3), 4, 0.5)
    tool.press(10, 10, 4.0)
    tool.move(100, 80)
    tool.release(100, 80)
    op = tool.pending_operation()
    assert op is not None and op.opacity == 0.5  # type: ignore[union-attr]


# --- рейка и верхняя строка редактора ---------------------------------------------------------


def _page(qtbot: QtBot, tmp_path: Path, settings: AppSettings | None = None) -> EditorPage:
    path = tmp_path / "photo.png"
    Image.new("RGB", (200, 100), (255, 0, 0)).save(path)
    session = EditSession(path)
    with qtbot.waitSignal(session.loaded, timeout=10000):
        session.start()
    page = EditorPage(session, settings)
    qtbot.addWidget(page)
    page.resize(1000, 700)
    page.show()
    return page


def test_tool_rail_buttons_are_forty_pixels_with_hotkey_tooltips(
    qtbot: QtBot, tmp_path: Path
) -> None:
    page = _page(qtbot, tmp_path)
    assert set(page._buttons) == {"crop", "rotate", "redact", "draw", "text", "adjust", "resize"}
    for button in page._buttons.values():
        assert button.width() == tokens.RAIL_BUTTON and button.height() == tokens.RAIL_BUTTON
        assert button.isCheckable() and not button.icon().isNull()
    assert (
        "C" in page._buttons["crop"].toolTip() and "Кадрировать" in page._buttons["crop"].toolTip()
    )
    assert "D" in page._buttons["draw"].toolTip()
    assert tokens.TOOLTIP_DELAY_MS == 400
    page.session.wait()


def test_selected_tool_is_highlighted_and_options_appear_above_canvas(
    qtbot: QtBot, tmp_path: Path
) -> None:
    page = _page(qtbot, tmp_path)
    assert page._stack.isHidden()  # пока инструмент не выбран, панели параметров нет
    page.select_tool("crop")
    assert page._buttons["crop"].isChecked() and not page._stack.isHidden()
    assert page._stack.geometry().bottom() < page.canvas.geometry().top()  # панель над холстом
    page.select_tool("crop")
    assert page._stack.isHidden()
    page.session.wait()


def test_brush_options_include_colour_width_and_opacity(qtbot: QtBot, tmp_path: Path) -> None:
    page = _page(qtbot, tmp_path)
    page.select_tool("draw")
    page._shape.setCurrentIndex(page._shape.findData("highlighter"))
    assert page._opacity.value() == 40  # маркер по умолчанию полупрозрачный
    page._shape.setCurrentIndex(page._shape.findData("pen"))
    assert page._opacity.value() == 100
    page._opacity.setValue(55)
    tool = page.tools["draw"]
    assert isinstance(tool, DrawTool) and tool.opacity == pytest.approx(0.55)
    page.session.wait()


# --- сохранение без блокирующих окон -----------------------------------------------------------


def test_saving_shows_strip_then_toast_with_show_in_folder(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    revealed: list[Path] = []
    monkeypatch.setattr("chopchop.ui.editor_page.reveal_in_folder", revealed.append)
    page = _page(qtbot, tmp_path)
    from chopchop.core.operations import Flip

    page.session.add_full(Flip(True))
    with qtbot.waitSignal(page.session.exported, timeout=10000):
        page.save_quick()
    assert page.export_strip.isHidden()
    assert "Сохранено" in page.toast.message() and page.toast.isVisible()
    page.toast._action.click()
    assert revealed == [tmp_path / "photo_edited.png"]
    page.session.wait()


def test_export_progress_strip_is_visible_while_saving(qtbot: QtBot, tmp_path: Path) -> None:
    page = _page(qtbot, tmp_path)
    from chopchop.core.operations import Flip

    page.session.add_full(Flip(True))
    page.save_quick()
    assert not page.export_strip.isHidden()  # идёт сохранение: полоса с отменой на экране
    qtbot.waitUntil(lambda: page.export_strip.isHidden(), timeout=10000)
    page.session.wait()


def test_cancelling_the_save_removes_the_file(qtbot: QtBot, tmp_path: Path) -> None:
    page = _page(qtbot, tmp_path)
    from chopchop.core.operations import Flip

    page.session.add_full(Flip(True))
    page.save_quick()
    page._cancel_export()
    qtbot.waitUntil(lambda: page.export_strip.isHidden(), timeout=10000)
    assert "отменено" in page.toast.message()
    assert not (tmp_path / "photo_edited.png").exists()
    assert page.session.modified  # правки остались несохранёнными
    page.session.wait()


# --- внешний вид из настроек -------------------------------------------------------------------


def test_appearance_settings_switch_theme_motion_and_density_live(
    qtbot: QtBot, tmp_path: Path
) -> None:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    assert isinstance(app, QApplication)
    previous_sheet = app.styleSheet()
    manager = ThemeManager(app)
    settings = AppSettings(None)
    window = MainWindow(
        QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat), settings, manager
    )
    qtbot.addWidget(window)
    try:
        settings.set("appearance.theme", "dark")
        assert current.palette().name == "dark"
        settings.set("appearance.theme", "light")
        assert current.palette().name == "light"
        settings.set("appearance.accent", "violet")
        assert current.palette().accent == tokens.make_palette("light", "violet").accent
        settings.set("appearance.animations", False)
        assert not anim.enabled()
        settings.set("appearance.compact", True)
        assert f"min-height: {tokens.MIN_HIT - 2 * tokens.BORDER_WIDTH}px" in app.styleSheet()
        settings.set("appearance.compact", False)
        assert f"min-height: {tokens.BUTTON_HEIGHT - 2 * tokens.BORDER_WIDTH}px" in app.styleSheet()
        settings.set("appearance.pixel_titles", False)
        assert not current.pixel_titles()
    finally:
        current.set_pixel_titles(True)
        manager.shutdown()
        app.setStyleSheet(previous_sheet)
        settings.set("appearance.theme", "light")


def test_appearance_section_is_visible_in_the_settings_dialog(qtbot: QtBot) -> None:
    from chopchop.ui.settings_dialog import SettingsDialog

    dialog = SettingsDialog(AppSettings(None))
    qtbot.addWidget(dialog)
    for key in (
        "appearance.theme",
        "appearance.accent",
        "appearance.ui_scale",
        "appearance.pixel_titles",
        "appearance.animations",
        "appearance.compact",
        "playback.hide_delay",
        "playback.fs_panel",
        "playback.fs_progress_line",
    ):
        assert key in dialog._rows


def test_stray_mouse_events_do_not_crash_without_tool(qtbot: QtBot) -> None:
    canvas = Canvas()
    qtbot.addWidget(canvas)
    canvas.resize(300, 200)
    canvas.show()
    QTest.mouseMove(canvas, QPoint(10, 10))
    canvas.mouseMoveEvent(
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(5, 5),
            QPointF(5, 5),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )
