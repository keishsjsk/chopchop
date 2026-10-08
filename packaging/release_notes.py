"""Выводит из CHANGELOG.md заметки для одной версии: python packaging/release_notes.py 0.1.0."""

import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parents[1] / "CHANGELOG.md"


def notes_for(version: str, text: str) -> str:
    """Текст раздела «## [версия] — дата» до следующего раздела; пустая строка, если версии нет."""
    pattern = re.compile(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", re.S | re.M)
    match = pattern.search(text)
    return match.group(1).strip() + "\n" if match else ""


def latest_version(text: str) -> str | None:
    match = re.search(r"^## \[(\d+\.\d+\.\d+)\]", text, re.M)
    return match.group(1) if match else None


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: release_notes.py <версия>", file=sys.stderr)
        return 2
    version = sys.argv[1].lstrip("v").split("-")[0]  # v0.1.0-beta.1 → 0.1.0
    notes = notes_for(version, CHANGELOG.read_text(encoding="utf-8"))
    if not notes:
        print(f"в CHANGELOG.md нет раздела для версии {sys.argv[1]}", file=sys.stderr)
        return 1
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    print(notes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
