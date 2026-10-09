"""Шрифты: пиксельный Tiny5 для заголовков и коротких подписей, системный для остального.

Tiny5 (SIL OFL) нарисован на сетке 8×8 единиц em, поэтому чёткий он только на размерах, кратных
8 пикселям экрана. `pixel_font` подбирает размер с учётом масштаба экрана и отключает
сглаживание, чтобы края оставались ровными.
"""

from PySide6.QtGui import QFont, QFontDatabase, QFontMetrics, QGuiApplication

from chopchop.services.paths import resource_dir

PIXEL_FAMILY = "Tiny5"
PIXEL_UNIT = 8  # пикселей экрана в «пикселе» шрифта на масштабе 1: размеры кратны 8
FONT_FILE = "Tiny5.ttf"

_loaded: bool | None = None


def load_fonts() -> bool:
    """Регистрирует поставляемые шрифты; False, если файла нет (тогда подписи системным шрифтом)."""
    global _loaded
    if _loaded is None:
        path = resource_dir() / "fonts" / FONT_FILE
        identifier = QFontDatabase.addApplicationFont(str(path)) if path.is_file() else -1
        _loaded = identifier >= 0 and PIXEL_FAMILY in QFontDatabase.applicationFontFamilies(
            identifier
        )
    return _loaded


def snapped_pixel_size(scale: int, ratio: float) -> float:
    """Логический размер шрифта, при котором на экране выходит число, кратное 8 пикселям."""
    device = max(PIXEL_UNIT, round(PIXEL_UNIT * scale * ratio / PIXEL_UNIT) * PIXEL_UNIT)
    return device / ratio


def pixel_font(scale: int = 2, ratio: float | None = None) -> QFont:
    """Пиксельный шрифт: scale 2 — 16 px, 3 — 24 px, 4 — 32 px (в пикселях экрана)."""
    if ratio is None:
        screen = QGuiApplication.primaryScreen()
        ratio = screen.devicePixelRatio() if screen is not None else 1.0
    font = QFont(PIXEL_FAMILY if load_fonts() else QFont().family())
    size = snapped_pixel_size(scale, ratio)
    if abs(size - round(size)) < 0.01:
        font.setPixelSize(round(size))
    else:
        screen = QGuiApplication.primaryScreen()
        dpi = screen.logicalDotsPerInchY() if screen is not None else 96.0
        font.setPointSizeF(size * 72.0 / dpi)
    font.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font


def ui_font() -> QFont:
    """Обычный читаемый шрифт интерфейса (системный)."""
    return QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)


def covers(font: QFont, text: str) -> bool:
    """Есть ли в шрифте все буквы текста (пробелы не в счёт)."""
    metrics = QFontMetrics(font)
    return all(metrics.inFontUcs4(ord(char)) for char in text if not char.isspace())
