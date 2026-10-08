"""Стартовый экран: зона «перетащите файл», кнопка «Открыть» и последние файлы."""

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class DropZone(QWidget):
    fileChosen = Signal(Path)
    openRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

        hint = QLabel(self.tr("Перетащите фото или видео"))
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = hint.font()
        font.setPointSize(font.pointSize() + 8)
        hint.setFont(font)

        self._open_button = QPushButton(self.tr("Открыть…"))
        self._open_button.clicked.connect(self.openRequested)

        self._recent_label = QLabel(self.tr("Последние файлы"))
        self._recent = QListWidget()
        self._recent.setMaximumHeight(160)
        self._recent.itemActivated.connect(self._on_recent_activated)

        layout = QVBoxLayout(self)
        layout.addStretch(1)
        layout.addWidget(hint)
        layout.addWidget(self._open_button, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(24)
        layout.addWidget(self._recent_label)
        layout.addWidget(self._recent)
        layout.addStretch(1)
        self.set_recent([])

    def set_recent(self, paths: list[Path]) -> None:
        self._recent.clear()
        for path in paths:
            item = QListWidgetItem(path.name)
            item.setToolTip(str(path))
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self._recent.addItem(item)
        has_items = bool(paths)
        self._recent_label.setVisible(has_items)
        self._recent.setVisible(has_items)

    def _on_recent_activated(self, item: QListWidgetItem) -> None:
        self.fileChosen.emit(Path(str(item.data(Qt.ItemDataRole.UserRole))))

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.fileChosen.emit(Path(url.toLocalFile()))
                event.acceptProposedAction()
                return
