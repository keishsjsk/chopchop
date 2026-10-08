"""Проект видеомонтажа: клипы с обрезкой, настройки звука, история. Чистый Python, без Qt."""

from dataclasses import dataclass, replace
from pathlib import Path

from quickedit.core.document import MediaInfo

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
class VideoProject:
    clips: tuple[Clip, ...]
    audio: AudioSettings = AudioSettings()

    @property
    def duration(self) -> float:
        return sum(clip.length for clip in self.clips)

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
