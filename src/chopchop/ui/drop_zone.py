"""Стартовый экран: зона «перетащите файл» с пиксельной иллюстрацией, кнопка «Открыть», недавние."""

from pathlib import Path

from PySide6.QtCore import QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDropEvent,
    QPainter,
    QPaintEvent,
)
from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from chopchop.ui.theme import current, fonts, tokens
from chopchop.ui.theme.tokens import Palette, blend

ART_WIDTH, ART_HEIGHT = 40, 26  # размер иллюстрации в «пикселях»
ART_UNIT = 8  # сторона пикселя иллюстрации на экране
DASH, GAP = 12, 8
FRAME_MARGIN = tokens.SPACE_6
FORMATS = "JPG · PNG · WebP · HEIC · BMP · GIF · TIFF   |   MP4 · MKV · AVI · MOV · WebM"


def paint_illustration(painter: QPainter, p: Palette, unit: int = ART_UNIT) -> None:
    """Пиксельная графика: карточка с пейзажем и перед ней кадр с кнопкой воспроизведения."""

    def block(x: int, y: int, w: int, h: int, color: str) -> None:
        painter.fillRect(QRect(x * unit, y * unit, w * unit, h * unit), QColor(color))

    def card(x: int, y: int, w: int, h: int, fill: str) -> None:
        block(x + 1, y + 1, w, h, p.shadow)  # жёсткая тень
        block(x, y, w, h, p.border_strong)
        block(x + 1, y + 1, w - 2, h - 2, fill)

    sky = blend(p.secondary, p.surface_raised, 0.35)
    # карточка с фото: небо, солнце, холмы
    card(1, 2, 24, 17, p.surface_raised)
    block(3, 4, 20, 11, sky)
    block(17, 5, 4, 4, p.accent)
    block(18, 4, 2, 6, p.accent)
    block(16, 6, 6, 2, p.accent)
    block(3, 11, 20, 4, p.success)
    block(3, 12, 9, 3, blend(p.success, p.text, 0.25))
    block(13, 10, 6, 1, p.success)
    block(14, 9, 3, 1, p.success)
    block(4, 16, 8, 1, p.border)
    block(4, 17, 5, 1, p.border)
    # кадр видео поверх: тёмный экран и кнопка воспроизведения
    card(15, 10, 23, 14, blend(p.text, p.surface, 0.9))
    block(17, 12, 19, 10, blend(p.text, p.secondary, 0.85))
    for step, width in enumerate((2, 4, 6, 8, 6, 4, 2)):
        block(24, 14 + step, 1, 1, p.accent)
        block(24, 14 + step, width, 1, p.accent)
    block(17, 20, 19, 1, blend(p.text, p.surface, 0.8))
    block(17, 20, 7, 1, p.accent)


class Illustration(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(QSize(ART_WIDTH * ART_UNIT, ART_HEIGHT * ART_UNIT))
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        paint_illustration(painter, current.palette())


class DropZone(QWidget):
    fileChosen = Signal(Path)
    openRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._dragging = False

        self._art = Illustration()
        self._hint = QLabel(self.tr("Перетащите фото или видео"))
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setFont(fonts.ui_font(fonts.TITLE))
        self._formats = QLabel(FORMATS)
        self._formats.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._formats.setProperty("muted", True)

        self._open_button = QPushButton(self.tr("Открыть…"))
        self._open_button.setProperty("variant", "primary")
        self._open_button.setMinimumWidth(180)
        self._open_button.clicked.connect(self.openRequested)

        self._recent_label = QLabel(self.tr("Последние файлы"))
        self._recent_label.setFont(fonts.ui_font(fonts.BODY))
        self._recent = QListWidget()
        self._recent.setMaximumHeight(176)
        self._recent.setMaximumWidth(460)
        self._recent.itemActivated.connect(self._on_recent_activated)
        self._recent.itemClicked.connect(self._on_recent_activated)

        layout = QVBoxLayout(self)
        layout.setSpacing(tokens.SPACE_3)
        layout.addStretch(1)
        layout.addWidget(self._art, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._hint)
        layout.addWidget(self._formats)
        layout.addSpacing(tokens.SPACE_2)
        layout.addWidget(self._open_button, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(tokens.SPACE_4)
        layout.addWidget(self._recent_label, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._recent, alignment=Qt.AlignmentFlag.AlignCenter)
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

    @property
    def dragging(self) -> bool:
        return self._dragging

    # --- рамка из чёрточек ------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        p = current.palette()
        color = QColor(p.accent if self._dragging else p.border_strong)
        inside = self.rect().adjusted(FRAME_MARGIN, FRAME_MARGIN, -FRAME_MARGIN, -FRAME_MARGIN)
        if self._dragging:
            tint = QColor(p.accent)
            tint.setAlpha(28)
            painter.fillRect(inside, tint)
        rect = QRectF(inside)
        thickness = tokens.BORDER_WIDTH * (2 if self._dragging else 1)
        x = rect.left()
        while x < rect.right():
            length = min(DASH, rect.right() - x)
            painter.fillRect(QRectF(x, rect.top(), length, thickness), color)
            painter.fillRect(QRectF(x, rect.bottom() - thickness, length, thickness), color)
            x += DASH + GAP
        y = rect.top()
        while y < rect.bottom():
            length = min(DASH, rect.bottom() - y)
            painter.fillRect(QRectF(rect.left(), y, thickness, length), color)
            painter.fillRect(QRectF(rect.right() - thickness, y, thickness, length), color)
            y += DASH + GAP

    def refresh_theme(self) -> None:
        self._hint.setFont(fonts.ui_font(fonts.TITLE))
        self._recent_label.setFont(fonts.ui_font(fonts.BODY))
        self.update()

    # --- перетаскивание ----------------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            self._dragging = True
            self.update()
            event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:  # noqa: N802
        self._dragging = False
        self.update()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        self._dragging = False
        self.update()
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.fileChosen.emit(Path(url.toLocalFile()))
                event.acceptProposedAction()
                return
