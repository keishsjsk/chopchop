"""Операции редактирования: неизменяемые описания, без Pillow и Qt.

Координаты хранятся в пикселях изображения в том состоянии, в каком оно было перед операцией.
"""

from dataclasses import dataclass, replace
from typing import Literal

from chopchop.core.geometry import Rect

Color = tuple[int, int, int]
Point = tuple[float, float]
RedactMode = Literal["blur", "pixelate", "fill"]
FilterName = Literal["grayscale", "sepia", "sharpen", "blur"]
Shape = Literal["arrow", "rect", "marker"]


@dataclass(frozen=True)
class Crop:
    rect: Rect


@dataclass(frozen=True)
class Rotate:
    degrees: Literal[90, 180, 270]  # по часовой стрелке


@dataclass(frozen=True)
class Flip:
    horizontal: bool  # True — слева направо, False — сверху вниз


@dataclass(frozen=True)
class Redact:
    rect: Rect
    mode: RedactMode = "fill"
    strength: float = 12.0  # радиус размытия или размер блока пикселизации, в пикселях
    color: Color = (0, 0, 0)


@dataclass(frozen=True)
class Adjust:
    brightness: float = 1.0
    contrast: float = 1.0
    saturation: float = 1.0
    gamma: float = 1.0

    @property
    def is_identity(self) -> bool:
        return (self.brightness, self.contrast, self.saturation, self.gamma) == (1.0,) * 4


@dataclass(frozen=True)
class Filter:
    name: FilterName


@dataclass(frozen=True)
class Annotate:
    shape: Shape
    start: Point
    end: Point
    color: Color = (255, 0, 0)
    width: float = 4.0


@dataclass(frozen=True)
class Stroke:
    """Линия, нарисованная мышью от руки: кисть (opacity 1) или маркер (полупрозрачный)."""

    points: tuple[Point, ...]
    color: Color = (255, 0, 0)
    width: float = 6.0
    opacity: float = 1.0


@dataclass(frozen=True)
class Text:
    text: str
    x: float
    y: float
    size: float = 32.0
    color: Color = (255, 255, 255)


@dataclass(frozen=True)
class Resize:
    width: int
    height: int


Operation = Crop | Rotate | Flip | Redact | Adjust | Filter | Annotate | Stroke | Text | Resize


def _scale_point(point: Point, factor: float) -> Point:
    return point[0] * factor, point[1] * factor


def scale_operation(op: Operation, factor: float) -> Operation:
    """Перевод геометрии операции в другой масштаб (из превью в полный размер и обратно)."""
    match op:
        case Crop(rect):
            return Crop(rect.scaled(factor))
        case Redact():
            return replace(op, rect=op.rect.scaled(factor), strength=op.strength * factor)
        case Annotate():
            return replace(
                op,
                start=_scale_point(op.start, factor),
                end=_scale_point(op.end, factor),
                width=op.width * factor,
            )
        case Stroke():
            points = tuple(_scale_point(point, factor) for point in op.points)
            return replace(op, points=points, width=op.width * factor)
        case Text():
            return replace(op, x=op.x * factor, y=op.y * factor, size=op.size * factor)
        case Resize():
            return Resize(max(1, round(op.width * factor)), max(1, round(op.height * factor)))
        case _:
            return op


def output_size(
    ops: list[Operation] | tuple[Operation, ...], size: tuple[int, int]
) -> tuple[int, int]:
    """Размер результата после всех операций, без обработки пикселей."""
    width, height = size
    for op in ops:
        match op:
            case Crop(rect):
                box = rect.to_box(width, height)
                if box is not None:
                    width, height = box[2] - box[0], box[3] - box[1]
            case Rotate(degrees) if degrees in (90, 270):
                width, height = height, width
            case Resize():
                width, height = op.width, op.height
    return width, height
