"""Проект видеомонтажа: клипы с обрезкой, настройки звука, история. Чистый Python, без Qt."""

from dataclasses import dataclass, replace
from pathlib import Path

from chopchop.core.document import MediaInfo
from chopchop.core.geometry import Rect
from chopchop.core.operations import Adjust, FilterName, Redact, Text

MIN_CLIP_SECONDS = 0.1
MAX_VOLUME = 2.0
FPS_TOLERANCE = 0.01


Range = tuple[float, float]
EPS = 0.0005
DEFAULT_FRAME = 0.04


def _merge(ranges: list[Range]) -> list[Range]:
    """Отсортировать диапазоны и объединить соседние и пересекающиеся."""
    merged: list[Range] = []
    for start, stop in sorted(ranges):
        if merged and start <= merged[-1][1] + EPS:
            merged[-1] = (merged[-1][0], max(merged[-1][1], stop))
        else:
            merged.append((start, stop))
    return merged


def _subtract(ranges: list[Range], start: float, stop: float) -> list[Range]:
    result: list[Range] = []
    for a, b in ranges:
        if b <= start or a >= stop:
            result.append((a, b))
            continue
        if a < start:
            result.append((a, start))
        if b > stop:
            result.append((stop, b))
    return result


@dataclass(frozen=True)
class Clip:
    """Клип: исходный файл и то, что от него оставлено.

    Оставленное — это внешние границы (`start`, `end`) минус вырезанные куски (`cuts`). Один
    диапазон без вырезов — это прежняя обрезка. `splits` — метки разрезов внутри оставленного:
    они дают границы сегментов для выбора и удаления, на результат без удаления не влияют.
    """

    path: Path
    info: MediaInfo
    start: float = 0.0
    end: float = -1.0  # отрицательное значение — до конца файла
    cuts: tuple[Range, ...] = ()
    splits: tuple[float, ...] = ()

    @property
    def stop(self) -> float:
        return self.info.duration if self.end < 0 else min(self.end, self.info.duration)

    @property
    def frame(self) -> float:
        """Длительность одного кадра: меньше оставленный диапазон быть не может."""
        fps = self.info.fps
        return 1.0 / fps if fps > 0 else DEFAULT_FRAME

    @property
    def ranges(self) -> tuple[Range, ...]:
        """Оставленные диапазоны в исходном времени, по порядку."""
        kept: list[Range] = [(self.start, self.stop)]
        for a, b in self.cuts:
            kept = _subtract(kept, a, b)
        return tuple(kept)

    @property
    def length(self) -> float:
        return sum(b - a for a, b in self.ranges)

    @property
    def has_cuts(self) -> bool:
        return bool(self.cuts)

    @property
    def is_trimmed(self) -> bool:
        return self.start > EPS or self.stop < self.info.duration - EPS or self.has_cuts

    def segments(self) -> tuple[Range, ...]:
        """Оставленное, разделённое метками разрезов: то, что можно выбрать и удалить."""
        pieces: list[Range] = []
        for a, b in self.ranges:
            points = [s for s in self.splits if a < s < b]
            edges = [a, *sorted(points), b]
            pieces += list(zip(edges[:-1], edges[1:], strict=True))
        return tuple(pieces)

    def ghosts(self) -> tuple[Range, ...]:
        """Удалённые участки (вместе с обрезанными краями): их показывают «призраками»."""
        gaps: list[Range] = []
        cursor = 0.0
        for a, b in self.ranges:
            if a - cursor > EPS:
                gaps.append((cursor, a))
            cursor = b
        if self.info.duration - cursor > EPS:
            gaps.append((cursor, self.info.duration))
        return tuple(gaps)

    def to_result(self, source: float) -> float:
        """Время в итоговом ролике для момента исходного файла (внутри оставленного)."""
        total = 0.0
        for a, b in self.ranges:
            if source >= b:
                total += b - a
            elif source > a:
                return total + (source - a)
        return total

    def with_trim(self, start: float, end: float) -> "Clip":
        """Новые внешние границы; вырезы внутри них остаются. Границы приводятся к допустимым."""
        duration = self.info.duration
        start = min(max(start, 0.0), max(duration - MIN_CLIP_SECONDS, 0.0))
        end = min(max(end, start + MIN_CLIP_SECONDS), duration)
        stored_end = -1.0 if end >= duration - EPS else end
        cuts = tuple((max(a, start), min(b, end)) for a, b in self.cuts if b > start and a < end)
        candidate = replace(self, start=start, end=stored_end, cuts=cuts)
        if not candidate.ranges:  # вырезы съели всё: оставляем только границы
            candidate = replace(candidate, cuts=())
        return candidate._clean_splits()

    def reset(self) -> "Clip":
        """Вернуть клип целиком: без обрезки, вырезов и разрезов."""
        return replace(self, start=0.0, end=-1.0, cuts=(), splits=())

    # --- разрезы и вырезы --------------------------------------------------------------------

    def _from_ranges(self, ranges: list[Range]) -> "Clip":
        """Клип с таким оставленным; куски короче кадра пропадают, соседние склеиваются."""
        kept = [(a, b) for a, b in _merge(ranges) if b - a >= self.frame - EPS]
        if not kept:
            return self
        duration = self.info.duration
        start, stop = kept[0][0], kept[-1][1]
        cuts = tuple((kept[i][1], kept[i + 1][0]) for i in range(len(kept) - 1))
        end = -1.0 if stop >= duration - EPS else stop
        return replace(self, start=max(start, 0.0), end=end, cuts=cuts)._clean_splits()

    def _clean_splits(self) -> "Clip":
        """Оставить только метки внутри оставленного и не ближе кадра друг к другу и к краям."""
        kept: list[float] = []
        for s in sorted(self.splits):
            inside = any(a + self.frame <= s <= b - self.frame for a, b in self.ranges)
            apart = all(abs(s - other) >= self.frame for other in kept)
            if inside and apart:
                kept.append(s)
        return replace(self, splits=tuple(kept))

    def split_at(self, time: float) -> "Clip":
        """Разрезать в указанный момент: появляются два сегмента, ничего не удаляется."""
        candidate = replace(self, splits=(*self.splits, time))._clean_splits()
        return candidate if len(candidate.splits) > len(self.splits) else self

    def remove_span(self, start: float, stop: float) -> "Clip":
        """Вырезать участок с удалением паузы: остаток встаёт вплотную. Всё удалить нельзя."""
        if stop - start < self.frame / 2:
            return self  # короче половины кадра: вырезать нечего
        remaining = _subtract(list(self.ranges), start, stop)
        if not [r for r in remaining if r[1] - r[0] >= self.frame - EPS]:
            return self
        return self._from_ranges(remaining)

    def restore_span(self, start: float, stop: float) -> "Clip":
        """Вернуть удалённый участок (клик по призраку)."""
        start, stop = max(start, 0.0), min(stop, self.info.duration)
        if stop - start < EPS:
            return self
        return self._from_ranges([*self.ranges, (start, stop)])


