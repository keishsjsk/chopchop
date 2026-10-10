"""Время показа текста и областей скрытия: пересчёт при правке блоков.

Время показа хранится во времени итога (блоки подряд). Плеер редактора играет тот же итог (EDL),
поэтому для предпросмотра окно показа берётся как есть. При правке блоков (разрез, удаление,
перестановка, края) окно пересчитывается так, чтобы эффект остался на том же месте картинки:
концы окна «привязываются» к моментам исходных файлов, затем ищутся в новой раскладке.
"""

from dataclasses import dataclass, replace

from chopchop.core.operations import Redact, Text, is_timed
from chopchop.core.video import EPS, VideoProject

MIN_WINDOW = 0.04  # окно показа короче этого не видно ни в одном кадре


def clip_offset(project: VideoProject, clip_index: int) -> float:
    """Где в итоге начинается блок."""
    return sum(clip.length for clip in project.clips[:clip_index])


def to_source(project: VideoProject, time: float, *, end: bool = False) -> tuple[int, float]:
    """Момент итога -> (блок, время файла); на шве начало берёт следующий блок, конец прежний."""
    return project.locate(time, end=end)


def to_result(project: VideoProject, clip_index: int, source: float) -> float:
    """Момент файла внутри блока -> момент итога."""
    return clip_offset(project, clip_index) + project.clips[clip_index].to_result(source)


@dataclass(frozen=True)
class TimeNote:
    """Что случилось со временем показа при правке: для сообщения пользователю."""

    kind: str  # collapsed: окно сжалось до нуля; clamped: пришлось обрезать по длине итога
    label: str  # название эффекта: текст или номер области


def _find(project: VideoProject, path: object, source: float, *, end: bool) -> float | None:
    """Где в итоге момент файла `source`; None — этот момент больше не входит в итог."""
    offsets = project.offsets()
    for index, clip in enumerate(project.clips):
        if clip.path != path or not clip.contains(source):
            continue
        inside = clip.start + EPS < source < clip.stop - EPS
        at_start = abs(source - clip.start) <= EPS
        at_stop = abs(source - clip.stop) <= EPS
        # на шве между блоками начало окна идёт к следующему блоку, конец к предыдущему
        if inside or (at_start and not end) or (at_stop and end):
            return offsets[index] + (source - clip.start)
    return None


def _find_near(
    project: VideoProject, path: object, source: float, *, forward: bool
) -> float | None:
    """Ближайший уцелевший момент того же файла: следующий после `source` или предыдущий до него."""
    offsets = project.offsets()
    best: tuple[float, float] | None = None  # расстояние в файле и момент итога
    for index, clip in enumerate(project.clips):
        if clip.path != path:
            continue
        if forward and clip.stop > source:
            point = max(source, clip.start)
        elif not forward and clip.start < source:
            point = min(source, clip.stop)
        else:
            continue
        result = offsets[index] + (point - clip.start)
        if best is None or abs(point - source) < best[0]:
            best = (abs(point - source), result)
    return None if best is None else best[1]


def _remap(
    old: VideoProject, new: VideoProject, show_from: float, show_to: float
) -> tuple[float, float, bool]:
    """Окно показа в новой раскладке; третье значение — пришлось ли подгонять без привязки."""
    start, stop, guessed = show_from, show_to, False
    if show_from > 0.0:
        index, source = old.locate(show_from)
        found = _find(new, old.clips[index].path, source, end=False)
        if found is None:  # момент вырезан: окно начнётся с ближайшего уцелевшего после него
            found = _find_near(new, old.clips[index].path, source, forward=True)
        if found is None:
            guessed = True
            start = min(show_from, new.duration)
        else:
            start = found
    if show_to >= 0.0:
        index, source = old.locate(show_to, end=True)
        found = _find(new, old.clips[index].path, source, end=True)
        if found is None:  # окно кончится на ближайшем уцелевшем моменте до вырезанного
            found = _find_near(new, old.clips[index].path, source, forward=False)
        if found is None:
            guessed = True
            stop = min(show_to, new.duration)
        else:
            stop = found
    return round(start, 3), round(stop, 3) if stop >= 0.0 else stop, guessed


def map_position(old: VideoProject, new: VideoProject, time: float) -> float:
    """Где в новом итоге то же содержимое кадра, что было в старом на момент `time`.

    Если этого кадра больше нет (блок удалён или обрезан), позиция остаётся на месте в пределах
    новой длины.
    """
    time = min(max(time, 0.0), old.duration)
    index, source = old.locate(time)
    found = _find(new, old.clips[index].path, source, end=False)
    if found is None:
        found = _find(new, old.clips[index].path, source, end=True)
    return min(found if found is not None else time, new.duration)


def retime(old: VideoProject, new: VideoProject) -> tuple[VideoProject, list[TimeNote]]:
    """Подгоняет время показа под новые блоки; сообщает о том, что не получилось.

    Если моменты, к которым привязано окно, остались в итоге (даже на другом месте), эффект идёт за
    ними. Если блок с концом окна удалён, конец обрезается по длине итога, и об этом сообщается;
    если после перестановки конец оказался раньше начала, окно схлопывается.
    """
    effects = new.effects
    timed: tuple[Redact | Text, ...] = (*effects.texts, *effects.redacts)
    if not any(is_timed(item) for item in timed) or old.clips == new.clips:
        return new, []
    notes: list[TimeNote] = []

    def fit(item: Redact | Text, label: str) -> Redact | Text:
        if not is_timed(item):
            return item
        start, stop, guessed = _remap(old, new, item.show_from, item.show_to)
        if guessed:
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
