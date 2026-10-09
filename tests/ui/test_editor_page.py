from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtWidgets import QMessageBox
from pytestqt.qtbot import QtBot

from chopchop.core.geometry import Rect
from chopchop.core.operations import Adjust, Crop, Flip, Redact, Rotate, Text
from chopchop.editor.session import EditSession
from chopchop.ui.editor_page import EditorPage
from chopchop.ui.tools.adjust_tool import AdjustTool
from chopchop.ui.tools.crop_tool import CropTool
from chopchop.ui.tools.draw_tool import DrawTool
from chopchop.ui.tools.redact_tool import RedactTool
from chopchop.ui.tools.text_tool import TextTool


def _page(qtbot: QtBot, tmp_path: Path, size: tuple[int, int] = (200, 100)) -> EditorPage:
    path = tmp_path / "photo.png"
    Image.new("RGB", size, (255, 0, 0)).save(path)
    session = EditSession(path)
    with qtbot.waitSignal(session.loaded, timeout=10000):
        session.start()
    page = EditorPage(session)
    qtbot.addWidget(page)
    page.resize(900, 600)
    page.show()
    return page


def _settle(qtbot: QtBot, page: EditorPage) -> None:
    """Превью считается в фоне: ждём, пока страница закончит."""
    qtbot.waitUntil(lambda: not page.is_busy(), timeout=10000)


def _drag(
    tool: CropTool | RedactTool | DrawTool, a: tuple[float, float], b: tuple[float, float]
) -> None:
    tool.press(*a, 4.0)
    tool.move(*b)
    tool.release(*b)


def test_rotate_and_flip_buttons_add_operations(qtbot: QtBot, tmp_path: Path) -> None:
    page = _page(qtbot, tmp_path)
    assert not page._undo_button.isEnabled()
    page.session.add_full(Rotate(90))
    page.session.add_full(Flip(True))
    _settle(qtbot, page)
    assert list(page.session.history.operations) == [Rotate(90), Flip(True)]
    assert page._undo_button.isEnabled()
    assert "100×200" in page._info.text()
    page.undo()
    page.undo()
    assert not page._undo_button.isEnabled()
    assert page._redo_button.isEnabled()
    page.redo()
    _settle(qtbot, page)
    assert list(page.session.history.operations) == [Rotate(90)]
    page.session.wait()


def test_crop_tool_applies_on_enter(qtbot: QtBot, tmp_path: Path) -> None:
    page = _page(qtbot, tmp_path)
    page.select_tool("crop")
    tool = page.tools["crop"]
    assert isinstance(tool, CropTool)
    assert tool.selection.rect is not None  # рамка сразу по всему кадру
    assert tool.pending_operation() is None  # но пока она кадр не меняет
    _drag(tool, (200, 100), (120, 60))  # тянем правый нижний угол
    assert tool.pending_operation() is not None
    page.apply_pending()
    _settle(qtbot, page)
    (op,) = page.session.history.operations
    assert isinstance(op, Crop)
    assert page.session.output_size() == (120, 60)
    assert tool.selection.rect is not None  # после обрезки рамка снова охватывает кадр
    assert tool.pending_operation() is None
    page.session.wait()


def test_apply_without_selection_explains_what_to_do(qtbot: QtBot, tmp_path: Path) -> None:
    page = _page(qtbot, tmp_path)
    messages: list[str] = []
    page.message.connect(messages.append)
    page.select_tool("crop")
    page.apply_pending()
    assert messages
    assert len(page.session.history) == 0
    page.session.wait()


def test_redact_defaults_to_fill_and_shows_hint_for_blur(qtbot: QtBot, tmp_path: Path) -> None:
    page = _page(qtbot, tmp_path)
    page.select_tool("redact")
    tool = page.tools["redact"]
    assert isinstance(tool, RedactTool)
    assert tool.mode == "fill"
    assert not page._redact_hint.isVisible()
    page._redact_mode.setCurrentIndex(page._redact_mode.findData("blur"))
    assert str(tool.mode) == "blur"
    assert page._redact_hint.isVisibleTo(page)
    page._redact_mode.setCurrentIndex(page._redact_mode.findData("fill"))
    _drag(tool, (10, 10), (50, 40))
    page.apply_pending()
    _settle(qtbot, page)
    (op,) = page.session.history.operations
    assert isinstance(op, Redact)
    assert op.mode == "fill"
    assert page.session.preview().getpixel((20, 20)) == (0, 0, 0)
    page.session.wait()


