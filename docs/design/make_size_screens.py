"""Скриншоты и замеры размеров плеера и редактора при масштабе Windows 100%, 150% и 200%.

Запуск (нужны libmpv, ffmpeg и настоящий экран):
    python docs/design/make_size_screens.py [папка]

Для каждого масштаба запускается отдельный процесс с `QT_SCALE_FACTOR`, дающим нужный
`devicePixelRatio`: так проверяются и размеры панелей, и то, что значки ложатся на пиксели.
В папку пишутся `size-<что>-<тема>-<масштаб>.png`, а в stdout — таблица размеров в логических
пикселях (по умолчанию: панель плеера 40, в полном экране 36, кнопки 28, верхняя панель 32, панель
параметров редактора 36, значки около 18, подписи 12).
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCALES = (100, 150, 200)


def child(scale: int, out: Path, theme: str) -> None:
    sys.path.insert(0, str(ROOT / "src"))
    sys.path.insert(0, str(ROOT / "tests"))
    from PySide6.QtCore import QSettings, QSize
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from chopchop import i18n
    from chopchop.services.app_settings import AppSettings
    from chopchop.ui.main_window import MainWindow
    from chopchop.ui.theme import fonts, icons
    from chopchop.ui.theme.manager import ThemeManager
    from media import make_video

    app = QApplication([])
    fonts.load_fonts()
    i18n.install_language(app, "ru")
    work = Path(tempfile.mkdtemp(prefix="chopchop-sizes-"))
    video = make_video(work / "demo.mp4", seconds=8, size=(1280, 720))
    settings = AppSettings(None)
    settings.set("appearance.theme", theme)
    window = MainWindow(
        QSettings(str(work / "s.ini"), QSettings.Format.IniFormat), settings, ThemeManager(app)
    )
    window.resize(QSize(1100, 680))
    window.show()
    QTest.qWait(400)
    window.open_file(video)
    waited = 0
    while not (window.video_page and window.video_page.player.duration) and waited < 8000:
        QTest.qWait(50)
        waited += 50
    QTest.qWait(900)
    page = window.video_page
    assert page is not None
    ratio = window.devicePixelRatioF()
    report: dict[str, object] = {"scale": scale, "dpr": ratio}
    page.wake()
    QTest.qWait(400)
    report["player_bar"] = [page.controls.width(), page.controls.height()]
    report["player_button"] = [page.controls._play.width(), page.controls._play.height()]
    report["player_icon"] = page.controls._play.iconSize().width()
    report["player_time_font_px"] = page.controls._time.font().pixelSize()
    report["player_top"] = [page.top.width(), page.top.height()]
    window.grab().save(str(out / f"size-player-{theme}-{scale}.png"))
    page.set_fullscreen(True)  # нижняя панель полного экрана: 36 px
    page.wake()
    QTest.qWait(400)
    report["player_bar_fullscreen"] = [page.controls.width(), page.controls.height()]
    window.grab().save(str(out / f"size-player-fs-{theme}-{scale}.png"))
    page.set_fullscreen(False)
    window.toggle_editor()
    waited = 0
    while window.video_editor is None and waited < 8000:
        QTest.qWait(50)
        waited += 50
    editor = window.video_editor
    assert editor is not None
    QTest.qWait(1200)
    editor.select_tool("rotate")
    QTest.qWait(600)
    shell = editor.shell
    report["editor_top"] = shell.top.height()
    report["editor_context"] = shell.context.height()
    report["editor_transport"] = editor.transport.height()
    report["editor_icon_button"] = [editor._play.width(), editor._play.height()]
    report["editor_icon"] = editor._play.iconSize().width()
    report["ui_icon"] = icons.ui_icon_size()
    heights = [w.height() for w in shell.context.findChildren(type(editor._back)) if w.isVisible()]
    report["context_buttons_max_height"] = max(heights, default=0)
    window.grab().save(str(out / f"size-editor-rotate-{theme}-{scale}.png"))
    editor.session.mark_saved()
    window.close()
    print(json.dumps(report, ensure_ascii=False))


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        child(int(sys.argv[2]), Path(sys.argv[3]), sys.argv[4])
        return 0
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "design"
    # машина с экраном 150% задаёт собственный коэффициент: приводим к нужному множителем
    from PySide6.QtGui import QGuiApplication

    base = QGuiApplication([]).primaryScreen().devicePixelRatio()
    results = []
    for theme in ("light", "dark"):
        for scale in SCALES:
            env = {**os.environ, "QT_SCALE_FACTOR": f"{scale / 100 / base:.6f}"}
            if sys.platform == "win32":
                env.setdefault("QT_QPA_PLATFORM", "windows")
            done = subprocess.run(
                [sys.executable, "-u", __file__, "--child", str(scale), str(out), theme],
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                timeout=300,
            )
            lines = [line for line in done.stdout.splitlines() if line.startswith("{")]
            if not lines:
                print("сбой", theme, scale, done.stderr[-500:])
                continue
            report = json.loads(lines[-1])
            report["theme"] = theme
            results.append(report)
            print(json.dumps(report, ensure_ascii=False))
    (out / "sizes.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
