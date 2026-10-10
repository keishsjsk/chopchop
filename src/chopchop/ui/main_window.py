"""Главное окно: стартовый экран, просмотр фото и плеер видео."""

import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QByteArray, QPoint, QProcess, QSettings, Qt
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QCursor,
    QDragEnterEvent,
    QDropEvent,
    QImage,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
)

from chopchop.core.document import (
    IMAGE_EXTENSIONS,
    VIDEO_EXTENSIONS,
    MediaInfo,
    MediaKind,
    detect_kind,
)
from chopchop.engines.ffmpeg import find_ffmpeg, find_ffprobe
from chopchop.player.libmpv import MpvUnavailableError, create_mpv, find_libmpv, load_mpv_module
from chopchop.player.player import Player
from chopchop.player.resume import ResumeStore
from chopchop.services import logs, sub_presets, temp_files
from chopchop.services.app_settings import AppSettings, config_dir
from chopchop.services.settings import RecentFiles, player_prefs
from chopchop.services.sub_presets import PresetStore
from chopchop.ui import anim
from chopchop.ui.actions import PHOTO, PHOTO_EDITOR, START, VIDEO, VIDEO_EDITOR
from chopchop.ui.context_menus import ContextMenus
from chopchop.ui.drop_zone import DropZone
from chopchop.ui.file_commands import FileCommands
from chopchop.ui.main_actions import build_registry
from chopchop.ui.settings_dialog import SettingsDialog
from chopchop.ui.theme import current
from chopchop.ui.theme.manager import ThemeManager
from chopchop.ui.themed_menu import ThemedMenu
from chopchop.ui.toast import Toast
from chopchop.ui.video_page import VideoPage
from chopchop.viewer.folder_nav import FolderNav
from chopchop.viewer.image_viewer import ImageViewer
from chopchop.viewer.prefetch import ImageCache
from chopchop.workers.tasks import TaskRunner

if TYPE_CHECKING:  # редакторы тяжёлые: загружаются при первом входе в редактирование
    from chopchop.editor.session import EditSession
    from chopchop.ui.editor_page import EditorPage
    from chopchop.ui.video_editor_page import VideoEditorPage

SUBTITLE_EXTENSIONS = frozenset({".srt", ".ass", ".ssa", ".vtt", ".sub"})


MIN_PREVIEW_SIDE = 1024
MAX_PREVIEW_SIDE = 3072


