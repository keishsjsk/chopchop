from pathlib import Path

from chopchop.viewer.folder_nav import FolderNav, natural_key


def _make(tmp_path: Path, names: list[str]) -> list[Path]:
    paths = [tmp_path / n for n in names]
    for p in paths:
        p.write_bytes(b"")
    return paths


def test_natural_order() -> None:
    names = ["img10.jpg", "img2.jpg", "IMG1.jpg"]
    assert sorted(names, key=natural_key) == ["IMG1.jpg", "img2.jpg", "img10.jpg"]


def test_lists_only_images_in_natural_order(tmp_path: Path) -> None:
    _, middle, _ = _make(tmp_path, ["p10.jpg", "p2.png", "p1.webp"])
    _make(tmp_path, ["notes.txt", "clip.mp4"])
    nav = FolderNav(middle)
    assert [p.name for p in nav.files] == ["p1.webp", "p2.png", "p10.jpg"]
    assert nav.current == middle


def test_step_wraps_around(tmp_path: Path) -> None:
    a, _, c = _make(tmp_path, ["a.jpg", "b.jpg", "c.jpg"])
    nav = FolderNav(c)
    assert nav.step(1) == a
    assert nav.step(-1) == c


def test_neighbors_for_prefetch(tmp_path: Path) -> None:
    paths = _make(tmp_path, [f"{i}.jpg" for i in range(6)])
    nav = FolderNav(paths[2])
    assert nav.neighbors(ahead=2, behind=1) == [paths[3], paths[4], paths[1]]


def test_single_file_has_no_neighbors(tmp_path: Path) -> None:
    (only,) = _make(tmp_path, ["only.jpg"])
    nav = FolderNav(only)
    assert nav.neighbors() == []
    assert nav.step(1) == only


def test_current_outside_extension_list_is_included(tmp_path: Path) -> None:
    _make(tmp_path, ["a.jpg"])
    odd = tmp_path / "b.xyz"
    assert odd in FolderNav(odd).files
