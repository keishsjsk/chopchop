"""Скриншоты контекстных меню: docs/design/menu-<экран>-<тема>.png.

Запуск (нужны libmpv, ffmpeg и настоящий экран, поэтому не offscreen):
    python docs/design/make_menu_screens.py [папка]

Правый щелчок отправляется в окно настоящим событием мыши, поэтому снимок заодно проверяет, что
ПКМ над OpenGL-виджетом плеера доходит до обработчика. Меню — отдельное окно: оно снимается
само и накладывается на снимок окна в том месте, где открылось.
"""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
if sys.platform == "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "windows")

from PIL import Image, ImageDraw  # noqa: E402
from PySide6.QtCore import QPoint, QSettings, QSize, Qt  # noqa: E402
from PySide6.QtGui import QContextMenuEvent, QPainter, QPixmap  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from chopchop import i18n  # noqa: E402
from chopchop.core.geometry import Rect  # noqa: E402
from chopchop.core.operations import Redact, Text  # noqa: E402
from chopchop.core.video import RemoveRange, SplitAt  # noqa: E402
from chopchop.services.app_settings import AppSettings  # noqa: E402
from chopchop.ui.main_window import MainWindow  # noqa: E402
from chopchop.ui.theme import fonts  # noqa: E402
from chopchop.ui.theme.manager import ThemeManager  # noqa: E402
from media import make_video  # noqa: E402

SIZE = (1280, 720)


def wait(ms: int) -> None:
    QTest.qWait(ms)


def until(condition, timeout_ms: int = 8000) -> bool:  # type: ignore[no-untyped-def]
    waited = 0
    while not condition() and waited < timeout_ms:
        QTest.qWait(50)
        waited += 50
    return bool(condition())


def make_photo(path: Path) -> Path:
    """Пейзаж-заглушка: небо, солнце, холмы (чтобы меню было видно на живой картинке)."""
    image = Image.new("RGB", (1600, 1000))
    draw = ImageDraw.Draw(image)
    for y in range(1000):
        shade = int(150 + 80 * y / 1000)
        draw.line([(0, y), (1600, y)], fill=(90, shade - 30, min(shade + 40, 255)))
    draw.ellipse((1100, 120, 1260, 280), fill=(255, 220, 120))
    draw.polygon(
        [(0, 1000), (0, 700), (400, 560), (800, 720), (1200, 580), (1600, 740), (1600, 1000)],
        fill=(60, 110, 70),
    )
    image.save(path, quality=92)
    return path


def snap_with_menu(window: MainWindow, name: str, out: Path) -> None:
    """Снимок окна и открытого меню: холст по объединению, если меню выше или шире окна."""
    wait(500)
    menu = QApplication.activePopupWidget()
    assert menu is not None, f"{name}: меню не открылось"
    ratio = window.devicePixelRatioF()
    base = window.grab()
    shot = menu.grab()
    origin = window.mapFromGlobal(menu.pos())
    left = min(0, origin.x())
    top = min(0, origin.y())
    right = max(window.width(), origin.x() + menu.width())
    bottom = max(window.height(), origin.y() + menu.height())
    canvas = QPixmap(round((right - left) * ratio), round((bottom - top) * ratio))
    canvas.setDevicePixelRatio(ratio)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.drawPixmap(QPoint(-left, -top), base)
    painter.drawPixmap(QPoint(origin.x() - left, origin.y() - top), shot)
    painter.end()
    canvas.save(str(out / f"menu-{name}.png"))
    print("saved", name, canvas.width(), "x", canvas.height())
    menu.close()
    wait(200)


def right_click(window: MainWindow, widget, point: QPoint) -> None:  # type: ignore[no-untyped-def]
    """Настоящий правый щелчок мыши средствами ОС (Windows), иначе событие меню вручную.

    Так проверяется путь «ОС → окно Qt → OpenGL-виджет → обработчик». Перед щелчком проверяем,
    что под точкой наше окно, чтобы не нажать в чужую программу.
    """
    global_point = widget.mapToGlobal(point)
    top = QApplication.widgetAt(global_point)
    if sys.platform == "win32" and top is not None and window.isAncestorOf(top):
        import ctypes

        window.activateWindow()
        wait(150)
        ratio = widget.devicePixelRatioF()
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        user32.SetCursorPos(round(global_point.x() * ratio), round(global_point.y() * ratio))
        wait(100)
        user32.mouse_event(0x0008, 0, 0, 0, 0)  # RIGHTDOWN
        user32.mouse_event(0x0010, 0, 0, 0, 0)  # RIGHTUP
        wait(300)
        if QApplication.activePopupWidget() is not None:
            return
    event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point, global_point)
    QApplication.sendEvent(widget, event)
    print("предупреждение: меню открыто искусственным событием, а не щелчком ОС")


def capture(
    name: str, work: Path, photo: Path, video: Path, theme_manager: ThemeManager, out: Path
) -> None:
    settings = AppSettings(None)
    settings.set("appearance.theme", name)
    window = MainWindow(
        QSettings(str(work / f"{name}.ini"), QSettings.Format.IniFormat),
        settings,
        theme_manager,
    )
    window.resize(QSize(*SIZE))
    window.show()
    wait(400)

    # --- фото
    window.open_file(photo)
    until(lambda: window.viewer.has_image())
    wait(300)
    centre = window.viewer.viewport().rect().center()
    right_click(window, window.viewer.viewport(), centre)
    snap_with_menu(window, f"photo-{name}", out)

    # --- видео: правый щелчок над настоящим кадром mpv (OpenGL)
    window.open_file(video)
    until(lambda: window.video_page is not None and window.video_page.player.duration)
    wait(800)
    assert window.video_page is not None
    right_click(window, window.video_page.video, window.video_page.video.rect().center())
    snap_with_menu(window, f"video-{name}", out)

    # --- редактор: меню на полосе обрезки, над призраком вырезанного
    window.toggle_editor()
    until(lambda: window.video_editor is not None)
    editor = window.video_editor
    assert editor is not None
    editor.session.cut(SplitAt(0, 8.0))
    editor.session.cut(RemoveRange(0, 4.0, 6.0))
    editor.session.add_redact(Redact(Rect(100, 80, 260, 140)))
    editor.session.add_text(Text("CHOPCHOP", 700, 560, 52))
    wait(800)
    editor._video_page.player.seek_to(2.0, exact=True)
    wait(400)
    point = QPoint(int(editor.trim._x(2.0)), editor.trim.height() // 2)
    right_click(window, editor.trim, point)
    snap_with_menu(window, f"editor-{name}", out)
    editor.session.mark_saved()
    window.close()
    wait(300)


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "design"
    app = QApplication([])
    fonts.load_fonts()
    fonts.apply(app, "monocraft")
    i18n.install_language(app, "ru")
    work = Path(tempfile.mkdtemp(prefix="chopchop-menus-"))
    photo = make_photo(work / "пейзаж.jpg")
    video = make_video(work / "demo.mp4", seconds=12, size=SIZE)
    theme_manager = ThemeManager(app)
    for name in ("light", "dark"):
        capture(name, work, photo, video, theme_manager, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
