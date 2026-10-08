"""Граф фильтров ffmpeg для эффектов видео. Чистые функции: проверяются сравнением строк.

Один и тот же граф строит и экспорт, и превью в mpv, поэтому на экране то же, что и в файле.
"""

from pathlib import Path

from quickedit.core.operations import Adjust, Color, Redact, Text
from quickedit.core.video import VideoEffects

MIN_FONT = 8
SHADOW_ALPHA = "0.6"

_FILTERS: dict[str, str] = {
    "grayscale": "hue=s=0",
    "sepia": "colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131",
    "sharpen": "unsharp=5:5:1.0:5:5:0.0",
    "blur": "gblur=sigma=3",
}


def quote_path(path: Path) -> str:
    """Путь для значения опции фильтра: в одинарных кавычках, двоеточия экранированы."""
    text = path.as_posix().replace("\\", "/").replace(":", "\\:").replace("'", "'\\''")
    return f"'{text}'"


def hex_color(color: Color) -> str:
    r, g, b = color
    return f"0x{r:02X}{g:02X}{b:02X}"


def _even(value: int) -> int:
    return max(value - value % 2, 2)


def adjust_filter(adjust: Adjust) -> str:
    """eq: яркость сдвигается, остальное — множители; 1.0 у множителей означает «без изменений»."""
    brightness = (adjust.brightness - 1.0) * 0.4
    return (
        f"eq=brightness={brightness:.3f}:contrast={adjust.contrast:.3f}"
        f":saturation={adjust.saturation:.3f}:gamma={adjust.gamma:.3f}"
    )


def _text_filter(text: Text, textfile: Path, font: Path | None) -> str:
    parts = [
        f"textfile={quote_path(textfile)}",
        f"x={round(text.x)}",
        f"y={round(text.y)}",
        f"fontsize={max(round(text.size), MIN_FONT)}",
        f"fontcolor={hex_color(text.color)}",
        "borderw=2",
        f"bordercolor=black@{SHADOW_ALPHA}",
    ]
    if font is not None:
        parts.append(f"fontfile={quote_path(font)}")
    return "drawtext=" + ":".join(parts)


class _Graph:
    """Собирает цепочку фильтров; простые фильтры идут через запятую, составные — со split."""

    def __init__(self, in_label: str) -> None:
        self.parts: list[str] = []
        self._chain: list[str] = []
        self._current = in_label
        self._counter = 0

    def add(self, filter_text: str) -> None:
        self._chain.append(filter_text)

    def _next(self) -> str:
        self._counter += 1
        return f"s{self._counter}"

    def flush(self, final_label: str | None = None) -> None:
        if not self._chain and final_label is None:
            return
        if not self._chain and self.parts:
            # последним шёл составной фильтр: его выход сразу получает итоговую метку
            tail = f"[{self._current}]"
            self.parts[-1] = self.parts[-1][: -len(tail)] + f"[{final_label}]"
            self._current = str(final_label)
            return
        label = final_label or self._next()
        chain = ",".join(self._chain) or "null"
        self.parts.append(f"[{self._current}]{chain}[{label}]")
        self._current = label
        self._chain = []

    def add_region(self, region_filter: str, box: tuple[int, int, int, int]) -> None:
        """Применить фильтр только к области: вырезать копию, обработать и наложить обратно."""
        self.flush()
        left, top, right, bottom = box
        base, copy, patch, out = (f"{name}{self._counter + 1}" for name in ("a", "b", "r", "s"))
        self._counter += 1
        self.parts.append(f"[{self._current}]split[{base}][{copy}]")
        crop = f"crop={right - left}:{bottom - top}:{left}:{top}"
        self.parts.append(f"[{copy}]{crop},{region_filter}[{patch}]")
        self.parts.append(f"[{base}][{patch}]overlay={left}:{top}[{out}]")
        self._current = out

    def text(self) -> str:
        return ";".join(self.parts)


def _redact_filters(graph: _Graph, redact: Redact, size: tuple[int, int]) -> None:
    box = redact.rect.to_box(*size)
    if box is None:
        return
    left, top, right, bottom = box
    width, height = right - left, bottom - top
    if redact.mode == "fill":
        graph.add(
            f"drawbox=x={left}:y={top}:w={width}:h={height}:color={hex_color(redact.color)}:t=fill"
        )
    elif redact.mode == "blur":
        radius = max(1, min(round(redact.strength), min(width, height) // 4))
        graph.add_region(f"boxblur={radius}:2", box)
    else:
        block = max(2, round(redact.strength))
        small = f"scale={max(1, width // block)}:{max(1, height // block)}"
        graph.add_region(f"{small},scale={width}:{height}:flags=neighbor", box)


def build_effects_graph(
    effects: VideoEffects,
    size: tuple[int, int],
    textfiles: dict[int, Path],
    font: Path | None = None,
    *,
    geometry: bool = True,
    in_label: str = "in",
    out_label: str = "out",
) -> str:
    """Граф от метки in_label до out_label.

    geometry=False пропускает кадрирование, поворот и преобразование формата: превью в mpv
    показывает полный кадр, а рамки кадра рисуются поверх.
    """
    graph = _Graph(in_label)
    for redact in effects.redacts:
        _redact_filters(graph, redact, size)
    for index, text in enumerate(effects.texts):
        if text.text.strip() and index in textfiles:
            graph.add(_text_filter(text, textfiles[index], font))
    if not effects.adjust.is_identity:
        graph.add(adjust_filter(effects.adjust))
    if effects.filter:
        graph.add(_FILTERS[effects.filter])
    if geometry:
        if effects.crop is not None:
            box = effects.crop.to_box(*size)
            if box is not None:
                left, top, right, bottom = box
                graph.add(f"crop={_even(right - left)}:{_even(bottom - top)}:{left}:{top}")
        graph.add(_rotation_filters(effects))
    graph.flush(out_label)
    return graph.text()


def _rotation_filters(effects: VideoEffects) -> str:
    steps: list[str] = []
    if effects.rotation == 90:
        steps.append("transpose=1")
    elif effects.rotation == 270:
        steps.append("transpose=2")
    elif effects.rotation == 180:
        steps += ["hflip", "vflip"]
    if effects.flip_h:
        steps.append("hflip")
    if effects.flip_v:
        steps.append("vflip")
    steps.append("format=yuv420p")
    return ",".join(steps)


def output_frame_size(effects: VideoEffects, size: tuple[int, int]) -> tuple[int, int]:
    """Размер кадра результата после кадрирования и поворота."""
    width, height = size
    if effects.crop is not None:
        box = effects.crop.to_box(width, height)
        if box is not None:
            width, height = _even(box[2] - box[0]), _even(box[3] - box[1])
    if effects.rotation in (90, 270):
        width, height = height, width
    return width, height
