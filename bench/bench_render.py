"""Бенчмарк режимов рендера: время кадра при перетаскивании, события Qt (без реальной мыши).

    python bench/bench_render.py --label before --modes gl-default,gl-igpu,gl-dgpu,raster

Каждый режим и каждый сценарий идут в своём процессе (режим OpenGL и видеокарту нельзя сменить на
лету). Режимы:
  gl-default   OpenGL как есть: Windows сама выбирает видеокарту для процесса (до фазы E);
  gl-igpu      OpenGL на встроенной видеокарте (запись в `UserGpuPreferences`, как в программе);
  gl-dgpu      OpenGL на дискретной видеокарте;
  gl-software  программный OpenGL Qt (`QT_OPENGL=software`, Mesa llvmpipe), плеер через GL;
  raster       режим «программный» программы: без OpenGL, mpv рисует кадр в память;
  app          то, что выберет сама программа (`graphics.plan` по настройкам по умолчанию).
`QT_OPENGL=angle` в Qt 6 не поддерживается (ANGLE убран), поэтому строки angle нет.

Сценарии (события идут прямо в виджеты через цикл Qt, курсор и фокус не трогаются):
  drag_block    перенос блока по полосе (кнопка зажата, блок ходит вправо и влево);
  stretch_edge  растяжение края блока;
  drag_seek     ползунок перемотки в плеере при воспроизведении;
  photo_crop    рамка кадрирования 24 Мп фото.

По каждому сценарию: интервалы между перерисовками целевого виджета (p50/p95/max, мс; это и есть
время кадра при перетаскивании), число зависаний цикла событий дольше 16 и 50 мс, время обработчиков
Paint и MouseMove (p95), отклик мыши. Результат — `bench/results/render-<метка>.json`.
"""

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

MODES = ("gl-default", "gl-igpu", "gl-dgpu", "gl-software", "raster", "app")
SCENARIOS = ("drag_block", "stretch_edge", "drag_seek", "photo_crop")
ROOT = Path(__file__).resolve().parents[1]
RESULTS = Path(__file__).resolve().parent / "results"
PHOTO = Path(__file__).resolve().parent / ".data" / "photo_24MP.jpg"


def configure(mode: str) -> str:
    """Среда режима: до создания приложения. Возвращает описание для отчёта."""
    from chopchop.services import graphics

    if mode == "gl-software":
        os.environ["QT_OPENGL"] = "software"
    plan = {
        "gl-default": graphics.Plan("hardware", "system", False, mode),
        "gl-igpu": graphics.Plan("hardware", "integrated", True, mode),
        "gl-dgpu": graphics.Plan("hardware", "discrete", True, mode),
        "gl-software": graphics.Plan("hardware", "system", False, mode),
        "raster": graphics.Plan("software", "system", False, mode),
        "app": graphics.plan("auto", "auto", False),
    }[mode]
    graphics.apply(plan)
    return f"{plan.render}/{plan.gpu}"


def wait_until(condition, timeout_ms: int = 15000) -> bool:  # type: ignore[no-untyped-def]
    from PySide6.QtTest import QTest

    waited = 0
    while not condition() and waited < timeout_ms:
        QTest.qWait(50)
        waited += 50
    return bool(condition())


def show_viewer(window, video: Path) -> None:  # type: ignore[no-untyped-def]
    """Плеер с открытым роликом (из редактора выходит)."""
    from PySide6.QtTest import QTest

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


