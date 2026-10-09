"""Кэш промежуточных состояний, фоновое превью и устаревшие расчёты."""

from pathlib import Path

import pytest
from PIL import Image
from pytestqt.qtbot import QtBot

from chopchop.core.geometry import Rect
from chopchop.core.operations import Adjust, Crop, Flip, Operation, Redact, Rotate
from chopchop.editor.session import EditSession, StateCache
from chopchop.engines.image_engine import apply_operation as real_apply


def _photo(path: Path, size: tuple[int, int] = (200, 100)) -> Path:
    Image.new("RGB", size, (255, 0, 0)).save(path)
    return path


def _loaded(qtbot: QtBot, session: EditSession) -> EditSession:
    with qtbot.waitSignal(session.loaded, timeout=10000):
        session.start()
    return session


def _image(side: int = 10) -> Image.Image:
    return Image.new("RGB", (side, side))


def test_cache_finds_the_longest_known_prefix() -> None:
    cache = StateCache()
    first, second = Rotate(90), Flip(True)
    cache.put((first,), _image(1))
    cache.put((first, second), _image(2))
    count, image = cache.longest_prefix((first, second, Rotate(180))) or (0, None)
    assert count == 2 and image is not None and image.width == 2
    assert cache.longest_prefix((Rotate(270),)) is None
    assert cache.longest_prefix(()) is None


def test_cache_drops_the_least_recently_used_state_over_budget() -> None:
    cache = StateCache(budget=2 * 10 * 10 * 3 + 5)  # места на два кадра 10x10
    keys = [(Rotate(90),), (Rotate(180),), (Rotate(270),)]
    cache.put(keys[0], _image())
    cache.put(keys[1], _image())
    assert cache.get(keys[0]) is not None  # свежее использование спасает от вытеснения
    cache.put(keys[2], _image())
    assert cache.get(keys[1]) is None
    assert cache.get(keys[0]) is not None and cache.get(keys[2]) is not None


def test_cache_keeps_at_least_the_newest_state() -> None:
    cache = StateCache(budget=1)
    cache.put((Rotate(90),), _image())
    assert len(cache) == 1


def test_new_operation_is_applied_to_the_cached_previous_result(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _loaded(qtbot, EditSession(_photo(tmp_path / "a.png")))
    session.add_full(Rotate(90))
    session.add_full(Flip(True))
    session.preview()
    applied: list[Operation] = []

    def counting(image: Image.Image, op: Operation) -> Image.Image:
        applied.append(op)
        return real_apply(image, op)

    monkeypatch.setattr("chopchop.editor.session.apply_operation", counting)
    session.add_full(Adjust(brightness=1.2))
    session.preview()
    assert applied == [Adjust(brightness=1.2)]  # предыдущие шаги не пересчитывались
    applied.clear()
    session.undo()
    session.undo()
    session.redo()
    session.preview()
    assert applied == []  # отмена и повтор берут готовые состояния
    session.wait()


def test_request_preview_computes_in_background(qtbot: QtBot, tmp_path: Path) -> None:
    session = _loaded(qtbot, EditSession(_photo(tmp_path / "a.png")))
    session.add_full(Crop(Rect(0, 0, 50, 50)))
    session.add_full(Rotate(90))
    with qtbot.waitSignal(session.previewReady, timeout=5000):
        session.request_preview()
    assert not session.is_busy
    assert session.preview().size == (50, 50)
    session.wait()


def test_stale_background_preview_is_not_announced(qtbot: QtBot, tmp_path: Path) -> None:
    session = _loaded(qtbot, EditSession(_photo(tmp_path / "a.png", (400, 300))))
    ready: list[bool] = []
    session.previewReady.connect(lambda: ready.append(True))
    session.add_full(Rotate(90))
    session.request_preview()  # этот расчёт устареет
    session.add_full(Rotate(180))
    session.request_preview()
    qtbot.waitUntil(lambda: not session.is_busy, timeout=5000)
    qtbot.wait(50)
    assert ready == [True]  # сообщили только о последнем списке операций
    session.wait()


def test_pending_operation_result_is_delivered_with_a_frame(qtbot: QtBot, tmp_path: Path) -> None:
    session = _loaded(qtbot, EditSession(_photo(tmp_path / "a.png")))
    session.frame_converter = lambda image: ("frame", image.size)
    pending = Redact(Rect(0, 0, 20, 20), "fill")
    with qtbot.waitSignal(session.pendingReady, timeout=5000) as signal:
        session.request_pending(pending)
    op, image, frame = signal.args
    assert op == pending
    assert image.getpixel((5, 5)) == (0, 0, 0)
    assert frame == ("frame", (200, 100))
    assert len(session.history) == 0  # предпросмотр историю не трогает
    session.wait()


def test_outdated_pending_answers_are_dropped(qtbot: QtBot, tmp_path: Path) -> None:
    session = _loaded(qtbot, EditSession(_photo(tmp_path / "a.png")))
    answers: list[Operation] = []
    session.pendingReady.connect(lambda op, _image, _frame: answers.append(op))
    session.request_pending(Adjust(brightness=1.1))
    session.request_pending(Adjust(brightness=1.2))
    session.request_pending(Adjust(brightness=1.3))
    qtbot.waitUntil(lambda: not session.is_busy, timeout=5000)
    qtbot.wait(50)
    assert answers == [Adjust(brightness=1.3)]
    session.request_pending(Adjust(brightness=1.4))
    session.cancel_pending()
    qtbot.waitUntil(lambda: not session.is_busy, timeout=5000)
    qtbot.wait(50)
    assert answers == [Adjust(brightness=1.3)]
    session.wait()


def test_rendered_result_seeds_the_cache_so_applying_costs_nothing(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _loaded(qtbot, EditSession(_photo(tmp_path / "a.png")))
    op = Adjust(brightness=1.3)
    rendered = session.render_with(op)
    monkeypatch.setattr(
        "chopchop.editor.session.apply_operation",
        lambda *_a: (_ for _ in ()).throw(AssertionError("must not recompute")),
    )
    session.add(op, rendered)
    assert session.preview() is rendered
    session.wait()


def test_preview_size_follows_the_requested_proxy_side(qtbot: QtBot, tmp_path: Path) -> None:
    path = tmp_path / "big.jpg"
    Image.new("RGB", (3000, 2000), (10, 20, 30)).save(path)
    session = _loaded(qtbot, EditSession(path, proxy_side=1024))
    assert session.preview().size == (1024, 683)
    assert session.original_size == (3000, 2000)
    session.wait()


def test_preview_load_respects_exif_orientation(qtbot: QtBot, tmp_path: Path) -> None:
    path = tmp_path / "rotated.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6  # повернуть на 90° по часовой стрелке при показе
    Image.new("RGB", (3000, 2000), (10, 20, 30)).save(path, exif=exif)
    session = _loaded(qtbot, EditSession(path, proxy_side=1000))
    assert session.original_size == (2000, 3000)
    assert session.preview().size == (667, 1000)
    session.wait()
