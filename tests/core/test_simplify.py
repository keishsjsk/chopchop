import math

from chopchop.core.geometry import simplify_path


def test_straight_line_collapses_to_endpoints() -> None:
    points = [(float(i), 2.0 * i) for i in range(50)]
    assert simplify_path(points, 0.5) == (points[0], points[-1])


def test_corner_is_kept() -> None:
    points = [(float(i), 0.0) for i in range(10)] + [(9.0, float(i)) for i in range(1, 10)]
    simplified = simplify_path(points, 0.5)
    assert simplified == ((0.0, 0.0), (9.0, 0.0), (9.0, 9.0))


def test_result_stays_within_tolerance_of_the_original() -> None:
    points = [(i * 0.5, 10 * math.sin(i / 8)) for i in range(400)]
    simplified = simplify_path(points, 0.3)
    assert len(simplified) < len(points) / 3
    for px, py in points:  # любая исходная точка близка к упрощённой ломаной
        assert (
            min(
                _distance_to_segment(px, py, a, b)
                for a, b in zip(simplified, simplified[1:], strict=False)
            )
            <= 0.31
        )


def test_short_paths_and_zero_tolerance_are_unchanged() -> None:
    assert simplify_path([(0.0, 0.0), (1.0, 1.0)], 5) == ((0.0, 0.0), (1.0, 1.0))
    line = [(0.0, 0.0), (1.0, 0.1), (2.0, 0.0)]
    assert simplify_path(line, 0) == tuple(line)


def test_very_long_path_does_not_hit_recursion_limit() -> None:
    zigzag = [(float(i), float(i % 2) * 5) for i in range(3000)]
    assert len(simplify_path(zigzag, 1.0)) > 100


def _distance_to_segment(
    px: float, py: float, a: tuple[float, float], b: tuple[float, float]
) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))
