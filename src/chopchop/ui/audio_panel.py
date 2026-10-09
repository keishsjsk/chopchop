"""Звук видео в контекстной панели: громкость, «Убрать звук», замена и возврат исходного."""

from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt, QTimer
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QWidget

from chopchop.editor.video_session import VideoSession
from chopchop.ui.click_slider import ClickSlider
from chopchop.ui.theme import tokens
from chopchop.ui.widgets import PixelToggle, button

AUDIO_FILTER = "*.mp3 *.wav *.m4a *.aac *.flac *.ogg *.opus"
VOLUME_COMMIT_MS = 350
VOLUME_WIDTH = 11 * tokens.SPACE_4


class AudioPanel(QWidget):
    def __init__(self, session: VideoSession, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(VOLUME_COMMIT_MS)
        self._timer.timeout.connect(self._commit_volume)

        self._volume = ClickSlider(Qt.Orientation.Horizontal)
        self._volume.setRange(0, 200)
        self._volume.setValue(100)
        self._volume.setFixedWidth(VOLUME_WIDTH)
        self._volume.setAccessibleName(self.tr("Громкость"))
        self._volume.valueChanged.connect(self._on_volume_changed)
        self._volume_label = QLabel("100%")
        self._volume_label.setMinimumWidth(5 * tokens.SPACE_2)
        self._mute = PixelToggle(self.tr("Убрать звук"))
        self._mute.toggled.connect(session.set_mute)
        self._replace = button(self.tr("Заменить звук…"), slot=self.choose_replacement)
        self._original_audio = button(
            self.tr("Исходный звук"), slot=lambda: session.set_replacement(None)
        )
        self._note = QLabel()
        self._note.setProperty("muted", True)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(tokens.SPACE_3)
        caption = QLabel(self.tr("Громкость"))
        caption.setProperty("muted", True)
        for widget in (
            caption,
            self._volume,
            self._volume_label,
            self._mute,
            self._replace,
            self._original_audio,
            self._note,
        ):
            row.addWidget(widget)
        row.addStretch(1)

    def _on_volume_changed(self, value: int) -> None:
        self._volume_label.setText(f"{value}%")
        self._timer.start()  # в историю попадает только итоговое значение

    def _commit_volume(self) -> None:
        self.session.set_volume(self._volume.value() / 100)

    def choose_replacement(self) -> None:
        name, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Заменить звук"),
            "",
            self.tr("Аудио (%1)").replace("%1", AUDIO_FILTER),
        )
        if name:
            self.session.set_replacement(Path(name))

    def refresh(self) -> None:
        audio = self.session.project.audio
        if not self._timer.isActive() and not self._volume.isSliderDown():
            with QSignalBlocker(self._volume):
                self._volume.setValue(round(audio.volume * 100))
            self._volume_label.setText(f"{round(audio.volume * 100)}%")
        with QSignalBlocker(self._mute):
            self._mute.setChecked(audio.mute)
        self._original_audio.setEnabled(audio.replacement is not None)
        self._note.setText(self.tr("Звук: ") + audio.replacement.name if audio.replacement else "")

    def is_customised(self) -> bool:
        audio = self.session.project.audio
        return audio.volume != 1.0 or audio.mute or audio.replacement is not None
