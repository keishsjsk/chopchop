"""Сессия монтажа видео: проект и история правок."""

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from quickedit.core.video import AudioSettings, Clip, ProjectHistory, VideoProject


class VideoSession(QObject):
    changed = Signal()

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
        if self._history.push(project):
            self.changed.emit()

    def undo(self) -> None:
        if self._history.undo():
            self.changed.emit()

    def redo(self) -> None:
        if self._history.redo():
            self.changed.emit()

    def set_trim(self, index: int, start: float, end: float) -> None:
        clip = self.project.clips[index]
        self._apply(self.project.with_clip(index, clip.with_trim(start, end)))

    def add_clip(self, clip: Clip) -> None:
        self._apply(self.project.add_clip(clip))

    def remove_clip(self, index: int) -> None:
        self._apply(self.project.remove_clip(index))

    def move_clip(self, index: int, delta: int) -> None:
        self._apply(self.project.move_clip(index, delta))

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
