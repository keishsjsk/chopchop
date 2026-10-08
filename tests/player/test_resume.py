from pathlib import Path

from PySide6.QtCore import QSettings

from chopchop.player.resume import MAX_ENTRIES, ResumeState, ResumeStore


def _store(tmp_path: Path) -> ResumeStore:
    return ResumeStore(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))


def test_roundtrip(tmp_path: Path) -> None:
    store = _store(tmp_path)
    state = ResumeState(position=61.5, volume=80, aid=2, sid=0, secondary_sid=3, sub_delay=-0.3)
    store.save(Path("a.mkv"), state, duration=3600)
    assert store.load(Path("a.mkv")) == state


def test_unknown_file_has_no_state(tmp_path: Path) -> None:
    assert _store(tmp_path).load(Path("none.mkv")) is None


def test_start_of_file_is_not_remembered(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save(Path("a.mkv"), ResumeState(position=2.0, aid=1), duration=3600)
    loaded = store.load(Path("a.mkv"))
    assert loaded is not None
    assert loaded.position == 0.0
    assert loaded.aid == 1  # дорожки при этом запоминаются


def test_finished_file_starts_over(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save(Path("a.mkv"), ResumeState(position=3595.0), duration=3600)
    loaded = store.load(Path("a.mkv"))
    assert loaded is not None
    assert loaded.position == 0.0


def test_oldest_entries_are_dropped(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for i in range(MAX_ENTRIES + 3):
        store.save(Path(f"{i}.mkv"), ResumeState(position=100.0), duration=None)
    assert store.load(Path("0.mkv")) is None
    assert store.load(Path(f"{MAX_ENTRIES + 2}.mkv")) is not None


def test_corrupt_data_is_ignored(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    settings.setValue("resume/entries", "{not json")
    assert ResumeStore(settings).load(Path("a.mkv")) is None
