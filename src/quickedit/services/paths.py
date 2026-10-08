"""Где искать бинарники, поставляемые вместе с программой."""

import sys
from pathlib import Path


def bundled_dirs() -> list[Path]:
    """Папки рядом с программой: в сборке — папка exe, при разработке — resources/bin."""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
        return [base, base / "bin"]
    repo_root = Path(__file__).resolve().parents[3]
    return [repo_root / "resources" / "bin"]
