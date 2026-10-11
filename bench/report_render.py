"""Таблица «до и после» по режимам рендера из результатов `bench_render.py`.

    python bench/report_render.py bench/results/render-before.json bench/results/render-after.json

Печатает таблицу Markdown: на каждый режим и сценарий медиана по прогонам для времени кадра
(p50/p95/max, мс) и числа пауз цикла событий дольше 50 мс. Режим, которого не было «до», показан
только «после».
"""

import json
import statistics
import sys
from pathlib import Path

SCENARIOS = ("drag_block", "stretch_edge", "drag_seek", "photo_crop")
LABELS = {
    "drag_block": "перенос блока",
    "stretch_edge": "растяжение края",
    "drag_seek": "ползунок перемотки",
    "photo_crop": "кадрирование 24 Мп",
}


def load(path: str) -> dict[str, dict[str, dict[str, float]]]:
    """Режим -> сценарий -> метрика -> медиана по прогонам."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out: dict[str, dict[str, dict[str, float]]] = {}
    for mode, entry in data.items():
        runs = entry["runs"]
        out[mode] = {}
        for scenario in SCENARIOS:
            rows = [run[scenario] for run in runs if scenario in run]
            if rows:
                out[mode][scenario] = {
                    key: statistics.median(row[key] for row in rows)
                    for key in ("frame_p50", "frame_p95", "frame_max", "stalls_50", "stall_max")
                }
    return out


def cell(row: dict[str, float] | None) -> str:
    if row is None:
        return "—"
    frame = f"{row['frame_p50']:.1f} / {row['frame_p95']:.1f} / {row['frame_max']:.0f}"
    return f"{frame}, пауз {row['stalls_50']:.0f}"


def main() -> int:
    before, after = load(sys.argv[1]), load(sys.argv[2])
    print("| Режим | Сценарий | До: кадр p50 / p95 / max, мс | После: кадр p50 / p95 / max, мс |")
    print("|---|---|---|---|")
    for mode in dict.fromkeys([*before, *after]):
        for scenario in SCENARIOS:
            old = before.get(mode, {}).get(scenario)
            new = after.get(mode, {}).get(scenario)
            if old is None and new is None:
                continue
            print(f"| {mode} | {LABELS[scenario]} | {cell(old)} | {cell(new)} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
