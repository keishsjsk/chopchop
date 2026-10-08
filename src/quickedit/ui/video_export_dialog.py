"""Диалог экспорта видео: файл, контейнер и пояснение, будет ли экспорт быстрым."""

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from quickedit.core.video import VideoProject
from quickedit.engines.video_engine import CONTAINERS, default_video_output


class VideoExportDialog(QDialog):
    def __init__(self, project: VideoProject, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Экспорт видео"))
        source = project.clips[0].path
        default = default_video_output(source)

        self._container = QComboBox()
        for extension in CONTAINERS:
            self._container.addItem(extension[1:].upper(), extension)
        self._container.setCurrentIndex(max(self._container.findData(default.suffix), 0))
        self._container.currentIndexChanged.connect(self._on_container_changed)

        self._path = QLineEdit(str(default))
        browse = QPushButton(self.tr("Обзор…"))
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self._path, 1)
        row.addWidget(browse)

        form = QFormLayout()
        form.addRow(self.tr("Контейнер"), self._container)
        form.addRow(self.tr("Файл"), row)

        notes = [self.tr("Видео не перекодируется: экспорт займёт секунды, качество не теряется.")]
        if not project.audio.is_default and not project.audio.mute:
            notes.append(self.tr("Звук будет перекодирован в AAC, это тоже быстро."))
        if any(clip.is_trimmed for clip in project.clips):
            notes.append(
                self.tr("Обрезка идёт по ключевым кадрам: начало может сдвинуться на долю секунды.")
            )
        notes.append(self.tr("Метаданные (место съёмки, устройство) удаляются."))
        summary = QLabel("\n".join(f"• {text}" for text in notes))
        summary.setWordWrap(True)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(summary)
        layout.addWidget(buttons)
        self.setMinimumWidth(480)

    def _on_container_changed(self) -> None:
        extension = str(self._container.currentData())
        current = Path(self._path.text())
        if current.suffix.lower() != extension:
            self._path.setText(str(current.with_suffix(extension)))

    def _browse(self) -> None:
        name, _ = QFileDialog.getSaveFileName(self, self.tr("Сохранить как"), self._path.text())
        if name:
            self._path.setText(name)
            suffix = Path(name).suffix.lower()
            index = self._container.findData(suffix)
            if index >= 0:
                self._container.setCurrentIndex(index)

    def path(self) -> Path:
        return Path(self._path.text())