def test_live_preview_does_not_touch_history(qtbot: QtBot, tmp_path: Path) -> None:
    page = _page(qtbot, tmp_path)
    page.select_tool("redact")
    tool = page.tools["redact"]
    assert isinstance(tool, RedactTool)
    _drag(tool, (10, 10), (50, 40))
    page._update_canvas()
    _settle(qtbot, page)
    assert len(page.session.history) == 0
    page.escape()  # отменяет незавершённое действие, из редактора не выходит
    assert tool.pending_operation() is None
    page.session.wait()


def test_escape_exits_when_nothing_pending(qtbot: QtBot, tmp_path: Path) -> None:
    page = _page(qtbot, tmp_path)
    with qtbot.waitSignal(page.exitRequested, timeout=2000):
        page.escape()
    page.session.wait()


def test_exit_asks_about_unsaved_changes(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = _page(qtbot, tmp_path)
    page.session.add_full(Flip(True))
    asked: list[bool] = []

    def fake_exec(box: QMessageBox) -> int:
        asked.append(True)
        discard = [b for b in box.buttons() if b.text() == "Не сохранять"][0]
        monkeypatch.setattr(QMessageBox, "clickedButton", lambda _self: discard)
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    with qtbot.waitSignal(page.exitRequested, timeout=2000):
        page.request_exit()
    assert asked
    page.session.wait()


def test_draw_tool_makes_annotation(qtbot: QtBot, tmp_path: Path) -> None:
    page = _page(qtbot, tmp_path)
    page.select_tool("draw")
    tool = page.tools["draw"]
    assert isinstance(tool, DrawTool)
    page._shape.setCurrentIndex(page._shape.findData("rect"))
    _drag(tool, (20, 20), (80, 60))
    page.apply_pending()
    (op,) = page.session.history.operations
    assert op.shape == "rect"  # type: ignore[union-attr]
    page.session.wait()


def test_text_tool_places_text_where_clicked(qtbot: QtBot, tmp_path: Path) -> None:
    page = _page(qtbot, tmp_path)
    page.select_tool("text")
    tool = page.tools["text"]
    assert isinstance(tool, TextTool)
    assert tool.pending_operation() is None  # пустой текст применять нечего
    page._text.setText("Привет")
    tool.press(30, 40, 4.0)
    page.apply_pending()
    (op,) = page.session.history.operations
    assert isinstance(op, Text)
    assert (op.text, op.x, op.y) == ("Привет", 30, 40)
    assert op.size == pytest.approx(6.0)  # 6% от высоты 100
    page.session.wait()


def test_adjust_sliders_and_reset(qtbot: QtBot, tmp_path: Path) -> None:
    page = _page(qtbot, tmp_path)
    page.select_tool("adjust")
    tool = page.tools["adjust"]
    assert isinstance(tool, AdjustTool)
    assert tool.pending_operation() is None
    page._sliders["brightness"].setValue(50)
    assert tool.pending_operation() == Adjust(brightness=1.5)
    page.apply_pending()
    assert list(page.session.history.operations) == [Adjust(brightness=1.5)]
    assert all(slider.value() == 0 for slider in page._sliders.values())
    assert tool.pending_operation() is None
    page.session.wait()


def test_filter_buttons_add_operations(qtbot: QtBot, tmp_path: Path) -> None:
    page = _page(qtbot, tmp_path)
    page.select_tool("adjust")
    from PySide6.QtWidgets import QPushButton

    sepia = [b for b in page.findChildren(QPushButton) if b.text() == "Сепия"][0]
    sepia.click()
    assert len(page.session.history) == 1
    page.session.wait()


def test_resize_keeps_aspect_ratio(qtbot: QtBot, tmp_path: Path) -> None:
    page = _page(qtbot, tmp_path)
    page._width.setValue(100)
    assert page._height.value() == 50
    page._apply_resize()
    assert page.session.output_size() == (100, 50)
    page.session.wait()


def test_quick_save_writes_new_file_next_to_source(qtbot: QtBot, tmp_path: Path) -> None:
    page = _page(qtbot, tmp_path)
    page.session.add_full(Flip(True))
    with qtbot.waitSignal(page.session.exported, timeout=10000):
        page.save_quick()
    assert (tmp_path / "photo_edited.png").exists()
    assert "*" not in page._info.text()  # правки сохранены
    page.session.add_full(Flip(False))
    with qtbot.waitSignal(page.session.exported, timeout=10000):
        page.save_quick()
    assert (tmp_path / "photo_edited (2).png").exists()  # старый результат не перезаписан
    page.session.wait()


def test_copy_puts_result_on_clipboard(qtbot: QtBot, tmp_path: Path) -> None:
    from PySide6.QtWidgets import QApplication

    page = _page(qtbot, tmp_path)
    page.session.add_full(Rotate(90))
    messages: list[str] = []
    page.message.connect(messages.append)
    page.copy_result()
    qtbot.waitUntil(lambda: any("буфер" in m for m in messages), timeout=10000)
    image = QApplication.clipboard().image()
    assert (image.width(), image.height()) == (100, 200)
    page.session.wait()


def test_crop_starts_with_the_whole_frame_selected(qtbot: QtBot, tmp_path: Path) -> None:
    page = _page(qtbot, tmp_path)
    page.select_tool("crop")
    tool = page.tools["crop"]
    assert isinstance(tool, CropTool)
    assert tool.selection.rect == Rect(0, 0, 200, 100)
    messages: list[str] = []
    page.message.connect(messages.append)
    page.apply_pending()  # рамка по всему кадру ничего не обрезает
    assert messages
    assert len(page.session.history) == 0
    page.session.wait()


def test_crop_ratio_selector_reshapes_the_frame(qtbot: QtBot, tmp_path: Path) -> None:
    page = _page(qtbot, tmp_path)
    page.select_tool("crop")
    tool = page.tools["crop"]
    assert isinstance(tool, CropTool)
    page._ratio_bar.set_value(1.0)
    assert tool.selection.rect == Rect(50, 0, 100, 100)
    page.apply_pending()
    _settle(qtbot, page)
    assert page.session.output_size() == (100, 100)
    assert tool.selection.rect == Rect(0, 0, 100, 100)  # рамка снова по всему новому кадру
    page._ratio_bar.swap()  # квадрат остаётся квадратом
    assert page._ratio_bar.value() == 1.0
    page.session.wait()


def test_crop_ratio_16_9_then_swap(qtbot: QtBot, tmp_path: Path) -> None:
    page = _page(qtbot, tmp_path, (160, 90))
    page.select_tool("crop")
    tool = page.tools["crop"]
    assert isinstance(tool, CropTool)
    page._ratio_bar.set_value(16 / 9)
    rect = tool.selection.rect
    assert rect is not None and rect.w == pytest.approx(160)
    page._ratio_bar.swap()
    rect = tool.selection.rect
    assert rect is not None
    assert rect.w / rect.h == pytest.approx(9 / 16)
    page.session.wait()


def test_brush_draws_with_the_mouse_and_applies_on_release(qtbot: QtBot, tmp_path: Path) -> None:
    from chopchop.core.operations import Stroke

    page = _page(qtbot, tmp_path)
    page.select_tool("draw")
    page._shape.setCurrentIndex(page._shape.findData("pen"))
    tool = page.tools["draw"]
    assert isinstance(tool, DrawTool)
    tool.press(20, 20, 4.0)
    for step in range(1, 8):
        tool.move(20 + step * 10, 20 + (step % 2) * 30)  # зигзаг не схлопывается при упрощении
    assert len(page.session.history) == 0  # пока кнопка зажата — ещё не применено
    tool.release(90, 20)
    _settle(qtbot, page)
    (op,) = page.session.history.operations
    assert isinstance(op, Stroke)
    assert len(op.points) >= 5
    tool.press(20, 80, 4.0)  # можно сразу рисовать дальше
    tool.move(120, 80)
    tool.release(120, 80)
    _settle(qtbot, page)
    assert len(page.session.history) == 2
    page.session.wait()


def test_marker_option_is_translucent(qtbot: QtBot, tmp_path: Path) -> None:
    from chopchop.core.operations import Stroke

    page = _page(qtbot, tmp_path)
    page.select_tool("draw")
    page._shape.setCurrentIndex(page._shape.findData("highlighter"))
    tool = page.tools["draw"]
    tool.press(20, 20, 4.0)
    tool.move(100, 20)
    tool.release(100, 20)
    (op,) = page.session.history.operations
    assert isinstance(op, Stroke)
    assert op.opacity < 1
    page.session.wait()


def test_draw_panel_lists_freehand_tools_first(qtbot: QtBot, tmp_path: Path) -> None:
    page = _page(qtbot, tmp_path)
    titles = [page._shape.itemText(i) for i in range(page._shape.count())]
    assert titles[0].startswith("Кисть")
    assert titles[1].startswith("Маркер")
    assert {"Стрелка", "Рамка", "Выделение области"} <= set(titles)
    page.session.wait()
