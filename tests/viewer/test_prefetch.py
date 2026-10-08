from pathlib import Path

from PIL import Image
from pytestqt.qtbot import QtBot

from quickedit.viewer.prefetch import ImageCache


def _png(path: Path) -> Path:
    Image.new("RGB", (8, 8), "green").save(path)
    return path


def test_request_loads_in_background(qtbot: QtBot, tmp_path: Path) -> None:
    cache = ImageCache()
    path = _png(tmp_path / "a.png")
    assert cache.get(path) is None
    with qtbot.waitSignal(cache.loaded, timeout=5000):
        cache.request(path)
    assert cache.get(path) is not None
    cache.wait()


def test_failure_is_reported(qtbot: QtBot, tmp_path: Path) -> None:
    cache = ImageCache()
    with qtbot.waitSignal(cache.failed, timeout=5000):
        cache.request(tmp_path / "missing.png")
    cache.wait()


def test_capacity_evicts_oldest(qtbot: QtBot, tmp_path: Path) -> None:
    cache = ImageCache(capacity=2)
    paths = [_png(tmp_path / f"{i}.png") for i in range(3)]
    for path in paths:
        with qtbot.waitSignal(cache.loaded, timeout=5000):
            cache.request(path)
    assert cache.get(paths[0]) is None
    assert cache.get(paths[1]) is not None
    assert cache.get(paths[2]) is not None
    cache.wait()
