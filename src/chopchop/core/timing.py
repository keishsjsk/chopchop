"""Время показа текста и областей скрытия: пересчёт между временем итога и временем файлов.

Время показа хранится во времени итога (после вырезов и склейки). Плеер в редакторе показывает
исходный файл, поэтому для предпросмотра окно показа переводится во время файла (оно может
распасться на несколько кусков, если внутри есть вырез). При изменении вырезов времена
пересчитываются так, чтобы эффект остался на том же месте картинки.
"""

from dataclasses import dataclass, replace

from chopchop.core.operations import Redact, Text, is_timed
from chopchop.core.video import EPS, VideoProject

MIN_WINDOW = 0.04  # окно показа короче этого не видно ни в одном кадре


def clip_offset(project: VideoProject, clip_index: int) -> float:
    """Где в итоге начинается клип."""
    return sum(clip.length for clip in project.clips[:clip_index])


def result_windows_to_source(
    project: VideoProject, clip_index: int, show_from: float, show_to: float
) -> list[tuple[float, float]]:
    """Окно показа (время итога) в кусках времени исходного файла одного клипа."""
    clip = project.clips[clip_index]
    total = project.duration
    start = max(show_from, 0.0)
    stop = total if show_to < 0.0 else min(show_to, total)
    cursor = clip_offset(project, clip_index)
    windows: list[tuple[float, float]] = []
    for a, b in clip.ranges:
        piece_start, piece_stop = cursor, cursor + (b - a)
        low, high = max(start, piece_start), min(stop, piece_stop)
        if high - low > EPS:
            windows.append((a + (low - piece_start), a + (high - piece_start)))
        cursor = piece_stop
    return windows


def to_source(project: VideoProject, time: float, *, end: bool = False) -> tuple[int, float]:
    """Момент итога -> (клип, время файла); на стыке начало берёт следующий кусок, конец прежний."""
    cursor = 0.0
    last: tuple[int, float] = (0, 0.0)
    for index, clip in enumerate(project.clips):
        for a, b in clip.ranges:
            length = b - a
            inside = cursor < time < cursor + length
            at_start = abs(time - cursor) <= EPS and not end
            at_end = abs(time - (cursor + length)) <= EPS and end
            if inside:
                return index, a + (time - cursor)
            if at_start:
                return index, a
            if at_end:
                return index, b
            cursor += length
            last = (index, b)
    return last


def to_result(project: VideoProject, clip_index: int, source: float) -> float:
    return clip_offset(project, clip_index) + project.clips[clip_index].to_result(source)


@dataclass(frozen=True)
class TimeNote:
    """Что случилось со временем показа при правке: для сообщения пользователю."""

    kind: str  # collapsed: окно сжалось до нуля; clamped: пришлось обрезать по длине итога
    label: str  # название эффекта: текст или номер области


def _same_structure(old: VideoProject, new: VideoProject) -> bool:
    return len(old.clips) == len(new.clips) and all(
        a.path == b.path for a, b in zip(old.clips, new.clips, strict=True)
    )


def _remap(
    old: VideoProject, new: VideoProject, show_from: float, show_to: float
) -> tuple[float, float]:
    start = show_from
    if show_from > 0.0:
        index, source = to_source(old, show_from)
        start = to_result(new, index, source)
    stop = show_to
    if show_to >= 0.0:
        index, source = to_source(old, show_to, end=True)
        stop = to_result(new, index, source)
    return round(start, 3), round(stop, 3) if stop >= 0.0 else stop


def _clamp(new: VideoProject, show_from: float, show_to: float) -> tuple[float, float, bool]:
    total = new.duration
    start = min(show_from, total)
    stop = show_to if show_to < 0.0 else min(show_to, total)
    return start, stop, (start, stop) != (show_from, show_to)


def retime(old: VideoProject, new: VideoProject) -> tuple[VideoProject, list[TimeNote]]:
    """Подгоняет время показа под новые вырезы и обрезку; сообщает о том, что не получилось.

    Если клипы остались теми же и в том же порядке, эффект остаётся на том же месте картинки
    (его окно переводится через время файла). Если клипы добавлены, удалены или переставлены,
    сопоставить моменты нельзя: окна лишь обрезаются по длине итога, и об этом сообщается.
    """
    effects = new.effects
    timed: tuple[Redact | Text, ...] = (*effects.texts, *effects.redacts)
    if not any(is_timed(item) for item in timed):
        return new, []
    notes: list[TimeNote] = []
    structured = _same_structure(old, new)

    def fit(item: Redact | Text, label: str) -> Redact | Text:
        if not is_timed(item):
            return item
        if structured:
            start, stop = _remap(old, new, item.show_from, item.show_to)
        else:
            start, stop, changed = _clamp(new, item.show_from, item.show_to)
            if changed:
                notes.append(TimeNote("clamped", label))
        end = new.duration if stop < 0.0 else stop
        if end - start < MIN_WINDOW:
            notes.append(TimeNote("collapsed", label))
        return replace(item, show_from=start, show_to=stop)

    texts = tuple(
        fit(text, text.text.strip()[:20] or f"#{i + 1}") for i, text in enumerate(effects.texts)
    )
    redacts = tuple(fit(r, f"#{i + 1}") for i, r in enumerate(effects.redacts))
    fitted = replace(effects, texts=texts, redacts=redacts)  # type: ignore[arg-type]
    return replace(new, effects=fitted), notes
