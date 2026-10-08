from pytestqt.qtbot import QtBot

from chopchop.workers.tasks import TaskRunner


def test_result_is_delivered_in_ui_thread(qtbot: QtBot) -> None:
    runner = TaskRunner()
    results: list[int] = []
    runner.run(lambda: 21 * 2, results.append)
    qtbot.waitUntil(lambda: results == [42], timeout=5000)
    runner.wait()


def test_error_is_reported(qtbot: QtBot) -> None:
    runner = TaskRunner()
    errors: list[str] = []

    def fail() -> None:
        raise ValueError("boom")

    runner.run(fail, lambda _result: None, errors.append)
    qtbot.waitUntil(lambda: errors == ["boom"], timeout=5000)
    runner.wait()


def test_error_without_handler_is_ignored(qtbot: QtBot) -> None:
    runner = TaskRunner()
    done: list[int] = []

    def fail() -> None:
        raise RuntimeError("ignored")

    runner.run(fail, done.append)
    runner.run(lambda: 1, done.append)
    qtbot.waitUntil(lambda: done == [1], timeout=5000)
    runner.wait()
