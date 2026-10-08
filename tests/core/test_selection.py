import pytest

from chopchop.core.geometry import Rect
from chopchop.core.selection import RectSelection


def _drag(sel: RectSelection, start: tuple[float, float], end: tuple[float, float]) -> None:
    sel.press(*start)
    sel.drag(*end)
    sel.release()


def test_drag_creates_rect_in_any_direction() -> None:
    sel = RectSelection(100, 100)
    _drag(sel, (50, 60), (10, 20))
    assert sel.rect == Rect(10, 20, 40, 40)


def test_selection_is_clamped_to_bounds() -> None:
    sel = RectSelection(100, 80)
    _drag(sel, (50, 50), (500, -20))
    assert sel.rect == Rect(50, 0, 50, 50)


def test_plain_click_makes_no_selection() -> None:
    sel = RectSelection(100, 100)
    _drag(sel, (30, 30), (30, 30))
    assert sel.rect is None


def test_drag_inside_moves_without_resizing() -> None:
    sel = RectSelection(100, 100)
    _drag(sel, (10, 10), (40, 40))
    _drag(sel, (25, 25), (45, 35))
    assert sel.rect == Rect(30, 20, 30, 30)


def test_move_stops_at_bounds() -> None:
    sel = RectSelection(100, 100)
    _drag(sel, (10, 10), (40, 40))
    _drag(sel, (25, 25), (500, 25))
    assert sel.rect == Rect(70, 10, 30, 30)


def test_drag_edge_resizes_one_side() -> None:
    sel = RectSelection(100, 100)
    _drag(sel, (10, 10), (40, 40))
    _drag(sel, (40, 25), (70, 25))  # правый край
    assert sel.rect == Rect(10, 10, 60, 30)


def test_drag_corner_resizes_two_sides() -> None:
    sel = RectSelection(100, 100)
    _drag(sel, (10, 10), (40, 40))
    _drag(sel, (10, 10), (0, 5))  # левый верхний угол
    assert sel.rect == Rect(0, 5, 40, 35)


def test_dragging_edge_past_opposite_flips_rect() -> None:
    sel = RectSelection(100, 100)
    _drag(sel, (10, 10), (40, 40))
    _drag(sel, (10, 25), (60, 25))
    assert sel.rect == Rect(40, 10, 20, 30)


def test_press_outside_starts_new_selection() -> None:
    sel = RectSelection(100, 100)
    _drag(sel, (10, 10), (30, 30))
    _drag(sel, (60, 60), (80, 90))
    assert sel.rect == Rect(60, 60, 20, 30)


def test_hit_regions() -> None:
    sel = RectSelection(100, 100)
    _drag(sel, (10, 10), (50, 50))
    assert sel.hit(30, 30, 4) == "move"
    assert sel.hit(10, 30, 4) == "l"
    assert sel.hit(50, 50, 4) == "br"
    assert sel.hit(80, 80, 4) is None


def test_clear() -> None:
    sel = RectSelection(100, 100)
    _drag(sel, (10, 10), (50, 50))
    sel.clear()
    assert sel.rect is None
    sel.drag(20, 20)  # без нажатия ничего не происходит
    assert sel.rect is None


def test_bounds_can_change() -> None:
    sel = RectSelection(10, 10)
    sel.set_bounds(200, 200)
    _drag(sel, (0, 0), (150, 150))
    assert sel.rect == pytest.approx(Rect(0, 0, 150, 150))
