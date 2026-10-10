"""Создание QApplication и главного окна."""

import os
import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLocale, QSettings, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from chopchop import __version__, i18n
from chopchop.services import event_profile, logs, temp_files
from chopchop.services.app_settings import AppSettings, default_settings_path
from chopchop.services.event_profile import ProfiledApplication
from chopchop.services.paths import resource_dir
from chopchop.services.profiling import LoopWatchdog, enabled, setup_logging
from chopchop.services.settings import default_settings
from chopchop.services.temp_files import cleanup_stale
from chopchop.ui.main_window import MainWindow
from chopchop.ui.theme import fonts
from chopchop.ui.theme.manager import ThemeManager

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
    # имена нужны до создания приложения: от них зависят папки настроек, журнала и кэша
    QCoreApplication.setApplicationName("CHOPCHOP")
    QCoreApplication.setOrganizationName("CHOPCHOP")
    settings = load_settings(default_settings_path(), default_settings())
    scale = settings.get_int("appearance.ui_scale")
    if scale != 100 and "QT_SCALE_FACTOR" not in os.environ:
        os.environ["QT_SCALE_FACTOR"] = f"{scale / 100:g}"  # масштаб интерфейса, после перезапуска
    app_class = ProfiledApplication if enabled() else QApplication  # время обработчиков событий
    app = app_class(sys.argv[:1])
    app.setApplicationVersion(__version__)
    icon = resource_dir() / "icons" / "chopchop.png"
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))

    logs.setup(settings.get_str("advanced.log_level"))
    logs.install_excepthook()
    fonts.load_fonts()
    i18n.install_language(app, settings.get_str("general.language"))
    folder = settings.get_str("advanced.temp_dir")
    temp_files.set_root(Path(folder) if folder else None)
    cleanup_stale()
    setup_logging()
    watchdogs = [LoopWatchdog(16), LoopWatchdog(50)] if enabled() else []  # кадр и «зависание»
    for watchdog in watchdogs:
        watchdog.start()
    theme = ThemeManager(app)
    window = MainWindow(default_settings(), settings, theme)
    for text in settings.startup_notices:
        window.statusBar().showMessage(text, 15000)
    settings.notice.connect(lambda text: window.statusBar().showMessage(text, 15000))
    window.show()
    if initial is not None:
        window.open_file(initial)
    code = app.exec()
    settings.flush()
    theme.shutdown()
    for watchdog in watchdogs:
        watchdog.stop()
    if enabled():
        print(event_profile.report(app), file=sys.stderr)
    logs.shutdown()
    return code
