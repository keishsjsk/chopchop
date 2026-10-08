"""Выделение с фиксированными пропорциями (1:1, 16:9 …)."""

import pytest

from quickedit.core.geometry import Rect
from quickedit.core.selection import RectSelection


def _selection(
    width: float = 400, height: float = 300, aspect: float | None = None
) -> RectSelection:
    selection = RectSelection(width, height)
    selection.set_aspect(aspect)
    return selection


def _drag(sel: RectSelection, start: tuple[float, float], end: tuple[float, float]) -> None:
    sel.press(*start, 6.0)
    sel.drag(*end)
    sel.release()


def _ratio(rect: Rect | None) -> float:
    assert rect is not None
    return rect.w / rect.h


def test_select_all_covers_the_whole_frame() -> None:
    sel = _selection()
    sel.select_all()
    assert sel.rect == Rect(0, 0, 400, 300)


@pytest.mark.parametrize(
    ("aspect", "size"), [(1.0, (300, 300)), (2.0, (400, 200)), (0.5, (150, 300))]
)
def test_select_all_with_aspect_is_the_biggest_centered_area(
    aspect: float, size: tuple[float, float]
) -> None:
    sel = _selection(aspect=aspect)
    sel.select_all()
    rect = sel.rect
    assert rect is not None
    assert (rect.w, rect.h) == pytest.approx(size)
    assert (rect.x + rect.w / 2, rect.y + rect.h / 2) == pytest.approx((200, 150))


def test_changing_aspect_refits_the_current_area() -> None:
    sel = _selection()
    sel.select_all()
    sel.set_aspect(1.0)
    assert sel.rect == Rect(50, 0, 300, 300)
    sel.set_aspect(None)  # свободно: рамка остаётся как есть
    assert sel.rect == Rect(50, 0, 300, 300)


def test_new_selection_keeps_the_ratio_and_follows_the_longer_side() -> None:
    sel = _selection(aspect=2.0)
    _drag(sel, (50, 50), (250, 90))  # по ширине 200 → высота 100
    assert sel.rect == Rect(50, 50, 200, 100)
    _drag(
        sel, (300, 250), (330, 150)
    )  # вверх-вправо; по высоте 100 → ширина 200 не влезает (до края 100)
    rect = sel.rect
    assert rect is not None
    assert _ratio(rect) == pytest.approx(2.0)
    assert rect.right <= 400 and rect.y >= 0


def test_new_selection_never_leaves_the_frame() -> None:
    sel = _selection(aspect=1.0)
    _drag(sel, (300, 200), (900, 900))
    rect = sel.rect
    assert rect is not None
    assert _ratio(rect) == pytest.approx(1.0)
    assert rect.right <= 400 + 1e-6 and rect.bottom <= 300 + 1e-6
    assert (rect.x, rect.y) == (300, 200)  # неподвижный угол остался на месте


def test_corner_resize_fixes_the_opposite_corner() -> None:
    sel = _selection(aspect=1.0)
    sel.select_all()  # 300x300 по центру: (50, 0)-(350, 300)
    _drag(sel, (350, 300), (250, 280))  # правый нижний угол внутрь
    rect = sel.rect
    assert rect is not None
    assert (rect.x, rect.y) == pytest.approx((50, 0))
    assert _ratio(rect) == pytest.approx(1.0)
    assert rect.w < 300


def test_edge_resize_keeps_ratio_and_center_of_the_other_axis() -> None:
    sel = _selection(aspect=2.0)
    _drag(sel, (100, 100), (300, 200))  # область 200x100 по (100,100)
    assert sel.rect == Rect(100, 100, 200, 100)
    _drag(sel, (300, 150), (260, 150))  # правая сторона внутрь
    rect = sel.rect
    assert rect is not None
    assert (rect.x, rect.w) == pytest.approx((100, 160))
    assert rect.h == pytest.approx(80)
    assert rect.y + rect.h / 2 == pytest.approx(150)  # центр по высоте на месте


def test_edge_resize_is_limited_by_the_frame() -> None:
    sel = _selection(aspect=1.0)
    _drag(sel, (100, 100), (200, 200))  # квадрат 100x100
    _drag(sel, (200, 150), (900, 150))  # правая сторона далеко за кадр
    rect = sel.rect
    assert rect is not None
    assert _ratio(rect) == pytest.approx(1.0)
    assert rect.x >= 0 and rect.right <= 400 + 1e-6
    assert rect.y >= -1e-6 and rect.bottom <= 300 + 1e-6


def test_top_edge_resize() -> None:
    sel = _selection(aspect=1.0)
    _drag(sel, (100, 100), (200, 200))
    _drag(sel, (150, 100), (150, 60))  # верхняя сторона вверх
    rect = sel.rect
    assert rect is not None
    assert rect.bottom == pytest.approx(200)
    assert rect.h == pytest.approx(140)
    assert _ratio(rect) == pytest.approx(1.0)


def test_move_keeps_size_with_aspect() -> None:
    sel = _selection(aspect=1.0)
    _drag(sel, (100, 100), (200, 200))
    _drag(sel, (150, 150), (170, 160))
    assert sel.rect == Rect(120, 110, 100, 100)
