"""Записывает docs/demo.gif из настоящего окна программы: python docs/make_demo.py.

Нужны ffmpeg и libmpv (как для обычной работы). Кадры снимает window.grab(), поэтому
скрипт запускают на обычном рабочем столе, без QT_QPA_PLATFORM=offscreen.
"""

import math
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageDraw
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chopchop.core.operations import Text  # noqa: E402
from chopchop.engines.ffmpeg import find_ffmpeg  # noqa: E402
from chopchop.engines.fonts import find_font  # noqa: E402
from chopchop.ui.main_window import MainWindow  # noqa: E402

WINDOW = (1000, 640)
GIF_WIDTH = 760
FRAME_MS = 1100
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


def make_video(path: Path) -> None:
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        raise SystemExit("нужен ffmpeg")
    subprocess.run(
        [str(ffmpeg), "-y", "-loglevel", "error", "-f", "lavfi", "-i"]
        + ["gradients=s=640x360:d=10:speed=0.03:n=4", "-f", "lavfi", "-i", "sine=f=330:d=10"]
        + ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-g", "25", "-c:a", "aac", str(path)],
        check=True,
    )


def snap(window: MainWindow, hold: int = FRAME_MS) -> None:
    image = window.grab().toImage().convertToFormat(QImage.Format.Format_RGB888)
    pil = Image.frombytes("RGB", (image.width(), image.height()), bytes(image.constBits()))
    pil = pil.crop((0, 0, image.width(), image.height()))
    pil = pil.resize(
        (GIF_WIDTH, round(pil.height * GIF_WIDTH / pil.width)), Image.Resampling.LANCZOS
    )
    frames.append((pil, hold))


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


def stroke(window: MainWindow, points: list[tuple[float, float]]) -> None:
    canvas = window.editor.canvas  # type: ignore[union-attr]
    first = canvas.to_widget(*points[0]).toPoint()
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=first)
    for point in points[1:]:
        QTest.mouseMove(canvas, canvas.to_widget(*point).toPoint())
    QTest.mouseRelease(
        canvas, Qt.MouseButton.LeftButton, pos=canvas.to_widget(*points[-1]).toPoint()
    )


def drag(window: MainWindow, start: tuple[float, float], end: tuple[float, float]) -> None:
    stroke(window, [start, end])


def main() -> None:
    work = Path(tempfile.mkdtemp(prefix="chopchop-demo-"))
    photo, video = work / "sunset.jpg", work / "trip.mp4"
    make_photo(photo)
    make_video(video)

    app = QApplication([])
    window = MainWindow(QSettings(str(work / "s.ini"), QSettings.Format.IniFormat))
    window.resize(*WINDOW)
    window.show()
    wait(600)
    snap(window, 1400)  # стартовый экран

    window.open_file(photo)
    wait_until(window.viewer.has_image)
    wait(300)
    snap(window)  # просмотр фото

    QTest.keyClick(window, Qt.Key.Key_E, Qt.KeyboardModifier.ControlModifier)
    wait_until(lambda: window.editor is not None)
    wait(300)
    editor = window.editor
    assert editor is not None

    # скрыть текст на табличке: пикселизация
    QTest.keyClick(window, Qt.Key.Key_B)
    editor._redact_mode.setCurrentIndex(editor._redact_mode.findData("pixelate"))
    drag(window, (150, 455), (610, 610))
    wait(300)
    snap(window)
    QTest.keyClick(window, Qt.Key.Key_Return)
    wait(300)

    # рисование мышью: кисть и маркер
    QTest.keyClick(window, Qt.Key.Key_D)
    editor._shape.setCurrentIndex(editor._shape.findData("pen"))
    editor._draw_color.set_color((255, 255, 255))
    editor._on_draw_options()
    stroke(window, [(700 + i * 18, 280 + 40 * math.sin(i / 3)) for i in range(34)])
    wait(300)
    editor._shape.setCurrentIndex(editor._shape.findData("highlighter"))
    editor._draw_color.set_color((255, 230, 0))
    editor._on_draw_options()
    stroke(window, [(160 + i * 15, 860 + 8 * math.sin(i / 2)) for i in range(40)])
    wait(300)
    snap(window)

    # кадрирование: рамка сразу на весь кадр, пропорции на выбор
    QTest.keyClick(window, Qt.Key.Key_C)
    wait(300)
    snap(window)
    editor._ratio_bar.set_value(1.0)
    wait(300)
    snap(window)
    editor._ratio_bar.set_value(16 / 9)
    wait(300)
    snap(window)
    QTest.keyClick(window, Qt.Key.Key_Return)
    wait(500)
    snap(window)

    editor.session.mark_saved()
    QTest.keyClick(window, Qt.Key.Key_Escape)
    wait_until(lambda: window.editor is None)

    # видео: обрезка, текст и фильтр
    window.open_file(video)
    wait_until(lambda: window.video_page is not None)
    wait(2500)
    QTest.keyClick(window, Qt.Key.Key_E, Qt.KeyboardModifier.ControlModifier)
    wait_until(lambda: window.video_editor is not None)
    wait(3500)
    video_editor = window.video_editor
    assert video_editor is not None
    snap(window)
    video_editor.session.set_trim(0, 1.0, 8.0)
    video_editor.session.add_text(Text("Привет из отпуска!", 40, 290, 44.0, (255, 255, 255)))
    video_editor.session.set_filter("sepia")
    wait(2500)
    snap(window, 1800)
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
