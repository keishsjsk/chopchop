"""Бенчмарк интерфейса с настоящим mpv и настоящей мышью (Windows, без offscreen).

    python bench/bench_realtime.py --label baseline [--sizes 1440p,1080p] [--scenarios ...]

Окно показывается на экране, видео играет через libmpv, а мышь двигается средствами ОС
(`SetCursorPos`, `mouse_event`), поэтому события идут тем же путём, что и у человека. Старые
бенчмарки (`bench_photo.py`, `bench_video.py`) идут без экрана и без mpv и ловят другое.

Что пишется по каждому сценарию (миллисекунды):
  - события интерфейса: длительность обработчиков Paint, MouseMove, Timer, MetaCall и других
    (медиана, p95, максимум, сколько раз дольше кадра в 16 мс);
  - зависания цикла событий: сколько раз цикл не отвечал дольше 16 и 50 мс и максимум;
  - отклик мыши: от `SetCursorPos` до обработки `MouseMove`, от `LEFTDOWN` до `MousePress`;
  - paintGL: время отрисовки кадра видео;
  - загрузка процессора процессом (доля одного ядра).

Критерий: при воспроизведении 2560x1440 наведение, нажатие и перетаскивание ползунков держат кадр
интерфейса до 16 мс, отклик на нажатие до 50 мс. Мышь пользователя на время запуска занята: не
трогайте её, пока идёт замер.
"""

import argparse
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
if sys.platform != "win32":
    raise SystemExit("этот бенчмарк только для Windows: он двигает настоящую мышь")
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
os.environ["CHOPCHOP_PROFILE"] = "1"

from PySide6.QtCore import QEvent, QObject, QPoint, QSettings, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QWidget  # noqa: E402

from chopchop import i18n  # noqa: E402
from chopchop.engines.ffmpeg import find_ffmpeg  # noqa: E402
from chopchop.player.mpv_widget import MpvWidget  # noqa: E402
from chopchop.services.app_settings import AppSettings  # noqa: E402
from chopchop.services.event_profile import ProfiledApplication  # noqa: E402
from chopchop.services.profiling import LoopWatchdog  # noqa: E402
from chopchop.ui.main_window import MainWindow  # noqa: E402
from chopchop.ui.theme import fonts  # noqa: E402
from chopchop.ui.theme.manager import ThemeManager  # noqa: E402

DATA = Path(__file__).resolve().parent / ".data"
RESULTS = Path(__file__).resolve().parent / "results"
SIZES = {"1440p": (2560, 1440), "1080p": (1920, 1080)}
SCENARIOS = (
    "play_idle",
    "hover_buttons",
    "hover_seek",
    "drag_seek",
    "drag_volume",
    "editor_idle",
    "editor_hover",
    "editor_drag_trim",
    "editor_open",
)
MOVE_PAUSE_MS = 8  # шаг мыши: около 120 Гц, как у игровой мыши
WINDOW = (1600, 900)

user32 = ctypes.windll.user32  # type: ignore[attr-defined]
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004


def make_video(size: str, seconds: int = 40) -> Path:
    """Ролик с ключевыми кадрами раз в 2 секунды (как у обычной камеры) и звуком."""
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        raise SystemExit("нужен ffmpeg")
    DATA.mkdir(exist_ok=True)
    width, height = SIZES[size]
    path = DATA / f"rt_{size}_{seconds}s.mp4"
    if not path.exists():
        subprocess.run(
            [str(ffmpeg), "-y", "-loglevel", "error", "-f", "lavfi", "-i"]
            + [f"testsrc2=duration={seconds}:size={width}x{height}:rate=30"]
            + ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
            + ["-c:v", "libx264", "-g", "60", "-pix_fmt", "yuv420p", "-preset", "veryfast"]
            + ["-b:v", "20M", "-c:a", "aac", "-shortest", str(path)],
            check=True,
            timeout=600,
        )
    return path


