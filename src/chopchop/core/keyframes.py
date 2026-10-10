"""Ключевые кадры и привязка быстрой резки к ним. Чистый Python, без Qt и ffmpeg.

При копировании потоков (без перекодирования) начать можно только с ключевого кадра: резка в
другой точке начинается с ближайшего ключевого кадра *до* неё. Здесь вычисляется, куда именно
привяжется каждое начало диапазона и где нужна точная резка (с перекодированием).
"""

from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from chopchop.core.video import VideoProject

SNAP_EPS = 0.001


def snap_back(keyframes: Sequence[float], time: float) -> float:
    """Ближайший ключевой кадр не позже указанного момента (без данных — сам момент)."""
    if not keyframes:
        return time
    index = bisect_right(keyframes, time + SNAP_EPS) - 1
    return keyframes[index] if index >= 0 else keyframes[0]


def needs_precise(keyframes: Sequence[float], time: float, frame: float) -> bool:
    """Начало не на ключевом кадре: при копировании оно сдвинется назад."""
    if not keyframes:
        return False  # ключевые кадры неизвестны: предупредить нечем
    return abs(snap_back(keyframes, time) - time) > frame / 2


@dataclass(frozen=True)
class Junction:
    """Начало одного диапазона итога и то, к чему оно привяжется при быстрой резке."""

    clip_index: int
    start: float  # где начало на самом деле
    snapped: float  # откуда начнётся копирование
    precise: bool  # здесь нужна точная резка

    @property
    def shift(self) -> float:
        return self.start - self.snapped


def junctions(project: VideoProject, keyframes: Mapping[Path, Sequence[float]]) -> list[Junction]:
    """Все начала диапазонов итога; у клипов без списка ключевых кадров привязки нет."""
    found: list[Junction] = []
    for flat in project.flat_ranges():
        clip = project.clips[flat.clip_index]
        frames = keyframes.get(clip.path, ())
        snapped = snap_back(frames, flat.start) if frames else flat.start
        precise = needs_precise(frames, flat.start, clip.frame)
        found.append(Junction(flat.clip_index, flat.start, snapped, precise))
    return found


def precise_count(project: VideoProject, keyframes: Mapping[Path, Sequence[float]]) -> int:
    return sum(1 for j in junctions(project, keyframes) if j.precise)
