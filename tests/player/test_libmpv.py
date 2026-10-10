import sys
from pathlib import Path

import pytest

from chopchop.player.libmpv import find_libmpv

_NAME = "libmpv-2.dll" if sys.platform == "win32" else "libmpv.so.2"


def test_finds_library_in_search_dir(tmp_path: Path) -> None:
    lib = tmp_path / _NAME
    lib.write_bytes(b"")
    assert find_libmpv([tmp_path]) == lib


def test_missing_returns_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ctypes.util.find_library", lambda _name: None)
    assert find_libmpv([tmp_path]) is None


def test_mpv_gets_the_programs_fonts_folder_for_subtitles() -> None:
    from types import SimpleNamespace

    from chopchop.player.libmpv import create_mpv
    from chopchop.services.settings import PlayerPrefs

    captured: dict[str, object] = {}

    def fake_mpv(**options: object) -> object:
        captured.update(options)
        return object()

    create_mpv(SimpleNamespace(MPV=fake_mpv), PlayerPrefs())  # type: ignore[arg-type]
    folder = Path(str(captured["sub_fonts_dir"]))
    assert (folder / "Monocraft.ttf").is_file()  # libass видит шрифт из папки программы
