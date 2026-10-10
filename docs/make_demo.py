"""Записывает docs/demo.gif из настоящего окна программы: python docs/make_demo.py.

Нужны ffmpeg и libmpv (как для обычной работы). Кадры снимает window.grab(), поэтому
скрипт запускают на обычном рабочем столе, без QT_QPA_PLATFORM=offscreen. Правки добавляются
через сессии редакторов, а не мышью: так демо не зависит от положения элементов в окне.
Меню снимается отдельным окном и накладывается на снимок там, где открылось.
"""

import math
import os
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageDraw
from PySide6.QtCore import QPoint, QSettings
from PySide6.QtGui import QContextMenuEvent, QImage, QPainter, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
if sys.platform == "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "windows")

from chopchop import i18n  # noqa: E402
from chopchop.core.geometry import Rect  # noqa: E402
from chopchop.core.operations import Annotate, Crop, Redact, Stroke, Text  # noqa: E402
from chopchop.core.video import RemoveRange, SplitAt  # noqa: E402
from chopchop.engines.fonts import find_font  # noqa: E402
from chopchop.services.app_settings import AppSettings  # noqa: E402
from chopchop.ui.main_window import MainWindow  # noqa: E402
from chopchop.ui.theme import fonts  # noqa: E402
from chopchop.ui.theme.manager import ThemeManager  # noqa: E402
from media import make_video  # noqa: E402

WINDOW = (1100, 680)
GIF_WIDTH = 800
FRAME_MS = 1200
frames: list[tuple[Image.Image, int]] = []


def make_photo(path: Path) -> None:
    """Пейзаж с табличкой, текст на которой потом скрываем."""
    width, height = 1600, 1000
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    for y in range(height):
        t = y / height
        draw.line(
            [(0, y), (width, y)], fill=(int(250 - 140 * t), int(150 + 20 * t), int(90 + 130 * t))
        )
    draw.ellipse((1050, 170, 1290, 410), fill=(255, 236, 170))
    draw.polygon([(0, 640), (260, 360), (520, 590), (760, 330), (1100, 640)], fill=(86, 70, 110))
    draw.polygon(
        [(500, 700), (900, 450), (1300, 640), (1600, 420), (1600, 760), (500, 760)],
        fill=(60, 52, 90),
    )
    draw.rectangle((0, 700, width, height), fill=(30, 64, 110))
    for i in range(14):
        y = 730 + i * 20
        draw.line([(0, y), (width, y + 6)], fill=(60, 110, 160), width=2)
    draw.rectangle((140, 420, 620, 620), fill=(240, 240, 230), outline=(60, 40, 30), width=6)
    draw.text((170, 470), "WIFI PASSWORD", fill=(40, 40, 40), font=find_font(44))
    draw.text((170, 540), "sunset-2026", fill=(180, 30, 30), font=find_font(52))
    draw.rectangle((364, 620, 396, 780), fill=(60, 40, 30))
    image.save(path, quality=95)


def wait(ms: int) -> None:
    QTest.qWait(ms)


def wait_until(condition: Callable[[], bool], timeout_ms: int = 15000) -> None:
    """Ждём нужного состояния, а не фиксированное время: первый запуск окна бывает медленным."""
    waited = 0
    while not condition() and waited < timeout_ms:
        QTest.qWait(50)
        waited += 50
    if not condition():
        raise SystemExit("не дождались нужного состояния окна")


def add_frame(pixmap: QPixmap, hold: int) -> None:
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB888)
    pil = Image.frombytes(
        "RGB",
        (image.width(), image.height()),
        bytes(image.constBits()),
        "raw",
        "RGB",
        image.bytesPerLine(),
    )
    pil = pil.resize(
        (GIF_WIDTH, round(pil.height * GIF_WIDTH / pil.width)), Image.Resampling.LANCZOS
    )
    frames.append((pil, hold))


def settle(editor: object) -> None:
    """Ждёт, пока превью редактора фото пересчитается после правки."""
    wait(200)
    wait_until(lambda: not editor.session.is_busy)  # type: ignore[attr-defined]
    wait(600)


def snap(window: MainWindow, hold: int = FRAME_MS) -> None:
    add_frame(window.grab(), hold)


