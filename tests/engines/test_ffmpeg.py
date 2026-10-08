import sys
from pathlib import Path

import pytest

from quickedit.engines.ffmpeg import find_binary, find_ffmpeg


def _exe(name: str) -> str:
    return f"{name}.exe" if sys.platform == "win32" else name


def test_finds_binary_in_search_dir(tmp_path: Path) -> None:
    exe = tmp_path / _exe("ffmpeg")
    exe.write_bytes(b"")
    assert find_ffmpeg([tmp_path]) == exe


def test_search_dir_wins_over_system(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    exe = tmp_path / _exe("ffprobe")
    exe.write_bytes(b"")
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/ffprobe")
    assert find_binary("ffprobe", [tmp_path]) == exe


def test_falls_back_to_system(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/ffmpeg")
    assert find_ffmpeg([tmp_path]) == Path("/usr/bin/ffmpeg")


def test_missing_returns_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: None)
    assert find_ffmpeg([tmp_path]) is None
