from pathlib import Path

from PySide6.QtCore import QSettings

from quickedit.services.settings import (
    MAX_RECENT,
    PlayerPrefs,
    RecentFiles,
    clean_langs,
    load_player_prefs,
    save_player_prefs,
)


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


def test_clean_langs_drops_junk() -> None:
    assert clean_langs(" rus, eng;rm -rf,,en-US ") == "rus,engrm-rf,en-US"


def test_player_prefs_roundtrip(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "p.ini"), QSettings.Format.IniFormat)
    assert load_player_prefs(settings) == PlayerPrefs()
    prefs = PlayerPrefs(audio_langs="jpn,eng", sub_langs="rus", sub_font_size=40, sub_margin=10)
    save_player_prefs(settings, prefs)
    assert load_player_prefs(settings) == prefs
