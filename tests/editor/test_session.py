import hashlib
from pathlib import Path

import pytest
from PIL import Image
from pytestqt.qtbot import QtBot

from chopchop.core.geometry import Rect
from chopchop.core.operations import Crop, Flip, Redact, Rotate
from chopchop.editor.session import EditSession
from chopchop.engines.image_engine import apply_operations


def _photo(path: Path, size: tuple[int, int] = (200, 100)) -> Path:
    image = Image.new("RGB", size, (255, 0, 0))
    image.paste((0, 0, 255), (size[0] // 2, 0, size[0], size[1]))
    exif = Image.Exif()
    exif[0x010F] = "TestCam"
    image.save(path, exif=exif)
    return path


def _loaded(qtbot: QtBot, session: EditSession) -> EditSession:
    with qtbot.waitSignal(session.loaded, timeout=10000):
        session.start()
    return session


def test_loads_preview_and_size(qtbot: QtBot, tmp_path: Path) -> None:
    session = _loaded(qtbot, EditSession(_photo(tmp_path / "a.jpg")))
    assert session.is_ready
    assert session.original_size == (200, 100)
    assert session.preview().size == (200, 100)
    assert not session.modified
    session.wait()


def test_missing_file_reports_failure(qtbot: QtBot, tmp_path: Path) -> None:
    session = EditSession(tmp_path / "nope.jpg")
    with qtbot.waitSignal(session.loadFailed, timeout=10000):
        session.start()
    assert not session.is_ready
    session.wait()


def test_undo_redo_and_modified_flag(qtbot: QtBot, tmp_path: Path) -> None:
    session = _loaded(qtbot, EditSession(_photo(tmp_path / "a.jpg")))
    session.add_full(Rotate(90))
    assert session.modified
    assert session.preview().size == (100, 200)
    session.undo()
    assert not session.modified
    assert session.preview().size == (200, 100)
    session.redo()
    assert session.preview().size == (100, 200)
    session.wait()


def test_incremental_preview_matches_full_recompute(qtbot: QtBot, tmp_path: Path) -> None:
    session = _loaded(qtbot, EditSession(_photo(tmp_path / "a.jpg")))
    session.add_full(Flip(True))
    first = session.preview()
    session.add_full(Redact(Rect(0, 0, 50, 50), "fill"))
    incremental = session.preview()
    fresh = apply_operations(first.copy(), [Redact(Rect(0, 0, 50, 50), "fill")])
    assert incremental.tobytes() == fresh.tobytes()
    session.undo()
    assert session.preview().tobytes() == first.tobytes()
    session.wait()


def test_preview_coordinates_are_stored_at_full_size(qtbot: QtBot, tmp_path: Path) -> None:
    session = _loaded(qtbot, EditSession(_photo(tmp_path / "big.jpg", (4096, 2048))))
    preview = session.preview()
    assert preview.width == 2048  # прокси вдвое меньше оригинала
    session.add(Crop(Rect(0, 0, 1024, 512)))
    (op,) = session.history.operations
    assert isinstance(op, Crop)
    assert op.rect.w == pytest.approx(2048)
    assert op.rect.h == pytest.approx(1024)
    assert session.output_size() == (2048, 1024)
    assert session.preview().size == (1024, 512)
    assert session.preview_scale() == pytest.approx(2.0)
    session.wait()


def test_render_with_pending_does_not_change_history(qtbot: QtBot, tmp_path: Path) -> None:
    session = _loaded(qtbot, EditSession(_photo(tmp_path / "a.jpg")))
    shown = session.render_with(Redact(Rect(0, 0, 20, 20), "fill"))
    assert shown.getpixel((5, 5)) == (0, 0, 0)
    assert len(session.history) == 0
    assert session.preview().getpixel((5, 5))[0] > 250  # JPEG: красный почти 255
    session.wait()


def test_export_applies_operations_to_original_and_strips_exif(
    qtbot: QtBot, tmp_path: Path
) -> None:
    source = _photo(tmp_path / "a.jpg")
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    session = _loaded(qtbot, EditSession(source))
    session.add_full(Crop(Rect(0, 0, 100, 100)))
    dest = tmp_path / "out" / "a_edited.png"
    with qtbot.waitSignal(session.exported, timeout=10000) as signal:
        session.export(dest, "png")
    assert signal.args == [dest]
    with Image.open(dest) as result:
        assert result.size == (100, 100)
        assert len(result.getexif()) == 0
    assert not session.modified
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before  # исходник не тронут
    session.wait()


def test_edit_made_during_export_stays_unsaved(qtbot: QtBot, tmp_path: Path) -> None:
    session = _loaded(qtbot, EditSession(_photo(tmp_path / "a.jpg")))
    session.add_full(Flip(True))
    with qtbot.waitSignal(session.exported, timeout=10000):
        session.export(tmp_path / "x.png", "png")
        session.add_full(Rotate(90))
    assert session.modified
    session.wait()


def test_export_can_keep_metadata(qtbot: QtBot, tmp_path: Path) -> None:
    session = _loaded(qtbot, EditSession(_photo(tmp_path / "a.jpg")))
    dest = tmp_path / "kept.jpg"
    with qtbot.waitSignal(session.exported, timeout=10000):
        session.export(dest, "jpeg", keep_metadata=True)
    with Image.open(dest) as result:
        assert result.getexif()[0x010F] == "TestCam"
    session.wait()


def test_export_failure_is_reported(qtbot: QtBot, tmp_path: Path) -> None:
    session = _loaded(qtbot, EditSession(_photo(tmp_path / "a.jpg")))
    blocker = tmp_path / "file.txt"
    blocker.write_text("x")
    with qtbot.waitSignal(session.exportFailed, timeout=10000):
        session.export(blocker / "sub" / "out.png", "png")  # родитель — файл, а не папка
    session.wait()


def test_render_full_returns_full_resolution(qtbot: QtBot, tmp_path: Path) -> None:
    session = _loaded(qtbot, EditSession(_photo(tmp_path / "big.jpg", (3000, 1500))))
    session.add(Crop(Rect(0, 0, 1000, 500)))
    results: list[Image.Image] = []
    session.render_full(results.append)
    qtbot.waitUntil(lambda: bool(results), timeout=10000)
    assert results[0].size == session.output_size()
    session.wait()


def test_memory_session_from_clipboard_image(qtbot: QtBot, tmp_path: Path) -> None:
    image = Image.new("RGBA", (80, 40), (0, 255, 0, 255))
    session = _loaded(qtbot, EditSession(None, image))
    session.add_full(Rotate(90))
    dest = tmp_path / "clip.png"
    with qtbot.waitSignal(session.exported, timeout=10000):
        session.export(dest, "png")
    with Image.open(dest) as result:
        assert result.size == (40, 80)
    session.wait()
