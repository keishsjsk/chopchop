"""Журнал работы: файл с ограничением размера в папке данных приложения, без сети и телеметрии."""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType

LOG_ENV = "CHOPCHOP_LOG_DIR"
FILE_NAME = "chopchop.log"
MAX_BYTES = 512 * 1024
BACKUPS = 3
LEVELS = {
    "error": logging.ERROR,
    "warning": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG,
}

log = logging.getLogger("chopchop")
_handler: RotatingFileHandler | None = None


def log_dir() -> Path:
    override = os.environ.get(LOG_ENV)
    if override:
        return Path(override)
    from PySide6.QtCore import QStandardPaths

    location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
    return Path(location or Path.home() / ".local" / "share" / "chopchop") / "logs"


def setup(level: str = "warning") -> Path | None:
    """Включает запись в файл журнала; возвращает путь к файлу (None, если писать некуда)."""
    global _handler
    if _handler is not None:
        set_level(level)
        return Path(_handler.baseFilename)
    try:
        folder = log_dir()
        folder.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            folder / FILE_NAME, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8"
        )
    except OSError:
        return None  # журнал не критичен: без него программа работает
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    log.addHandler(handler)
    _handler = handler
    set_level(level)
    return Path(handler.baseFilename)


def set_level(level: str) -> None:
    log.setLevel(LEVELS.get(level, logging.WARNING))


def shutdown() -> None:
    global _handler
    if _handler is not None:
        log.removeHandler(_handler)
        _handler.close()
        _handler = None


def install_excepthook() -> None:
    """Необработанные исключения попадают в журнал, а затем в обычный вывод."""
    previous = sys.excepthook

    def hook(kind: type[BaseException], error: BaseException, trace: TracebackType | None) -> None:
        log.error("Необработанное исключение", exc_info=(kind, error, trace))
        previous(kind, error, trace)

    sys.excepthook = hook
