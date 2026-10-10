"""Сессия монтажа видео: проект и история правок."""

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from chopchop.core.geometry import Rect
from chopchop.core.operations import Adjust, FilterName, Redact, Text
from chopchop.core.timing import retime
from chopchop.core.video import (
    AudioSettings,
    Clip,
    CutOperation,
    EffectEntry,
    ProjectHistory,
    VideoEffects,
    VideoProject,
    without_effect,
)


class VideoSession(QObject):
    changed = Signal()
    timeNotes = Signal(list)  # list[TimeNote]: время показа сжалось или обрезано

    def __init__(self, project: VideoProject, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._history = ProjectHistory(project)

    @property
    def project(self) -> VideoProject:
        return self._history.current

    @property
    def can_undo(self) -> bool:
        return self._history.can_undo

    @property
    def can_redo(self) -> bool:
        return self._history.can_redo

    @property
    def modified(self) -> bool:
        return self._history.modified

    def mark_saved(self) -> None:
        self._history.mark_saved()
        self.changed.emit()

    def _apply(self, project: VideoProject) -> None:
        # время показа текста и областей хранится во времени итога: после вырезов подгоняем его
        fitted, notes = retime(self._history.current, project)
        if self._history.push(fitted):
            self.changed.emit()
            if notes:
                self.timeNotes.emit(notes)

    def undo(self) -> None:
        if self._history.undo():
            self.changed.emit()

    def redo(self) -> None:
        if self._history.redo():
            self.changed.emit()

    def set_trim(self, index: int, start: float, end: float) -> None:
        """Края блока в исходном времени (тянуть можно до границ файла)."""
        self._apply(self.project.trim_clip(index, start, end))

    def cut(self, operation: CutOperation) -> None:
        """Разрезать, удалить, переставить блок или сдвинуть его край: один шаг истории."""
        self._apply(operation.apply(self.project))

    def reset_clip(self, index: int) -> None:
        """Вернуть блок целым: границы исходного файла."""
        self._apply(self.project.with_clip(index, self.project.clips[index].reset()))

    def add_clip(self, clip: Clip) -> None:
        self._apply(self.project.add_clip(clip))

    def remove_clip(self, index: int) -> None:
        self._apply(self.project.remove_clip(index))

    def move_clip(self, index: int, delta: int) -> None:
        self._apply(self.project.move_clip(index, delta))

    def move_clip_to(self, index: int, target: int) -> None:
        self._apply(self.project.move_clip_to(index, target))

    def set_volume(self, volume: float) -> None:
        self._apply(self.project.with_audio(self._audio(volume=volume)))

    def set_mute(self, mute: bool) -> None:
        self._apply(self.project.with_audio(self._audio(mute=mute)))

    def set_replacement(self, path: Path | None) -> None:
        # выбор своего звука включает звук обратно, иначе замена не имела бы смысла
        mute = False if path is not None else self.project.audio.mute
        self._apply(self.project.with_audio(self._audio(replacement=path, mute=mute)))

    def _audio(self, **changes: object) -> AudioSettings:
        return replace(self.project.audio, **changes)  # type: ignore[arg-type]

    # --- эффекты -----------------------------------------------------------------------------

    def _effects(self, **changes: object) -> None:
        self._apply(self.project.with_effects(replace(self.project.effects, **changes)))  # type: ignore[arg-type]

    def set_crop(self, rect: Rect | None) -> None:
        """Кадр результата; прямоугольник на весь кадр равен «без кадрирования»."""
        width, height = self.project.frame_size
        if rect is not None:
            box = rect.to_box(width, height)
            if box is None or box == (0, 0, width, height):
                rect = None
            else:
                rect = Rect(box[0], box[1], box[2] - box[0], box[3] - box[1])
        self._effects(crop=rect)

    def add_redact(self, redact: Redact) -> None:
        self._effects(redacts=(*self.project.effects.redacts, redact))

    def add_text(self, text: Text) -> None:
        self._effects(texts=(*self.project.effects.texts, text))

    def set_adjust(self, adjust: Adjust) -> None:
        self._effects(adjust=adjust)

    def set_filter(self, name: FilterName | None) -> None:
        self._effects(filter=name)

    def rotate(self, degrees: int) -> None:
        """Поворот на 90°, 180° или 270° по часовой (накапливается)."""
        self._effects(rotation=(self.project.effects.rotation + degrees) % 360)

    def flip(self, horizontal: bool) -> None:
        current = self.project.effects
        if horizontal:
            self._effects(flip_h=not current.flip_h)
        else:
            self._effects(flip_v=not current.flip_v)

    def remove_effect(self, entry: EffectEntry) -> None:
        self._apply(self.project.with_effects(without_effect(self.project.effects, entry)))

    def clear_effects(self) -> None:
        self._apply(self.project.with_effects(VideoEffects()))
