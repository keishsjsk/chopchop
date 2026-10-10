"""Таблица «до и после» из bench/results/realtime-*.json: python bench/report_realtime.py A B."""

import json
import sys
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"


def load(label: str) -> dict[str, dict[str, object]]:
    return json.loads((RESULTS / f"realtime-{label}.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def cell(row: dict[str, object] | None) -> str:
    if row is None:
        return "падение"
    press = row["press_latency"]
    worst = f"{max(press):.0f}" if press else "-"  # type: ignore[type-var, arg-type]
    return (
        f"зав.>50: {row['stalls_50']}, >16: {row['stalls_16']}, "
        f"мышь p95 {row['move_latency_p95']} мс, нажатие {worst} мс, "
        f"paintGL p95 {row['paintgl_p95']}"
    )


def main(argv: list[str]) -> None:
    before, after = load(argv[1]), load(argv[2])
    print(f"| сценарий | {argv[1]} | {argv[2]} |\n|---|---|---|")
    for key in sorted(after):
        print(f"| {key} | {cell(before.get(key))} | {cell(after.get(key))} |")


if __name__ == "__main__":
    main(sys.argv)