class MainWindow(QMainWindow):
    def __init__(
        self,
        settings: QSettings,
        app_settings: AppSettings | None = None,
        theme: ThemeManager | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("CHOPCHOP")
        self.resize(960, 600)
        self.setMinimumSize(960, 600)
        self.setAcceptDrops(True)

        self._settings = settings
        self._app = app_settings or AppSettings(None)
        self._theme = theme
        self._recent = RecentFiles(settings)
        self._presets = PresetStore(config_dir() / sub_presets.FILE_NAME)
        self._resume = ResumeStore(settings)
        self.current_path: Path | None = None
        self._nav: FolderNav | None = None
        self._video_path: Path | None = None
        self._video_nav: FolderNav | None = None
        self.video_page: VideoPage | None = None
        self.editor: EditorPage | None = None
        self.video_editor: VideoEditorPage | None = None
        self._tasks = TaskRunner(self)
        self._session: EditSession | None = None
        self._cache = ImageCache(parent=self)
        self._cache.loaded.connect(self._on_image_loaded)
        self._cache.reducedLoaded.connect(self._on_reduced_loaded)
        self._cache.failed.connect(self._on_image_failed)
        self._showing_reduced = False  # на экране пока уменьшенный вариант, полный грузится

        self._drop_zone = DropZone()
        self._drop_zone.fileChosen.connect(self.open_file)
        self._drop_zone.openRequested.connect(self.choose_file)
        self._drop_zone.set_recent(self._recent.items())

        self.viewer = ImageViewer()
        self.viewer.setAcceptDrops(False)  # перетаскивание обрабатывает окно
        self.viewer.doubleClicked.connect(self.toggle_fullscreen)
        self.viewer.zoomChanged.connect(self._on_zoom_changed)
        self.viewer.navigateRequested.connect(self.step)
        self._apply_viewer_settings()

        self._stack = QStackedWidget()
        self._stack.addWidget(self._drop_zone)
        self._stack.addWidget(self.viewer)
        self.setCentralWidget(self._stack)

        self._zoom_label = QLabel()
        self.statusBar().addPermanentWidget(self._zoom_label)
        self.statusBar().showMessage(self._tools_summary())

        self.toast = Toast(self._stack)  # короткие сообщения: «Скопировано», «Сохранено»
        self.files = FileCommands(self)
        self.registry = build_registry(self)
        self.menus = ContextMenus(self)
        self.registry.add(
            "context_menu",
            self.tr("Контекстное меню"),
            [Qt.Key.Key_Menu, "Shift+F10"],
            self.show_context_menu,
        )
        self._build_menubar()
        self._stack.currentChanged.connect(lambda _index: self._sync_context())
        self.viewer.contextMenuRequested.connect(self._on_photo_menu)
        self._sync_context()
        self._app.changed.connect(self._on_setting_changed)
        if theme is not None:
            theme.changed.connect(self._on_theme_changed)
        self._apply_appearance()
        self._restore_window()

    def _build_menubar(self) -> None:
        """Строка меню из тех же действий, что у горячих клавиш и контекстных меню."""
        reg = self.registry
        file_menu = self.menuBar().addMenu(self.tr("Файл"))
        for action_id in (
            "open",
            "-",
            "rename",
            "delete_file",
            "reveal",
            "copy_path",
            "properties",
        ):
            if action_id == "-":
                file_menu.addSeparator()
            else:
                file_menu.addAction(reg[action_id])
        file_menu.addSeparator()
        file_menu.addAction(reg["settings"])
        file_menu.addSeparator()
        file_menu.addAction(reg["quit"])
        edit_menu = self.menuBar().addMenu(self.tr("Правка"))
        for action_id in (
            "edit",
            "back_to_view",
            "-",
            "undo",
            "redo",
            "-",
            "copy_image",
            "copy_result",
            "paste_image",
            "-",
            "save",
            "export",
            "save_as",
        ):
            if action_id == "-":
                edit_menu.addSeparator()
            else:
                edit_menu.addAction(reg[action_id])

    # --- контекстные меню --------------------------------------------------------------------

    def _screen_context(self) -> str:
        """Какой экран открыт: от него зависит, какие действия и клавиши включены."""
        current_widget = self._stack.currentWidget()
        if current_widget is self.viewer:
            return PHOTO
        if self.video_page is not None and current_widget is self.video_page:
            return VIDEO
        if self.editor is not None and current_widget is self.editor:
            return PHOTO_EDITOR
        if self.video_editor is not None and current_widget is self.video_editor:
            return VIDEO_EDITOR
        return START

    def _sync_context(self) -> None:
        self.registry.set_context(self._screen_context())

    def _popup(self, menu: ThemedMenu, pos: QPoint) -> None:
        self._open_menu = menu  # меню живёт, пока открыто
        menu.popup(pos)

    def _on_photo_menu(self, pos: QPoint) -> None:
        if self._screen_context() == PHOTO:
            self._popup(self.menus.photo(), pos)

    def _on_video_menu(self, pos: QPoint) -> None:
        context = self._screen_context()
        if context == VIDEO:
            self._popup(self.menus.video(), pos)
        elif context == VIDEO_EDITOR:
            self._popup(self.menus.editor_preview(), pos)

    def _on_editor_menu(self, pos: QPoint) -> None:
        if self._screen_context() == PHOTO_EDITOR:
            self._popup(self.menus.editor_preview(), pos)

    def _on_video_editor_menu(self, kind: str, pos: QPoint, payload: object) -> None:
        if kind == "preview":
            self._popup(self.menus.editor_preview(), pos)
        elif kind == "timeline":
            data = payload if isinstance(payload, tuple) else None
            self._popup(self.menus.timeline(data), pos)
        elif kind == "effects" and isinstance(payload, list) and payload:
            self._popup(self.menus.effects(payload), pos)

    def show_context_menu(self) -> None:
        """Клавиша Menu и Shift+F10: меню текущего экрана у указателя или в центре окна."""
        menu = self.menus.for_context()
        if menu is None:
            return
        centre = self._stack.mapToGlobal(self._stack.rect().center())
        cursor = QCursor.pos()
        inside = self._stack.rect().contains(self._stack.mapFromGlobal(cursor))
        self._popup(menu, cursor if inside else centre)

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
        wants_new_window = self._app.get_str("general.open_in") == "new"
        if self.current_path is not None and wants_new_window and self._open_in_new_window(path):
            return
        if not self._leave_editors():
            return
        self._save_resume()
        self._recent.add(path)
        self._drop_zone.set_recent(self._recent.items())
        if kind is MediaKind.IMAGE:
            self._stop_video()
            self._nav = FolderNav(path)
            if self._app.get_str("general.open_mode") == "edit":
                self._open_in_editor(path)
            else:
                self._show(path)
        else:
            self._open_video(path)

    def _open_in_new_window(self, path: Path) -> bool:
        """Запускает ещё одно окно программы с этим файлом; False — запустить не удалось."""
        if getattr(sys, "frozen", False):
            program, arguments = sys.executable, [str(path)]
        else:
            program, arguments = sys.executable, ["-m", "chopchop", str(path)]
        return bool(QProcess.startDetached(program, arguments))

    def _open_in_editor(self, path: Path) -> None:
        from chopchop.editor.session import EditSession

        self._stop_video()
        self.current_path = path
        self._update_title()
        self._open_editor(EditSession(path, parent=self, proxy_side=self._preview_side()))

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
        self._showing_reduced = False
        image = self._cache.get(path)
        if image is not None:
            self._display(image)
        else:
            # сначала быстрый уменьшенный вариант (если формат умеет), затем полный
            self._cache.request_reduced(path, self._viewer_side())
            self._cache.request(path)

    def _viewer_side(self) -> int:
        """Сколько пикселей нужно длинной стороне картинки, чтобы окно выглядело чётко."""
        size = self.viewer.viewport().size()
        return max(1024, round(max(size.width(), size.height()) * self.devicePixelRatioF()))

    def _on_reduced_loaded(self, path: Path, image: QImage) -> None:
        if path != self.current_path or self._nav is None or self._cache.get(path) is not None:
            return
        self._showing_reduced = True
        self.viewer.set_image(image)
        self._stack.setCurrentWidget(self.viewer)
        self.statusBar().showMessage(f"{image.width()}×{image.height()}")

    def _display(self, image: QImage) -> None:
        if self._showing_reduced:
            self._showing_reduced = False
            self.viewer.replace_image(image)
        else:
            self.viewer.set_image(image)
        self._stack.setCurrentWidget(self.viewer)
        self.statusBar().showMessage(f"{image.width()}×{image.height()}")
        if self._nav is not None:
            ahead = self._app.get_int("photo.preload")
            for neighbor in self._nav.neighbors(ahead, 1 if ahead else 0):
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
        """Показан плеер (в том числе внутри видеоредактора): работают клавиши воспроизведения."""
        if self.video_page is None:
            return False
        return self._stack.currentWidget() is self.video_page or self._on_video_editor()

    def _ensure_video_page(self) -> VideoPage | None:
        if self.video_page is not None:
            return self.video_page
        try:
            module = load_mpv_module()
            mpv = create_mpv(module, player_prefs(self._app))
        except MpvUnavailableError as error:
            hint = self.tr(
                "Не удалось загрузить libmpv. Положите libmpv-2.dll (Windows) "
                "рядом с программой или установите libmpv (Linux)."
            )
            QMessageBox.warning(self, self.tr("Плеер недоступен"), f"{hint}\n\n{error}")
            return None
        page = VideoPage(module, mpv, settings=self._app, presets=self._presets)
        page.editRequested.connect(self.toggle_editor)
        page.contextMenuRequested.connect(self._on_video_menu)
        page.subtitleSettingsRequested.connect(lambda: self.show_settings("subtitles"))
        page.fullscreenRequested.connect(self.toggle_fullscreen)
        page.player.errorOccurred.connect(self._on_video_error)
        page.player.ended.connect(self._on_video_ended)
        page.player.apply_prefs(player_prefs(self._app))
        page.player.pausedChanged.connect(lambda _paused: self._save_resume())
        self._stack.addWidget(page)
        self.video_page = page
        return page

    def _open_video(self, path: Path) -> None:
        page = self._ensure_video_page()
        if page is None:
            return
        self._nav = None
        self._video_nav = FolderNav(path, VIDEO_EXTENSIONS)
        self.current_path = path
        self._video_path = path
        self._update_title()
        self.statusBar().clearMessage()
        self._zoom_label.clear()
        self._stack.setCurrentWidget(page)
        page.set_title(path.name)
        resume = self._resume.load(path)
        if resume is not None and not self._app.get_bool("playback.remember_position"):
            resume.position = 0.0  # позицию не возобновляем; дорожки и громкость остаются
        page.player.load(path, resume)
        page.wake()

    def show_start(self) -> None:
        """Ничего не открыто (например, удалён последний файл папки): стартовый экран."""
        self._nav = None
        self._video_nav = None
        self.current_path = None
        self._video_path = None
        self._zoom_label.clear()
        self._stack.setCurrentWidget(self._drop_zone)
        self.setWindowTitle("CHOPCHOP")
        self.statusBar().clearMessage()

    def _on_video_ended(self) -> None:
        """Файл доигран: следующее видео в папке, повтор или возврат на стартовый экран."""
        if not self._on_video_page() or self._on_video_editor() or self.video_page is None:
            return
        nav = self._video_nav
        has_next = nav is not None and nav.index + 1 < len(nav.files)
        if self._app.get_bool("playback.autoplay_next") and nav is not None and has_next:
            self._open_video(nav.files[nav.index + 1])
            return
        action = self._app.get_str("playback.end_action")
        if action == "loop":
            self.video_page.player.seek_to(0.0, exact=True)
            if self.video_page.player.paused:
                self.video_page.player.toggle_pause()
        elif action == "close":
            self._stop_video()
            self._stack.setCurrentWidget(self._drop_zone)
            self.setWindowTitle("CHOPCHOP")

    def _on_video_error(self, _message: str) -> None:
        name = self._video_path.name if self._video_path else ""
        self.statusBar().showMessage(self.tr("Не удалось воспроизвести: ") + name, 8000)

    def _stop_video(self) -> None:
        if self.video_page is not None and self._video_path is not None:
            self.video_page.player.stop()
        self._video_path = None

    def _save_resume(self) -> None:
        if self.video_editor is not None:
            return  # в редакторе плеер показывает другие клипы и обрезки
        if self.video_page is not None and self._video_path is not None:
            player = self.video_page.player
            self._resume.save(self._video_path, player.state(), player.duration)

    def _with_player(self, action: Callable[[Player], object]) -> None:
        if self._on_video_page() and self.video_page is not None:
            action(self.video_page.player)

    def _horizontal(self, direction: int) -> None:
        if self._on_editor():
            return
        if self._on_video_editor() and self.video_editor is not None:
            self.video_editor.step_frame(direction)  # в редакторе стрелки — по кадрам
            return
        if self._on_video_page():
            self._with_player(
                lambda p: p.seek(direction * self._app.get_int("playback.seek_short"))
            )
        else:
            self.step(direction)

    def _seek_long(self, direction: int) -> None:
        if self._on_editor() or not self._on_video_page():
            return
        if self._on_video_editor() and self.video_editor is not None:
            self.video_editor.step_seconds(direction)  # в редакторе Shift + стрелки — секунда
            return
        self._with_player(lambda p: p.seek(direction * self._app.get_int("playback.seek_long")))

    def _change_speed(self, player: Player, direction: int) -> None:
        player.add_speed(direction * self._app.get_float("playback.speed_step"))
        self.statusBar().showMessage(f"{player.speed:g}×", 2000)

    def _reset_speed(self, player: Player) -> None:
        player.set_speed(1.0)
        self.statusBar().showMessage("1×", 2000)

    def _volume(self, delta: float) -> None:
        self._with_player(lambda p: p.add_volume(delta))

    def show_settings(self, section: object = "") -> None:
        dialog = SettingsDialog(self._app, self, self._presets)
        if isinstance(section, str) and section:
            dialog.open_section(section)  # быстрая панель плеера ведёт сразу в «Субтитры»
        dialog.exec()
        self._app.flush()

    def _on_setting_changed(self, key: str, _value: object) -> None:
        """Настройка изменилась (в окне настроек, сбросом или импортом): применяем на лету."""
        section = key.split(".", 1)[0]
        if section == "appearance":
            self._apply_appearance()
            return
        if key in ("playback.fs_panel", "playback.fs_progress_line", "playback.hide_delay"):
            if self.video_page is not None:
                self.video_page.set_fullscreen(self.isFullScreen())
            return
        if section in ("playback", "subtitles") and self.video_page is not None:
            self.video_page.player.apply_prefs(player_prefs(self._app))
        elif section == "photo":
            self._apply_viewer_settings()
        elif key == "advanced.temp_dir":
            temp_files.set_root(Path(self._app.get_str(key)) if self._app.get_str(key) else None)
        elif key == "advanced.log_level":
            logs.set_level(self._app.get_str(key))

    def _apply_appearance(self) -> None:
        """Тема, акцент, плотность, анимации и пиксельные заголовки из настроек, на лету."""
        app = self._app
        anim.set_enabled(app.get_bool("appearance.animations"))
        current.set_pixel_titles(app.get_bool("appearance.pixel_titles"))
        if self._theme is not None:
            self._theme.set_theme(
                app.get_str("appearance.theme"),
                app.get_str("appearance.accent"),
                compact=app.get_bool("appearance.compact"),
            )
        else:
            self._on_theme_changed(current.palette())

    def _on_theme_changed(self, _palette: object) -> None:
        self._drop_zone.refresh_theme()
        self.registry.refresh_icons()
        if self.video_page is not None:
            self.video_page.refresh_theme()
        if self.editor is not None:
            self.editor.refresh_theme()
        if self.video_editor is not None:
            self.video_editor.refresh_theme()
        self.viewer.setBackgroundBrush(QColor(self._app.get_str("photo.background")))
        self.update()

    def _apply_viewer_settings(self) -> None:
        app = self._app
        self.viewer.apply_settings(
            fit_mode=app.get_str("photo.fit_mode"),
            zoom_step=app.get_float("photo.zoom_step"),
            wheel_action=app.get_str("photo.wheel_action"),
            background=app.get_str("photo.background"),
            smoothing=app.get_str("photo.smoothing"),
        )

    def _restore_window(self) -> None:
        saved = self._app.get_str("state.window")
        if self._app.get_bool("general.remember_window") and saved:
            self.restoreGeometry(QByteArray.fromBase64(saved.encode("ascii", "ignore")))

    def _remember_window(self) -> None:
        if self._app.get_bool("general.remember_window") and not self.isFullScreen():
            encoded = bytes(self.saveGeometry().toBase64().data()).decode("ascii")
            self._app.set("state.window", encoded)

    # --- редактор ----------------------------------------------------------------------------

    def _tool_slot(self, tool: str) -> Callable[[], object]:
        def select() -> None:
            self._with_editor(lambda e: e.select_tool(tool))

        return select

    def _on_editor(self) -> bool:
        return self.editor is not None and self._stack.currentWidget() is self.editor

    def _on_video_editor(self) -> bool:
        return self.video_editor is not None and self._stack.currentWidget() is self.video_editor

    def _with_editor(self, action: Callable[["EditorPage | VideoEditorPage"], object]) -> None:
        """Действие для текущего редактора: фото или видео (у них общие имена методов)."""
        if self._on_editor() and self.editor is not None:
            action(self.editor)
        elif self._on_video_editor() and self.video_editor is not None:
            action(self.video_editor)

    def _with_video_editor(self, action: Callable[["VideoEditorPage"], object]) -> None:
        if self._on_video_editor() and self.video_editor is not None:
            action(self.video_editor)

    def _copy(self) -> None:
        self._with_editor(lambda e: e.copy_result())

    def _escape(self) -> None:
        if self.isFullScreen():
            self.exit_fullscreen()
        else:
            self._with_editor(lambda e: e.escape())

    def toggle_editor(self) -> None:
        if self._on_editor() or self._on_video_editor():
            self._with_editor(lambda e: e.request_exit())
        elif self._stack.currentWidget() is self.viewer and self.current_path is not None:
            from chopchop.editor.session import EditSession

            self._open_editor(
                EditSession(self.current_path, parent=self, proxy_side=self._preview_side())
            )
        elif self._stack.currentWidget() is self.video_page and self._video_path is not None:
            self._open_video_editor(self._video_path)

    def paste_image(self) -> None:
        image = QApplication.clipboard().image()
        if image.isNull():
            self.statusBar().showMessage(self.tr("В буфере обмена нет картинки"), 5000)
            return
        from chopchop.editor.session import EditSession
        from chopchop.ui.pil_qt import qimage_to_pil

        self._open_editor(
            EditSession(None, qimage_to_pil(image), parent=self, proxy_side=self._preview_side())
        )

    def _preview_side(self) -> int:
        """Размер превью редактора по окну и плотности экрана: больше — только лишние расчёты."""
        size = self._stack.size()
        side = round(max(size.width(), size.height()) * self.devicePixelRatioF())
        return min(max(side, MIN_PREVIEW_SIDE), MAX_PREVIEW_SIDE)

    def _open_editor(self, session: "EditSession") -> None:
        if self._on_editor():
            return
        self._discard_session()
        self._session = session
        session.loaded.connect(lambda: self._show_editor(session))
        session.loadFailed.connect(self._on_editor_load_failed)
        self.statusBar().showMessage(self.tr("Загрузка…"))
        session.start()

    def _on_editor_load_failed(self, error: str) -> None:
        self._discard_session()
        self.statusBar().showMessage(
            self.tr("Не удалось открыть для редактирования: ") + error, 8000
        )

    def _discard_session(self) -> None:
        if self._session is not None:
            self._session.wait()
            self._session.deleteLater()
            self._session = None

    def _show_editor(self, session: "EditSession") -> None:
        from chopchop.ui.editor_page import EditorPage

        if session is not self._session:
            return
        self._stop_video()
        if self.editor is not None:
            self._stack.removeWidget(self.editor)
            self.editor.deleteLater()
        self.editor = EditorPage(session, self._app)
        self.editor.message.connect(lambda text: self.statusBar().showMessage(text, 8000))
        self.editor.exitRequested.connect(self._leave_editor)
        self.editor.menuRequested.connect(self._on_editor_menu)
        self._stack.addWidget(self.editor)
        self._stack.setCurrentWidget(self.editor)
        self._zoom_label.clear()
        name = session.source.name if session.source else self.tr("Из буфера обмена")
        self.setWindowTitle(f"{name} — {self.tr('редактор')} — CHOPCHOP")
        self.statusBar().clearMessage()

    def _leave_editor(self) -> None:
        if self.editor is None:
            return
        self._stack.removeWidget(self.editor)
        self.editor.deleteLater()
        self.editor = None
        self._discard_session()
        if self._nav is not None and self.current_path is not None:
            if not self.viewer.has_image():
                self._show(self.current_path)  # открыли сразу в редакторе: просмотр ещё пуст
            self._stack.setCurrentWidget(self.viewer)
            self._update_title()
            self.statusBar().showMessage(self.tr("Просмотр"), 3000)
        else:
            self._stack.setCurrentWidget(self._drop_zone)
            self.setWindowTitle("CHOPCHOP")

    # --- редактор видео ----------------------------------------------------------------------

    def _open_video_editor(self, path: Path) -> None:
        from chopchop.engines.probe import probe

        ffmpeg, ffprobe = find_ffmpeg(), find_ffprobe()
        if ffmpeg is None or ffprobe is None:
            self.statusBar().showMessage(
                self.tr(
                    "Для редактора видео нужны ffmpeg и ffprobe (рядом с программой или в PATH)"
                ),
                8000,
            )
            return
        self.statusBar().showMessage(self.tr("Анализ видео…"))
        self._tasks.run(
            lambda: probe(path, ffprobe),
            lambda info: self._show_video_editor(path, info, ffmpeg, ffprobe),
            lambda error: self.statusBar().showMessage(
                self.tr("Не удалось прочитать видео: ") + error, 8000
            ),
        )

    def _show_video_editor(self, path: Path, info: MediaInfo, ffmpeg: Path, ffprobe: Path) -> None:
        from chopchop.core.video import Clip, VideoProject
        from chopchop.editor.video_session import VideoSession
        from chopchop.ui.video_editor_page import VideoEditorPage

        if self.video_page is None or self._video_path != path or self.video_editor is not None:
            return
        self._save_resume()
        session = VideoSession(VideoProject((Clip(path, info),)), self)
        self._stack.removeWidget(self.video_page)
        editor = VideoEditorPage(
            session, self.video_page, ffmpeg, ffprobe, settings=self._app, actions=self.registry
        )
        editor.menuRequested.connect(self._on_video_editor_menu)
        editor.message.connect(lambda text: self.statusBar().showMessage(text, 8000))
        editor.exitRequested.connect(self._leave_video_editor)
        self.video_editor = editor
        self._stack.addWidget(editor)
        self._stack.setCurrentWidget(editor)
        self.statusBar().hide()  # у редактора своя строка состояния
        self.setWindowTitle(f"{path.name} — {self.tr('редактор')} — CHOPCHOP")
        self.statusBar().clearMessage()

    def _leave_video_editor(self) -> None:
        editor = self.video_editor
        if editor is None:
            return
        editor.shutdown()
        page = editor.release_video_page()
        self.video_editor = None
        self.statusBar().show()
        self._stack.removeWidget(editor)
        editor.deleteLater()
        self._stack.addWidget(page)
        self._stack.setCurrentWidget(page)
        if editor.loaded_path is not None:
            self._video_path = self.current_path = editor.loaded_path
        self._update_title()
        self.statusBar().showMessage(self.tr("Просмотр"), 3000)

    def _leave_editors(self) -> bool:
        """Закрывает редакторы перед открытием другого файла; False — пользователь отказался."""
        if self.video_editor is not None:
            if self.video_editor.session.modified and not self._confirm_discard():
                return False
            self._leave_video_editor()
        if self.editor is not None:
            if self.editor.session.modified and not self._confirm_discard():
                return False
            self._leave_editor()
        return True

    def _confirm_discard(self) -> bool:
        answer = QMessageBox.question(
            self, self.tr("Несохранённые правки"), self.tr("Закрыть редактор без сохранения?")
        )
        return answer == QMessageBox.StandardButton.Yes

    # --- окно --------------------------------------------------------------------------------

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.exit_fullscreen()
        elif self._stack.currentWidget() in (self.viewer, self.video_page):
            self.statusBar().hide()
            self.menuBar().hide()
            self.showFullScreen()
            if self.video_page is not None:
                self.video_page.set_fullscreen(True)

    def exit_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
            self.statusBar().show()
            self.menuBar().show()
            if self.video_page is not None:
                self.video_page.set_fullscreen(False)

    def _update_title(self) -> None:
        if self.current_path is None:
            return
        position = ""
        if self._nav is not None:
            position = f" ({self._nav.index + 1}/{len(self._nav.files)})"
        self.setWindowTitle(f"{self.current_path.name}{position} — CHOPCHOP")

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        pending = (self.editor and self.editor.session.modified) or (
            self.video_editor and self.video_editor.session.modified
        )
        if pending:
            answer = QMessageBox.question(
                self,
                self.tr("Несохранённые правки"),
                self.tr("Закрыть редактор без сохранения?"),
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        if self._session is not None:
            self._session.wait()
        if self.video_editor is not None:
            self.video_editor.shutdown()
        self._tasks.wait()
        self._save_resume()
        self._cache.wait()
        self._remember_window()
        self._app.flush()
        if self.video_page is not None:
            self.video_page.release()
        super().closeEvent(event)
