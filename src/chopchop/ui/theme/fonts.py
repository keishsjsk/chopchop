"""Шрифт интерфейса: пиксельный Monocraft (SIL OFL) или системный, на выбор в настройках.

Monocraft нарисован на сетке 9 пикселей, поэтому чёткий он только на размерах, кратных 9 пикселям
экрана: 9, 18, 27. Основной текст 18 px, заголовки 27 px, мелкие подписи 9 px. С учётом
`devicePixelRatio` размер округляется так, чтобы в пикселях устройства он оставался кратным 9.
Сглаживание и хинтинг выключены, иначе края букв размываются.

В Monocraft нет некоторых символов (например № и ✓): для них задан запасной шрифт
(`QFont.insertSubstitutions`), а в строках интерфейса такие символы не используются, это
проверяет тест `tests/ui/test_font_coverage.py`.
"""

from PySide6.QtGui import QFont, QFontDatabase, QFontMetrics, QGuiApplication
from PySide6.QtWidgets import QApplication

from chopchop.services.paths import resource_dir

FONT_FILE = "Monocraft.ttf"
GRID = 9  # пикселей экрана на «пиксель» шрифта
SMALL, BODY, TITLE = GRID, 2 * GRID, 3 * GRID  # 9, 18, 27
CHOICES = ("monocraft", "system")
# символы, которых нет в Monocraft и для которых нужен запасной шрифт, если они всё же встретятся
FALLBACK_CHARS = frozenset("№✓≥≤▾▸↕≈")
FALLBACK_FAMILIES = ("Segoe UI Symbol", "Segoe UI", "DejaVu Sans", "Noto Sans Symbols", "Noto Sans")

_family: str | None = None
_loaded: bool | None = None


def load_fonts() -> bool:
    """Регистрирует Monocraft; False, если файла нет (тогда интерфейс системным шрифтом)."""
    global _loaded, _family
    if _loaded is None:
        path = resource_dir() / "fonts" / FONT_FILE
        identifier = QFontDatabase.addApplicationFont(str(path)) if path.is_file() else -1
        families = QFontDatabase.applicationFontFamilies(identifier) if identifier >= 0 else []
        _family = families[0] if families else None  # название из метаданных файла
        _loaded = _family is not None
        if _family is not None:
            QFont.insertSubstitutions(_family, list(FALLBACK_FAMILIES))
    return _loaded


def family() -> str:
    """Название семейства Monocraft из метаданных файла (пусто, если шрифт не загрузился)."""
    load_fonts()
    return _family or ""


def device_ratio(ratio: float | None = None) -> float:
    if ratio is not None:
        return ratio
    screen = QGuiApplication.primaryScreen()
    return screen.devicePixelRatio() if screen is not None else 1.0


def snapped_pixel_size(logical: int, ratio: float) -> float:
    """Логический размер так, чтобы в пикселях устройства он был кратен 9 (не меньше 9)."""
    device = max(int(logical * ratio / GRID + 0.5), 1) * GRID  # ближайшее кратное, середина вверх
    return device / ratio


def pixel_font(size: int = BODY, ratio: float | None = None) -> QFont:
    """Monocraft нужного размера (9, 18 или 27) без сглаживания и хинтинга."""
    ratio = device_ratio(ratio)
    font = QFont(family() if load_fonts() else QFont().family())
    snapped = snapped_pixel_size(size, ratio)
    if abs(snapped - round(snapped)) < 0.01:
        font.setPixelSize(round(snapped))
    else:
        screen = QGuiApplication.primaryScreen()
        dpi = screen.logicalDotsPerInchY() if screen is not None else 96.0
        font.setPointSizeF(snapped * 72.0 / dpi)
    font.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font


def system_font() -> QFont:
    """Обычный читаемый шрифт системы."""
    return QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)


def ui_font(size: int = BODY) -> QFont:
    """Шрифт интерфейса по выбору в настройках (Monocraft или системный)."""
    if _choice == "system" or not load_fonts():
        font = system_font()
        if size != BODY:
            font.setPixelSize(round(size * 2 / 3))  # те же пропорции: заголовок крупнее текста
        return font
    return pixel_font(size)


_choice = "monocraft"


def choice() -> str:
    return _choice


def apply(app: QApplication, name: str) -> None:
    """Шрифт всего приложения: Monocraft или системный; виджеты с особым шрифтом обновляет окно."""
    global _choice
    _choice = name if name in CHOICES else "monocraft"
    if _choice == "monocraft" and load_fonts():
        app.setFont(pixel_font(BODY))
    else:
        app.setFont(system_font())


def covers(font: QFont, text: str) -> bool:
    """Есть ли в шрифте все буквы текста (пробелы не в счёт)."""
    metrics = QFontMetrics(font)
    return all(metrics.inFontUcs4(ord(char)) for char in text if not char.isspace())
