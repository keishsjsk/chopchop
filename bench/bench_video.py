"""Бенчмарк видеоредактора: анализ файла, открытие, миниатюры, полоса обрезки, экспорт.

Запуск:  python bench/bench_video.py [--label before] [--repeat 3]
Плеер подменён заглушкой (без OpenGL и libmpv): измеряется наш код, а не декодер.
"""

import argparse
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import common
from common import Results
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(common.ROOT / "tests"))

from chopchop.core.operations import Adjust  # noqa: E402
from chopchop.core.video import Clip, VideoEffects, VideoProject  # noqa: E402
from chopchop.editor.video_session import VideoSession  # noqa: E402
from chopchop.engines.ffmpeg import find_ffmpeg, find_ffprobe, run_steps  # noqa: E402
from chopchop.engines.probe import probe  # noqa: E402
from chopchop.engines.video_engine import build_plan  # noqa: E402
from chopchop.ui.video_editor_page import VideoEditorPage  # noqa: E402
from fakes import FakeVideoPage  # noqa: E402

BUDGETS = {
    "video.open_editor": 100,
    "video.trimbar_frame": 16,
    "video.thumbs_first": 1500,
    "ui.max_blocking": 50,
}


def pump(app: QApplication, condition, timeout: float = 60.0) -> float:  # type: ignore[no-untyped-def]
    started = time.perf_counter()
    while not condition():
        app.processEvents()
        time.sleep(0.001)
        if time.perf_counter() - started > timeout:
            raise TimeoutError
    return (time.perf_counter() - started) * 1000


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="run")
    parser.add_argument("--repeat", type=int, default=3)
    args = parser.parse_args()

    ffmpeg, ffprobe = find_ffmpeg(), find_ffprobe()
    assert ffmpeg is not None and ffprobe is not None
    source = common.video(20)
    tmp = Path(tempfile.mkdtemp(prefix="chopchop-bench-"))
    os.environ["CHOPCHOP_CACHE_DIR"] = str(tmp / "cache")  # холодный старт: кэша миниатюр нет
    app = QApplication([])
    results = Results()

    for _ in range(args.repeat):
        started = time.perf_counter()
        info = probe(source, ffprobe)
        results.add("video.probe", (time.perf_counter() - started) * 1000)

    longest = 0.0
    for attempt in range(2):  # первый раз миниатюр ни в каком кэше нет, второй раз могут быть
        session = VideoSession(VideoProject((Clip(source, info),)))
        fake = FakeVideoPage()
        started = time.perf_counter()
        page = VideoEditorPage(session, fake.as_video_page(), ffmpeg, ffprobe)
        page.resize(1100, 700)
        page.show()
        app.processEvents()
        opened = (time.perf_counter() - started) * 1000
        longest = max(longest, opened)
        results.add("video.open_editor", opened)
        name = "video.thumbs_first" if attempt == 0 else "video.thumbs_again"
        waiting = page.trim
        results.add(
            name,
            pump(app, lambda trim=waiting: all(t is not None for t in trim._thumbs)) + opened,
        )
        if attempt == 0:
            # полоса обрезки с готовыми миниатюрами: кадр рисования и перетаскивание границы
            trim = page.trim
            for _ in range(30):
                started = time.perf_counter()
                trim.repaint()
                results.add("video.trimbar_frame", (time.perf_counter() - started) * 1000)
            left = QPoint(round(trim.width() * 0.05), trim.height() // 2)
            QTest.mousePress(trim, Qt.MouseButton.LeftButton, pos=left)
            for i in range(60):
                started = time.perf_counter()
                QTest.mouseMove(trim, left + QPoint(i * 6, 0))
                app.processEvents()
                elapsed = (time.perf_counter() - started) * 1000
                longest = max(longest, elapsed)
                results.add("video.trim_drag_frame", elapsed)
            QTest.mouseRelease(trim, Qt.MouseButton.LeftButton, pos=left + QPoint(360, 0))
            app.processEvents()
        page.shutdown()
        page.close()

    # --- экспорт: быстрый (копирование потоков) и с перекодированием и эффектом
    trimmed = VideoProject((Clip(source, info, start=4.0, end=16.0),))
    effects = VideoProject(
        (Clip(source, info, start=4.0, end=16.0),),
        effects=VideoEffects(adjust=Adjust(brightness=1.2, saturation=1.3)),
    )
    for name, project, precise in (
        ("video.export_copy_12s", trimmed, False),
        ("video.export_reencode_12s", effects, False),
    ):
        workdir = Path(tempfile.mkdtemp(prefix="chopchop-bench-", dir=tmp))
        plan = build_plan(project, tmp / f"{name}.mp4", ffmpeg, workdir, precise=precise)
        started = time.perf_counter()
        run_steps(plan.steps, lambda _f: None, None)
        results.add(name, (time.perf_counter() - started) * 1000)
        shutil.rmtree(workdir, ignore_errors=True)

    results.add("ui.max_blocking", longest)
    results.print(BUDGETS)
    print("saved:", results.save(args.label, "video"))


if __name__ == "__main__":
    main()
