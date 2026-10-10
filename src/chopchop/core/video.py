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


@dataclass(frozen=True)
class Clip:
    """Блок: непрерывный кусок исходного файла. Ролик — блоки подряд в порядке списка.

    Резка делит блок на два, удаление убирает блок, перемещение меняет порядок, а края блока
    можно тянуть в пределах исходного файла (вернуть то, что было обрезано). Склейка разных
    роликов — тот же список блоков.
    """

    path: Path
    info: MediaInfo
    start: float = 0.0
    end: float = -1.0  # отрицательное значение — до конца файла

    @property
    def stop(self) -> float:
        return self.info.duration if self.end < 0 else min(self.end, self.info.duration)

    @property
    def frame(self) -> float:
        """Длительность одного кадра: меньше блок быть не может."""
        fps = self.info.fps
        return 1.0 / fps if fps > 0 else DEFAULT_FRAME

    @property
    def ranges(self) -> tuple[Range, ...]:
        """Оставленное в исходном времени: у блока один диапазон (общий вид для экспорта)."""
        return ((self.start, self.stop),)

    @property
    def length(self) -> float:
        return self.stop - self.start

    @property
    def is_trimmed(self) -> bool:
        return self.start > EPS or self.stop < self.info.duration - EPS

    def to_result(self, source: float) -> float:
        """Смещение от начала блока для момента исходного файла (внутри блока)."""
        return min(max(source, self.start), self.stop) - self.start

    def contains(self, source: float) -> bool:
        return self.start - EPS <= source <= self.stop + EPS

    def with_trim(self, start: float, end: float) -> "Clip":
        """Новые границы блока в пределах исходного файла; короче `MIN_CLIP_SECONDS` не бывает."""
        duration = self.info.duration
        start = min(max(start, 0.0), max(duration - MIN_CLIP_SECONDS, 0.0))
        end = min(max(end, start + MIN_CLIP_SECONDS), duration)
        return replace(self, start=start, end=-1.0 if end >= duration - EPS else end)

    def reset(self) -> "Clip":
        """Вернуть блок целым: границы файла."""
        return replace(self, start=0.0, end=-1.0)

    def split_source(self, source: float) -> tuple["Clip", "Clip"] | None:
        """Разрезать в момент исходного файла; None, если до края меньше кадра."""
        if source - self.start < self.frame - EPS or self.stop - source < self.frame - EPS:
            return None
        return replace(self, end=source), replace(self, start=source)


