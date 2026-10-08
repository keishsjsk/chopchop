from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtWidgets import QMessageBox
from pytestqt.qtbot import QtBot

from quickedit.core.operations import Adjust, Crop, Flip, Redact, Rotate, Text
from quickedit.editor.session import EditSession
from quickedit.ui.editor_page import EditorPage
from quickedit.ui.tools.adjust_tool import AdjustTool
from quickedit.ui.tools.crop_tool import CropTool
from quickedit.ui.tools.draw_tool import DrawTool
from quickedit.ui.tools.redact_tool import RedactTool
from quickedit.ui.tools.text_tool import TextTool


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
    assert list(page.session.history.operations) == [Rotate(90), Flip(True)]
    assert page._undo_button.isEnabled()
    assert "100×200" in page._info.text()
    page.undo()
    page.undo()
    assert not page._undo_button.isEnabled()
    assert page._redo_button.isEnabled()
    page.redo()
    assert list(page.session.history.operations) == [Rotate(90)]
    page.session.wait()


def test_crop_tool_applies_on_enter(qtbot: QtBot, tmp_path: Path) -> None:
    page = _page(qtbot, tmp_path)
    page.select_tool("crop")
    tool = page.tools["crop"]
    assert isinstance(tool, CropTool)
    _drag(tool, (20, 10), (120, 60))
    assert tool.pending_operation() is not None
    page.apply_pending()
    (op,) = page.session.history.operations
    assert isinstance(op, Crop)
    assert page.session.output_size() == (100, 50)
    assert tool.pending_operation() is None  # выделение сброшено
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
