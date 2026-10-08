from pytestqt.qtbot import QtBot

from chopchop.services.settings import HWDEC_MODES, PlayerPrefs
from chopchop.ui.settings_dialog import SettingsDialog


def test_dialog_offers_all_decoding_modes_and_returns_the_choice(qtbot: QtBot) -> None:
    dialog = SettingsDialog(PlayerPrefs())
    qtbot.addWidget(dialog)
    assert [dialog._hwdec.itemData(i) for i in range(dialog._hwdec.count())] == list(HWDEC_MODES)
    assert dialog.prefs().hwdec == "auto-copy-safe"
    dialog._hwdec.setCurrentIndex(dialog._hwdec.findData("no"))
    assert dialog.prefs().hwdec == "no"


def test_dialog_shows_the_saved_mode(qtbot: QtBot) -> None:
    dialog = SettingsDialog(PlayerPrefs(hwdec="auto-safe"))
    qtbot.addWidget(dialog)
    assert dialog._hwdec.currentData() == "auto-safe"
