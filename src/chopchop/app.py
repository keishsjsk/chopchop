"""Создание QApplication и главного окна."""

import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLocale, QSettings, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from chopchop import __version__, i18n
from chopchop.services import logs, temp_files
from chopchop.services.app_settings import AppSettings, default_settings_path
from chopchop.services.paths import resource_dir
from chopchop.services.profiling import LoopWatchdog, enabled, setup_logging
from chopchop.services.settings import default_settings
from chopchop.services.temp_files import cleanup_stale
from chopchop.ui.main_window import MainWindow

APP_ID = "CHOPCHOP.CHOPCHOP"


def _set_windows_app_id() -> None:
    """Свой идентификатор приложения: значок в панели задач не склеивается с Python."""
    if sys.platform != "win32":
        return
    import contextlib
    import ctypes

    with contextlib.suppress(AttributeError, OSError):
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)


def load_settings(path: Path | None, legacy: QSettings | None) -> AppSettings:
    """Настройки из файла; при первом запуске язык берётся из системы, старое переносится."""
    settings = AppSettings(path)
    if settings.first_run:
        if legacy is not None:
            settings.import_legacy(legacy)
        system_is_russian = QLocale.system().language() == QLocale.Language.Russian
        settings.set("general.language", "ru" if system_is_russian else "en")
        settings.restart_pending.clear()  # это начальное значение, а не просьба пользователя
        settings.flush()
    return settings


def run(initial: Path | None = None) -> int:
    _set_windows_app_id()
    # много событий мыши подряд склеиваются в одно: рисуем по последнему положению
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_CompressHighFrequencyEvents, True)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("CHOPCHOP")
    app.setOrganizationName("CHOPCHOP")
    app.setApplicationVersion(__version__)
    icon = resource_dir() / "icons" / "chopchop.png"
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))

    settings = load_settings(default_settings_path(), default_settings())
    logs.setup(settings.get_str("advanced.log_level"))
    logs.install_excepthook()
    i18n.install_language(app, settings.get_str("general.language"))
    folder = settings.get_str("advanced.temp_dir")
    temp_files.set_root(Path(folder) if folder else None)
    cleanup_stale()
    setup_logging()
    watchdog = LoopWatchdog() if enabled() else None
    if watchdog is not None:
        watchdog.start()
    window = MainWindow(default_settings(), settings)
    for text in settings.startup_notices:
        window.statusBar().showMessage(text, 15000)
    settings.notice.connect(lambda text: window.statusBar().showMessage(text, 15000))
    window.show()
    if initial is not None:
        window.open_file(initial)
    code = app.exec()
    settings.flush()
    if watchdog is not None:
        watchdog.stop()
    logs.shutdown()
    return code