@dataclass(frozen=True)
class FlatRange:
    """Один оставленный диапазон итога склейки: из какого клипа и какой кусок исходного файла."""

    clip_index: int
    start: float
    stop: float

    @property
    def length(self) -> float:
        return self.stop - self.start


@dataclass(frozen=True)
class AudioSettings:
    volume: float = 1.0  # 1.0 — как в исходнике, до 2.0
    mute: bool = False
    replacement: Path | None = None  # свой аудиофайл вместо исходного звука

    @property
    def is_default(self) -> bool:
        return self.volume == 1.0 and not self.mute and self.replacement is None


@dataclass(frozen=True)
class VideoEffects:
    """Эффекты на весь итоговый ролик. Координаты — в пикселях кадра `VideoProject.frame_size`.

    Порядок при обработке фиксирован: скрытие областей, текст, цветокоррекция, фильтр, затем кадр
    и в самом конце поворот. Поэтому всё, что рисуется поверх превью, совпадает с результатом.
    """

    crop: Rect | None = None
    redacts: tuple[Redact, ...] = ()
    texts: tuple[Text, ...] = ()
    adjust: Adjust = Adjust()
    filter: FilterName | None = None
    rotation: int = 0  # по часовой стрелке: 0, 90, 180, 270
    flip_h: bool = False
    flip_v: bool = False

    @property
    def is_default(self) -> bool:
        return self == VideoEffects()

    @property
    def has_picture_effects(self) -> bool:
        """Есть ли эффекты, меняющие картинку (кроме поворота и кадра)."""
        return bool(self.redacts or self.texts or not self.adjust.is_identity or self.filter)

    def describe(self) -> list[str]:
        """Краткий список применённых эффектов для подписи в интерфейсе."""
        parts: list[str] = []
        if self.crop is not None:
            parts.append("кадр")
        if self.redacts:
            parts.append(f"скрытия: {len(self.redacts)}")
        if self.texts:
            parts.append(f"текст: {len(self.texts)}")
        if not self.adjust.is_identity:
            parts.append("цвет")
        if self.filter:
            parts.append("фильтр")
        if self.rotation:
            parts.append(f"поворот {self.rotation}°")
        if self.flip_h or self.flip_v:
            parts.append("отражение")
        return parts


