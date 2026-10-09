"""Менеджер темы: выбирает палитру, собирает стили и применяет их к приложению на лету."""

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from chopchop.services.temp_files import new_workspace, remove_workspace
from chopchop.ui.theme import qss
from chopchop.ui.theme.tokens import DEFAULT_ACCENT, Palette, make_palette

THEME_CHOICES = ("system", "light", "dark")


def system_theme() -> str:
    """Тема ОС: «dark» или «light» (если ОС не сообщает — светлая)."""
    scheme = QGuiApplication.styleHints().colorScheme()
    return "dark" if scheme == Qt.ColorScheme.Dark else "light"


class ThemeManager(QObject):
    changed = Signal(object)  # новая Palette

    def __init__(self, app: QApplication | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._app = app
        self._choice = "system"
        self._accent = DEFAULT_ACCENT
        self._palette = make_palette(system_theme(), self._accent)
        self._assets = new_workspace()  # значки флажков и стрелок для стилей
        QGuiApplication.styleHints().colorSchemeChanged.connect(self._on_system_changed)

    @property
    def palette(self) -> Palette:
        return self._palette

    @property
    def choice(self) -> str:
        return self._choice

    def set_theme(self, choice: str, accent: str | None = None) -> None:
        """Тема («system», «light», «dark») и акцент; применяется сразу, без перезапуска."""
        self._choice = choice if choice in THEME_CHOICES else "system"
        if accent is not None:
            self._accent = accent
        self.apply()

    def _on_system_changed(self, _scheme: object) -> None:
        if self._choice == "system":
            self.apply()

    def apply(self) -> None:
        name = system_theme() if self._choice == "system" else self._choice
        self._palette = make_palette(name, self._accent)
        assets = qss.write_assets(self._palette, self._assets)
        sheet = qss.build(self._palette, assets)
        if self._app is not None:
            self._app.setStyleSheet(sheet)
        self.stylesheet = sheet
        self.changed.emit(self._palette)

    def shutdown(self) -> None:
        remove_workspace(self._assets)
