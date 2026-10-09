"""Панель плеера: пауза, перемотка, громкость, меню дорожек, полный экран."""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QToolButton,
    QWidget,
)

from chopchop.core.tracks import Track, TrackKind, of_kind
from chopchop.player.player import VOLUME_MAX, Player
from chopchop.ui.click_slider import ClickSlider

SEEK_RESOLUTION = 1000
SUBTITLE_FILTER = "*.srt *.ass *.ssa *.vtt *.sub"


def format_time(seconds: float) -> str:
    total = max(int(seconds), 0)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02}:{secs:02}" if hours else f"{minutes}:{secs:02}"


class PlayerControls(QWidget):
    fullscreenRequested = Signal()

    def __init__(self, player: Player, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._player = player
        self._duration = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "PlayerControls { background: rgba(0, 0, 0, 200); }"
            "QLabel, QToolButton, QPushButton { color: white; }"
            "QToolButton::menu-indicator { image: none; }"
        )

        self._play = QPushButton("▶")
        self._play.setFixedWidth(40)
        self._play.setFlat(True)
        self._play.clicked.connect(player.toggle_pause)

        self._time = QLabel("0:00 / 0:00")
        self._seek = ClickSlider(Qt.Orientation.Horizontal)
        self._seek.setRange(0, SEEK_RESOLUTION)
        self._seek.sliderMoved.connect(self._on_seek_moved)
        self._seek.sliderReleased.connect(self._on_seek_released)

        self._volume = ClickSlider(Qt.Orientation.Horizontal)
        self._volume.setRange(0, int(VOLUME_MAX))
        self._volume.setFixedWidth(90)
        self._volume.setValue(100)
        self._volume.valueChanged.connect(lambda v: player.set_volume(float(v)))

        self._audio_menu = QMenu(self)
        self._sub_menu = QMenu(self)
        self._sub2_menu = QMenu(self)
        audio = self._menu_button(self.tr("Аудио"), self._audio_menu)
        sub = self._menu_button(self.tr("Субтитры 1"), self._sub_menu)
        sub2 = self._menu_button(self.tr("Субтитры 2"), self._sub2_menu)

        full = QPushButton("⛶")
        full.setFlat(True)
        full.setFixedWidth(36)
        full.clicked.connect(self.fullscreenRequested)

        layout = QHBoxLayout(self)
        layout.addWidget(self._play)
        layout.addWidget(self._time)
        layout.addWidget(self._seek, 1)
        for widget in (QLabel(self.tr("Громк.")), self._volume, audio, sub, sub2, full):
            layout.addWidget(widget)

        player.positionChanged.connect(self._on_position)
        player.durationChanged.connect(self._on_duration)
        player.pausedChanged.connect(self._on_paused)
        player.volumeChanged.connect(self._on_volume)
        player.tracksChanged.connect(self.rebuild_menus)
        self.rebuild_menus()

    def _menu_button(self, text: str, menu: QMenu) -> QToolButton:
        button = QToolButton()
        button.setText(text)
        button.setMenu(menu)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        return button

    # --- обновление от плеера ----------------------------------------------------------------

    def _on_position(self, seconds: float) -> None:
        if not self._seek.isSliderDown() and self._duration > 0:
            self._seek.setValue(int(seconds / self._duration * SEEK_RESOLUTION))
        self._time.setText(f"{format_time(seconds)} / {format_time(self._duration)}")

    def _on_duration(self, seconds: float) -> None:
        self._duration = seconds

    def _on_paused(self, paused: bool) -> None:
        self._play.setText("▶" if paused else "⏸")

    def _on_volume(self, value: float) -> None:
        if not self._volume.isSliderDown():
            self._volume.blockSignals(True)
            self._volume.setValue(int(value))
            self._volume.blockSignals(False)

    def _on_seek_moved(self, value: int) -> None:
        if self._duration > 0:
            self._player.seek_to(value / SEEK_RESOLUTION * self._duration)

    def _on_seek_released(self) -> None:
        """Ползунок отпустили: окончательная перемотка точно на выбранный кадр."""
        if self._duration > 0:
            self._player.seek_to(self._seek.value() / SEEK_RESOLUTION * self._duration, exact=True)

    # --- меню дорожек ------------------------------------------------------------------------

    def rebuild_menus(self) -> None:
        tracks = self._player.tracks()
        self._fill(
            self._audio_menu, of_kind(tracks, "audio"), self._player.audio_id(), False,
            self._player.set_audio, "audio",
        )  # fmt: skip
        self._fill(
            self._sub_menu, of_kind(tracks, "sub"), self._player.sub_id(), True,
            self._player.set_sub, "sub",
        )  # fmt: skip
        self._fill(
            self._sub2_menu, of_kind(tracks, "sub"), self._player.sub2_id(), True,
            self._player.set_sub2, "sub",
        )  # fmt: skip

    def _fill(
        self,
        menu: QMenu,
        tracks: list[Track],
        current: int | None,
        allow_off: bool,
        apply: Callable[[int | None], None],
        kind: TrackKind,
    ) -> None:
        menu.clear()
        group = QActionGroup(menu)
        if allow_off:
            self._add_choice(menu, group, self.tr("Выключено"), current is None, None, apply)
        for track in tracks:
            self._add_choice(menu, group, track.label, track.id == current, track.id, apply)
        if kind == "sub":
            menu.addSeparator()
            load = menu.addAction(self.tr("Загрузить файл…"))
            load.triggered.connect(self.choose_subtitle_file)

    def _add_choice(
        self,
        menu: QMenu,
        group: QActionGroup,
        text: str,
        checked: bool,
        track_id: int | None,
        apply: Callable[[int | None], None],
    ) -> None:
        action = QAction(text, menu)
        action.setCheckable(True)
        action.setChecked(checked)
        action.triggered.connect(lambda _=False, tid=track_id: apply(tid))
        group.addAction(action)
        menu.addAction(action)

    def choose_subtitle_file(self) -> None:
        name, _ = QFileDialog.getOpenFileName(
            self, self.tr("Субтитры"), "", self.tr("Субтитры (%1)").replace("%1", SUBTITLE_FILTER)
        )
        if name:
            self._player.add_subtitle(Path(name))
