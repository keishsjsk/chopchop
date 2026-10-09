import pytest
from pytestqt.qtbot import QtBot

from chopchop.core.operations import Annotate, Stroke
from chopchop.ui.tools.draw_tool import DrawTool


def _tool(shape: str = "pen") -> DrawTool:
    tool = DrawTool()
    tool.set_bounds(1500, 1000)
    tool.set_options(shape, (10, 200, 30), 4)  # type: ignore[arg-type]
    return tool


def test_pen_follows_the_mouse(qtbot: QtBot) -> None:
    tool = _tool("pen")
    finished: list[bool] = []
    tool.strokeFinished.connect(lambda: finished.append(True))
    tool.press(10, 10, 4.0)
    for step in range(1, 6):
        tool.move(10 + step * 20, 10 + (step % 2) * 40)  # зигзаг: точки не лежат на одной прямой
    tool.release(110, 10)
    op = tool.pending_operation()
    assert isinstance(op, Stroke)
    assert op.points[0] == (10, 10)
    assert len(op.points) >= 5
    assert op.opacity == 1.0
    assert op.color == (10, 200, 30)
    assert finished == [True]  # линию можно применять сразу, без Enter


def test_marker_is_wide_and_translucent() -> None:
    pen, marker = _tool("pen"), _tool("highlighter")
    for tool in (pen, marker):
        tool.press(0, 0, 4.0)
        tool.move(50, 50)
        tool.release(50, 50)
    pen_op, marker_op = pen.pending_operation(), marker.pending_operation()
    assert isinstance(pen_op, Stroke) and isinstance(marker_op, Stroke)
    assert marker_op.width == pytest.approx(pen_op.width * 3)
    assert 0 < marker_op.opacity < 1


def test_tiny_jitter_is_not_recorded() -> None:
    tool = _tool("pen")
    tool.press(100, 100, 4.0)
    tool.move(100.2, 100.1)
    tool.move(100.3, 100.2)
    tool.release(100.3, 100.2)
    op = tool.pending_operation()
    assert isinstance(op, Stroke)
    assert len(op.points) == 1  # только начальная точка


def test_a_click_draws_a_dot() -> None:
    tool = _tool("pen")
    tool.press(40, 40, 4.0)
    tool.release(40, 40)
    op = tool.pending_operation()
    assert isinstance(op, Stroke)
    assert op.points == ((40, 40),)


def test_moving_without_pressing_draws_nothing() -> None:
    tool = _tool("pen")
    tool.move(10, 10)
    tool.release(10, 10)
    assert tool.pending_operation() is None


def test_shapes_still_work_and_wait_for_enter() -> None:
    tool = _tool("arrow")
    finished: list[bool] = []
    tool.strokeFinished.connect(lambda: finished.append(True))
    tool.press(10, 10, 4.0)
    tool.move(100, 80)
    tool.release(100, 80)
    op = tool.pending_operation()
    assert isinstance(op, Annotate)
    assert (op.shape, op.start, op.end) == ("arrow", (10, 10), (100, 80))
    assert finished == []  # фигура ждёт подтверждения


def test_changing_shape_drops_the_unfinished_drawing() -> None:
    tool = _tool("arrow")
    tool.press(10, 10, 4.0)
    tool.move(100, 80)
    tool.release(100, 80)
    tool.set_options("pen", (255, 0, 0), 4)
    assert tool.pending_operation() is None


def test_reset_forgets_the_stroke() -> None:
    tool = _tool("pen")
    tool.press(10, 10, 4.0)
    tool.move(80, 80)
    tool.release(80, 80)
    tool.reset()
    assert tool.pending_operation() is None
