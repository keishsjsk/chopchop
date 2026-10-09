import pytest


@pytest.fixture
def no_thumbnails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Не запускать ffmpeg за миниатюрами: в тестах страницы это лишние секунды ожидания."""
    monkeypatch.setattr("chopchop.workers.thumbs_worker.extract_batch", lambda *a: False)


@pytest.fixture(autouse=True)
def isolated_cache(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Тесты не трогают настоящий кэш пользователя."""
    monkeypatch.setenv("CHOPCHOP_CACHE_DIR", str(tmp_path_factory.mktemp("cache")))
