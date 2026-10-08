import pytest
from pytestqt.qtbot import QtBot

from quickedit.core.geometry import Rect
from quickedit.core.operations import Crop
from quickedit.ui.crop_ratio import CropRatioBar
from quickedit.ui.tools.crop_tool import CropTool


def _tool(width: float = 400, height: float = 300) -> CropTool:
    tool = CropTool()
    tool.set_bounds(width, height)
    return tool


def test_select_all_gives_a_frame_that_changes_nothing_yet() -> None:
    tool = _tool()
    tool.select_all()
    assert tool.selection.rect == Rect(0, 0, 400, 300)
    assert tool.covers_frame()
    assert tool.pending_operation() is None


def test_partial_frame_becomes_a_crop() -> None:
    tool = _tool()
    tool.select_all()
    tool.press(400, 300, 6.0)
    tool.move(300, 200)
    tool.release(300, 200)
    assert not tool.covers_frame()
    assert tool.pending_operation() == Crop(Rect(0, 0, 300, 200))


def test_nearly_full_frame_is_still_full() -> None:
    tool = _tool()
    tool.selection.rect = Rect(0.2, 0.2, 399.5, 299.6)
    assert tool.pending_operation() is None


def test_fixed_ratio_refits_the_frame() -> None:
    tool = _tool()
    tool.select_all()
    tool.set_ratio(1.0)
    assert tool.selection.rect == Rect(50, 0, 300, 300)
    assert tool.aspect() == 1.0
    tool.set_ratio(None)
    assert tool.aspect() is None


def test_original_and_flipped_ratio_follow_the_frame_size() -> None:
    tool = _tool(400, 300)
    tool.set_ratio("original")
    assert tool.aspect() == pytest.approx(4 / 3)
    tool.set_ratio("original_flipped")
    assert tool.aspect() == pytest.approx(3 / 4)
    tool.set_bounds(800, 800)  # другой кадр — другие «исходные» пропорции
    tool.set_ratio("original")
    assert tool.aspect() == pytest.approx(1.0)


def test_ratio_bar_values_and_swap(qtbot: QtBot) -> None:
    bar = CropRatioBar()
    qtbot.addWidget(bar)
    values: list[object] = []
    bar.ratioChanged.connect(values.append)
    assert bar.value() is None
    assert not bar._swap.isEnabled()  # у свободных пропорций нечего поворачивать
    bar.set_value(16 / 9)
    assert bar.value() == pytest.approx(16 / 9)
    assert bar._swap.isEnabled()
    bar.swap()
    assert bar.value() == pytest.approx(9 / 16)
    assert values[-1] == pytest.approx(9 / 16)
    bar.set_value(1.0)
    bar.swap()
    assert bar.value() == 1.0


def test_ratio_bar_flips_the_original_ratio(qtbot: QtBot) -> None:
    bar = CropRatioBar()
    qtbot.addWidget(bar)
    bar.set_value("original")
    bar.swap()
    assert bar.value() == "original_flipped"
    assert "повёрнутое" in bar._combo.currentText()
    bar.swap()
    assert bar.value() == "original"
    assert bar._combo.currentText() == "Исходное"


def test_ratio_bar_offers_the_common_ratios(qtbot: QtBot) -> None:
    bar = CropRatioBar()
    qtbot.addWidget(bar)
    titles = [bar._combo.itemText(i) for i in range(bar._combo.count())]
    assert titles[:3] == ["Свободно", "Исходное", "1:1"]
    assert {"4:3", "3:2", "16:9", "9:16"} <= set(titles)
