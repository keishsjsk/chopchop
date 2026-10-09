"""Прямоугольники и перевод координат. Чистый Python, без Qt."""

import math
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    @classmethod
    def from_points(cls, x0: float, y0: float, x1: float, y1: float) -> "Rect":
        """Прямоугольник по двум противоположным углам в любом порядке."""
        return cls(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h

    def scaled(self, factor: float) -> "Rect":
        return Rect(self.x * factor, self.y * factor, self.w * factor, self.h * factor)

    def contains(self, px: float, py: float) -> bool:
        return self.x <= px <= self.right and self.y <= py <= self.bottom

    def to_box(self, width: int, height: int) -> tuple[int, int, int, int] | None:
        """Целочисленная рамка (left, top, right, bottom) внутри картинки; None, если пуста."""
        left = min(max(round(self.x), 0), width)
        top = min(max(round(self.y), 0), height)
        right = min(max(round(self.right), 0), width)
        bottom = min(max(round(self.bottom), 0), height)
        if right <= left or bottom <= top:
            return None
        return left, top, right, bottom


def clamp(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


def simplify_path(
    points: Sequence[tuple[float, float]], tolerance: float
) -> tuple[tuple[float, float], ...]:
    """Рамер — Дуглас — Пекер: убирает точки, отклоняющиеся от линии меньше tolerance.

    Итеративная версия (стек вместо рекурсии): длинные штрихи не упираются в лимит глубины.
    Первая и последняя точки всегда остаются.
    """
    if len(points) < 3 or tolerance <= 0:
        return tuple(points)
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        (x0, y0), (x1, y1) = points[first], points[last]
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        farthest, index = 0.0, -1
        for i in range(first + 1, last):
            px, py = points[i]
            if length == 0:
                distance = math.hypot(px - x0, py - y0)
            else:
                distance = abs(dy * (px - x0) - dx * (py - y0)) / length
            if distance > farthest:
                farthest, index = distance, i
        if farthest > tolerance:
            keep[index] = True
            stack.append((first, index))
            stack.append((index, last))
    return tuple(p for p, kept in zip(points, keep, strict=True) if kept)
