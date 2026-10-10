"""Загрузка EDL после правки монтажа: сколько держится интерфейс и когда плеер готов.

    QT_QPA_PLATFORM=offscreen python bench/bench_reload.py [--label run] [--repeat 5]

Окно не показывается (offscreen), мышь и экран не используются. Плеер идёт в программном режиме
(mpv рисует кадр в память), поэтому видеокарта не нужна. Правки делаются вызовами страницы
редактора, как при отпускании мыши: перенос блока, растяжение края, удаление блока, отмена.

Для каждой правки: время, на которое интерфейс замер (самая длинная пауза цикла событий и сумма
обработчиков), и время до готовности плеера (длительность в mpv стала равна проекту).
Результат — `bench/results/reload-<метка>.json`.
"""

import argparse
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

RESULTS = Path(__file__).resolve().parent / "results"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="run")
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--size", default="1080p")
    args = parser.parse_args()

    from chopchop.services import graphics

    graphics.apply(graphics.Plan("software", "system", False, "bench"))
    import bench_realtime as rt
    from PySide6.QtCore import QSettings
    from PySide6.QtTest import QTest

    from chopchop import i18n
    from chopchop.services.app_settings import AppSettings
    from chopchop.services.event_profile import ProfiledApplication
    from chopchop.services.profiling import LoopWatchdog
    from chopchop.ui.main_window import MainWindow
    from chopchop.ui.theme import fonts
    from chopchop.ui.theme.manager import ThemeManager

    app = ProfiledApplication([])
    fonts.load_fonts()
    fonts.apply(app, "monocraft")
    i18n.install_language(app, "ru")
    work = Path(tempfile.mkdtemp(prefix="chopchop-reload-"))
    os.environ["CHOPCHOP_CACHE_DIR"] = str(work / "cache")
    window = MainWindow(
        QSettings(str(work / "s.ini"), QSettings.Format.IniFormat),
        AppSettings(None),
        ThemeManager(app),
    )
    window.resize(1200, 700)
    window.show()
    QTest.qWait(500)
    video = rt.make_video(args.size)
    window.open_file(video)
    rt.wait_until(lambda: window.video_page is not None and bool(window.video_page.player.duration))
    QTest.qWait(1000)
    window.toggle_editor()
    rt.wait_until(lambda: window.video_editor is not None)
    page = window.video_editor
    assert page is not None
    QTest.qWait(2500)
    player = page._video_page.player
    for at in (8.0, 16.0, 24.0, 32.0):
        page.split_at(at)
        QTest.qWait(300)
    QTest.qWait(1000)

    def settle() -> float:
        """Ждёт, пока длительность в mpv станет равна проекту; возвращает мс."""
        started = time.perf_counter()
        while time.perf_counter() - started < 8:
            duration = player.duration
            if duration and abs(duration - page.session.project.duration) < 0.3:
                break
            QTest.qWait(10)
        return (time.perf_counter() - started) * 1000

    edits = {
        "move_block": lambda: page.move_block(0, 4),
        "delete_block": lambda: (page.select_block(1), page.delete_selected()),
        "undo": lambda: page.undo(),
        "stretch_edge": lambda: page.session.set_trim(
            0, page.session.project.clips[0].start, page.session.project.clips[0].stop - 1.0
        ),
    }
    results: dict[str, dict[str, object]] = {}
    for name, edit in edits.items():
        blocked: list[float] = []
        pause: list[float] = []
        ready: list[float] = []
        for _ in range(args.repeat):
            watchdog = LoopWatchdog(16)
            watchdog.start()
            started = time.perf_counter()
            if os.environ.get("BENCH_PROFILE") and name == os.environ["BENCH_PROFILE"]:
                import cProfile
                import pstats

                profiler = cProfile.Profile()
                profiler.enable()
                edit()
                profiler.disable()
                pstats.Stats(profiler).sort_stats("cumulative").print_stats(22)
            else:
                edit()  # то, что делает отпускание мыши: правка и перезагрузка плеера
            blocked.append((time.perf_counter() - started) * 1000)
            wait = settle()
            watchdog.stop()
            ready.append(blocked[-1] + wait)
            pause.append(max(watchdog.stalls, default=0.0))
            page.undo() if name != "undo" else page.redo()
            QTest.qWait(300)
            settle()
        results[name] = {
            "gui_blocked_ms_median": round(statistics.median(blocked), 1),
            "gui_blocked_ms_max": round(max(blocked), 1),
            "longest_pause_ms_median": round(statistics.median(pause), 1),
            "longest_pause_ms_max": round(max(pause), 1),
            "ready_ms_median": round(statistics.median(ready), 1),
            "ready_ms_max": round(max(ready), 1),
        }
        print(f"{name:14}", results[name], flush=True)
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"reload-{args.label}.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    page.session.mark_saved()
    window.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
