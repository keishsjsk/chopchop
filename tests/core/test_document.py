from pathlib import Path

import pytest

from quickedit.core.document import MediaKind, detect_kind


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("a.JPG", MediaKind.IMAGE),
        ("a.heic", MediaKind.IMAGE),
        ("b.mkv", MediaKind.VIDEO),
        ("b.MP4", MediaKind.VIDEO),
        ("c.txt", None),
        ("noext", None),
    ],
)
def test_detect_kind(name: str, kind: MediaKind | None) -> None:
    assert detect_kind(Path(name)) is kind
