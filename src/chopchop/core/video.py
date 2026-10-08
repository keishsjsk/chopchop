"""Проект видеомонтажа: клипы с обрезкой, настройки звука, история. Чистый Python, без Qt."""

from dataclasses import dataclass, replace
from pathlib import Path

from chopchop.core.document import MediaInfo
from chopchop.core.geometry import Rect
from chopchop.core.operations import Adjust, FilterName, Redact, Text

MIN_CLIP_SECONDS = 0.1
MAX_VOLUME = 2.0
FPS_TOLERANCE = 0.01


@dataclass(frozen=True)
class Clip:
    path: Path
    info: MediaInfo
    start: float = 0.0
    end: float = -1.0  # отрицательное значение — до конца файла

    @property
    def stop(self) -> float:
        return self.info.duration if self.end < 0 else min(self.end, self.info.duration)

    @property
    def length(self) -> float:
        return max(self.stop - self.start, 0.0)

    @property
    def is_trimmed(self) -> bool:
        return self.start > 0.0005 or self.stop < self.info.duration - 0.0005

    def with_trim(self, start: float, end: float) -> "Clip":
        """Новая обрезка; границы приводятся к допустимым значениям."""
        duration = self.info.duration
        start = min(max(start, 0.0), max(duration - MIN_CLIP_SECONDS, 0.0))
        end = min(max(end, start + MIN_CLIP_SECONDS), duration)
        if end >= duration - 0.0005:
            end = -1.0  # до конца файла: так клип без обрезки равен исходному
        return replace(self, start=start, end=end)


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
