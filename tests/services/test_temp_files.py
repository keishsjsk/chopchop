import os
import time
from pathlib import Path

from quickedit.services.output import unique_path
from quickedit.services.temp_files import cleanup_stale, new_workspace, remove_workspace


def test_workspace_lifecycle(tmp_path: Path) -> None:
    workspace = new_workspace(tmp_path)
    assert workspace.is_dir()
    assert workspace.name.startswith("quickedit-")
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
