"""Главное окно: стартовый экран, просмотр фото и плеер видео."""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QCloseEvent, QDragEnterEvent, QDropEvent, QImage, QKeySequence
from PySide6.QtWidgets import QFileDialog, QLabel, QMainWindow, QMessageBox, QStackedWidget

from quickedit.core.document import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, MediaKind, detect_kind
from quickedit.engines.ffmpeg import find_ffmpeg
from quickedit.player.libmpv import MpvUnavailableError, create_mpv, find_libmpv, load_mpv_module
from quickedit.player.player import Player
from quickedit.player.resume import ResumeStore
from quickedit.services.settings import RecentFiles, load_player_prefs, save_player_prefs
from quickedit.ui.drop_zone import DropZone
from quickedit.ui.settings_dialog import SettingsDialog
from quickedit.ui.video_page import VideoPage
from quickedit.viewer.folder_nav import FolderNav
from quickedit.viewer.image_viewer import ImageViewer
from quickedit.viewer.prefetch import ImageCache

SUBTITLE_EXTENSIONS = frozenset({".srt", ".ass", ".ssa", ".vtt", ".sub"})
SEEK_SECONDS = 5
VOLUME_STEP = 5


class MainWindow(QMainWindow):
    def __init__(self, settings: QSettings) -> None:
        super().__init__()
        self.setWindowTitle("QuickEdit")
        self.resize(960, 600)
        self.setAcceptDrops(True)

        self._settings = settings
        self._recent = RecentFiles(settings)
        self._resume = ResumeStore(settings)
        self.current_path: Path | None = None
        self._nav: FolderNav | None = None
        self._video_path: Path | None = None
        self.video_page: VideoPage | None = None
        self._cache = ImageCache(parent=self)
        self._cache.loaded.connect(self._on_image_loaded)
        self._cache.failed.connect(self._on_image_failed)

        self._drop_zone = DropZone()
        self._drop_zone.fileChosen.connect(self.open_file)
        self._drop_zone.openRequested.connect(self.choose_file)
        self._drop_zone.set_recent(self._recent.items())

        self.viewer = ImageViewer()
        self.viewer.setAcceptDrops(False)  # перетаскивание обрабатывает окно
        self.viewer.doubleClicked.connect(self.toggle_fullscreen)
        self.viewer.zoomChanged.connect(self._on_zoom_changed)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._drop_zone)
        self._stack.addWidget(self.viewer)
        self.setCentralWidget(self._stack)

        self._zoom_label = QLabel()
        self.statusBar().addPermanentWidget(self._zoom_label)
        self.statusBar().showMessage(self._tools_summary())

        self._build_actions()

    def _build_actions(self) -> None:
        file_menu = self.menuBar().addMenu(self.tr("Файл"))
        file_menu.addAction(
            self._action(self.tr("Открыть…"), QKeySequence.StandardKey.Open, self.choose_file)
        )
        file_menu.addAction(self._action(self.tr("Настройки…"), "", self.show_settings))
        file_menu.addSeparator()
        file_menu.addAction(self._action(self.tr("Выход"), "Ctrl+Q", self.close))

        def player_action(text: str, shortcut: str, do: Callable[[Player], object]) -> None:
            self._add_action(text, shortcut, lambda: self._with_player(do))

        add = self._add_action
        add(self.tr("Следующее"), Qt.Key.Key_Right, lambda: self._horizontal(1))
        add(self.tr("Предыдущее"), Qt.Key.Key_Left, lambda: self._horizontal(-1))
        add(self.tr("Громче"), Qt.Key.Key_Up, lambda: self._volume(VOLUME_STEP))
        add(self.tr("Тише"), Qt.Key.Key_Down, lambda: self._volume(-VOLUME_STEP))
        player_action(self.tr("Пауза"), "Space", lambda p: p.toggle_pause())
        player_action(self.tr("Аудиодорожка"), "A", lambda p: p.cycle_audio())
        player_action(self.tr("Субтитры 1"), "S", lambda p: p.cycle_sub())
        player_action(self.tr("Субтитры 2"), "Shift+S", lambda p: p.cycle_sub2())
        player_action(self.tr("Субтитры 1 раньше"), "Z", lambda p: p.shift_sub(-1))
        player_action(self.tr("Субтитры 1 позже"), "X", lambda p: p.shift_sub(1))
        player_action(self.tr("Субтитры 2 раньше"), "Shift+Z", lambda p: p.shift_sub2(-1))
        player_action(self.tr("Субтитры 2 позже"), "Shift+X", lambda p: p.shift_sub2(1))
        add(self.tr("Полный экран"), Qt.Key.Key_F, self.toggle_fullscreen)
        add(self.tr("Полный экран"), Qt.Key.Key_F11, self.toggle_fullscreen)
        add(self.tr("Выйти из полного экрана"), Qt.Key.Key_Escape, self.exit_fullscreen)
        add(self.tr("Вписать в окно"), "Ctrl+0", self.viewer.fit_to_window)
        add(self.tr("Масштаб 100%"), "Ctrl+1", self.viewer.actual_size)

    def _action(
        self,
        text: str,
        shortcut: QKeySequence.StandardKey | Qt.Key | str,
        slot: Callable[[], object],
    ) -> QAction:
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(slot)
        return action

    def _add_action(
        self,
        text: str,
        shortcut: QKeySequence.StandardKey | Qt.Key | str,
        slot: Callable[[], object],
    ) -> None:
        self.addAction(self._action(text, shortcut, slot))

    def _tools_summary(self) -> str:
        ffmpeg = self.tr("найден") if find_ffmpeg() else self.tr("не найден")
        libmpv = self.tr("найден") if find_libmpv() else self.tr("не найден")
        return f"ffmpeg: {ffmpeg} · libmpv: {libmpv}"

    # --- открытие файлов ---------------------------------------------------------------------

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
        self._save_resume()
        self._recent.add(path)
        self._drop_zone.set_recent(self._recent.items())
        if kind is MediaKind.IMAGE:
            self._stop_video()
            self._nav = FolderNav(path)
            self._show(path)
        else:
            self._open_video(path)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if path.suffix.lower() in SUBTITLE_EXTENSIONS and self.video_page is not None:
                if self._on_video_page():
                    self.video_page.player.add_subtitle(path)
            else:
                self.open_file(path)
            event.acceptProposedAction()
            return

    # --- фото --------------------------------------------------------------------------------

    def step(self, delta: int) -> None:
        if self._nav is not None:
            self._show(self._nav.step(delta))

    def _show(self, path: Path) -> None:
        self.current_path = path
        self._update_title()
        image = self._cache.get(path)
        if image is not None:
            self._display(image)
        else:
            self._cache.request(path)

    def _display(self, image: QImage) -> None:
        self.viewer.set_image(image)
        self._stack.setCurrentWidget(self.viewer)
        self.statusBar().showMessage(f"{image.width()}×{image.height()}")
        if self._nav is not None:
            for neighbor in self._nav.neighbors():
                self._cache.request(neighbor)

    def _on_image_loaded(self, path: Path, image: QImage) -> None:
        if path == self.current_path and self._nav is not None:
            self._display(image)

    def _on_image_failed(self, path: Path) -> None:
        if path == self.current_path:
            self.statusBar().showMessage(self.tr("Не удалось открыть: ") + path.name, 5000)

    def _on_zoom_changed(self, zoom: float) -> None:
        self._zoom_label.setText(f"{round(zoom * 100)}%")

    # --- видео -------------------------------------------------------------------------------

    def _on_video_page(self) -> bool:
        return self.video_page is not None and self._stack.currentWidget() is self.video_page

    def _ensure_video_page(self) -> VideoPage | None:
        if self.video_page is not None:
            return self.video_page
        try:
            module = load_mpv_module()
            mpv = create_mpv(module, load_player_prefs(self._settings))
        except MpvUnavailableError as error:
            hint = self.tr(
                "Не удалось загрузить libmpv. Положите libmpv-2.dll (Windows) "
                "рядом с программой или установите libmpv (Linux)."
            )
            QMessageBox.warning(self, self.tr("Плеер недоступен"), f"{hint}\n\n{error}")
            return None
        page = VideoPage(module, mpv)
        page.fullscreenRequested.connect(self.toggle_fullscreen)
        page.player.errorOccurred.connect(self._on_video_error)
        page.player.pausedChanged.connect(lambda _paused: self._save_resume())
        self._stack.addWidget(page)
        self.video_page = page
        return page

    def _open_video(self, path: Path) -> None:
        page = self._ensure_video_page()
        if page is None:
            return
        self._nav = None
        self.current_path = path
        self._video_path = path
        self._update_title()
        self.statusBar().clearMessage()
        self._zoom_label.clear()
        self._stack.setCurrentWidget(page)
        page.player.load(path, self._resume.load(path))
        page.wake()

    def _on_video_error(self, _message: str) -> None:
        name = self._video_path.name if self._video_path else ""
        self.statusBar().showMessage(self.tr("Не удалось воспроизвести: ") + name, 8000)

    def _stop_video(self) -> None:
        if self.video_page is not None and self._video_path is not None:
            self.video_page.player.stop()
        self._video_path = None

    def _save_resume(self) -> None:
        if self.video_page is not None and self._video_path is not None:
            player = self.video_page.player
            self._resume.save(self._video_path, player.state(), player.duration)

    def _with_player(self, action: Callable[[Player], object]) -> None:
        if self._on_video_page() and self.video_page is not None:
            action(self.video_page.player)

    def _horizontal(self, direction: int) -> None:
        if self._on_video_page():
            self._with_player(lambda p: p.seek(direction * SEEK_SECONDS))
        else:
            self.step(direction)

    def _volume(self, delta: float) -> None:
        self._with_player(lambda p: p.add_volume(delta))

    def show_settings(self) -> None:
        dialog = SettingsDialog(load_player_prefs(self._settings), self)
        if dialog.exec():
            prefs = dialog.prefs()
            save_player_prefs(self._settings, prefs)
            if self.video_page is not None:
                self.video_page.player.apply_prefs(prefs)

    # --- окно --------------------------------------------------------------------------------

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.exit_fullscreen()
        elif self._stack.currentWidget() in (self.viewer, self.video_page):
            self.statusBar().hide()
            self.menuBar().hide()
            self.showFullScreen()

    def exit_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
            self.statusBar().show()
            self.menuBar().show()

    def _update_title(self) -> None:
        if self.current_path is None:
            return
        position = ""
        if self._nav is not None:
            position = f" ({self._nav.index + 1}/{len(self._nav.files)})"
        self.setWindowTitle(f"{self.current_path.name}{position} — QuickEdit")

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._save_resume()
        self._cache.wait()
        if self.video_page is not None:
            self.video_page.release()
        super().closeEvent(event)
