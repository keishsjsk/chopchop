"""Выдвижная боковая панель: звуковые дорожки и две строки субтитров вместо выпадающих меню."""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSize, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from chopchop.core.tracks import Track, of_kind
from chopchop.player.player import Player
from chopchop.ui.floating import FloatingPanel
from chopchop.ui.theme import fonts, tokens

SUBTITLE_FILTER = "*.srt *.ass *.ssa *.vtt *.sub"
PANEL_WIDTH = 320


class TracksPanel(FloatingPanel):
    closed = Signal()

    def __init__(self, player: Player, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._player = player
        self._groups: list[QButtonGroup] = []
        self.setFixedWidth(PANEL_WIDTH)

        title = QLabel(self.tr("Дорожки и субтитры"))
        title.setFont(fonts.pixel_font(2))
        self._close = QPushButton("×")
        self._close.setProperty("variant", "flat")
        self._close.setFixedWidth(tokens.MIN_HIT)
        self._close.clicked.connect(self.closed)
        header = QHBoxLayout()
        header.addWidget(title, 1)
        header.addWidget(self._close)

        self._body = QVBoxLayout()
        self._body.setSpacing(tokens.SPACE_1)
        holder = QWidget()
        holder.setLayout(self._body)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(holder)
        scroll.viewport().setAutoFillBackground(False)
        holder.setAutoFillBackground(False)

        self._load = QPushButton(self.tr("Загрузить файл субтитров…"))
        self._load.clicked.connect(self.choose_subtitle_file)

        layout = self.vertical(tokens.SPACE_2)
        layout.addLayout(header)
        layout.addWidget(scroll, 1)
        layout.addWidget(self._load)
        player.tracksChanged.connect(self.rebuild)
        self.rebuild()
        self.hide()

    # --- содержимое --------------------------------------------------------------------------

    def rebuild(self) -> None:
        while self._body.count():
            item = self._body.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        self._groups.clear()
        tracks = self._player.tracks()
        sub_tracks = of_kind(tracks, "sub")
        self._section(
            self.tr("Звук"),
            of_kind(tracks, "audio"),
            self._player.audio_id(),
            False,
            self._player.set_audio,
        )
        self._section(
            self.tr("Субтитры 1"), sub_tracks, self._player.sub_id(), True, self._player.set_sub
        )
        self._section(
            self.tr("Субтитры 2"), sub_tracks, self._player.sub2_id(), True, self._player.set_sub2
        )
        self._body.addStretch(1)

    def _section(
        self,
        title: str,
        tracks: list[Track],
        current: int | None,
        allow_off: bool,
        apply: Callable[[int | None], None],
    ) -> None:
        heading = QLabel(title)
        heading.setFont(fonts.pixel_font(2))
        heading.setContentsMargins(0, tokens.SPACE_2, 0, 0)
        self._body.addWidget(heading)
        group = QButtonGroup(self)
        self._groups.append(group)
        if allow_off:
            self._add_choice(group, self.tr("Выключено"), current is None, None, apply)
        for track in tracks:
            self._add_choice(group, track.label, track.id == current, track.id, apply)
        if not tracks and not allow_off:
            empty = QLabel(self.tr("Нет дорожек"))
            empty.setProperty("muted", True)
            self._body.addWidget(empty)

    def _add_choice(
        self,
        group: QButtonGroup,
        text: str,
        checked: bool,
        track_id: int | None,
        apply: Callable[[int | None], None],
    ) -> None:
        button = QRadioButton(text)
        button.setChecked(checked)
        button.setMinimumHeight(tokens.MIN_HIT)
        button.toggled.connect(lambda on, tid=track_id: apply(tid) if on else None)
        group.addButton(button)
        self._body.addWidget(button)

    def choice_count(self) -> int:
        return sum(len(group.buttons()) for group in self._groups)

    def choose_subtitle_file(self) -> None:
        name, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Субтитры"),
            "",
            self.tr("Субтитры (%1)").replace("%1", SUBTITLE_FILTER),
        )
        if name:
            self._player.add_subtitle(Path(name))

    def sizeHint(self) -> QSize:
        return QSize(PANEL_WIDTH, 420)
