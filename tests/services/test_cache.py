import os
from pathlib import Path

from chopchop.services import cache


def test_cache_dir_can_be_overridden(tmp_path: Path, monkeypatch: object) -> None:
    folder = cache.cache_dir()
    assert folder.is_dir()
    assert os.environ[cache.CACHE_ENV] == str(folder)


def test_file_key_depends_on_content_identity_and_parameters(tmp_path: Path) -> None:
    video = tmp_path / "v.bin"
    video.write_bytes(b"1234")
    key = cache.file_key(video, 1, 14)
    assert key == cache.file_key(video, 1, 14)
    assert key != cache.file_key(video, 2, 14)
    video.write_bytes(b"12345")  # размер изменился
    assert key != cache.file_key(video, 1, 14)


def test_prune_removes_oldest_files_first(tmp_path: Path) -> None:
    for number in range(4):
        path = tmp_path / f"{number}.jpg"
        path.write_bytes(b"x" * 100)
        os.utime(path, (1000 + number, 1000 + number))
    assert cache.prune(tmp_path, 250) == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == ["2.jpg", "3.jpg"]
    assert cache.clear(tmp_path) == 2
