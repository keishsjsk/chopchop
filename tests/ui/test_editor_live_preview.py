"""Живой предпросмотр: движок работает в фоне и не чаще нужного, рамки рисуются на холсте."""

from pathlib import Path

import pytest
from PIL import Image
from pytestqt.qtbot import QtBot

from chopchop.core.operations import Adjust, Operation
from chopchop.editor.session import EditSession
from chopchop.engines.image_engine import apply_operation as real_apply
from chopchop.ui.editor_page import EditorPage
from chopchop.ui.tools.redact_tool import RedactTool


def _page(qtbot: QtBot, tmp_path: Path) -> EditorPage:
    path = tmp_path / "photo.png"
    Image.new("RGB", (200, 100), (100, 100, 100)).save(path)
    session = EditSession(path)
    with qtbot.waitSignal(session.loaded, timeout=10000):
        session.start()
    page = EditorPage(session)
    qtbot.addWidget(page)
    page.resize(900, 600)
    page.show()
    qtbot.waitExposed(page)
    return page


def _settle(qtbot: QtBot, page: EditorPage) -> None:
    qtbot.waitUntil(lambda: not page.is_busy(), timeout=10000)


def _count_applied(monkeypatch: pytest.MonkeyPatch) -> list[Operation]:
    applied: list[Operation] = []

    def counting(image: Image.Image, op: Operation) -> Image.Image:
        applied.append(op)
        return real_apply(image, op)

    monkeypatch.setattr("chopchop.editor.session.apply_operation", counting)
    return applied


def test_dragging_a_slider_renders_only_the_latest_value(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = _page(qtbot, tmp_path)
    page.select_tool("adjust")
    applied = _count_applied(monkeypatch)
    for value in range(5, 60, 5):  # быстрое движение ползунка, быстрее паузы перед расчётом
        page._sliders["brightness"].setValue(value)
    _settle(qtbot, page)
    assert applied[-1] == Adjust(brightness=1.55)
    assert len(applied) <= 3  # промежуточные значения пропущены, а не рассчитаны
    page.session.wait()


def test_applying_a_previewed_adjustment_does_not_recompute_it(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = _page(qtbot, tmp_path)
    page.select_tool("adjust")
    page._sliders["contrast"].setValue(40)
    _settle(qtbot, page)
    applied = _count_applied(monkeypatch)
    page.apply_pending()
    _settle(qtbot, page)
    assert applied == []  # результат взят из предпросмотра
    assert list(page.session.history.operations) == [Adjust(contrast=1.4)]
    assert page.session.modified
    page.session.wait()


def test_fill_redaction_is_painted_without_the_engine(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = _page(qtbot, tmp_path)
    page.select_tool("redact")
    tool = page.tools["redact"]
    assert isinstance(tool, RedactTool)
    applied = _count_applied(monkeypatch)
    tool.press(10, 10, 4.0)
    tool.move(80, 60)
    tool.release(80, 60)
    _settle(qtbot, page)
    assert applied == []  # заливку показывает холст, картинка не пересчитывалась
    assert not tool.live


def test_blur_redaction_uses_a_background_preview(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = _page(qtbot, tmp_path)
    page.select_tool("redact")
    page._redact_mode.setCurrentIndex(page._redact_mode.findData("blur"))
    tool = page.tools["redact"]
    assert isinstance(tool, RedactTool)
    assert tool.live
    applied = _count_applied(monkeypatch)
    tool.press(10, 10, 4.0)
    tool.move(80, 60)
    tool.release(80, 60)
    _settle(qtbot, page)
    assert [type(op).__name__ for op in applied] == ["Redact"]
    page.session.wait()


def test_page_stays_idle_when_nothing_changes(qtbot: QtBot, tmp_path: Path) -> None:
    page = _page(qtbot, tmp_path)
    _settle(qtbot, page)
    qtbot.wait(60)
    assert not page.is_busy()  # сам по себе ничего не пересчитывает
    page.session.wait()
