"""Страница видео: кадр mpv на всё окно и плавающие панели поверх него.

Панели (верхняя с названием, нижняя с управлением, боковая с дорожками) и курсор прячутся после
паузы в движении мыши и возвращаются от мыши или клавиши. В полном экране нижняя панель
компактнее, а когда она спрятана, остаётся тонкая линия прогресса.
"""

from types import ModuleType
from typing import Any

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QContextMenuEvent, QImage, QPainter, QPaintEvent, QResizeEvent
from PySide6.QtWidgets import QApplication, QWidget

from chopchop.engines.ffmpeg import find_ffmpeg
from chopchop.player.mpv_widget import create_video_widget
from chopchop.player.player import Player
from chopchop.services.app_settings import AppSettings
from chopchop.services.sub_presets import PresetStore
from chopchop.ui.context_gate import menu_allowed
from chopchop.ui.player_controls import PlayerControls, PreviewBubble
from chopchop.ui.theme import current, tokens
from chopchop.ui.top_bar import TopBar
from chopchop.ui.tracks_panel import TracksPanel
from chopchop.workers.thumbs_worker import ThumbnailLoader

HIDE_DELAY_MS = 2500
THUMB_COUNT = 40
GAP = tokens.SPACE_4
FULLSCREEN_GAP = tokens.SPACE_6  # отступ плавающей панели от нижнего края в полном экране
MINI_LINE = 3


