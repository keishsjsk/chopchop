from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from chopchop.workers.thumbs_worker import ThumbnailLoader, extract_thumbnail
from media import FFMPEG, HAS_FFMPEG, make_video

pytestmark = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg не установлен")


def test_extract_thumbnail_returns_png(tmp_path: Path) -> None:
    assert FFMPEG is not None
    video = make_video(tmp_path / "a.mp4", seconds=4)
    data = extract_thumbnail(FFMPEG, video, 2.0)
    assert data.startswith(b"\x89PNG")


def test_extract_thumbnail_of_broken_file_is_empty(tmp_path: Path) -> None:
    assert FFMPEG is not None
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"not a video")
    assert extract_thumbnail(FFMPEG, junk, 1.0) == b""


def test_loader_delivers_and_caches_thumbnails(qtbot: QtBot, tmp_path: Path) -> None:
    assert FFMPEG is not None
    video = make_video(tmp_path / "a.mp4", seconds=4)
    loader = ThumbnailLoader(FFMPEG)
    received: dict[int, int] = {}
    loader.thumbnail.connect(lambda _path, index, image: received.update({index: image.width()}))
    first = loader.request(video, 4.0, 3)
    assert first == [None, None, None]
    qtbot.waitUntil(lambda: len(received) == 3, timeout=30000)
    assert set(received.values()) == {160}
    again = loader.request(video, 4.0, 3)  # из кэша, без повторного запуска ffmpeg
    assert all(image is not None for image in again)
    loader.wait()
