"""Страница видеоредактора на подделке плеера и настоящем ffmpeg (без него тесты пропускаются)."""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox
from pytestqt.qtbot import QtBot

from chopchop.core.geometry import Rect
from chopchop.core.operations import Text
from chopchop.core.video import Clip, VideoProject
from chopchop.editor.video_session import VideoSession
from chopchop.engines.probe import probe
from chopchop.ui.video_editor_page import VideoEditorPage
from chopchop.ui.video_export_dialog import VideoExportDialog
from fakes import FakeVideoPage
from media import FFMPEG, FFPROBE, HAS_FFMPEG, make_video

pytestmark = [
    pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg не установлен"),
    pytest.mark.usefixtures("no_thumbnails"),
]


def _page(
    qtbot: QtBot, tmp_path: Path, name: str = "a.mp4"
) -> tuple[VideoEditorPage, FakeVideoPage]:
    assert FFMPEG is not None and FFPROBE is not None
    source = make_video(tmp_path / name, seconds=6)
    session = VideoSession(VideoProject((Clip(source, probe(source)),)))
    fake = FakeVideoPage()
    page = VideoEditorPage(session, fake.as_video_page(), FFMPEG, FFPROBE)
    qtbot.addWidget(page)
    page.resize(1000, 700)
    page.show()
    return page, fake


def test_opens_first_clip_in_player(qtbot: QtBot, tmp_path: Path) -> None:
    page, fake = _page(qtbot, tmp_path)
    assert fake.mpv.loaded[0][0] == str(tmp_path / "a.mp4")
    assert page._clips.count() == 1
    assert "0:06" in page._summary.text()
    assert not page._undo_button.isEnabled()
    page.shutdown()


def test_set_in_and_out_use_playhead_position(qtbot: QtBot, tmp_path: Path) -> None:
    page, fake = _page(qtbot, tmp_path)
    fake.mpv.time_pos = 2.0
    page.set_in()
    fake.mpv.time_pos = 5.0
    page.set_out()
    clip = page.session.project.clips[0]
    assert (clip.start, clip.stop) == (2.0, 5.0)
    assert "0:03" in page._summary.text()
    assert "*" in page._summary.text()
    assert (fake.mpv.ab_loop_a, fake.mpv.ab_loop_b) == (2.0, 5.0)  # предпросмотр зациклен
    page.undo()
    page.undo()
    assert page.session.project.clips[0].start == 0.0
    page.shutdown()


def test_reset_trim(qtbot: QtBot, tmp_path: Path) -> None:
    page, _fake = _page(qtbot, tmp_path)
    page.session.set_trim(0, 1.0, 2.0)
    page._reset_trim()
    assert not page.session.project.clips[0].is_trimmed
    page.shutdown()


def test_file_loaded_pauses_and_seeks_to_start(qtbot: QtBot, tmp_path: Path) -> None:
    page, fake = _page(qtbot, tmp_path)
    page.session.set_trim(0, 3.0, 5.0)
    fake.mpv.pause = False
    fake.mpv.event_handlers[1](object())  # file-loaded
    qtbot.waitUntil(lambda: fake.mpv.pause is True, timeout=2000)
    assert fake.mpv.seeks[-1] == (3.0, "absolute", "keyframes")
    page.shutdown()


def test_volume_is_committed_once_after_pause_in_dragging(qtbot: QtBot, tmp_path: Path) -> None:
    page, _fake = _page(qtbot, tmp_path)
    for value in (90, 70, 50):
        page._volume.setValue(value)
    qtbot.waitUntil(lambda: page.session.project.audio.volume == 0.5, timeout=3000)
    page.undo()
    assert page.session.project.audio.volume == 1.0  # одним шагом, а не тремя
    page.shutdown()


def test_mute_and_replacement_controls(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page, _fake = _page(qtbot, tmp_path)
    page._mute.setChecked(True)
    assert page.session.project.audio.mute
    song = tmp_path / "song.mp3"
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(song), ""))
    page._choose_replacement()
    assert page.session.project.audio.replacement == song
    assert not page._mute.isChecked()
    assert page._original_audio.isEnabled()
    page._original_audio.click()
    assert page.session.project.audio.replacement is None
    page.shutdown()


def test_add_compatible_clip(qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    page, fake = _page(qtbot, tmp_path)
    other = make_video(tmp_path / "b.mp4", seconds=4)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(other), ""))
    page.add_clip()
    qtbot.waitUntil(lambda: len(page.session.project.clips) == 2, timeout=10000)
    qtbot.waitUntil(lambda: page._clips.currentRow() == 1, timeout=2000)
    assert fake.mpv.loaded[-1][0] == str(other)  # новый клип сразу открыт в плеере
    assert "0:10" in page._summary.text()
    page.shutdown()


