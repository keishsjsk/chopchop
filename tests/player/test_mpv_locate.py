import sys
from pathlib import Path

import pytest

from quickedit.player.mpv_widget import find_libmpv

_NAME = "libmpv-2.dll" if sys.platform == "win32" else "libmpv.so.2"


def test_finds_library_in_search_dir(tmp_path: Path) -> None:
    lib = tmp_path / _NAME
    lib.write_bytes(b"")
    assert find_libmpv([tmp_path]) == lib


def test_missing_returns_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ctypes.util.find_library", lambda _name: None)
    assert find_libmpv([tmp_path]) is None