def child(args: argparse.Namespace) -> int:
    configure_text = configure(args.mode)
    import bench_realtime as rt
    from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QSettings, Qt
    from PySide6.QtGui import QGuiApplication, QMouseEvent, QOffscreenSurface, QOpenGLContext
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QWidget

    from chopchop import i18n
    from chopchop.services.app_settings import AppSettings
    from chopchop.services.event_profile import ProfiledApplication
    from chopchop.services.profiling import LoopWatchdog
    from chopchop.ui.main_window import MainWindow
    from chopchop.ui.theme import fonts
    from chopchop.ui.theme.manager import ThemeManager

    class Frames(QObject):
        """Моменты перерисовки целевого виджета."""

        def __init__(self) -> None:
            super().__init__()
            self.target: QObject | None = None
            self.stamps: list[float] = []

        def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
            if watched is self.target and event.type() == QEvent.Type.Paint:
                self.stamps.append(time.perf_counter())
            return False

    import logging

    logging.getLogger("chopchop.profile").setLevel(logging.CRITICAL)
    app = ProfiledApplication([])
    app.recording = True
    fonts.load_fonts()
    fonts.apply(app, "monocraft")
    i18n.install_language(app, "ru")
    work = Path(tempfile.mkdtemp(prefix="chopchop-render-"))
    os.environ["CHOPCHOP_CACHE_DIR"] = str(work / "cache")
    settings = AppSettings(None)
    window = MainWindow(
        QSettings(str(work / "s.ini"), QSettings.Format.IniFormat), settings, ThemeManager(app)
    )
    window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)  # без захвата фокуса
    screen = QGuiApplication.primaryScreen().availableGeometry()
    window.resize(min(1360, screen.width() - 40), min(760, screen.height() - 60))
    window.move(screen.left() + 10, screen.top() + 10)
    window.show()
    QTest.qWait(800)
    frames = Frames()
    app.installEventFilter(frames)
    video = rt.make_video(args.size)
    renderer = "?"
    probe = QOpenGLContext()
    if probe.create():
        surface = QOffscreenSurface()
        surface.create()
        if probe.makeCurrent(surface):
            renderer = str(probe.functions().glGetString(0x1F01))
            probe.doneCurrent()
    info = {
        "mode": args.mode,
        "plan": configure_text,
        "renderer": renderer,
        "dpr": QGuiApplication.primaryScreen().devicePixelRatio(),
    }

    def percentile(values: list[float], fraction: float) -> float:
        ordered = sorted(values)
        return ordered[min(int(len(ordered) * fraction), len(ordered) - 1)] if ordered else 0.0

    def send(widget: QWidget, kind: QEvent.Type, point: QPoint) -> None:
        """Событие мыши прямо в виджет через цикл Qt: настоящий курсор не трогаем."""
        left = Qt.MouseButton.LeftButton
        pressed = kind != QEvent.Type.MouseButtonRelease
        event = QMouseEvent(
            kind,
            QPointF(point),
            QPointF(widget.mapToGlobal(point)),
            left if kind != QEvent.Type.MouseMove else Qt.MouseButton.NoButton,
            left if pressed else Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(widget, event)

    def hold_and_sweep(widget: QWidget, points: list[QPoint], seconds: float, steps: int) -> None:
        """Нажать в первой точке, идти по маршруту шагом 8 мс (мышь 120 Гц), отпустить там же."""
        send(widget, QEvent.Type.MouseButtonPress, points[0])
        QTest.qWait(30)
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            for a, b in zip(points, points[1:], strict=False):
                for i in range(1, steps + 1):
                    x = a.x() + (b.x() - a.x()) * i / steps
                    y = a.y() + (b.y() - a.y()) * i / steps
                    send(widget, QEvent.Type.MouseMove, QPoint(round(x), round(y)))
                    QTest.qWait(8)
        send(widget, QEvent.Type.MouseMove, points[0])
        send(widget, QEvent.Type.MouseButtonRelease, points[0])
        QTest.qWait(30)

    def run_measured(
        name: str, target: QWidget, points: list[QPoint], steps: int
    ) -> dict[str, object]:
        frames.target = target
        frames.stamps.clear()
        app.reset()
        short, long_ = LoopWatchdog(16), LoopWatchdog(50)
        short.start()
        long_.start()
        cpu0, wall0 = time.process_time(), time.perf_counter()
        hold_and_sweep(target, points, args.seconds, steps)
        cpu = (time.process_time() - cpu0) / (time.perf_counter() - wall0)
        short.stop()
        long_.stop()
        gaps = [(b - a) * 1000 for a, b in zip(frames.stamps, frames.stamps[1:], strict=False)]
        stats = {f"{kind}": [] for kind, _widget in app.stats}
        for (kind, _widget), stat in app.stats.items():
            stats[f"{kind}"].append(stat)

        def worst(prefix: str, fraction: float | None) -> float:
            values = [
                (s.longest if fraction is None else s.percentile(fraction))
                for kind, group in stats.items()
                if kind.startswith(prefix)
                for s in group
            ]
            return round(max(values, default=0.0), 2)

        out = {
            "frames": len(frames.stamps),
            "frame_p50": round(statistics.median(gaps), 1) if gaps else 0.0,
            "frame_p95": round(percentile(gaps, 0.95), 1),
            "frame_max": round(max(gaps, default=0.0), 1),
            "stalls_16": len(short.stalls),
            "stalls_50": len(long_.stalls),
            "stall_max": round(max(short.stalls, default=0.0), 1),
            "paint_p95": worst("Paint", 0.95),
            "paint_max": worst("Paint", None),
            "mousemove_p95": worst("MouseMove", 0.95),
            "mousemove_max": worst("MouseMove", None),
            "cpu_share": round(cpu, 2),
        }
        print(f"{name:14}", out, flush=True)
        return out

    results: dict[str, object] = {"info": info}
    for name in args.scenarios.split(","):
        if name in ("drag_block", "stretch_edge"):
            show_viewer(window, video)
            window.toggle_editor()
            wait_until(lambda: window.video_editor is not None)
            page = window.video_editor
            assert page is not None
            QTest.qWait(2000)
            for at in (8.0, 16.0, 24.0, 32.0):  # пять блоков
                page.split_at(at)
                QTest.qWait(250)
            QTest.qWait(500)
            timeline = page.timeline
            y = int(timeline._track().center().y())
            first = timeline.block_rect(0)
            if name == "drag_block":
                x0 = int(first.center().x())
                x1 = int(timeline.block_rect(len(timeline.blocks) - 1).center().x())
                points = [QPoint(x0, y), QPoint(x1, y), QPoint(x0, y)]
            else:
                edge = int(first.right())
                points = [
                    QPoint(edge, y),
                    QPoint(edge + 70, y),
                    QPoint(edge - 40, y),
                    QPoint(edge, y),
                ]
            results[name] = run_measured(name, timeline, points, 30)
            page.session.mark_saved()
            window.toggle_editor()
            wait_until(lambda: window.video_editor is None)
        elif name == "drag_seek":
            show_viewer(window, video)
            page = window.video_page
            assert page is not None
            page.player._mpv.pause = False
            QTest.qWait(500)
            seek = page.controls._seek
            row = seek.height() // 2
            points = [QPoint(20, row), QPoint(seek.width() - 20, row), QPoint(20, row)]
            results[name] = run_measured(name, seek, points, 40)
        elif name == "photo_crop":
            window.open_file(PHOTO)
            wait_until(lambda: window.current_path == PHOTO)
            QTest.qWait(1500)
            window.toggle_editor()
            wait_until(lambda: window.editor is not None)
            editor = window.editor
            assert editor is not None
            QTest.qWait(1500)
            editor.select_tool("crop")
            QTest.qWait(500)
            canvas = editor.canvas
            rect = canvas.image_rect()
            corner = QPoint(int(rect.left()) + 2, int(rect.top()) + 2)
            inner = corner + QPoint(int(rect.width() * 0.4), int(rect.height() * 0.4))
            results[name] = run_measured(name, canvas, [corner, inner, corner], 40)
            editor.select_tool(None)
            window.toggle_editor()
            QTest.qWait(300)
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"render-{args.label}-{args.mode}.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    window.close()
    return 0


def parent(args: argparse.Namespace) -> int:
    from chopchop.services import graphics

    merged: dict[str, object] = {}
    try:
        for mode in args.modes.split(","):
            part = RESULTS / f"render-{args.label}-{mode}.json"
            runs: list[dict[str, object]] = []
            for _ in range(args.repeat):
                command = [sys.executable, "-u", __file__, "--child", "--mode", mode]
                command += ["--label", args.label, "--scenarios", args.scenarios]
                command += ["--seconds", str(args.seconds), "--size", args.size]
                done = subprocess.run(command, check=False, timeout=1800)
                if done.returncode == 0 and part.exists():
                    runs.append(json.loads(part.read_text(encoding="utf-8")))
                    part.unlink()
                else:
                    print(f"{mode}: сбой (код {done.returncode})")
            if runs:
                merged[mode] = {
                    "info": runs[0]["info"],
                    "runs": runs,
                }
    finally:
        graphics.write_gpu_preference(None)  # опыты не должны оставлять запись в реестре
    out = RESULTS / f"render-{args.label}.json"
    out.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved", out)
    return 0


def main() -> int:
    sys.path.insert(0, str(ROOT / "src"))
    sys.path.insert(0, str(ROOT / "tests"))
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="run")
    parser.add_argument("--modes", default=",".join(MODES[:5]))
    parser.add_argument("--mode", default="gl-default")
    parser.add_argument("--scenarios", default=",".join(SCENARIOS))
    parser.add_argument("--seconds", type=float, default=5.0)
    parser.add_argument("--size", default="1080p")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    return child(args) if args.child else parent(args)


if __name__ == "__main__":
    sys.exit(main())
