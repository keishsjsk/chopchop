"""Где искать бинарники и ресурсы, поставляемые вместе с программой."""

import sys
from pathlib import Path


def is_frozen() -> bool:
    """Запущена ли программа из собранной PyInstaller версии."""
    return bool(getattr(sys, "frozen", False))


def _bundle_roots() -> list[Path]:
    """Папка с exe и папка с данными PyInstaller (у onedir это _internal)."""
    roots = [Path(sys.executable).resolve().parent]
    internal = getattr(sys, "_MEIPASS", None)
    if internal:
        roots.append(Path(internal))
    return roots


def bundled_dirs() -> list[Path]:
    """Где лежат бинарники: в сборке рядом с exe и в её данных, при разработке — resources/bin."""
    if is_frozen():
        dirs: list[Path] = []
        for root in _bundle_roots():
            for candidate in (root, root / "bin"):
                if candidate not in dirs:
                    dirs.append(candidate)
        return dirs
    repo_root = Path(__file__).resolve().parents[3]
    return [repo_root / "resources" / "bin"]


def resource_dir() -> Path:
    """Папка resources: иконки и другие файлы, которые не код."""
    if is_frozen():
        return _bundle_roots()[-1] / "resources"
    return Path(__file__).resolve().parents[3] / "resources"