class Probe(QObject):
    """Отклик мыши: время от отправки до обработки события Qt."""

    def __init__(self) -> None:
        super().__init__()
        self.pending_moves: list[tuple[QPoint, float]] = []
        self.pending_press: float | None = None
        self.move_latency: list[float] = []
        self.press_latency: list[float] = []

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        kind = event.type()
        if kind == QEvent.Type.MouseMove and isinstance(event, QMouseEvent):
            point = event.globalPosition().toPoint()
            now = time.perf_counter()
            # событие могло склеиться с соседними: берём самую свежую отправку в этой точке
            # и забываем более старые
            for index in range(len(self.pending_moves) - 1, -1, -1):
                target, sent = self.pending_moves[index]
                if abs(target.x() - point.x()) <= 2 and abs(target.y() - point.y()) <= 2:
                    self.move_latency.append((now - sent) * 1000)
                    del self.pending_moves[: index + 1]
                    break
        elif kind == QEvent.Type.MouseButtonPress and self.pending_press is not None:
            self.press_latency.append((time.perf_counter() - self.pending_press) * 1000)
            self.pending_press = None
        return False


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(int(len(ordered) * fraction), len(ordered) - 1)]


class Rig:
    """Окно, настоящая мышь и сбор замеров."""

    def __init__(self, app: ProfiledApplication, window: MainWindow) -> None:
        self.app = app
        self.window = window
        self.probe = Probe()
        app.installEventFilter(self.probe)
        self.gl_times: list[float] = []
        original = MpvWidget.paintGL

        def timed(widget: MpvWidget) -> None:
            started = time.perf_counter()
            original(widget)
            self.gl_times.append((time.perf_counter() - started) * 1000)

        if not os.environ.get("BENCH_NO_GLWRAP"):
            MpvWidget.paintGL = timed  # type: ignore[method-assign]
        self.dpr = window.devicePixelRatioF()

    # --- мышь ------------------------------------------------------------------------------

    def move_to(self, point: QPoint) -> None:
        """Передвигает настоящий курсор в глобальную точку (логические пиксели Qt)."""
        self.probe.pending_moves.append((point, time.perf_counter()))
        user32.SetCursorPos(round(point.x() * self.dpr), round(point.y() * self.dpr))
        QTest.qWait(MOVE_PAUSE_MS)

    def path(self, points: list[QPoint], steps: int = 24) -> None:
        for a, b in zip(points, points[1:], strict=False):
            for i in range(1, steps + 1):
                t = i / steps
                self.move_to(
                    QPoint(round(a.x() + (b.x() - a.x()) * t), round(a.y() + (b.y() - a.y()) * t))
                )

    def press(self) -> None:
        self.probe.pending_press = time.perf_counter()
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        QTest.qWait(30)

    def release(self) -> None:
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        QTest.qWait(30)

    def centre(self, widget: QWidget) -> QPoint:
        return widget.mapToGlobal(widget.rect().center())

    # --- замер -----------------------------------------------------------------------------

    def measure(self, name: str, action) -> dict[str, object]:  # type: ignore[no-untyped-def]
        self.app.reset()
        self.probe.move_latency.clear()
        self.probe.press_latency.clear()
        self.probe.pending_moves.clear()
        self.gl_times.clear()
        short, long_ = LoopWatchdog(16), LoopWatchdog(50)
        short.start()
        long_.start()
        cpu_start, wall_start = time.process_time(), time.perf_counter()
        action()
        cpu = (time.process_time() - cpu_start) / (time.perf_counter() - wall_start)
        short.stop()
        long_.stop()
        rows = {}
        for (kind, widget), stat in sorted(self.app.stats.items(), key=lambda i: -i[1].total)[:8]:
            rows[f"{kind}:{widget}"] = {
                "n": stat.count,
                "p50": round(stat.percentile(0.5), 2),
                "p95": round(stat.percentile(0.95), 2),
                "max": round(stat.longest, 2),
                "over16": stat.over_frame,
                "total_ms": round(stat.total),
            }
        result = {
            "events": rows,
            "stalls_16": len(short.stalls),
            "stalls_50": len(long_.stalls),
            "stall_max": round(max(short.stalls, default=0.0), 1),
            "move_latency_p50": round(percentile(self.probe.move_latency, 0.5), 1),
            "move_latency_p95": round(percentile(self.probe.move_latency, 0.95), 1),
            "move_latency_max": round(max(self.probe.move_latency, default=0.0), 1),
            "press_latency": [round(v, 1) for v in self.probe.press_latency],
            "paintgl_p50": round(percentile(self.gl_times, 0.5), 2),
            "paintgl_p95": round(percentile(self.gl_times, 0.95), 2),
            "paintgl_n": len(self.gl_times),
            "cpu_share": round(cpu, 2),
        }
        return result


