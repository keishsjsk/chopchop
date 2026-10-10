"""Снимки окна настроек: docs/design/settings-<тема>-<ширина>x<высота>[-<раздел>].png.

Запуск (нужен настоящий экран, шрифты ОС): python docs/design/make_settings_screens.py [папка]
Снимается само окно настроек в двух темах и трёх размерах (минимальный 720x480, обычный 860x600 и
большой 1200x800 для экрана 1440x900), плюс несколько разделов и результаты поиска.
"""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
if sys.platform == "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "windows")

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from chopchop import i18n  # noqa: E402
from chopchop.services.app_settings import AppSettings  # noqa: E402
from chopchop.services.sub_presets import PresetStore  # noqa: E402
from chopchop.ui.settings_dialog import SettingsDialog  # noqa: E402
from chopchop.ui.theme import fonts  # noqa: E402
from chopchop.ui.theme.manager import ThemeManager  # noqa: E402

SIZES = ((720, 480), (860, 600), (960, 600), (1200, 800), (1440, 900))


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "design"
    app = QApplication([])
    fonts.load_fonts()
    fonts.apply(app, "monocraft")
    i18n.install_language(app, "ru")
    manager = ThemeManager(app)
    work = Path(tempfile.mkdtemp(prefix="chopchop-settings-"))
    for theme in ("light", "dark"):
        manager.set_theme(theme, "ember")
        settings = AppSettings(None)
        for width, height in SIZES:
            dialog = SettingsDialog(settings, None, PresetStore(work / "presets.json"))
            dialog.resize(width, height)
            dialog.show()
            QTest.qWait(300)
            dialog.open_section("general")
            QTest.qWait(150)
            dialog.grab().save(str(out / f"settings-{theme}-{width}x{height}.png"))
            if (width, height) == (860, 600):
                for section in ("playback", "appearance", "advanced", "subtitles"):
                    dialog.open_section(section)
                    QTest.qWait(200)
                    dialog.grab().save(
                        str(out / f"settings-{theme}-{width}x{height}-{section}.png")
                    )
                dialog.search.setText("громкость")
                QTest.qWait(500)
                dialog.grab().save(str(out / f"settings-{theme}-{width}x{height}-search.png"))
            dialog.done(0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
