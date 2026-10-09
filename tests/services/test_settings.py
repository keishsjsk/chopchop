from pathlib import Path

from PySide6.QtCore import QSettings

from chopchop.services.app_settings import AppSettings
from chopchop.services.settings import MAX_RECENT, PlayerPrefs, RecentFiles, player_prefs


def _recent(tmp_path: Path) -> RecentFiles:
    return RecentFiles(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))


def test_add_puts_newest_first_without_duplicates(tmp_path: Path) -> None:
    recent = _recent(tmp_path)
    recent.add(Path("a.jpg"))
    recent.add(Path("b.jpg"))
    recent.add(Path("a.jpg"))
    assert recent.items() == [Path("a.jpg"), Path("b.jpg")]


def test_list_is_capped(tmp_path: Path) -> None:
    recent = _recent(tmp_path)
    for i in range(MAX_RECENT + 5):
        recent.add(Path(f"{i}.jpg"))
    assert len(recent.items()) == MAX_RECENT


def test_player_prefs_default_to_safe_hardware_decoding() -> None:
    prefs = player_prefs(AppSettings(None))
    assert prefs == PlayerPrefs()
    assert prefs.hwdec == "auto-copy-safe"


def test_player_prefs_follow_the_settings() -> None:
    settings = AppSettings(None)
    settings.set("playback.audio_langs", "jpn,eng")
    settings.set("subtitles.font_size", 40)
    settings.set("subtitles.margin", 10)
    settings.set("playback.hwdec", "off")
    settings.set("playback.volume_default", 80)
    assert player_prefs(settings) == PlayerPrefs("jpn,eng", "", 40, 10, "no", 80.0)