def wait_until(condition, timeout_ms: int = 15000) -> bool:  # type: ignore[no-untyped-def]
    waited = 0
    while not condition() and waited < timeout_ms:
        QTest.qWait(50)
        waited += 50
    return bool(condition())


def to_viewer(rig: Rig, video: Path) -> None:
    window = rig.window
    if window.video_editor is not None:
        window.toggle_editor()
        wait_until(lambda: window.video_editor is None)
    page = window.video_page
    if page is None or page.player.current != video:
        window.open_file(video)
        wait_until(
            lambda: window.video_page is not None and bool(window.video_page.player.duration)
        )
    QTest.qWait(1500)


def to_editor(rig: Rig, video: Path) -> None:
    window = rig.window
    if window.video_editor is None:
        if window.video_page is None or window.video_page.player.current != video:
            window.open_file(video)
            wait_until(
                lambda: window.video_page is not None and bool(window.video_page.player.duration)
            )
        window.toggle_editor()
        wait_until(lambda: window.video_editor is not None)
        QTest.qWait(2500)
    editor = window.video_editor
    assert editor is not None
    editor._video_page.player._mpv.pause = False


TWEAKS = os.environ.get("BENCH_TWEAKS", "").split(",") if os.environ.get("BENCH_TWEAKS") else []


def apply_tweaks(rig: Rig) -> None:
    """Опыты методом исключения (BENCH_TWEAKS=paused,no_effects,mpv:scale=bilinear,...)."""
    window = rig.window
    page = window.video_page
    if page is None:
        return
    for tweak in TWEAKS:
        if tweak == "paused":
            page.player._mpv.pause = True
        elif tweak == "no_effects":
            for panel in (page.controls, page.top, page.tracks, page.bubble):
                panel.setGraphicsEffect(None)
        elif tweak == "no_shadow_translucent":
            for panel in (page.controls, page.top, page.tracks, page.bubble):
                panel.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        elif tweak.startswith("mpv:"):
            key, value = tweak[4:].split("=", 1)
            setattr(page.player._mpv, key.replace("-", "_"), value)
        elif tweak == "hide_panels":
            page.set_editor_mode(True)
        else:
            raise SystemExit(f"неизвестная правка {tweak}")


