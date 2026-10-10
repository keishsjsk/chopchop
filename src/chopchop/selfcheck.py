"""Самопроверка: всё ли нужное найдено и загружается (для CI и для проверки собранной версии)."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from chopchop import __version__
from chopchop.services.paths import is_frozen
from chopchop.services.process import no_window_flags

TIMEOUT = 30


def _result(ok: bool, detail: str = "") -> dict[str, Any]:
    return {"ok": ok, "detail": detail}


def _check_qt() -> dict[str, Any]:
    try:
        from PySide6 import QtCore, QtGui, QtOpenGLWidgets, QtWidgets  # noqa: F401
    except ImportError as error:
        return _result(False, str(error))
    return _result(True, QtCore.qVersion())


def _check_pillow() -> dict[str, Any]:
    try:
        import PIL
        import pillow_heif

        pillow_heif.register_heif_opener()
    except ImportError as error:
        return _result(False, str(error))
    return _result(True, PIL.__version__)


def _version_of(binary: Path | None) -> dict[str, Any]:
    if binary is None:
        return _result(False, "не найден")
    flags = no_window_flags()
    try:
        output = subprocess.run(
            [str(binary), "-version"],
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            check=True,
            creationflags=flags,
        ).stdout
    except (OSError, subprocess.SubprocessError) as error:
        return _result(False, f"{binary}: {error}")
    return _result(True, f"{binary} — {output.splitlines()[0] if output else ''}")


def _check_ffmpeg() -> dict[str, Any]:
    from chopchop.engines.ffmpeg import find_ffmpeg

    return _version_of(find_ffmpeg())


def _check_ffprobe() -> dict[str, Any]:
    from chopchop.engines.ffmpeg import find_ffprobe

    return _version_of(find_ffprobe())


def _check_libmpv() -> dict[str, Any]:
    from chopchop.player.libmpv import MpvUnavailableError, find_libmpv, load_mpv_module

    path = find_libmpv()
    if path is None:
        return _result(False, "не найдена")
    try:
        module = load_mpv_module()
        player = module.MPV(vo="null", ao="null", terminal=False, config=False, ytdl=False)
        version = str(player.mpv_version)
        player.terminate()
    except (MpvUnavailableError, OSError, RuntimeError) as error:
        return _result(False, f"{path}: {error}")
    return _result(True, f"{path} — {version}")


REQUIRED_RESOURCES = (
    "fonts/Monocraft.ttf",
    "fonts/Monocraft-LICENSE.txt",
    "i18n/chopchop_en.ts",
    "icons/chopchop.png",
)


def _check_resources() -> dict[str, Any]:
    """Шрифт, его лицензия, перевод и значок попали в сборку (PyInstaller, AppImage)."""
    from chopchop.services.paths import resource_dir

    root = resource_dir()
    missing = [name for name in REQUIRED_RESOURCES if not (root / name).is_file()]
    if missing:
        return _result(False, "нет файлов: " + ", ".join(missing))
    return _result(True, str(root))


def collect() -> dict[str, Any]:
    checks = {
        "qt": _check_qt(),
        "pillow": _check_pillow(),
        "ffmpeg": _check_ffmpeg(),
        "ffprobe": _check_ffprobe(),
        "libmpv": _check_libmpv(),
        "resources": _check_resources(),
    }
    return {
        "version": __version__,
        "frozen": is_frozen(),
        "python": sys.version.split()[0],
        "checks": checks,
        "ok": all(check["ok"] for check in checks.values()),
    }


def run(report_path: Path | None) -> int:
    """Выполняет проверки; результат — в файл (у окна без консоли stdout нет) или на экран."""
    report = collect()
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if report_path is not None:
        report_path.write_text(text, encoding="utf-8")
    elif sys.stdout is not None:
        print(text)
    return 0 if report["ok"] else 1
