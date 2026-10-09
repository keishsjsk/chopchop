"""Таблица «до / после» в Markdown по сохранённым результатам бенчмарков.

Запуск:  python bench/report.py  (читает bench/results/*-before.json и *-after.json)
"""

import json
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"


def table(suite: str) -> str:
    before = json.loads((RESULTS / f"{suite}-before.json").read_text(encoding="utf-8"))
    after = json.loads((RESULTS / f"{suite}-after.json").read_text(encoding="utf-8"))
    lines = ["| Стадия | до, мс | после, мс |", "|---|---:|---:|"]
    for name in after:
        if name not in before:
            continue
        lines.append(f"| `{name}` | {before[name]['median']:.1f} | {after[name]['median']:.1f} |")
    return "\n".join(lines)


if __name__ == "__main__":
    print("### Фото 24 Мп\n")
    print(table("photo-24MP"))
    print("\n### Видео 20 с, 1080p\n")
    print(table("video"))