@dataclass(frozen=True)
class EffectEntry:
    """Один применённый эффект для списка в интерфейсе: вид и номер (для скрытий и текстов)."""

    kind: str  # crop, redact, text, adjust, filter, rotation, flip
    index: int = 0

    @property
    def tool(self) -> str:
        """Пункт рейки редактора, к которому относится эффект."""
        return TOOL_OF_EFFECT[self.kind]


TOOL_OF_EFFECT = {
    "crop": "crop",
    "redact": "redact",
    "text": "text",
    "adjust": "adjust",
    "filter": "adjust",
    "rotation": "rotate",
    "flip": "rotate",
}


def effect_entries(effects: VideoEffects) -> list[EffectEntry]:
    """Применённые эффекты по порядку обработки; пустой список — «без эффектов»."""
    entries: list[EffectEntry] = []
    if effects.crop is not None:
        entries.append(EffectEntry("crop"))
    entries += [EffectEntry("redact", i) for i in range(len(effects.redacts))]
    entries += [EffectEntry("text", i) for i in range(len(effects.texts))]
    if not effects.adjust.is_identity:
        entries.append(EffectEntry("adjust"))
    if effects.filter:
        entries.append(EffectEntry("filter"))
    if effects.rotation:
        entries.append(EffectEntry("rotation"))
    if effects.flip_h or effects.flip_v:
        entries.append(EffectEntry("flip"))
    return entries


def without_effect(effects: VideoEffects, entry: EffectEntry) -> VideoEffects:
    """Те же эффекты без одного."""
    match entry.kind:
        case "crop":
            return replace(effects, crop=None)
        case "redact":
            kept = tuple(r for i, r in enumerate(effects.redacts) if i != entry.index)
            return replace(effects, redacts=kept)
        case "text":
            kept_texts = tuple(x for i, x in enumerate(effects.texts) if i != entry.index)
            return replace(effects, texts=kept_texts)
        case "adjust":
            return replace(effects, adjust=Adjust())
        case "filter":
            return replace(effects, filter=None)
        case "rotation":
            return replace(effects, rotation=0)
        case "flip":
            return replace(effects, flip_h=False, flip_v=False)
    return effects


