"""Менеджер темы: выбирает палитру, собирает стили и применяет их к приложению на лету."""

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QProxyStyle,
    QStyle,
    QStyleHintReturn,
    QStyleOption,
    QWidget,
)

from chopchop.services.temp_files import new_workspace, remove_workspace
from chopchop.ui.theme import current, qss, tokens
from chopchop.ui.theme.tokens import DEFAULT_ACCENT, Palette, make_palette

THEME_CHOICES = ("system", "light", "dark")


MENU_ICON_SIZE = 32


class ThemeStyle(QProxyStyle):
    """Fusion с нашими задержками: подсказка появляется через 400 мс."""

    def __init__(self) -> None:
        super().__init__("Fusion")

    def styleHint(  # noqa: N802
        self,
        hint: QStyle.StyleHint,
        option: QStyleOption | None = None,
        widget: QWidget | None = None,
        returnData: QStyleHintReturn | None = None,  # noqa: N803
    ) -> int:
        if hint == QStyle.StyleHint.SH_ToolTip_WakeUpDelay:
            return tokens.TOOLTIP_DELAY_MS
        return super().styleHint(hint, option, widget, returnData)

    def pixelMetric(  # noqa: N802
        self,
        metric: QStyle.PixelMetric,
        option: QStyleOption | None = None,
        widget: QWidget | None = None,
    ) -> int:
        # значки контекстных меню рисуются в 32 px, как у рейки: целый масштаб пиксельной сетки
        if (
            metric == QStyle.PixelMetric.PM_SmallIconSize
            and widget is not None
            and widget.property("themed")
        ):
            return MENU_ICON_SIZE
        return super().pixelMetric(metric, option, widget)


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
        self._compact = False
        self._palette = make_palette(system_theme(), self._accent)
        self._assets = new_workspace()  # значки флажков и стрелок для стилей
        self._previous_style = app.style().objectName() if app is not None else ""
        self.stylesheet = ""
        QGuiApplication.styleHints().colorSchemeChanged.connect(self._on_system_changed)

    @property
    def palette(self) -> Palette:
        return self._palette

    @property
    def choice(self) -> str:
        return self._choice

    def set_theme(
        self, choice: str, accent: str | None = None, compact: bool | None = None
    ) -> None:
        """Тема («system», «light», «dark»), акцент и плотность; применяются сразу."""
        self._choice = choice if choice in THEME_CHOICES else "system"
        if accent is not None:
            self._accent = accent
        if compact is not None:
            self._compact = compact
        self.apply()

    def _on_system_changed(self, _scheme: object) -> None:
        if self._choice == "system":
            self.apply()

    def apply(self) -> None:
        name = system_theme() if self._choice == "system" else self._choice
        self._palette = make_palette(name, self._accent)
        current.set_palette(self._palette)
        current.set_compact(self._compact)
        assets = qss.write_assets(self._palette, self._assets)
        sheet = qss.build(self._palette, assets, compact=self._compact)
        self.stylesheet = sheet
        if self._app is not None:
            if not isinstance(self._app.style(), ThemeStyle):
                self._app.setStyle(ThemeStyle())
            self._app.setStyleSheet(sheet)
            for widget in self._app.allWidgets():  # сами рисующие виджеты берут новые цвета
                widget.update()
        self.changed.emit(self._palette)

    def shutdown(self) -> None:
        if (
            self._app is not None
            and isinstance(self._app.style(), ThemeStyle)
            and self._previous_style
        ):
            self._app.setStyle(self._previous_style)
        remove_workspace(self._assets)
