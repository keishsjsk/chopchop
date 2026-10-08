from pathlib import Path

from PySide6.QtCore import QSettings

from quickedit.services.settings import MAX_RECENT, RecentFiles


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
