"""Цвета интерфейса берутся только из `ui/theme`: ни одного «цвета от руки» в остальных модулях."""

import re
from pathlib import Path

UI = Path(__file__).resolve().parents[2] / "src" / "chopchop" / "ui"

HEX = re.compile(r"[\"']#[0-9a-fA-F]{3,8}[\"']")
QCOLOR_LITERAL = re.compile(r"QColor\(\s*(?:[0-9\"'])")
CSS_COLOR = re.compile(r"\brgba?\(")
GLOBAL_COLOR = re.compile(r"Qt\.GlobalColor\.(?!transparent)\w+")


def _sources() -> list[Path]:
    return [p for p in UI.rglob("*.py") if "theme" not in p.relative_to(UI).parts]


def test_ui_modules_use_only_theme_colours() -> None:
    offenders: list[str] = []
    for path in _sources():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            code = (
                line.split("#")[0]
                if "#" in line and '"#' not in line and "'#" not in line
                else line
            )
            for pattern in (HEX, QCOLOR_LITERAL, CSS_COLOR, GLOBAL_COLOR):
                if pattern.search(code):
                    offenders.append(f"{path.relative_to(UI)}:{number}: {line.strip()}")
    assert offenders == [], "цвета вне ui/theme:\n" + "\n".join(offenders)


def test_scan_actually_finds_modules() -> None:
    names = {path.name for path in _sources()}
    assert {"canvas.py", "editor_page.py", "video_page.py", "trim_bar.py"} <= names
