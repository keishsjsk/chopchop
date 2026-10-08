"""Выделение прямоугольной области мышью: новая область, перенос и растягивание за края."""

from quickedit.core.geometry import Rect, clamp

MIN_SIZE = 2.0


class RectSelection:
    def __init__(self, width: float = 0.0, height: float = 0.0) -> None:
        self.bounds = (width, height)
        self.rect: Rect | None = None
        self._mode: str | None = None  # "new", "move" или набор сторон из "ltrb"
        self._anchor = (0.0, 0.0)
        self._origin: Rect | None = None

    def set_bounds(self, width: float, height: float) -> None:
        self.bounds = (width, height)

    def clear(self) -> None:
        self.rect = None
        self._mode = None

    def _clamp_point(self, x: float, y: float) -> tuple[float, float]:
        return clamp(x, 0, self.bounds[0]), clamp(y, 0, self.bounds[1])

    def hit(self, x: float, y: float, tolerance: float) -> str | None:
        """Что под точкой: стороны ("l", "tr" ...), "move" или None."""
        rect = self.rect
        if rect is None:
            return None
        within_x = rect.x - tolerance <= x <= rect.right + tolerance
        within_y = rect.y - tolerance <= y <= rect.bottom + tolerance
        if not (within_x and within_y):
            return None
        sides = ""
        if abs(y - rect.y) <= tolerance:
            sides += "t"
        elif abs(y - rect.bottom) <= tolerance:
            sides += "b"
        if abs(x - rect.x) <= tolerance:
            sides += "l"
        elif abs(x - rect.right) <= tolerance:
            sides += "r"
        if sides:
            return sides
        return "move" if rect.contains(x, y) else None

    def press(self, x: float, y: float, tolerance: float = 6.0) -> None:
        hit = self.hit(x, y, tolerance)
        self._origin = self.rect
        self._anchor = (x, y)
        if hit is None:
            px, py = self._clamp_point(x, y)
            self._anchor = (px, py)
            self._mode = "new"
            self.rect = None
        else:
            self._mode = hit

    def drag(self, x: float, y: float) -> None:
        if self._mode is None:
            return
        px, py = self._clamp_point(x, y)
        if self._mode == "new":
            self.rect = Rect.from_points(*self._anchor, px, py)
        elif self._mode == "move" and self._origin is not None:
            origin = self._origin
            dx = clamp(x - self._anchor[0], -origin.x, self.bounds[0] - origin.right)
            dy = clamp(y - self._anchor[1], -origin.y, self.bounds[1] - origin.bottom)
            self.rect = Rect(origin.x + dx, origin.y + dy, origin.w, origin.h)
        elif self._origin is not None:
            origin = self._origin
            left, top, right, bottom = origin.x, origin.y, origin.right, origin.bottom
            if "l" in self._mode:
                left = px
            if "r" in self._mode:
                right = px
            if "t" in self._mode:
                top = py
            if "b" in self._mode:
                bottom = py
            self.rect = Rect.from_points(left, top, right, bottom)

    def release(self) -> None:
        self._mode = None
        if self.rect is not None and (self.rect.w < MIN_SIZE or self.rect.h < MIN_SIZE):
            self.rect = None  # случайный клик не создаёт область
