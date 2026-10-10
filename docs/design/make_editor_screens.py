"""Скриншоты экрана видеоредактора: docs/design/video-editor-<тема>-<ширина>x<высота>.png.

Запуск (нужны libmpv, ffmpeg и настоящий экран, поэтому не offscreen):
    python docs/design/make_editor_screens.py [папка] [--sizes 1440x900,1280x720,960x600]

Скрипт открывает в окне программы сгенерированный ролик, входит в редактор, добавляет эффекты
и второй клип и снимает окно в светлой и тёмной темах. Показывает состояние «выбран инструмент»
(контекстная панель раскрыта) и, для самого большого размера, «инструмент не выбран».
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

from PySide6.QtCore import QSettings, QSize  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from chopchop import i18n  # noqa: E402
from chopchop.core.geometry import Rect  # noqa: E402
from chopchop.core.operations import Redact, Text  # noqa: E402
from chopchop.core.video import Clip  # noqa: E402
from chopchop.engines.probe import probe  # noqa: E402
from chopchop.services.app_settings import AppSettings  # noqa: E402
from chopchop.ui.main_window import MainWindow  # noqa: E402
from chopchop.ui.theme import fonts  # noqa: E402
from chopchop.ui.theme.manager import ThemeManager  # noqa: E402
from media import FFPROBE, make_video  # noqa: E402

DEFAULT_SIZES = "1440x900,1280x720,960x600"


def wait(ms: int) -> None:
    QTest.qWait(ms)


def until(condition, timeout_ms: int = 8000) -> bool:  # type: ignore[no-untyped-def]
    waited = 0
    while not condition() and waited < timeout_ms:
        QTest.qWait(50)
        waited += 50
    return bool(condition())


def prepare(window: MainWindow, video: Path, second: Path) -> None:
    window.open_file(video)
    until(lambda: window.video_page is not None and window.video_page.player.duration)
    window.toggle_editor()
    until(lambda: window.video_editor is not None)
    editor = window.video_editor
    assert editor is not None and FFPROBE is not None
    editor.session.set_trim(0, 1.0, 9.5)
    width, height = editor.session.project.frame_size
    editor.session.add_redact(Redact(Rect(width * 0.08, height * 0.12, width * 0.2, height * 0.16)))
    editor.session.add_text(Text("CHOPCHOP", width * 0.55, height * 0.78, height * 0.07))
    editor.session.set_volume(0.8)
    editor.session.add_clip(Clip(second, probe(second, FFPROBE)))
    editor.clip_strip.set_current(0)
    editor._on_row_changed(0)
    wait(600)
    editor._video_page.player.seek_to(4.0, exact=True)
    wait(500)


def snap(window: MainWindow, path: Path) -> None:
    wait(500)
    window.repaint()
    wait(200)
    image = window.grab()  # QOpenGLWidget с кадром mpv тоже попадает в снимок
    image.save(str(path))
    print("saved", path.name, image.width(), "x", image.height())


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = Path(args[0]) if args else ROOT / "docs" / "design"
    sizes = DEFAULT_SIZES
    for index, arg in enumerate(sys.argv[1:]):
        if arg == "--sizes":
            sizes = sys.argv[index + 2]
    wanted = [tuple(int(n) for n in item.split("x")) for item in sizes.split(",")]

    app = QApplication([])
    fonts.load_fonts()
    i18n.install_language(app, "ru")
    work = Path(tempfile.mkdtemp(prefix="chopchop-shots-"))
    video = make_video(work / "demo.mp4", seconds=12, size=(1280, 720))
    second = make_video(work / "second.mp4", seconds=6, size=(1280, 720), frequency=660)
    theme = ThemeManager(app)
    for name in ("light", "dark"):
        theme.set_theme(name, "orange")
        for number, (w, h) in enumerate(wanted):
            settings = AppSettings(None)
            settings.set("appearance.theme", name)
            window = MainWindow(
                QSettings(str(work / f"{name}{w}.ini"), QSettings.Format.IniFormat), settings, theme
            )
            window.resize(QSize(w, h))
            window.show()
            wait(400)
            prepare(window, video, second)
            editor = window.video_editor
            assert editor is not None
            if number == 0:
                snap(window, out / f"video-editor-{name}-idle-{w}x{h}.png")
            editor.select_tool("redact")
            snap(window, out / f"video-editor-{name}-{w}x{h}.png")
            editor.session.mark_saved()  # без вопроса о несохранённом при закрытии
            window.close()
            wait(300)
    return 0


if __name__ == "__main__":
    sys.exit(main())