def legacy_blocks(
    path: Path,
    info: MediaInfo,
    start: float = 0.0,
    end: float = -1.0,
    cuts: tuple[Range, ...] = (),
    splits: tuple[float, ...] = (),
) -> tuple[Clip, ...]:
    """Блоки из прежнего описания клипа (внешние границы, вырезы, метки разрезов).

    Каждый оставленный диапазон становится блоком, а метка разреза внутри диапазона делит его на
    два соседних блока: так прежние проекты открываются в том же виде, что и раньше.
    """
    stop = info.duration if end < 0 else min(end, info.duration)
    kept: list[Range] = [(start, stop)]
    for a, b in cuts:
        next_kept: list[Range] = []
        for x, y in kept:
            if b <= x or a >= y:
                next_kept.append((x, y))
                continue
            if a > x:
                next_kept.append((x, a))
            if b < y:
                next_kept.append((b, y))
        kept = next_kept
    blocks: list[Clip] = []
    for a, b in kept:
        edges = [a, *sorted(s for s in splits if a < s < b), b]
        for x, y in zip(edges[:-1], edges[1:], strict=True):
            blocks.append(Clip(path, info, x, -1.0 if y >= info.duration - EPS else y))
    return tuple(blocks)


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
        """Итог склейки: плоский список блоков по порядку (на блок один диапазон)."""
        return [FlatRange(index, clip.start, clip.stop) for index, clip in enumerate(self.clips)]

    def offsets(self) -> list[float]:
        """Где в итоге начинается каждый блок."""
        result: list[float] = []
        total = 0.0
        for clip in self.clips:
            result.append(total)
            total += clip.length
        return result

    def locate(self, time: float, *, end: bool = False) -> tuple[int, float]:
        """Момент итога -> (номер блока, время исходного файла).

        На шве начало берёт следующий блок, а конец (`end=True`) предыдущий.
        """
        offsets = self.offsets()
        time = min(max(time, 0.0), self.duration)
        for index, clip in enumerate(self.clips):
            low, high = offsets[index], offsets[index] + clip.length
            if low < time < high:
                return index, clip.start + (time - low)
            if end and abs(time - high) <= EPS:
                return index, clip.stop
            if not end and abs(time - low) <= EPS:
                return index, clip.start
        last = len(self.clips) - 1
        return last, self.clips[last].stop

    def with_clip(self, index: int, clip: Clip) -> "VideoProject":
        clips = list(self.clips)
        clips[index] = clip
        return replace(self, clips=tuple(clips))

    def split_at(self, time: float) -> "VideoProject":
        """Разрезать ролик в момент итога: блок делится надвое, ничего не удаляется."""
        index, source = self.locate(time)
        parts = self.clips[index].split_source(source)
        if parts is None:
            return self
        clips = list(self.clips)
        clips[index : index + 1] = list(parts)
        return replace(self, clips=tuple(clips))

    def remove_span(self, start: float, stop: float) -> "VideoProject":
        """Вырезать участок итога: блоки по краям делятся, всё внутри удаляется, остаток встаёт
        вплотную. Удалить весь ролик нельзя."""
        if stop - start < EPS:
            return self
        project = self.split_at(start).split_at(stop)
        offsets = project.offsets()
        kept = [
            clip
            for clip, offset in zip(project.clips, offsets, strict=True)
            if not (offset >= start - EPS and offset + clip.length <= stop + EPS)
        ]
        if not kept:
            return self
        return replace(project, clips=tuple(kept))

    def trim_clip(self, index: int, start: float, end: float) -> "VideoProject":
        """Края блока в пределах исходного файла (укоротить или вернуть обрезанное)."""
        return self.with_clip(index, self.clips[index].with_trim(start, end))

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


# --- операции монтажа в истории --------------------------------------------------------------


@dataclass(frozen=True)
class SplitAt:
    """Разрезать ролик в момент итога."""

    time: float

    def apply(self, project: VideoProject) -> VideoProject:
        return project.split_at(self.time)


@dataclass(frozen=True)
class RemoveRange:
    """Вырезать участок итога (остаток сдвигается)."""

    start: float
    stop: float

    def apply(self, project: VideoProject) -> VideoProject:
        return project.remove_span(self.start, self.stop)


@dataclass(frozen=True)
class RemoveBlock:
    """Удалить блок. Последний блок удалить нельзя."""

    index: int

    def apply(self, project: VideoProject) -> VideoProject:
        return project.remove_clip(self.index)


@dataclass(frozen=True)
class MoveBlock:
    """Переставить блок на новое место (остальные сдвигаются)."""

    index: int
    target: int

    def apply(self, project: VideoProject) -> VideoProject:
        return project.move_clip_to(self.index, self.target)


@dataclass(frozen=True)
class TrimBlock:
    """Новые края блока в исходном времени (тянуть можно до границ файла)."""

    index: int
    start: float
    end: float

    def apply(self, project: VideoProject) -> VideoProject:
        return project.trim_clip(self.index, self.start, self.end)


CutOperation = SplitAt | RemoveRange | RemoveBlock | MoveBlock | TrimBlock


def cut_summary(project: VideoProject) -> tuple[int, float]:
    """Сколько фрагментов исходных файлов вырезано и на сколько секунд короче итог.

    Считается по покрытию: для каждого файла то, что не вошло ни в один блок, разбивается на
    промежутки; их число и общая длина и есть «вырезано».
    """
    by_path: dict[Path, tuple[float, list[Range]]] = {}
    for clip in project.clips:
        _duration, spans = by_path.setdefault(clip.path, (clip.info.duration, []))
        spans.append((clip.start, clip.stop))
    gaps, seconds = 0, 0.0
    for duration, spans in by_path.values():
        cursor = 0.0
        for a, b in sorted(spans):
            if a - cursor > EPS:
                gaps += 1
                seconds += a - cursor
            cursor = max(cursor, b)
        if duration - cursor > EPS:
            gaps += 1
            seconds += duration - cursor
    return gaps, seconds
