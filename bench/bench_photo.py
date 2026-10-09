"""Бенчмарк фоторедактора: открытие, переключение инструментов, перетаскивание, кисть, ползунки.

Запуск:  python bench/bench_photo.py [--size 24MP] [--label before] [--repeat 5]
Qt работает без экрана (offscreen), поэтому цифры сравнимы между запусками на одной машине,
но не заменяют проверку на настоящем окне.
"""

import argparse
import tempfile
import time
from pathlib import Path

import common
from common import Results
from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from chopchop.editor.session import EditSession
from chopchop.services import profiling
from chopchop.services.profiling import LoopWatchdog
from chopchop.ui.editor_page import EditorPage
from chopchop.ui.main_window import MainWindow

# бюджеты из задания (мс); ключ совпадает с названием замера
BUDGETS = {
    "viewer.first_show": 300,
    "editor.tool_switch": 50,
    "crop.drag_frame": 16,
    "brush.stroke_frame": 16,
    "redact.drag_frame": 16,
    "crop.release_to_preview": 100,
    "brush.release_to_preview": 100,
    "adjust.slider_to_preview": 100,
    "ui.max_blocking": 50,
}


def wait_until(app: QApplication, condition, timeout: float = 30.0) -> float:  # type: ignore[no-untyped-def]
    started = time.perf_counter()
    while not condition():
        app.processEvents()
        time.sleep(0.001)  # QTest.qWait держит GIL и тормозит фоновые потоки
        if time.perf_counter() - started > timeout:
            raise TimeoutError
    return (time.perf_counter() - started) * 1000


def settle(app: QApplication, page: EditorPage) -> float:
    """Ждёт, пока страница закончит все отложенные расчёты превью; возвращает мс."""
    started = time.perf_counter()
    while True:
        app.processEvents()
        busy = getattr(page, "is_busy", None)
        if busy is not None:
            if not busy():
                break
        elif not page._timer.isActive():
            break
        time.sleep(0.001)  # QTest.qWait держит GIL и тормозит фоновые потоки
    return (time.perf_counter() - started) * 1000


