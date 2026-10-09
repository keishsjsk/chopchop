"""Нижняя плавающая панель плеера: пауза, время, линия прогресса, громкость, дорожки, полный экран.

Линия прогресса тонкая и утолщается при наведении, показывает время и миниатюру кадра. Громкость
сворачивается в значок и раскрывается при наведении. Дорожки и субтитры живут в боковой панели.
В полноэкранном режиме панель компактнее: «таблетка» до 720 px по центру.
"""

from collections.abc import Callable

from PySide6.QtCore import QEvent, QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QEnterEvent, QImage, QMouseEvent, QPainter, QPaintEvent, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QToolButton, QWidget

from chopchop.player.player import VOLUME_MAX, Player
from chopchop.ui import anim
from chopchop.ui.click_slider import ClickSlider
from chopchop.ui.floating import FloatingPanel
from chopchop.ui.theme import current, icons, tokens

SEEK_RESOLUTION = 1000
SUBTITLE_FILTER = "*.srt *.ass *.ssa *.vtt *.sub"
LINE_THIN = 4  # толщина линии прогресса в покое
LINE_THICK = 8  # при наведении
LINE_HEIGHT = 24  # высота области нажатия
VOLUME_WIDTH = 96
COMPACT_MAX_WIDTH = 720
NORMAL_ICON = 32
COMPACT_ICON = 16
BUBBLE_THUMB_WIDTH = 160


def format_time(seconds: float) -> str:
    total = max(int(seconds), 0)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02}:{secs:02}" if hours else f"{minutes}:{secs:02}"


class ProgressLine(QWidget):
    """Тонкая линия прогресса: клик и перетаскивание перематывают, наведение показывает кадр."""

    seekRequested = Signal(float)  # секунды; пока тянем (по ключевым кадрам)
    seekFinished = Signal(float)  # отпустили: точная перемотка
    hovered = Signal(float, QPoint)  # секунды под курсором и точка над линией (в её координатах)
    left = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._duration = 0.0
        self._position = 0.0
        self._thickness = float(LINE_THIN)
        self._hover_x: float | None = None
        self._dragging = False
        self.setMouseTracking(True)
        self.setFixedHeight(LINE_HEIGHT)
        self.setMinimumWidth(80)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    # --- данные ------------------------------------------------------------------------------

    @property
    def thickness(self) -> float:
        return self._thickness

    def set_duration(self, seconds: float) -> None:
        self._duration = max(seconds, 0.0)
        self.update()

    def set_position(self, seconds: float) -> None:
        if not self._dragging:
            self._position = seconds
            self.update()

    @property
    def fraction(self) -> float:
        return min(self._position / self._duration, 1.0) if self._duration > 0 else 0.0

    def _seconds_at(self, x: float) -> float:
        if self._duration <= 0 or self.width() <= 0:
            return 0.0
        return min(max(x / self.width(), 0.0), 1.0) * self._duration

    # --- толщина при наведении ---------------------------------------------------------------

    def _set_thickness(self, value: float) -> None:
        self._thickness = value
        self.update()

    def enterEvent(self, event: QEnterEvent) -> None:  # noqa: N802
        anim.tween(self._thickness, LINE_THICK, tokens.HOVER_MS, self._set_thickness, self)

    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802
        self._hover_x = None
        if not self._dragging:
            anim.tween(self._thickness, LINE_THIN, tokens.HOVER_MS, self._set_thickness, self)
        self.left.emit()
        self.update()

    # --- мышь --------------------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._duration > 0:
            self._dragging = True
            self._seek(event.position().x(), final=False)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        x = event.position().x()
        self._hover_x = x
        if self._dragging:
            self._seek(x, final=False)
        if self._duration > 0:
            self.hovered.emit(self._seconds_at(x), QPoint(round(x), 0))
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self._seek(event.position().x(), final=True)
            if not self.underMouse():
                anim.tween(self._thickness, LINE_THIN, tokens.HOVER_MS, self._set_thickness, self)

    def _seek(self, x: float, final: bool) -> None:
        seconds = self._seconds_at(x)
        self._position = seconds
        self.update()
        (self.seekFinished if final else self.seekRequested).emit(seconds)

    # --- рисование ---------------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        p = current.palette()
        thickness = round(self._thickness / 2) * 2  # чётная толщина: линия ровно по пикселям
        top = (self.height() - thickness) / 2
        track = QRectF(0, top, self.width(), thickness)
        painter.fillRect(track, QColor(p.border))
        painter.fillRect(QRectF(0, top, self.width() * self.fraction, thickness), QColor(p.accent))
        if self._hover_x is not None or self._dragging:
            knob = tokens.SPACE_3
            x = self.width() * self.fraction
            rect = QRectF(
                min(max(x - knob / 2, 0), self.width() - knob),
                (self.height() - knob) / 2,
                knob,
                knob,
            )
            painter.fillRect(rect, QColor(p.text))
            painter.fillRect(rect.adjusted(2, 2, -2, -2), QColor(p.accent))
            if self._hover_x is not None:
                painter.fillRect(
                    QRectF(self._hover_x - 1, top - 2, 2, thickness + 4), QColor(p.text_muted)
                )


