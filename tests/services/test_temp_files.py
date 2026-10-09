import os
import time
from pathlib import Path

from chopchop.services.output import unique_path
from chopchop.services.temp_files import cleanup_stale, new_workspace, remove_workspace


def test_workspace_lifecycle(tmp_path: Path) -> None:
    workspace = new_workspace(tmp_path)
    assert workspace.is_dir()
    assert workspace.name.startswith("chopchop-")
    (workspace / "x.tmp").write_text("x")
    remove_workspace(workspace)
    assert not workspace.exists()
    remove_workspace(workspace)  # повторное удаление безопасно


def test_cleanup_removes_only_old_app_folders(tmp_path: Path) -> None:
    old = new_workspace(tmp_path)
    fresh = new_workspace(tmp_path)
    foreign = tmp_path / "other-folder"
    foreign.mkdir()
    long_ago = time.time() - 10_000
    os.utime(old, (long_ago, long_ago))
    os.utime(foreign, (long_ago, long_ago))
    assert cleanup_stale(tmp_path) == 1
    assert not old.exists()
    assert fresh.exists()
    assert foreign.exists()


def test_cleanup_with_missing_root(tmp_path: Path) -> None:
    assert cleanup_stale(tmp_path / "nope") == 0


def test_unique_path(tmp_path: Path) -> None:
    assert unique_path(tmp_path, "a", ".mp4") == tmp_path / "a.mp4"
    (tmp_path / "a.mp4").write_bytes(b"")
    (tmp_path / "a (2).mp4").write_bytes(b"")
    assert unique_path(tmp_path, "a", ".mp4") == tmp_path / "a (3).mp4"


def test_custom_temp_root_is_used_and_created(tmp_path: Path) -> None:
    from chopchop.services import temp_files

    target = tmp_path / "scratch" / "deep"
    temp_files.set_root(target)
    try:
        workspace = new_workspace()
        assert workspace.parent == target
        remove_workspace(workspace)
    finally:
        temp_files.set_root(None)


def test_unusable_custom_root_falls_back_to_system_temp(tmp_path: Path) -> None:
    import tempfile

    from chopchop.services import temp_files

    blocker = tmp_path / "file"
    blocker.write_text("x")
    temp_files.set_root(blocker / "inside")  # «папка» внутри файла создана быть не может
    try:
        assert temp_files.temp_root() == Path(tempfile.gettempdir())
    finally:
        temp_files.set_root(None)