class Stopwatch:
    """Самый долгий блок кода, выполненный подряд в потоке интерфейса."""

    def __init__(self) -> None:
        self.longest = 0.0

    def measure(self, fn):  # type: ignore[no-untyped-def]
        started = time.perf_counter()
        result = fn()
        self.longest = max(self.longest, (time.perf_counter() - started) * 1000)
        return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--size", default="24MP", choices=list(common.PHOTO_SIZES))
    parser.add_argument("--label", default="run")
    parser.add_argument("--repeat", type=int, default=5)
    args = parser.parse_args()

    path = common.photo(args.size)
    app = QApplication([])
    results = Results()
    stopwatch = Stopwatch()
    watchdog = LoopWatchdog(
        threshold_ms=25
    )  # зависания цикла событий во время работы с инструментами
    profiling.set_enabled(True)
    tmp = Path(tempfile.mkdtemp(prefix="chopchop-bench-"))

    # --- первый показ в просмотрщике
    window = MainWindow(QSettings(str(tmp / "s.ini"), QSettings.Format.IniFormat))
    window.resize(1400, 900)
    window.show()
    app.processEvents()
    started = time.perf_counter()
    window.open_file(path)
    wait_until(app, lambda: window.viewer.has_image())
    app.processEvents()
    results.add("viewer.first_show", (time.perf_counter() - started) * 1000)
    window.close()

    # --- открытие редактора
    session = EditSession(path)
    started = time.perf_counter()
    session.start()
    wait_until(app, lambda: session.is_ready)
    results.add("editor.open", (time.perf_counter() - started) * 1000)

    page = EditorPage(session)
    page.resize(1400, 900)
    page.show()
    settle(app, page)
    canvas = page.canvas
    cw, ch = canvas.width(), canvas.height()

    def pt(fx: float, fy: float) -> QPoint:
        return QPoint(round(cw * fx), round(ch * fy))

    # --- переключение инструментов
    for key in ("crop", "redact", "draw", "text", "adjust", "rotate", "resize"):
        for _ in range(args.repeat):
            started = time.perf_counter()
            page.select_tool(key)
            app.processEvents()
            results.add("editor.tool_switch", (time.perf_counter() - started) * 1000)
            page.select_tool(key)  # снять выбор
            app.processEvents()

    # --- кадрирование: тянем рамку
    watchdog.start()
    page.select_tool("crop")
    settle(app, page)
    edge = canvas.image_rect()
    left_edge = QPoint(round(edge.left()) + 1, round(edge.center().y()))
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=left_edge)
    steps = 60
    for i in range(steps):
        started = time.perf_counter()
        QTest.mouseMove(canvas, left_edge + QPoint(round(edge.width() * 0.3 * i / steps), 0))
        app.processEvents()
        elapsed = (time.perf_counter() - started) * 1000
        results.add("crop.drag_frame", elapsed)
        stopwatch.longest = max(stopwatch.longest, elapsed)
    QTest.mouseRelease(
        canvas, Qt.MouseButton.LeftButton, pos=left_edge + QPoint(round(edge.width() * 0.3), 0)
    )
    settle(app, page)
    for _ in range(args.repeat):
        started = time.perf_counter()
        page.apply_pending()
        settle(app, page)
        results.add("crop.release_to_preview", (time.perf_counter() - started) * 1000)
        page.undo()
        settle(app, page)
        settle(app, page)
        edge = canvas.image_rect()
        left_edge = QPoint(round(edge.left()) + 1, round(edge.center().y()))
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=left_edge)
        QTest.mouseMove(canvas, left_edge + QPoint(round(edge.width() * 0.3), 0))
        QTest.mouseRelease(
            canvas, Qt.MouseButton.LeftButton, pos=left_edge + QPoint(round(edge.width() * 0.3), 0)
        )
        settle(app, page)
    page.select_tool("crop")  # снять
    page.undo()
    settle(app, page)

    # --- кисть: длинный штрих (300 точек)
    page.select_tool("draw")
    settle(app, page)
    for _ in range(args.repeat):
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=pt(0.2, 0.5))
        for i in range(300):
            started = time.perf_counter()
            fx = 0.2 + 0.6 * i / 300
            QTest.mouseMove(canvas, pt(fx, 0.5 + 0.2 * __import__("math").sin(i / 15)))
            app.processEvents()
            elapsed = (time.perf_counter() - started) * 1000
            results.add("brush.stroke_frame", elapsed)
            stopwatch.longest = max(stopwatch.longest, elapsed)
        started = time.perf_counter()
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=pt(0.8, 0.5))
        settle(app, page)
        results.add("brush.release_to_preview", (time.perf_counter() - started) * 1000)
    page.select_tool("draw")

    # --- скрытие области (размытие): тянем рамку с живым превью
    page.select_tool("redact")
    page._redact_mode.setCurrentIndex(2)
    settle(app, page)
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=pt(0.3, 0.3))
    for i in range(40):
        started = time.perf_counter()
        QTest.mouseMove(canvas, pt(0.3 + 0.3 * i / 40, 0.3 + 0.3 * i / 40))
        app.processEvents()
        elapsed = (time.perf_counter() - started) * 1000
        results.add("redact.drag_frame", elapsed)
        stopwatch.longest = max(stopwatch.longest, elapsed)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=pt(0.6, 0.6))
    results.add("redact.release_to_preview", settle(app, page))
    page.escape()
    page.select_tool("redact")

    # --- ползунки цветокоррекции
    page.select_tool("adjust")
    settle(app, page)
    slider = page._sliders["brightness"]
    for i in range(args.repeat * 4):
        started = time.perf_counter()
        slider.setValue(10 + i * 3)
        settle(app, page)
        elapsed = (time.perf_counter() - started) * 1000
        results.add("adjust.slider_to_preview", elapsed)
        stopwatch.longest = max(stopwatch.longest, elapsed)
    page.select_tool("adjust")

    # --- применение коррекции, фильтра и отмена
    for _ in range(args.repeat):
        page.select_tool("adjust")
        slider.setValue(30)
        settle(app, page)
        started = time.perf_counter()
        page.apply_pending()
        settle(app, page)
        results.add("adjust.apply_to_preview", (time.perf_counter() - started) * 1000)
        started = time.perf_counter()
        page.undo()
        settle(app, page)
        results.add("history.undo", (time.perf_counter() - started) * 1000)
        started = time.perf_counter()
        page.redo()
        settle(app, page)
        results.add("history.redo", (time.perf_counter() - started) * 1000)
        page.undo()
        settle(app, page)
        page.select_tool("adjust")

    watchdog.stop()
    # --- экспорт (в фоне, поток интерфейса свободен)
    exported: list[Path] = []
    session.exported.connect(exported.append)
    started = time.perf_counter()
    session.export(tmp / "out.jpg", "jpeg", 90)
    wait_until(app, lambda: bool(exported), timeout=120)
    results.add("export.jpeg_full", (time.perf_counter() - started) * 1000)

    results.add("ui.max_blocking", max(watchdog.stalls, default=0.0))  # 0: короче 25 мс
    results.print(BUDGETS)
    print("\nstages inside the engine (profile log):")
    for name, (n, mean, peak) in sorted(profiling.summary().items()):
        print(f"  {name:<28} n={n:<4} mean={mean:7.2f}ms  max={peak:7.2f}ms")
    print("saved:", results.save(args.label, f"photo-{args.size}"))
    page.close()


if __name__ == "__main__":
    main()
