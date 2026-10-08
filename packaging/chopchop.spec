# -*- mode: python ; coding: utf-8 -*-
"""Сборка PyInstaller (режим папки: быстрее стартует, чем один exe).

Переменная CHOPCHOP_BINARIES — папка с bin/ (ffmpeg, ffprobe, libmpv-2.dll) и lib/
(общие библиотеки ffmpeg на Linux), её готовит packaging/fetch_binaries.py.
"""

import os
import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent  # noqa: F821 (SPECPATH задаёт PyInstaller)
BINARIES = Path(os.environ.get("CHOPCHOP_BINARIES", ROOT / "resources")).resolve()
IS_WINDOWS = sys.platform == "win32"


def folder(source: Path, target: str) -> list[tuple[str, str]]:
    """Все файлы папки как данные: ffmpeg и DLL копируются как есть, без анализа зависимостей."""
    if not source.is_dir():
        return []
    return [(str(path), target) for path in sorted(source.iterdir()) if path.is_file()]


def system_libmpv() -> list[tuple[str, str]]:
    """На Linux libmpv берётся из системы; PyInstaller подтянет и её зависимости."""
    if IS_WINDOWS:
        return []
    for directory in ("/usr/lib/x86_64-linux-gnu", "/usr/lib64", "/usr/lib"):
        for name in ("libmpv.so.2", "libmpv.so.1"):
            candidate = Path(directory) / name
            if candidate.exists():
                return [(str(candidate.resolve()), ".")]
    raise SystemExit("libmpv не найдена: установите libmpv2 (apt install libmpv2)")


datas = [(str(ROOT / "resources" / "icons"), "resources/icons")]
datas += folder(BINARIES / "bin", "bin")
datas += folder(BINARIES / "lib", "lib")

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT / "src")],
    binaries=system_libmpv(),
    datas=datas,
    hiddenimports=["pillow_heif", "mpv"],
    excludes=["tkinter", "unittest", "PySide6.QtTest", "pytest"],
    noarchive=False,
)

# PyInstaller сам копирует зависимости DLL из bin/ в корень сборки (вторая копия ffmpeg, +190 МБ).
# Ищут их рядом с ffmpeg.exe, поэтому корневые копии не нужны.
OWN_DLLS = {path.name.lower() for path in (BINARIES / "bin").glob("*.dll")}
a.binaries = [
    entry
    for entry in a.binaries
    if "/" in entry[0].replace("\\", "/") or entry[0].lower() not in OWN_DLLS
]

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CHOPCHOP" if IS_WINDOWS else "chopchop",
    console=False,
    icon=str(ROOT / "resources" / "icons" / "chopchop.ico") if IS_WINDOWS else None,
    upx=False,
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    name="CHOPCHOP",
    upx=False,
)