def run_scenario(rig: Rig, name: str, video: Path, seconds: float) -> dict[str, object]:
    window = rig.window
    if name == "editor_open":
        # холодное открытие редактора при игре: миниатюры и ключевые кадры считаются заново
        to_viewer(rig, video)

        def open_editor() -> None:
            window.toggle_editor()
            wait_until(lambda: window.video_editor is not None)
            QTest.qWait(int(seconds * 1000))

        return rig.measure(name, open_editor)
    if name.startswith("editor"):
        to_editor(rig, video)
    else:
        to_viewer(rig, video)
        assert window.video_page is not None
        window.video_page.player._mpv.pause = False
    apply_tweaks(rig)

    def idle() -> None:
        QTest.qWait(int(seconds * 1000))

    if name == "play_idle":
        return rig.measure(name, idle)
    if name == "editor_idle":
        return rig.measure(name, idle)

    if name.startswith("editor"):
        editor = window.video_editor
        assert editor is not None
        trim = editor.trim
        left = trim.mapToGlobal(QPoint(40, trim.height() // 2))
        right = trim.mapToGlobal(QPoint(trim.width() - 40, trim.height() // 2))
        if name == "editor_hover":
            buttons = [editor._play, editor._step_back, editor._step_forward, editor._set_in]
            buttons += [editor._split, editor._zoom_in, editor._zoom_out]
            points = [rig.centre(b) for b in buttons]
            rig.move_to(points[0])

            def hover() -> None:
                end = time.perf_counter() + seconds
                while time.perf_counter() < end:
                    rig.path(points + points[::-1], steps=8)

            return rig.measure(name, hover)

        def drag_trim() -> None:
            rig.move_to(left)
            rig.press()
            end = time.perf_counter() + seconds
            while time.perf_counter() < end:
                rig.path([left, right, left], steps=40)
            rig.release()

        return rig.measure(name, drag_trim)

    page = window.video_page
    assert page is not None
    video_area = page.video.mapToGlobal(page.video.rect().center())
    rig.move_to(video_area)
    rig.path([video_area, video_area + QPoint(30, 20)], steps=4)  # будит панели
    QTest.qWait(400)
    controls = page.controls
    if name == "hover_buttons":
        buttons = [controls._play, controls._tracks, controls._full]
        points = [rig.centre(b) for b in buttons]

        def hover() -> None:
            end = time.perf_counter() + seconds
            while time.perf_counter() < end:
                rig.path(points + points[::-1], steps=10)

        return rig.measure(name, hover)

    seek = controls._seek
    row = seek.mapToGlobal(QPoint(0, seek.height() // 2))
    left, right = row + QPoint(20, 0), row + QPoint(seek.width() - 20, 0)
    if name == "hover_seek":

        def sweep() -> None:
            end = time.perf_counter() + seconds
            while time.perf_counter() < end:
                rig.path([left, right, left], steps=40)

        return rig.measure(name, sweep)
    if name == "drag_seek":

        def drag() -> None:
            rig.move_to(left)
            rig.press()
            end = time.perf_counter() + seconds
            while time.perf_counter() < end:
                rig.path([left, right, left], steps=40)
            rig.release()

        return rig.measure(name, drag)
    if name == "drag_volume":
        volume = controls.volume
        rig.move_to(rig.centre(volume._button))
        QTest.qWait(600)  # ползунок раскрылся
        slider = volume.slider
        a = slider.mapToGlobal(QPoint(8, slider.height() // 2))
        b = slider.mapToGlobal(QPoint(slider.width() - 8, slider.height() // 2))

        def drag_volume() -> None:
            rig.move_to(a)
            rig.press()
            end = time.perf_counter() + seconds
            while time.perf_counter() < end:
                rig.path([a, b, a], steps=30)
            rig.release()

        return rig.measure(name, drag_volume)
    raise SystemExit(f"неизвестный сценарий {name}")


def run_children(args: argparse.Namespace, sizes: list[str]) -> int:
    """Каждый сценарий — в своём процессе, `--repeat` раз; в итог идёт прогон с медианным числом
    зависаний, остальные цифры сохраняются списком `runs`.

    Один прогон зависит от того, что ещё делает компьютер (браузер, синхронизация), поэтому
    сравнивать нужно медианы нескольких запусков.
    """
    merged: dict[str, object] = {}
    for size in sizes:
        for name in args.scenarios.split(","):
            label = f"{args.label}-{size}-{name}"
            command = [sys.executable, "-u", __file__, "--label", label, "--sizes", size]
            command += ["--child", "--scenarios", name, "--seconds", str(args.seconds)]
            command += ["--theme", args.theme]
            part = RESULTS / f"realtime-{label}.json"
            runs: list[dict[str, object]] = []
            crashes = 0
            attempts = 0
            while len(runs) < args.repeat and attempts < args.repeat * 3:
                attempts += 1
                done = subprocess.run(command, check=False, timeout=1200)
                if done.returncode == 0 and part.exists():
                    runs.append(json.loads(part.read_text(encoding="utf-8"))[f"{size}.{name}"])
                    part.unlink()
                else:
                    crashes += 1
                    print(f"{size}.{name}: сбой (код {done.returncode})")
            if runs:
                runs.sort(key=lambda r: (r["stalls_50"], r["stalls_16"]))  # type: ignore[index]
                best = dict(runs[len(runs) // 2])
                best["runs"] = [
                    {
                        "stalls_16": r["stalls_16"],
                        "stalls_50": r["stalls_50"],
                        "move_latency_p95": r["move_latency_p95"],
                        "press_latency": r["press_latency"],
                    }
                    for r in runs
                ]
                best["crashes"] = crashes
                merged[f"{size}.{name}"] = best
                print(summary_line(f"{size}.{name}", best), f"(медиана из {len(runs)})")
    out = RESULTS / f"realtime-{args.label}.json"
    out.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved", out)
    return 0


def summary_line(key: str, r: dict[str, object]) -> str:
    return (
        f"{key:28} stalls16={r['stalls_16']:3} stalls50={r['stalls_50']:2} "
        f"max={r['stall_max']:6.1f} move_p95={r['move_latency_p95']:6.1f} "
        f"press={r['press_latency']} paintGL_p95={r['paintgl_p95']:5.2f} cpu={r['cpu_share']}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="run")
    parser.add_argument("--sizes", default="1440p,1080p")
    parser.add_argument("--scenarios", default=",".join(SCENARIOS))
    parser.add_argument("--seconds", type=float, default=6.0)
    parser.add_argument("--theme", default="light")
    parser.add_argument("--repeat", type=int, default=3, help="прогонов на сценарий")
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    sizes = args.sizes.split(",")
    if len(sizes) > 1 and not args.child:
        return run_children(args, sizes)

    import logging

    logging.getLogger("chopchop.profile").setLevel(
        logging.CRITICAL
    )  # таблица ниже вместо потока строк
    if os.environ.get("BENCH_SWAP0"):
        from PySide6.QtGui import QSurfaceFormat

        fmt = QSurfaceFormat.defaultFormat()
        fmt.setSwapInterval(0)
        QSurfaceFormat.setDefaultFormat(fmt)
    app = ProfiledApplication([])
    app.recording = os.environ.get("BENCH_NO_NOTIFY") is None
    if os.environ.get("BENCH_NO_TIPFX"):
        app.setEffectEnabled(Qt.UIEffect.UI_FadeTooltip, False)
        app.setEffectEnabled(Qt.UIEffect.UI_AnimateTooltip, False)
    fonts.load_fonts()
    i18n.install_language(app, "ru")
    work = Path(tempfile.mkdtemp(prefix="chopchop-rt-"))
    os.environ["CHOPCHOP_CACHE_DIR"] = str(work / "cache")  # холодный кэш на каждый прогон
    settings = AppSettings(None)
    settings.set("appearance.theme", args.theme)
    window = MainWindow(
        QSettings(str(work / "s.ini"), QSettings.Format.IniFormat), settings, ThemeManager(app)
    )
    window.resize(*WINDOW)
    window.move(40, 40)
    window.show()
    window.raise_()
    window.activateWindow()
    QTest.qWait(800)
    rig = Rig(app, window)
    if os.environ.get("BENCH_NO_BUBBLE"):
        from chopchop.ui.player_controls import PreviewBubble

        PreviewBubble.show_at = lambda *a, **k: None  # type: ignore[method-assign]
    results: dict[str, dict[str, object]] = {}
    for size in sizes:
        video = make_video(size)
        for name in args.scenarios.split(","):
            key = f"{size}.{name}"
            results[key] = run_scenario(rig, name, video, args.seconds)
            r = results[key]
            paint = max(
                (v["p95"] for k, v in r["events"].items() if k.startswith("Paint")), default=0
            )  # type: ignore[union-attr, index]
            print(
                f"{key:28} stalls16={r['stalls_16']:3} stalls50={r['stalls_50']:2} "
                f"max={r['stall_max']:6.1f} move_p95={r['move_latency_p95']:6.1f} "
                f"press={r['press_latency']} paintGL_p95={r['paintgl_p95']:5.2f} "
                f"paint_p95={paint} cpu={r['cpu_share']}"
            )
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"realtime-{args.label}.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved", out)
    if window.video_editor is not None:
        window.video_editor.session.mark_saved()
    window.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