def test_add_clip_with_other_parameters_is_allowed_with_a_warning(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page, _fake = _page(qtbot, tmp_path)
    other = make_video(tmp_path / "big.mp4", seconds=2, size=(640, 480))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(other), ""))
    messages: list[str] = []
    page.message.connect(messages.append)
    page.add_clip()
    qtbot.waitUntil(lambda: len(page.session.project.clips) == 2, timeout=10000)
    assert any("разрешение" in m and "перекодировано" in m for m in messages)
    assert page.session.project.reencode_reason() == "clips"
    page.shutdown()


def test_remove_and_reorder_clips(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page, _fake = _page(qtbot, tmp_path)
    page._remove_clip()  # единственный клип остаётся
    assert len(page.session.project.clips) == 1
    other = make_video(tmp_path / "b.mp4", seconds=2)
    page.session.add_clip(Clip(other, probe(other)))
    page._clips.setCurrentRow(1)
    page._move_clip(-1)
    assert [c.path.name for c in page.session.project.clips] == ["b.mp4", "a.mp4"]
    page.shutdown()


def test_export_writes_trimmed_file_and_marks_saved(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page, _fake = _page(qtbot, tmp_path)
    page.session.set_trim(0, 1.0, 4.0)
    dest = tmp_path / "result.mp4"
    monkeypatch.setattr(VideoExportDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(VideoExportDialog, "path", lambda self: dest)
    messages: list[str] = []
    page.message.connect(messages.append)
    page.export()
    qtbot.waitUntil(lambda: any("Сохранено" in m for m in messages), timeout=30000)
    assert probe(dest).duration == pytest.approx(3.0, abs=0.4)
    assert not page.session.modified
    assert page._progress is None
    page.shutdown()


def test_export_refuses_to_overwrite_source(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page, _fake = _page(qtbot, tmp_path)
    source = tmp_path / "a.mp4"
    before = source.read_bytes()
    monkeypatch.setattr(VideoExportDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(VideoExportDialog, "path", lambda self: source)
    warned: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _p, _t, text: warned.append(text))
    page.export()
    assert warned
    assert source.read_bytes() == before
    page.shutdown()


def test_export_dialog_describes_mode(qtbot: QtBot, tmp_path: Path) -> None:
    source = make_video(tmp_path / "a.mp4", seconds=3)
    project = VideoProject((Clip(source, probe(source)).with_trim(1, 2),))
    dialog = VideoExportDialog(project)
    qtbot.addWidget(dialog)
    assert dialog.path() == tmp_path / "a_edited.mp4"
    dialog._container.setCurrentIndex(dialog._container.findData(".mkv"))
    assert dialog.path().suffix == ".mkv"


def test_exit_asks_when_modified(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page, _fake = _page(qtbot, tmp_path)
    exits: list[bool] = []
    page.exitRequested.connect(lambda: exits.append(True))
    page.request_exit()  # правок нет: выходим без вопросов
    assert exits == [True]
    page.session.set_volume(0.5)
    answers = iter([QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes])
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: next(answers))
    page.request_exit()
    assert exits == [True]
    page.request_exit()
    assert exits == [True, True]
    page.shutdown()


def test_release_returns_video_page(qtbot: QtBot, tmp_path: Path) -> None:
    page, fake = _page(qtbot, tmp_path)
    released = page.release_video_page()
    assert released is fake.as_video_page()
    assert fake.parent() is None
    page.shutdown()


def _vf_commands(fake: FakeVideoPage) -> list[tuple[object, ...]]:
    return [c for c in fake.mpv.commands if c and c[0] == "vf"]


def test_effects_are_previewed_through_the_same_graph_as_export(
    qtbot: QtBot, tmp_path: Path
) -> None:
    page, fake = _page(qtbot, tmp_path)
    assert _vf_commands(fake) == []  # без эффектов фильтр не нужен
    page.session.set_filter("grayscale")
    command = _vf_commands(fake)[-1]
    assert command[:2] == ("vf", "set")
    assert str(command[2]) == "lavfi=[[vid1]hue=s=0[vo]]"
    page.session.undo()
    assert _vf_commands(fake)[-1] == ("vf", "clear", "")
    page.shutdown()


def test_preview_skips_crop_and_rotation_but_writes_text_files(
    qtbot: QtBot, tmp_path: Path
) -> None:
    page, fake = _page(qtbot, tmp_path)
    page.session.set_crop(Rect(0, 0, 100, 100))
    page.session.rotate(90)
    assert "100×100" in page._summary.text()  # размер результата виден сразу
    assert _vf_commands(fake) == []  # кадр и поворот рисует слой, а не mpv
    page.session.add_text(Text("Привет", 10, 10))
    graph = str(_vf_commands(fake)[-1][2])
    assert "drawtext=textfile=" in graph
    assert "crop=" not in graph
    assert (page._workspace / "text00.txt").read_text(encoding="utf-8") == "Привет"
    page.shutdown()
    assert not page._workspace.exists()  # временные файлы убраны


def test_unchanged_effects_do_not_reapply_the_filter(qtbot: QtBot, tmp_path: Path) -> None:
    page, fake = _page(qtbot, tmp_path)
    page.session.set_filter("blur")
    count = len(_vf_commands(fake))
    page.session.set_volume(0.5)  # звук на картинку не влияет
    assert len(_vf_commands(fake)) == count
    page.shutdown()


def test_color_dialog_preview_and_cancel(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from chopchop.core.operations import Adjust
    from chopchop.ui.video_color_dialog import VideoColorDialog

    page, fake = _page(qtbot, tmp_path)

    def cancel(dialog: VideoColorDialog) -> int:
        dialog.previewChanged.emit(Adjust(contrast=1.5), "sepia")  # пользователь подвигал ползунок
        return 0

    monkeypatch.setattr(VideoColorDialog, "exec", cancel)
    page.effects_panel.open_color_dialog()
    assert "colorchannelmixer" in str(_vf_commands(fake)[-2][2])  # на время диалога видно изменение
    assert _vf_commands(fake)[-1] == ("vf", "clear", "")  # после отмены прежний вид
    assert page.session.project.effects.is_default

    def accept(dialog: VideoColorDialog) -> int:
        dialog._filter.setCurrentIndex(dialog._filter.findData("grayscale"))
        return 1

    monkeypatch.setattr(VideoColorDialog, "exec", accept)
    page.effects_panel.open_color_dialog()
    assert page.session.project.effects.filter == "grayscale"
    page.shutdown()


def test_keyboard_actions_reach_effects_panel(qtbot: QtBot, tmp_path: Path) -> None:
    page, _fake = _page(qtbot, tmp_path)
    page.select_tool("redact")
    assert page.effects_panel.active == "redact"
    tool = page.effects_panel.tools["redact"]
    tool.press(10, 10, 4.0)
    tool.move(100, 100)
    tool.release(100, 100)
    page.apply_pending()  # Enter
    assert len(page.session.project.effects.redacts) == 1
    page.select_tool("text")
    exits: list[bool] = []
    page.exitRequested.connect(lambda: exits.append(True))
    page.escape()  # снимает инструмент
    assert page.effects_panel.active is None
    assert exits == []
    page.session.mark_saved()
    page.escape()  # инструмента нет — выходим
    assert exits == [True]
    page.shutdown()


def test_export_with_effects_uses_reencoding_and_precise_option(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page, _fake = _page(qtbot, tmp_path)
    page.session.set_filter("sepia")
    page.session.set_trim(0, 1.0, 4.0)
    dest = tmp_path / "fx.mp4"
    monkeypatch.setattr(VideoExportDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(VideoExportDialog, "path", lambda self: dest)
    monkeypatch.setattr(VideoExportDialog, "precise", lambda self: True)
    messages: list[str] = []
    page.message.connect(messages.append)
    page.export()
    qtbot.waitUntil(lambda: any("Сохранено" in m for m in messages), timeout=60000)
    info = probe(dest)
    assert info.duration == pytest.approx(3.0, abs=0.15)  # точная обрезка по кадрам
    page.shutdown()


def test_export_dialog_explains_the_mode(qtbot: QtBot, tmp_path: Path) -> None:
    from chopchop.core.operations import Adjust
    from chopchop.core.video import VideoEffects

    source = make_video(tmp_path / "a.mp4", seconds=3)
    clip = Clip(source, probe(source)).with_trim(1, 2)
    fast = VideoExportDialog(VideoProject((clip,)))
    qtbot.addWidget(fast)
    assert any("не перекодируется" in note for note in fast.notes())
    assert fast._precise.isEnabled()
    fast._precise.setChecked(True)
    assert any("Точная обрезка" in note for note in fast.notes())
    assert fast.precise()
    effects = VideoEffects(adjust=Adjust(contrast=1.2))
    slow = VideoExportDialog(VideoProject((clip,), effects=effects))
    qtbot.addWidget(slow)
    assert any("Эффекты" in note for note in slow.notes())
    untrimmed = VideoExportDialog(VideoProject((Clip(source, probe(source)),)))
    qtbot.addWidget(untrimmed)
    assert not untrimmed._precise.isEnabled()  # резать нечего