class MiniProgress(QWidget):
    """Тонкая линия прогресса внизу окна, пока панель спрятана."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._fraction = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFixedHeight(MINI_LINE)
        self.hide()

    def set_fraction(self, value: float) -> None:
        self._fraction = min(max(value, 0.0), 1.0)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        p = current.palette()
        scrim = QColor(*p.scrim)
        painter.fillRect(self.rect(), scrim)
        painter.fillRect(
            QRectF(0, 0, self.width() * self._fraction, self.height()), QColor(p.accent)
        )


class VideoPage(QWidget):
    fullscreenRequested = Signal()
    subtitleSettingsRequested = Signal()
    contextMenuRequested = Signal(QPoint)  # ПКМ над видео или его панелями

    def __init__(
        self,
        module: ModuleType,
        mpv: Any,
        parent: QWidget | None = None,
        settings: AppSettings | None = None,
        presets: PresetStore | None = None,
    ) -> None:
        super().__init__(parent)
        self._app = settings or AppSettings(None)
        self._fullscreen = False
        self._editor_mode = False
        self._duration = 0.0
        self._thumb_path: str | None = None
        self._thumbs: list[QImage | None] = []
        ffmpeg = find_ffmpeg()
        self._loader = ThumbnailLoader(ffmpeg, self) if ffmpeg is not None else None
        if self._loader is not None:
            self._loader.thumbnail.connect(self._on_thumbnail)

        self.player = Player(mpv, self)
        self.video = create_video_widget(module, mpv, self)
        self.controls = PlayerControls(self.player, self)
        self.top = TopBar(self)
        self.tracks = TracksPanel(self.player, self, self._app, presets)
        self.bubble = PreviewBubble(self)
        self.mini = MiniProgress(self)
        for panel in (self.controls, self.top, self.tracks, self.bubble, self.mini):
            panel.raise_()

        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.timeout.connect(self.player.toggle_pause)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._hide_idle)

        self.video.renderContextRecreated.connect(self.player.restore_video)
        self.video.clicked.connect(self._on_click)
        self.video.doubleClicked.connect(self._on_double_click)
        self.video.mouseMoved.connect(self.wake)
        self.controls.fullscreenRequested.connect(self.fullscreenRequested)
        self.controls.tracksRequested.connect(self.toggle_tracks)
        self.tracks.closed.connect(self.toggle_tracks)
        self.tracks.openAllRequested.connect(self.subtitleSettingsRequested)
        self.controls._seek.hovered.connect(self._on_progress_hover)
        self.controls._seek.left.connect(self.bubble.hide)
        self.player.pausedChanged.connect(lambda paused: self.wake() if paused else None)
        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)
        self.player.fileLoaded.connect(self._on_file_loaded)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._place()

    # --- состояние ---------------------------------------------------------------------------

    def set_title(self, name: str) -> None:
        self.top.set_name(name)

    @property
    def fullscreen(self) -> bool:
        return self._fullscreen

    def set_fullscreen(self, value: bool) -> None:
        """Полный экран: панель компактная (по настройке), отступ снизу больше."""
        self._fullscreen = value
        compact = value and self._app.get_str("playback.fs_panel") == "compact"
        self.controls.set_compact(compact)
        self.controls.set_fullscreen(value)
        self._place()
        self.wake()

    def refresh_theme(self) -> None:
        self.controls.refresh_theme()
        self.top.refresh_theme()
        self.update()

    def set_editor_mode(self, value: bool) -> None:
        """В редакторе плавающих панелей нет: управление лежит в строке транспорта редактора."""
        self._editor_mode = value
        if value:
            self._hide_timer.stop()
            for panel in (self.controls, self.top, self.tracks, self.bubble, self.mini):
                panel.hide()
            self.video.unsetCursor()

    def toggle_tracks(self) -> None:
        if self._editor_mode:
            return
        if self.tracks.isVisible():
            self.tracks.disappear()
        else:
            self._place()
            self.tracks.appear()
            self.wake()

    # --- панели ------------------------------------------------------------------------------

    def _place(self) -> None:
        width, height = self.width(), self.height()
        self.video.setGeometry(self.rect())
        gap = FULLSCREEN_GAP if self._fullscreen else GAP
        panel_width = min(width - 2 * GAP, self.controls.max_width)
        panel_width = max(panel_width, 0)
        bottom = self.controls.height()
        self.controls.setGeometry(
            (width - panel_width) // 2,
            height - bottom - gap + self.controls.reserve,  # отступ считается от видимой рамки
            panel_width,
            bottom,
        )
        self.top.setGeometry(GAP, GAP, max(width - 2 * GAP, 0), self.top.height())
        drawer_top = self.top.y() + self.top.height() + tokens.SPACE_2
        drawer_height = max(self.controls.y() - tokens.SPACE_2 - drawer_top, 120)
        self.tracks.setGeometry(
            width - self.tracks.width() - GAP, drawer_top, self.tracks.width(), drawer_height
        )
        self.mini.setGeometry(0, height - MINI_LINE, width, MINI_LINE)
        for widget in (self.controls, self.top, self.tracks, self.bubble, self.mini):
            widget.raise_()

    def hide_delay_ms(self) -> int:
        return round(self._app.get_float("playback.hide_delay") * 1000)

    def wake(self) -> None:
        """Показать панели и курсор; спрятать снова, если мышь неподвижна."""
        if self._editor_mode:
            return
        self.controls.appear()
        self.top.appear()
        self.mini.hide()
        self.video.unsetCursor()
        self._hide_timer.start(self.hide_delay_ms())

    def _busy(self) -> bool:
        """Прятать нельзя, пока курсор над панелью, открыта боковая панель или меню."""
        pointer_over = self.controls.is_pointer_inside() or self.top.underMouse()
        popup = QApplication.activePopupWidget() is not None
        return pointer_over or self.tracks.isVisible() or popup or self.player.paused

    def _hide_idle(self) -> None:
        if self._busy():
            self._hide_timer.start(self.hide_delay_ms())
            return
        self.controls.disappear()
        self.top.disappear()
        self.bubble.hide()
        if self._fullscreen and self._app.get_bool("playback.fs_progress_line"):
            self.mini.show()
            self.mini.raise_()
        if self.isActiveWindow():
            self.video.setCursor(Qt.CursorShape.BlankCursor)

    # --- миниатюры и подсказка на линии прогресса --------------------------------------------

    def _on_file_loaded(self) -> None:
        self._thumbs = []
        self._thumb_path = None
        self._request_thumbs()

    def _on_duration(self, seconds: float) -> None:
        self._duration = seconds
        self.mini.set_fraction(0.0)
        self._request_thumbs()

    def _request_thumbs(self) -> None:
        path = self.player.current
        if self._loader is None or path is None or self._duration <= 0:
            return
        if self._thumb_path == str(path) and self._thumbs:
            return
        self._thumb_path = str(path)
        self._thumbs = self._loader.request(path, self._duration, THUMB_COUNT)

    def _on_thumbnail(self, path: str, index: int, image: QImage) -> None:
        if path == self._thumb_path and 0 <= index < len(self._thumbs):
            self._thumbs[index] = image

    def _thumb_at(self, seconds: float) -> QImage | None:
        if not self._thumbs or self._duration <= 0:
            return None
        index = min(int(seconds / self._duration * len(self._thumbs)), len(self._thumbs) - 1)
        return self._thumbs[index]

    def _on_progress_hover(self, seconds: float, point: QPoint) -> None:
        x = self.controls._seek.mapTo(self, point).x()
        anchor = QPoint(x, self.controls.y() - tokens.SPACE_2)  # над панелью, а не над линией
        self.bubble.show_at(anchor, seconds, self._thumb_at(seconds))

    def _on_position(self, seconds: float) -> None:
        if self._duration > 0:
            self.mini.set_fraction(seconds / self._duration)

    # --- мышь --------------------------------------------------------------------------------

    def _on_click(self) -> None:
        # одиночный клик ждёт, не станет ли он двойным (полный экран)
        self._click_timer.start(QApplication.doubleClickInterval())

    def _on_double_click(self) -> None:
        self._click_timer.stop()
        self.fullscreenRequested.emit()

    def release(self) -> None:
        self._hide_timer.stop()
        self._click_timer.stop()
        if self._loader is not None:
            self._loader.cancel()
            self._loader.wait()
        self.video.release()
        self.player.shutdown()

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802
        """Меню — отдельное окно, поэтому OpenGL под ним не мешает; события панелей доходят сюда."""
        if menu_allowed():
            self.contextMenuRequested.emit(event.globalPos())
            event.accept()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._place()
