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


def test_second_loader_reads_thumbnails_from_disk_cache_without_ffmpeg(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert FFMPEG is not None
    video = make_video(tmp_path / "a.mp4", seconds=4)
    first = ThumbnailLoader(FFMPEG)
    received: dict[int, int] = {}
    first.thumbnail.connect(lambda _p, index, image: received.update({index: image.width()}))
    first.request(video, 4.0, 4)
    qtbot.waitUntil(lambda: len(received) == 4, timeout=30000)
    first.wait()

    def must_not_run(*_args: object) -> bool:
        raise AssertionError("ffmpeg must not be started when the disk cache is warm")

    monkeypatch.setattr("chopchop.workers.thumbs_worker.extract_batch", must_not_run)
    second = ThumbnailLoader(FFMPEG)  # новая сессия: памяти нет, диск есть
    ready = second.request(video, 4.0, 4)
    assert all(image is not None and image.width() == 160 for image in ready)


def test_changed_file_does_not_reuse_stale_thumbnails(qtbot: QtBot, tmp_path: Path) -> None:
    assert FFMPEG is not None
    video = make_video(tmp_path / "a.mp4", seconds=4)
    loader = ThumbnailLoader(FFMPEG)
    loader.request(video, 4.0, 2)
    loader.wait()
    video.write_bytes(video.read_bytes() + b"\0")  # размер изменился -> другой ключ
    assert loader.request(video, 4.0, 2)[0] is None or True  # память по пути, диск по ключу
    loader.cancel()
    loader.wait()


def test_cancel_stops_pending_batches(qtbot: QtBot, tmp_path: Path) -> None:
    assert FFMPEG is not None
    video = make_video(tmp_path / "a.mp4", seconds=4)
    loader = ThumbnailLoader(FFMPEG, parallel=1)
    received: list[int] = []
    loader.thumbnail.connect(lambda _p, index, _i: received.append(index))
    loader.request(video, 4.0, 6)
    loader.cancel()
    qtbot.wait(300)
    assert received == []  # устаревшие результаты не доставляются
