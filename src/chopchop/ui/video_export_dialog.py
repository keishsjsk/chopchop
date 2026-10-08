"""Диалог экспорта видео: файл, контейнер, точная обрезка и пояснение, будет ли экспорт быстрым."""

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
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

from chopchop.core.video import VideoProject
from chopchop.engines.video_engine import CONTAINERS, default_video_output


class VideoExportDialog(QDialog):
    def __init__(self, project: VideoProject, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Экспорт видео"))
        self._project = project
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

        self._precise = QCheckBox(self.tr("Точная обрезка (медленнее, с перекодированием)"))
        self._precise.setToolTip(
            self.tr("Без неё резать можно только по ключевым кадрам, начало может сдвинуться")
        )
        self._precise.setEnabled(any(clip.is_trimmed for clip in project.clips))
        self._precise.toggled.connect(self._update_notes)

        form = QFormLayout()
        form.addRow(self.tr("Контейнер"), self._container)
        form.addRow(self.tr("Файл"), row)
        form.addRow("", self._precise)

        self._summary = QLabel()
        self._summary.setWordWrap(True)
        self._update_notes()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._summary)
        layout.addWidget(buttons)
        self.setMinimumWidth(500)

    def notes(self) -> list[str]:
        """Что произойдёт при экспорте: быстрый режим или перекодирование и почему."""
        project = self._project
        reason = project.reencode_reason(self._precise.isChecked())
        notes: list[str] = []
        if reason is None:
            notes.append(
                self.tr("Видео не перекодируется: экспорт займёт секунды, качество не теряется.")
            )
            if any(clip.is_trimmed for clip in project.clips):
                notes.append(
                    self.tr(
                        "Обрезка идёт по ключевым кадрам: начало может сдвинуться на долю секунды."
                    )
                )
        elif reason == "effects":
            notes.append(self.tr("Эффекты требуют перекодирования видео (H.264): это дольше."))
        elif reason == "clips":
            notes.append(
                self.tr(
                    "Клипы с разными параметрами будут приведены к размеру и частоте кадров "
                    "первого клипа (перекодирование, это дольше)."
                )
            )
        else:
            notes.append(self.tr("Точная обрезка: видео перекодируется, границы точны до кадра."))
        audio = project.audio
        if not audio.is_default and not audio.mute:
            notes.append(self.tr("Звук будет перекодирован в AAC."))
        notes.append(self.tr("Метаданные (место съёмки, устройство) удаляются."))
        return notes

    def _update_notes(self) -> None:
        self._summary.setText("\n".join(f"• {text}" for text in self.notes()))

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

    def precise(self) -> bool:
        return self._precise.isChecked()
