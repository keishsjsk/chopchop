"""Общее для бенчмарков: тестовые файлы, замер и таблица результатов."""

import json
import os
import statistics
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

DATA = Path(__file__).resolve().parent / ".data"
RESULTS = Path(__file__).resolve().parent / "results"

PHOTO_SIZES = {"12MP": (4000, 3000), "24MP": (6000, 4000)}


def photo(name: str = "24MP") -> Path:
    """JPEG нужного размера: градиент, фигуры и шум, чтобы файл был похож на настоящий."""
    from PIL import Image, ImageDraw

    DATA.mkdir(exist_ok=True)
    path = DATA / f"photo_{name}.jpg"
    if path.exists():
        return path
    width, height = PHOTO_SIZES[name]
    base = Image.linear_gradient("L").resize((width, height))
    image = Image.merge("RGB", (base, base.transpose(Image.Transpose.FLIP_TOP_BOTTOM), base))
    draw = ImageDraw.Draw(image)
    for i in range(60):
        x, y = (i * 997) % width, (i * 577) % height
        draw.ellipse((x, y, x + 300 + i * 5, y + 200 + i * 4), outline=(255 - i * 3, i * 4, 90))
    noise = Image.effect_noise((width, height), 40).convert("RGB")
    Image.blend(image, noise, 0.25).save(path, "JPEG", quality=90)
    return path


def video(seconds: int = 20, size: tuple[int, int] = (1920, 1080)) -> Path:
    """Ролик 1080p с ключевым кадром каждые 2 секунды и звуком."""
    from chopchop.engines.ffmpeg import find_ffmpeg

    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        raise SystemExit("ffmpeg не найден (resources/bin или PATH)")
    DATA.mkdir(exist_ok=True)
    path = DATA / f"video_{seconds}s_{size[1]}p.mp4"
    if path.exists():
        return path
    subprocess.run(
        [str(ffmpeg), "-y", "-loglevel", "error"]
        + ["-f", "lavfi", "-i", f"testsrc2=duration={seconds}:size={size[0]}x{size[1]}:rate=30"]
        + ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
        + ["-c:v", "libx264", "-g", "60", "-pix_fmt", "yuv420p", "-preset", "veryfast"]
        + ["-c:a", "aac", "-shortest", str(path)],
        check=True,
        timeout=300,
    )
    return path


class Results:
    """Набор замеров в миллисекундах: по несколько повторов, в таблице медиана и максимум."""

    def __init__(self) -> None:
        self.rows: dict[str, list[float]] = {}

    def add(self, name: str, milliseconds: float) -> None:
        self.rows.setdefault(name, []).append(milliseconds)

    def time(self, name: str, fn: Callable[[], object], repeat: int = 1) -> None:
        for _ in range(repeat):
            started = time.perf_counter()
            fn()
            self.add(name, (time.perf_counter() - started) * 1000)

    def summary(self) -> dict[str, dict[str, float]]:
        return {
            name: {
                "median": statistics.median(values),
                "max": max(values),
                "n": float(len(values)),
            }
            for name, values in self.rows.items()
        }

    def print(self, budgets: dict[str, float] | None = None) -> None:
        budgets = budgets or {}
        width = max((len(n) for n in self.rows), default=10)
        print(f"{'stage':<{width}}  {'median':>9}  {'max':>9}  budget")
        for name, stats in self.summary().items():
            budget = budgets.get(name)
            mark = ""
            if budget is not None:
                mark = f"{budget:>6.0f}  {'ok' if stats['median'] <= budget else 'OVER'}"
            print(f"{name:<{width}}  {stats['median']:>7.1f}ms  {stats['max']:>7.1f}ms  {mark}")

    def save(self, label: str, suite: str) -> Path:
        RESULTS.mkdir(exist_ok=True)
        path = RESULTS / f"{suite}-{label}.json"
        path.write_text(json.dumps(self.summary(), indent=2), encoding="utf-8")
        return path
