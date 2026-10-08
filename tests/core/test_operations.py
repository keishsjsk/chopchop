import pytest

from chopchop.core.geometry import Rect
from chopchop.core.history import History
from chopchop.core.operations import (
    Adjust,
    Annotate,
    Crop,
    Filter,
    Flip,
    Operation,
    Redact,
    Resize,
    Rotate,
    Text,
    output_size,
    scale_operation,
)


def test_rect_from_points_is_order_independent() -> None:
    assert Rect.from_points(10, 20, 4, 8) == Rect(4, 8, 6, 12)


def test_rect_to_box_clamps_and_rejects_empty() -> None:
    assert Rect(-5, -5, 20, 20).to_box(10, 10) == (0, 0, 10, 10)
    assert Rect(2.4, 3.6, 4, 4).to_box(100, 100) == (2, 4, 6, 8)
    assert Rect(50, 50, 10, 10).to_box(20, 20) is None
    assert Rect(5, 5, 0, 10).to_box(20, 20) is None


def test_scale_geometry_operations() -> None:
    assert scale_operation(Crop(Rect(10, 20, 30, 40)), 2.0) == Crop(Rect(20, 40, 60, 80))
    redact = scale_operation(Redact(Rect(1, 2, 3, 4), "blur", 10.0), 0.5)
    assert redact == Redact(Rect(0.5, 1, 1.5, 2), "blur", 5.0)
    arrow = scale_operation(Annotate("arrow", (10, 10), (20, 30), width=4), 2.0)
    assert arrow == Annotate("arrow", (20, 20), (40, 60), width=8)
    assert scale_operation(Text("Hi", 10, 20, size=30), 0.5) == Text("Hi", 5, 10, size=15)
    assert scale_operation(Resize(100, 50), 0.1) == Resize(10, 5)
    assert scale_operation(Resize(2, 2), 0.1) == Resize(1, 1)


def test_scale_leaves_non_geometric_operations_alone() -> None:
    for op in (Rotate(90), Flip(True), Adjust(brightness=1.2), Filter("sepia")):
        assert scale_operation(op, 3.0) == op


def test_output_size_follows_operations() -> None:
    ops: list[Operation] = [Crop(Rect(0, 0, 100, 50)), Rotate(90), Resize(30, 60), Rotate(180)]
    assert output_size(ops[:1], (400, 300)) == (100, 50)
    assert output_size(ops[:2], (400, 300)) == (50, 100)
    assert output_size(ops, (400, 300)) == (30, 60)


def test_output_size_ignores_empty_crop() -> None:
    assert output_size([Crop(Rect(500, 500, 10, 10))], (400, 300)) == (400, 300)


def test_history_undo_redo() -> None:
    history = History()
    first, second = Rotate(90), Flip(True)
    history.push(first)
    history.push(second)
    assert history.operations == (first, second)
    assert history.undo() == second
    assert history.can_redo
    assert history.redo() == second
    assert history.operations == (first, second)


def test_new_operation_clears_redo() -> None:
    history = History()
    history.push(Rotate(90))
    history.undo()
    history.push(Flip(False))
    assert not history.can_redo
    assert history.redo() is None


def test_empty_history() -> None:
    history = History()
    assert not history.can_undo
    assert history.undo() is None
    assert len(history) == 0


def test_adjust_identity() -> None:
    assert Adjust().is_identity
    assert not Adjust(contrast=1.1).is_identity
    assert Adjust(gamma=2.0).gamma == pytest.approx(2.0)
