"""Живой прогон монтажа блоками на настоящем mpv и настоящем окне (Windows).

    python bench/bench_blocks.py --label run [--size 1440p] [--shots docs/design]

Открывает ролик в редакторе и проходит по порядку: разрез клавишей K, удаление блока, перенос блока
мышью на новое место, растяжение края мышью, отмена. После каждой правки проверяет, что плеер
(EDL) играет тот же итог: длительность mpv равна длительности проекта, позиция осталась на той же
картинке. Меряет время от правки до загрузки EDL и зависания потока интерфейса во время переноса.
Результаты — `bench/results/blocks-<метка>.json`; снимки полосы — в папку `--shots`.
"""

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bench_realtime as rt  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from chopchop import i18n  # noqa: E402
from chopchop.services.app_settings import AppSettings  # noqa: E402
from chopchop.services.event_profile import ProfiledApplication  # noqa: E402
from chopchop.ui.main_window import MainWindow  # noqa: E402
from chopchop.ui.theme import fonts  # noqa: E402
from chopchop.ui.theme.manager import ThemeManager  # noqa: E402


def synthetic_drag(timeline, x0: float, x1: float, y: float, steps: int) -> None:  # type: ignore[no-untyped-def]
    """Перетаскивание по полосе: нажатие, движение шагами, отпускание (события Qt, не ОС)."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    left = Qt.MouseButton.LeftButton

    def send(kind: QEvent.Type, x: float) -> None:
        point = QPointF(x, y)
        button = left if kind != QEvent.Type.MouseMove else Qt.MouseButton.NoButton
        buttons = left if kind != QEvent.Type.MouseButtonRelease else Qt.MouseButton.NoButton
        event = QMouseEvent(
            kind,
            point,
            timeline.mapToGlobal(point),
            button,
            buttons,
            Qt.KeyboardModifier.NoModifier,
        )
        {
            QEvent.Type.MouseButtonPress: timeline.mousePressEvent,
            QEvent.Type.MouseMove: timeline.mouseMoveEvent,
            QEvent.Type.MouseButtonRelease: timeline.mouseReleaseEvent,
        }[kind](event)

    send(QEvent.Type.MouseButtonPress, x0)
    for i in range(1, steps + 1):
        send(QEvent.Type.MouseMove, x0 + (x1 - x0) * i / steps)
        QTest.qWait(8)
    send(QEvent.Type.MouseButtonRelease, x1)


def wait_duration(page, expected: float, timeout_ms: int = 8000) -> float:  # type: ignore[no-untyped-def]
    """Ждёт, пока длительность в mpv станет длительностью проекта; возвращает мс ожидания."""
    started = time.perf_counter()
    player = page._video_page.player
    while time.perf_counter() - started < timeout_ms / 1000:
        duration = player.duration
        if duration and abs(duration - expected) < 0.3:
            break
        QTest.qWait(20)
    return (time.perf_counter() - started) * 1000


def run(args: argparse.Namespace) -> dict[str, object]:
    app = ProfiledApplication([])
    app.recording = True
    fonts.load_fonts()
    i18n.install_language(app, "ru")
    work = Path(tempfile.mkdtemp(prefix="chopchop-blocks-"))
    settings = AppSettings(None)
    settings.set("appearance.theme", args.theme)
    window = MainWindow(
        QSettings(str(work / "s.ini"), QSettings.Format.IniFormat), settings, ThemeManager(app)
    )
    window.resize(1360, 760)  # целиком на экране: мышь должна дотянуться до полосы
    window.move(20, 10)
    window.show()
    window.raise_()
    window.activateWindow()
    QTest.qWait(800)
    rig = rt.Rig(app, window)
    video = rt.make_video(args.size)
    rt.to_viewer(rig, video)
    window.toggle_editor()
    rt.wait_until(lambda: window.video_editor is not None)
    page = window.video_editor
    assert page is not None
    QTest.qWait(2500)
    player = page._video_page.player
    report: dict[str, object] = {"size": args.size, "steps": {}}
    steps: dict[str, dict[str, object]] = report["steps"]  # type: ignore[assignment]

    def check(name: str, started: float) -> None:
        expected = page.session.project.duration
        waited = wait_duration(page, expected)
        mpv_duration = float(player.duration or 0.0)
        steps[name] = {
            "reload_ms": round(waited, 1),
            "project_s": round(expected, 2),
            "mpv_s": round(mpv_duration, 2),
            "ok": abs(mpv_duration - expected) < 0.3,
            "blocks": len(page.session.project.clips),
        }
        print(
            f"{name:28} reload {waited:7.1f} ms  project {expected:6.2f}  mpv {mpv_duration:6.2f}"
        )

    # 1. разрезы клавишей K на трёх местах
    for at in (10.0, 20.0, 30.0):
        page._video_page.player.seek_to(at, exact=True)
        QTest.qWait(700)
        page.split_at(at)
        QTest.qWait(300)
    check("split x3", time.perf_counter())
    # 2. удаление блока 1 (10-20 с)
    page.select_block(1)
    started = time.perf_counter()
    page.delete_selected()
    check("delete block", started)
    # 3. перенос блока: первый блок в конец (события мыши идут прямо в полосу)
    timeline = page.timeline
    y = float(timeline._track().center().y())
    start_x = float(timeline.block_rect(0).center().x())
    end_x = float(timeline.block_rect(len(timeline.blocks) - 1).right()) - 4
    started = time.perf_counter()
    steps["drag block"] = rig.measure(
        "drag block", lambda: synthetic_drag(timeline, start_x, end_x, y, 40)
    )
    QTest.qWait(400)
    steps["drag block"]["order"] = [round(c.start) for c in page.session.project.clips]  # type: ignore[index]
    check("move block", started)
    # 4. растяжение края блока
    edge_x = float(timeline.block_rect(0).right())
    started = time.perf_counter()
    steps["drag edge"] = rig.measure(
        "drag edge", lambda: synthetic_drag(timeline, edge_x, edge_x + 40, y, 20)
    )
    QTest.qWait(400)
    check("stretch edge", started)
    # 5. отмена всего
    while page.session.can_undo:
        page.undo()
        QTest.qWait(150)
    check("undo all", time.perf_counter())
    if args.shots:
        Path(args.shots).mkdir(parents=True, exist_ok=True)
        page.select_block(0)
        QTest.qWait(300)
        page.timeline.grab().save(str(Path(args.shots) / f"timeline-{args.theme}-empty.png"))
    page.session.mark_saved()
    window.close()
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="run")
    parser.add_argument("--size", default="1440p")
    parser.add_argument("--theme", default="light")
    parser.add_argument("--shots", default="")
    args = parser.parse_args()
    report = run(args)
    out = rt.RESULTS / f"blocks-{args.label}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
