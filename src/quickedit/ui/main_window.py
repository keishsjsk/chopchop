"""Главное окно: стартовый экран и просмотр фото. Плеер и редактор появятся позже."""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QCloseEvent, QImage, QKeySequence
from PySide6.QtWidgets import QFileDialog, QLabel, QMainWindow, QStackedWidget

from quickedit.core.document import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, MediaKind, detect_kind
from quickedit.engines.ffmpeg import find_ffmpeg
from quickedit.player.mpv_widget import find_libmpv
from quickedit.services.settings import RecentFiles
from quickedit.ui.drop_zone import DropZone
from quickedit.viewer.folder_nav import FolderNav
from quickedit.viewer.image_viewer import ImageViewer
from quickedit.viewer.prefetch import ImageCache


class MainWindow(QMainWindow):
    def __init__(self, settings: QSettings) -> None:
        super().__init__()
        self.setWindowTitle("QuickEdit")
        self.resize(960, 600)

        self._recent = RecentFiles(settings)
        self.current_path: Path | None = None
        self._nav: FolderNav | None = None
        self._cache = ImageCache(parent=self)
        self._cache.loaded.connect(self._on_image_loaded)
        self._cache.failed.connect(self._on_image_failed)

        self._drop_zone = DropZone()
        self._drop_zone.fileChosen.connect(self.open_file)
        self._drop_zone.openRequested.connect(self.choose_file)
        self._drop_zone.set_recent(self._recent.items())

        self.viewer = ImageViewer()
        self.viewer.doubleClicked.connect(self.toggle_fullscreen)
        self.viewer.zoomChanged.connect(self._on_zoom_changed)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._drop_zone)
        self._stack.addWidget(self.viewer)
        self.setCentralWidget(self._stack)

        self._zoom_label = QLabel()
        self.statusBar().addPermanentWidget(self._zoom_label)
        self.statusBar().showMessage(self._tools_summary())

        self._add_action(self.tr("Открыть…"), QKeySequence.StandardKey.Open, self.choose_file)
        self._add_action(self.tr("Следующее"), Qt.Key.Key_Right, lambda: self.step(1))
        self._add_action(self.tr("Предыдущее"), Qt.Key.Key_Left, lambda: self.step(-1))
        self._add_action(self.tr("Полный экран"), Qt.Key.Key_F, self.toggle_fullscreen)
        self._add_action(self.tr("Полный экран"), Qt.Key.Key_F11, self.toggle_fullscreen)
        self._add_action(
            self.tr("Выйти из полного экрана"), Qt.Key.Key_Escape, self.exit_fullscreen
        )
        self._add_action(self.tr("Вписать в окно"), "Ctrl+0", self.viewer.fit_to_window)
        self._add_action(self.tr("Масштаб 100%"), "Ctrl+1", self.viewer.actual_size)

    def _add_action(
        self,
        text: str,
        shortcut: QKeySequence.StandardKey | Qt.Key | str,
        slot: Callable[[], object],
    ) -> None:
        action = QAction(text, self)
        action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(slot)
        self.addAction(action)

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
        self._recent.add(path)
        self._drop_zone.set_recent(self._recent.items())
        if kind is MediaKind.IMAGE:
            self._nav = FolderNav(path)
            self._show(path)
        else:
            # плеер видео — этап 3
            self.current_path = path
            self._nav = None
            self._update_title()
            self.statusBar().showMessage(self.tr("Видео: ") + str(path))

    def step(self, delta: int) -> None:
        if self._nav is not None:
            self._show(self._nav.step(delta))

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.exit_fullscreen()
        elif self._stack.currentWidget() is self.viewer:
            self.statusBar().hide()
            self.showFullScreen()

    def exit_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
            self.statusBar().show()

    def _show(self, path: Path) -> None:
        self.current_path = path
        self._update_title()
        image = self._cache.get(path)
        if image is not None:
            self._display(path, image)
        else:
            self._cache.request(path)

    def _display(self, path: Path, image: QImage) -> None:
        self.viewer.set_image(image)
        self._stack.setCurrentWidget(self.viewer)
        self.statusBar().showMessage(f"{image.width()}×{image.height()}")
        if self._nav is not None:
            for neighbor in self._nav.neighbors():
                self._cache.request(neighbor)

    def _on_image_loaded(self, path: Path, image: QImage) -> None:
        if path == self.current_path:
            self._display(path, image)

    def _on_image_failed(self, path: Path) -> None:
        if path == self.current_path:
            self.statusBar().showMessage(self.tr("Не удалось открыть: ") + path.name, 5000)

    def _on_zoom_changed(self, zoom: float) -> None:
        self._zoom_label.setText(f"{round(zoom * 100)}%")

    def _update_title(self) -> None:
        if self.current_path is None:
            return
        position = ""
        if self._nav is not None:
            position = f" ({self._nav.index + 1}/{len(self._nav.files)})"
        self.setWindowTitle(f"{self.current_path.name}{position} — QuickEdit")

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._cache.wait()
        super().closeEvent(event)
