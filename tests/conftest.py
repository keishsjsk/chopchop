import pytest


@pytest.fixture
def no_thumbnails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Не запускать ffmpeg за миниатюрами: в тестах страницы это лишние секунды ожидания."""
    monkeypatch.setattr("quickedit.workers.thumbs_worker.extract_thumbnail", lambda *a: b"")
