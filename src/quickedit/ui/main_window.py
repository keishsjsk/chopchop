"""Главное окно. Пока только стартовый экран; режимы просмотра и редактора позже."""

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QFileDialog, QMainWindow, QStackedWidget

from quickedit.core.document import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, MediaKind, detect_kind
from quickedit.engines.ffmpeg import find_ffmpeg
from quickedit.player.mpv_widget import find_libmpv
from quickedit.services.settings import RecentFiles
from quickedit.ui.drop_zone import DropZone


class MainWindow(QMainWindow):
    def __init__(self, settings: QSettings) -> None:
        super().__init__()
        self.setWindowTitle("QuickEdit")
        self.resize(960, 600)

        self._recent = RecentFiles(settings)
        self.current_path: Path | None = None

        self._drop_zone = DropZone()
        self._drop_zone.fileChosen.connect(self.open_file)
        self._drop_zone.openRequested.connect(self.choose_file)
        self._drop_zone.set_recent(self._recent.items())

        self._stack = QStackedWidget()
        self._stack.addWidget(self._drop_zone)
        self.setCentralWidget(self._stack)

        open_action = QAction(self.tr("Открыть…"), self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self.choose_file)
        self.addAction(open_action)

        self.statusBar().showMessage(self._tools_summary())

    def _tools_summary(self) -> str:
        ffmpeg = self.tr("найден") if find_ffmpeg() else self.tr("не найден")
        libmpv = self.tr("найден") if find_libmpv() else self.tr("не найден")
        return f"ffmpeg: {ffmpeg} · libmpv: {libmpv}"

    def choose_file(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(IMAGE_EXTENSIONS | VIDEO_EXTENSIONS))
        name, _ = QFileDialog.getOpenFileName(
            self, self.tr("Открыть"), "", self.tr("Фото и видео (%1)").replace("%1", exts)
        )
        if name:
            self.open_file(Path(name))

    def open_file(self, path: Path) -> None:
        kind = detect_kind(path)
        if kind is None:
            self.statusBar().showMessage(self.tr("Формат не поддерживается: ") + path.name, 5000)
            return
        self.current_path = path
        self._recent.add(path)
        self._drop_zone.set_recent(self._recent.items())
        label = self.tr("Фото") if kind is MediaKind.IMAGE else self.tr("Видео")
        self.setWindowTitle(f"{path.name} — QuickEdit")
        self.statusBar().showMessage(f"{label}: {path}")