class PreviewBubble(FloatingPanel):
    """Подсказка над линией прогресса: кадр и время."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._image = QLabel()
        self._image.setFixedSize(BUBBLE_THUMB_WIDTH, BUBBLE_THUMB_WIDTH * 9 // 16)
        self._image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._time = QLabel()
        self._time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = self.vertical(tokens.SPACE_1)
        layout.addWidget(self._image)
        layout.addWidget(self._time)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.hide()

    def show_at(self, anchor: QPoint, seconds: float, thumb: QImage | None) -> None:
        """anchor — центр нижнего края подсказки в координатах родителя."""
        self._time.setText(format_time(seconds))
        has_thumb = thumb is not None and not thumb.isNull()
        self._image.setVisible(has_thumb)
        if has_thumb and thumb is not None:
            scaled = thumb.scaledToWidth(
                BUBBLE_THUMB_WIDTH, Qt.TransformationMode.SmoothTransformation
            )
            self._image.setPixmap(QPixmap.fromImage(scaled))
        self.adjustSize()
        parent = self.parentWidget()
        width = self.sizeHint().width()
        x = anchor.x() - width // 2
        if parent is not None:
            x = min(max(x, tokens.SPACE_2), parent.width() - width - tokens.SPACE_2)
        self.resize(self.sizeHint())
        self.move(x, anchor.y() - self.height())
        self.raise_()
        if not self.isVisible():
            self.show()


class VolumeControl(QWidget):
    """Значок громкости, ползунок раскрывается при наведении."""

    def __init__(
        self,
        player: Player,
        make_button: Callable[[str], QToolButton],
        set_icon: Callable[[QToolButton, str], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._player = player
        self._set_icon = set_icon
        self._muted = False
        self._volume = 100.0
        self._width = 0.0
        self._button = make_button("volume")
        self._button.clicked.connect(player.toggle_mute)
        self.slider = ClickSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, int(VOLUME_MAX))
        self.slider.setValue(100)
        self.slider.setFixedWidth(0)
        self.slider.valueChanged.connect(lambda value: player.set_volume(float(value)))
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(tokens.SPACE_1)
        row.addWidget(self._button)
        row.addWidget(self.slider)
        player.volumeChanged.connect(self.set_volume)
        player.muteChanged.connect(self.set_muted)

    def set_volume(self, value: float) -> None:
        self._volume = value
        if not self.slider.isSliderDown():
            self.slider.blockSignals(True)
            self.slider.setValue(int(value))
            self.slider.blockSignals(False)
        self.refresh_icon()

    def set_muted(self, muted: bool) -> None:
        self._muted = muted
        self.refresh_icon()

    def refresh_icon(self) -> None:
        silent = self._muted or self._volume <= 0
        self._set_icon(self._button, "mute" if silent else "volume")

    def _resize_slider(self, width: float) -> None:
        self._width = width
        self.slider.setFixedWidth(round(width))

    def enterEvent(self, event: QEnterEvent) -> None:  # noqa: N802
        anim.tween(self._width, VOLUME_WIDTH, tokens.PANEL_MS, self._resize_slider, self)

    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802
        if not self.slider.isSliderDown():
            anim.tween(self._width, 0, tokens.PANEL_MS, self._resize_slider, self)


class PlayerControls(FloatingPanel):
    fullscreenRequested = Signal()
    tracksRequested = Signal()

    def __init__(self, player: Player, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._player = player
        self._duration = 0.0
        self._compact = False
        self._paused = True
        self._fullscreen = False
        self._buttons: dict[QToolButton, str] = {}

        self._play = self._make_button("play")
        self._play.clicked.connect(player.toggle_pause)
        self._time = QLabel("0:00 / 0:00")
        self._time.setMinimumWidth(110)
        self._seek = ProgressLine()
        self._seek.seekRequested.connect(self._on_seek_moved)
        self._seek.seekFinished.connect(self._on_seek_released)
        self.volume = VolumeControl(player, self._make_button, self._set_button_icon)
        self._tracks = self._make_button("subtitles")
        self._tracks.setToolTip(self.tr("Дорожки и субтитры"))
        self._tracks.clicked.connect(self.tracksRequested)
        self._full = self._make_button("fullscreen")
        self._full.setToolTip(self.tr("Полный экран"))
        self._full.clicked.connect(self.fullscreenRequested)
        self._play.setToolTip(self.tr("Пауза"))

        row = self.horizontal(tokens.SPACE_2)
        row.addWidget(self._play)
        row.addWidget(self._time)
        row.addWidget(self._seek, 1)
        row.addWidget(self.volume)
        row.addWidget(self._tracks)
        row.addWidget(self._full)
        self._row = row

        player.positionChanged.connect(self._on_position)
        player.durationChanged.connect(self._on_duration)
        player.pausedChanged.connect(self._on_paused)
        self.apply_size()

    # --- вид ---------------------------------------------------------------------------------

    def _make_button(self, icon_name: str) -> QToolButton:
        button = QToolButton()
        button.setCheckable(False)
        button.setFocusPolicy(
            Qt.FocusPolicy.TabFocus
        )  # кольцо фокуса только при работе с клавиатуры
        self._buttons[button] = icon_name
        self._set_button_icon(button, icon_name)
        return button

    def _set_button_icon(self, button: QToolButton, name: str) -> None:
        self._buttons[button] = name
        size = COMPACT_ICON if self._compact else NORMAL_ICON
        button.setIcon(icons.qicon(name, current.palette(), logical=size))
        button.setIconSize(QSize(size, size))

    def apply_size(self) -> None:
        """Обычная панель 64 px и значки 32, компактная (полный экран) — 44 px и значки 16."""
        size = COMPACT_ICON if self._compact else NORMAL_ICON
        side = tokens.MIN_HIT if self._compact else tokens.RAIL_BUTTON
        for button, name in self._buttons.items():
            button.setIcon(icons.qicon(name, current.palette(), logical=size))
            button.setIconSize(QSize(size, size))
            button.setFixedSize(side, side)
        padding = tokens.SPACE_1 // 2 if self._compact else tokens.SPACE_2
        edge = tokens.BORDER_WIDTH + padding
        self._row.setContentsMargins(edge, edge, edge + self.reserve, edge + self.reserve)
        self.setFixedHeight(side + 2 * edge + self.reserve)
        self.updateGeometry()

    @property
    def compact(self) -> bool:
        return self._compact

    def set_compact(self, value: bool) -> None:
        if value != self._compact:
            self._compact = value
            self.apply_size()
            self._refresh_state_icons()

    def set_fullscreen(self, value: bool) -> None:
        self._fullscreen = value
        self._set_button_icon(self._full, "exit_fullscreen" if value else "fullscreen")
        self._full.setToolTip(
            self.tr("Выйти из полного экрана") if value else self.tr("Полный экран")
        )

    def _refresh_state_icons(self) -> None:
        self._on_paused(self._paused)
        self.set_fullscreen(self._fullscreen)
        self.volume.refresh_icon()

    @property
    def max_width(self) -> int:
        return COMPACT_MAX_WIDTH if self._compact else 16777215

    # --- обновление от плеера ----------------------------------------------------------------

    def _on_position(self, seconds: float) -> None:
        self._seek.set_position(seconds)
        self._time.setText(f"{format_time(seconds)} / {format_time(self._duration)}")

    def _on_duration(self, seconds: float) -> None:
        self._duration = seconds
        self._seek.set_duration(seconds)

    def _on_paused(self, paused: bool) -> None:
        self._paused = paused
        self._set_button_icon(self._play, "play" if paused else "pause")
        self._play.setToolTip(self.tr("Пауза") if not paused else self.tr("Воспроизвести"))

    def _on_seek_moved(self, seconds: float) -> None:
        if self._duration > 0:
            self._player.seek_to(seconds)

    def _on_seek_released(self, seconds: float) -> None:
        """Линию отпустили: окончательная перемотка точно на выбранный кадр."""
        if self._duration > 0:
            self._player.seek_to(seconds, exact=True)

    def is_pointer_inside(self) -> bool:
        return self.underMouse() or self.volume.underMouse()

    # --- события ----------------------------------------------------------------------------

    def refresh_theme(self) -> None:
        """Значки перекрашиваются в цвета активной темы."""
        self.apply_size()
        self._refresh_state_icons()