@dataclass(frozen=True)
class VideoProject:
    clips: tuple[Clip, ...]
    audio: AudioSettings = AudioSettings()
    effects: VideoEffects = VideoEffects()

    @property
    def duration(self) -> float:
        return sum(clip.length for clip in self.clips)

    @property
    def frame_size(self) -> tuple[int, int]:
        """Размер кадра итогового ролика: как у первого клипа с учётом поворота из метаданных."""
        info = self.clips[0].info
        width, height = (
            (info.height, info.width) if info.rotation in (90, 270) else (info.width, info.height)
        )
        return width - width % 2, height - height % 2  # h264 требует чётных размеров

    @property
    def clips_compatible(self) -> bool:
        first = self.clips[0].info
        return all(incompatibility(first, clip.info) is None for clip in self.clips[1:])

    def reencode_reason(self, precise: bool = False) -> str | None:
        """Почему нужно перекодировать видео: effects, precise, clips; None — хватит копирования."""
        if not self.effects.is_default:
            return "effects"
        if precise and any(clip.is_trimmed for clip in self.clips):
            return "precise"
        if not self.clips_compatible:
            return "clips"
        return None

    def add_clip(self, clip: Clip) -> "VideoProject":
        return replace(self, clips=(*self.clips, clip))

    def remove_clip(self, index: int) -> "VideoProject":
        if len(self.clips) <= 1:
            return self  # последний клип удалить нельзя
        return replace(self, clips=self.clips[:index] + self.clips[index + 1 :])

    def move_clip(self, index: int, delta: int) -> "VideoProject":
        target = index + delta
        if not (0 <= index < len(self.clips) and 0 <= target < len(self.clips)):
            return self
        clips = list(self.clips)
        clips[index], clips[target] = clips[target], clips[index]
        return replace(self, clips=tuple(clips))

    def move_clip_to(self, index: int, target: int) -> "VideoProject":
        """Клип на новое место (остальные сдвигаются); перетаскивание — один шаг истории."""
        if not (0 <= index < len(self.clips) and 0 <= target < len(self.clips)) or index == target:
            return self
        clips = list(self.clips)
        clips.insert(target, clips.pop(index))
        return replace(self, clips=tuple(clips))

    def flat_ranges(self) -> list[FlatRange]:
        """Итог склейки: плоский список оставленных диапазонов по клипам в порядке следования."""
        return [
            FlatRange(index, a, b) for index, clip in enumerate(self.clips) for a, b in clip.ranges
        ]

    def with_clip(self, index: int, clip: Clip) -> "VideoProject":
        clips = list(self.clips)
        clips[index] = clip
        return replace(self, clips=tuple(clips))

    def with_audio(self, audio: AudioSettings) -> "VideoProject":
        return replace(self, audio=audio)

    def with_effects(self, effects: VideoEffects) -> "VideoProject":
        return replace(self, effects=effects)


def incompatibility(a: MediaInfo, b: MediaInfo) -> str | None:
    """Чем отличаются два ролика для склейки без перекодирования; None — склеиваются."""
    if a.video_codec != b.video_codec:
        return "codec"
    if (a.width, a.height, a.rotation) != (b.width, b.height, b.rotation):
        return "resolution"
    if abs(a.fps - b.fps) > FPS_TOLERANCE:
        return "fps"
    if a.pix_fmt != b.pix_fmt:
        return "pixel format"
    if a.audio != b.audio:
        return "audio"
    return None


class ProjectHistory:
    """Отмена и повтор по снимкам проекта: проект неизменяемый, поэтому снимки дёшевы."""

    def __init__(self, project: VideoProject) -> None:
        self._states = [project]
        self._index = 0
        self._saved = project

    @property
    def current(self) -> VideoProject:
        return self._states[self._index]

    @property
    def can_undo(self) -> bool:
        return self._index > 0

    @property
    def can_redo(self) -> bool:
        return self._index < len(self._states) - 1

    def push(self, project: VideoProject) -> bool:
        """Добавляет состояние; False, если оно не отличается от текущего."""
        if project == self.current:
            return False
        del self._states[self._index + 1 :]  # новая правка обнуляет стек повтора
        self._states.append(project)
        self._index += 1
        return True

    def undo(self) -> bool:
        if not self.can_undo:
            return False
        self._index -= 1
        return True

    def redo(self) -> bool:
        if not self.can_redo:
            return False
        self._index += 1
        return True

    @property
    def modified(self) -> bool:
        return self.current != self._saved

    def mark_saved(self) -> None:
        self._saved = self.current


# --- операции разрезания в истории -----------------------------------------------------------


@dataclass(frozen=True)
class SplitAt:
    """Разрезать клип в момент исходного файла."""

    clip: int
    time: float

    def apply(self, project: VideoProject) -> VideoProject:
        return project.with_clip(self.clip, project.clips[self.clip].split_at(self.time))


@dataclass(frozen=True)
class RemoveRange:
    """Вырезать участок исходного файла (рип-удаление: остаток сдвигается)."""

    clip: int
    start: float
    stop: float

    def apply(self, project: VideoProject) -> VideoProject:
        clip = project.clips[self.clip].remove_span(self.start, self.stop)
        return project.with_clip(self.clip, clip)


@dataclass(frozen=True)
class RestoreRange:
    """Вернуть удалённый участок."""

    clip: int
    start: float
    stop: float

    def apply(self, project: VideoProject) -> VideoProject:
        clip = project.clips[self.clip].restore_span(self.start, self.stop)
        return project.with_clip(self.clip, clip)


CutOperation = SplitAt | RemoveRange | RestoreRange