def snap_menu(window: MainWindow, target: QWidget, point: QPoint, hold: int = 1800) -> None:
    """Правый щелчок на виджете: кадр окна вместе с открывшимся меню."""
    event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point, target.mapToGlobal(point))
    QApplication.sendEvent(target, event)
    wait(500)
    menu = QApplication.activePopupWidget()
    if menu is None:
        raise SystemExit("меню не открылось")
    canvas = window.grab()
    origin = window.mapFromGlobal(menu.pos())
    painter = QPainter(canvas)
    # меню у нижнего края окна поднимаем, чтобы оно не обрезалось в кадре
    x = max(0, min(origin.x(), window.width() - menu.width()))
    y = max(0, min(origin.y(), window.height() - menu.height()))
    painter.drawPixmap(QPoint(x, y), menu.grab())
    painter.end()
    add_frame(canvas, hold)
    menu.close()
    wait(200)


def main() -> None:
    work = Path(tempfile.mkdtemp(prefix="chopchop-demo-"))
    photo, video = work / "sunset.jpg", work / "trip.mp4"
    make_photo(photo)
    make_video(video, seconds=12, size=(960, 540))

    app = QApplication([])
    fonts.load_fonts()
    i18n.install_language(app, "ru")
    settings = AppSettings(None)
    settings.set("appearance.theme", "light")
    window = MainWindow(
        QSettings(str(work / "s.ini"), QSettings.Format.IniFormat), settings, ThemeManager(app)
    )
    window.resize(*WINDOW)
    window.show()
    wait(700)
    snap(window, 1500)  # стартовый экран

    window.open_file(photo)
    wait_until(window.viewer.has_image)
    wait(300)
    snap(window)  # просмотр фото
    snap_menu(window, window.viewer.viewport(), QPoint(260, 160))

    window.toggle_editor()
    wait_until(lambda: window.editor is not None)
    editor = window.editor
    assert editor is not None
    wait_until(lambda: editor.session.is_ready)
    wait(400)
    snap(window)
    session = editor.session
    # скрыть текст на табличке, нарисовать отметку, стрелку и обрезать кадр
    session.add_full(Redact(Rect(150, 455, 470, 160), mode="pixelate", strength=22))
    settle(editor)
    snap(window)
    session.add_full(
        Stroke(
            tuple((700 + i * 18, 280 + 40 * math.sin(i / 3)) for i in range(34)), (255, 255, 255), 8
        )
    )
    session.add_full(Annotate("arrow", (900, 860), (400, 640), (255, 230, 0), 8))
    settle(editor)
    snap(window)
    session.add_full(Crop(Rect(80, 160, 1440, 810)))
    settle(editor)
    snap(window)
    session.mark_saved()
    window.toggle_editor()
    wait_until(lambda: window.editor is None)

    # видео: плеер, вырез из середины, текст, меню на полосе обрезки
    window.open_file(video)
    wait_until(lambda: window.video_page is not None and bool(window.video_page.player.duration))
    wait(1500)
    snap(window)
    window.toggle_editor()
    wait_until(lambda: window.video_editor is not None)
    video_editor = window.video_editor
    assert video_editor is not None
    wait(1500)
    video_editor.session.cut(SplitAt(0, 8.0))
    video_editor.session.cut(RemoveRange(0, 4.0, 6.0))
    video_editor.session.add_text(Text("Привет из отпуска!", 60, 440, 48.0, (255, 255, 255)))
    wait(1500)
    video_editor._video_page.player.seek_to(2.0, exact=True)
    wait(500)
    snap(window, 1800)
    trim = video_editor.trim
    snap_menu(window, trim, QPoint(int(trim._x(2.0)), trim.height() // 2))
    video_editor.session.mark_saved()
    window.close()
    app.quit()

    frames[0][0].save(
        ROOT / "docs" / "demo.gif",
        save_all=True,
        append_images=[frame for frame, _ in frames[1:]],
        duration=[hold for _, hold in frames],
        loop=0,
        optimize=True,
    )
    size = (ROOT / "docs" / "demo.gif").stat().st_size / 1024 / 1024
    print(f"docs/demo.gif: {len(frames)} кадров, {size:.1f} МБ")


if __name__ == "__main__":
    main()
