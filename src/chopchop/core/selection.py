"""Выделение прямоугольной области мышью: новая область, перенос и растягивание за края.

Можно зафиксировать пропорции (aspect = ширина / высота): тогда область растягивается,
сохраняя их, и не выходит за границы кадра.
"""

from chopchop.core.geometry import Rect, clamp

MIN_SIZE = 2.0


class RectSelection:
    def __init__(self, width: float = 0.0, height: float = 0.0) -> None:
        self.bounds = (width, height)
        self.rect: Rect | None = None
        self.aspect: float | None = None
        self._mode: str | None = None  # "new", "move" или набор сторон из "ltrb"
        self._anchor = (0.0, 0.0)
        self._origin: Rect | None = None

    def set_bounds(self, width: float, height: float) -> None:
        self.bounds = (width, height)

    def clear(self) -> None:
        self.rect = None
        self._mode = None

    # --- пропорции ---------------------------------------------------------------------------

    def set_aspect(self, aspect: float | None) -> None:
        """Зафиксировать пропорции (None — свободно); текущая область подгоняется под них."""
        self.aspect = aspect if aspect and aspect > 0 else None
        if self.rect is not None:
            self.rect = self._fit_inside(self.rect)

    def select_all(self) -> None:
        """Выделить весь кадр (с учётом пропорций — самую большую подходящую область)."""
        width, height = self.bounds
        self.rect = self._fit_inside(Rect(0, 0, width, height))

    def _fit_inside(self, rect: Rect) -> Rect:
        """Самая большая область нужных пропорций внутри rect, по его центру."""
        if self.aspect is None or rect.w <= 0 or rect.h <= 0:
            return rect
        if rect.w / rect.h > self.aspect:
            width, height = rect.h * self.aspect, rect.h
        else:
            width, height = rect.w, rect.w / self.aspect
        return Rect(rect.x + (rect.w - width) / 2, rect.y + (rect.h - height) / 2, width, height)

    # --- мышь --------------------------------------------------------------------------------

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
            self.rect = self._from_corner(self._anchor, px, py)
        elif self._mode == "move" and self._origin is not None:
            origin = self._origin
            dx = clamp(x - self._anchor[0], -origin.x, self.bounds[0] - origin.right)
            dy = clamp(y - self._anchor[1], -origin.y, self.bounds[1] - origin.bottom)
            self.rect = Rect(origin.x + dx, origin.y + dy, origin.w, origin.h)
        elif self._origin is not None:
            self.rect = self._resize(self._origin, self._mode, px, py)

    def release(self) -> None:
        self._mode = None
        if self.rect is not None and (self.rect.w < MIN_SIZE or self.rect.h < MIN_SIZE):
            self.rect = None  # случайный клик не создаёт область

    # --- растягивание ------------------------------------------------------------------------

    def _from_corner(self, anchor: tuple[float, float], px: float, py: float) -> Rect:
        """Область от неподвижного угла до указателя; с пропорциями — максимальная вдоль курсора."""
        ax, ay = anchor
        if self.aspect is None:
            return Rect.from_points(ax, ay, px, py)
        sign_x = 1.0 if px >= ax else -1.0
        sign_y = 1.0 if py >= ay else -1.0
        width, height = abs(px - ax), abs(py - ay)
        if width / self.aspect >= height:
            height = width / self.aspect
        else:
            width = height * self.aspect
        room_x = self.bounds[0] - ax if sign_x > 0 else ax
        room_y = self.bounds[1] - ay if sign_y > 0 else ay
        shrink = min(1.0, room_x / width if width else 1.0, room_y / height if height else 1.0)
        width, height = width * shrink, height * shrink
        return Rect.from_points(ax, ay, ax + sign_x * width, ay + sign_y * height)

    def _resize(self, origin: Rect, sides: str, px: float, py: float) -> Rect:
        horizontal = "l" in sides or "r" in sides
        vertical = "t" in sides or "b" in sides
        if self.aspect is not None and horizontal != vertical:
            return self._resize_edge(origin, sides, px, py)
        if self.aspect is not None:  # угол: противоположный угол неподвижен
            anchor = (
                origin.right if "l" in sides else origin.x,
                origin.bottom if "t" in sides else origin.y,
            )
            return self._from_corner(anchor, px, py)
        left, top, right, bottom = origin.x, origin.y, origin.right, origin.bottom
        if "l" in sides:
            left = px
        if "r" in sides:
            right = px
        if "t" in sides:
            top = py
        if "b" in sides:
            bottom = py
        return Rect.from_points(left, top, right, bottom)

    def _resize_edge(self, origin: Rect, side: str, px: float, py: float) -> Rect:
        """Тянем одну сторону при фиксированных пропорциях: другая ось растёт от центра."""
        assert self.aspect is not None
        bw, bh = self.bounds
        center_x, center_y = origin.x + origin.w / 2, origin.y + origin.h / 2
        if side in ("l", "r"):
            width = origin.right - px if side == "l" else px - origin.x
            room = bw - origin.x if side == "r" else origin.right
            width = clamp(
                width, MIN_SIZE, min(room, 2 * min(center_y, bh - center_y) * self.aspect)
            )
            height = width / self.aspect
            left = origin.right - width if side == "l" else origin.x
            return Rect(left, center_y - height / 2, width, height)
        height = origin.bottom - py if side == "t" else py - origin.y
        room = bh - origin.y if side == "b" else origin.bottom
        height = clamp(height, MIN_SIZE, min(room, 2 * min(center_x, bw - center_x) / self.aspect))
        width = height * self.aspect
        top = origin.bottom - height if side == "t" else origin.y
        return Rect(center_x - width / 2, top, width, height)
