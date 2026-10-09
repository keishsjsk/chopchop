"""Страница видеоредактора на подделке плеера и настоящем ffmpeg (без него тесты пропускаются)."""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox
from pytestqt.qtbot import QtBot

from chopchop.core.geometry import Rect
from chopchop.core.operations import Redact, Text
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
    assert page.clip_strip.count() == 1
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
    assert fake.mpv.seeks[-1] == (3.0, "absolute", "exact")
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
    qtbot.waitUntil(lambda: page.clip_strip.current == 1, timeout=2000)
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
    page._on_row_changed(1)
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
    page.export()
    assert "Экспорт невозможен" in page.toast.message()  # уведомление, а не блокирующее окно
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


def test_color_panel_previews_live_then_commits(qtbot: QtBot, tmp_path: Path) -> None:
    page, fake = _page(qtbot, tmp_path)
    color = page.effects_panel.color
    color._filter.setCurrentIndex(color._filter.findData("sepia"))
    assert "colorchannelmixer" in str(_vf_commands(fake)[-1][2])  # видно сразу
    assert page.session.project.effects.is_default  # в историю ещё не записано
    qtbot.waitUntil(lambda: page.session.project.effects.filter == "sepia", timeout=3000)
    page.undo()
    assert page.session.project.effects.filter is None
    assert _vf_commands(fake)[-1] == ("vf", "clear", "")
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


def test_hardware_encoder_failure_falls_back_to_the_processor(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from chopchop.services.app_settings import AppSettings

    assert FFMPEG is not None and FFPROBE is not None
    source = make_video(tmp_path / "a.mp4", seconds=2)
    settings = AppSettings(None)
    settings.set("editor.hw_encoder", "nvenc")
    session = VideoSession(VideoProject((Clip(source, probe(source)),)))
    fake = FakeVideoPage()
    page = VideoEditorPage(session, fake.as_video_page(), FFMPEG, FFPROBE, settings=settings)
    qtbot.addWidget(page)
    monkeypatch.setattr(
        "chopchop.ui.video_editor_page.available_hw_encoders", lambda _ffmpeg: ("h264_nvenc",)
    )
    assert page._encode_options().encoder == "nvenc"  # видеокарта выбрана
    session.set_filter("grayscale")  # эффект: без перекодирования не обойтись
    dest = tmp_path / "out.mp4"
    monkeypatch.setattr(VideoExportDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(VideoExportDialog, "path", lambda self: dest)
    messages: list[str] = []
    page.message.connect(messages.append)
    page.export()
    qtbot.waitUntil(lambda: page._export_dir is None and bool(messages), timeout=120000)
    assert dest.exists() and dest.stat().st_size > 0  # результат есть в любом случае
    args = page._export_args
    assert args is not None
    if not args[2].is_hardware:  # на машине без подходящей видеокарты экспорт повторён
        assert any("процессоре" in text for text in messages)
    page.shutdown()


def test_cpu_encoder_options_come_from_settings(qtbot: QtBot, tmp_path: Path) -> None:
    from chopchop.services.app_settings import AppSettings

    assert FFMPEG is not None and FFPROBE is not None
    source = make_video(tmp_path / "a.mp4", seconds=2)
    settings = AppSettings(None)
    settings.set("editor.x264_crf", 31)
    settings.set("editor.x264_preset", "slow")
    settings.set("advanced.threads", 3)
    session = VideoSession(VideoProject((Clip(source, probe(source)),)))
    fake = FakeVideoPage()
    page = VideoEditorPage(session, fake.as_video_page(), FFMPEG, FFPROBE, settings=settings)
    qtbot.addWidget(page)
    options = page._encode_options()
    assert (options.crf, options.preset, options.encoder, options.threads) == (31, "slow", "cpu", 3)
    page.shutdown()


# --- новая компоновка ---------------------------------------------------------------------------


def test_layout_shows_rail_preview_transport_and_status(qtbot: QtBot, tmp_path: Path) -> None:
    from chopchop.ui.theme import tokens

    page, _fake = _page(qtbot, tmp_path)
    shell = page.shell
    assert shell.rail.names() == ["crop", "redact", "text", "adjust", "rotate", "audio"]
    assert shell.rail.isVisible() and page._video_page.isVisible()
    assert shell.status.isVisible() and "Итог" in shell.status.summary()
    assert page.transport.height() == tokens.TRANSPORT_H
    assert not shell.context.isVisible()  # без инструмента панели параметров нет
    assert not page.effects_chip.isEnabled() and page.effects_chip.text() == "Без эффектов"
    page.shutdown()


def test_selecting_a_tool_expands_and_deselecting_collapses_context_bar(
    qtbot: QtBot, tmp_path: Path
) -> None:
    from chopchop.ui.theme import tokens

    page, _fake = _page(qtbot, tmp_path)
    page.select_tool("crop")
    qtbot.waitUntil(lambda: page.shell.context.height() == tokens.CONTEXT_H, timeout=2000)
    assert page.shell.rail.button("crop").isChecked()
    assert "Enter" in page.shell.status.hint()  # подсказка по активному инструменту
    page.select_tool("crop")
    qtbot.waitUntil(lambda: page.shell.context.height() == 0, timeout=2000)
    assert not page.shell.rail.button("crop").isChecked()
    page.shutdown()


def test_applied_effect_updates_chip_mark_and_can_be_removed(qtbot: QtBot, tmp_path: Path) -> None:
    from chopchop.core.video import EffectEntry

    page, _fake = _page(qtbot, tmp_path)
    page.session.add_redact(Redact(Rect(0, 0, 50, 50)))
    page.session.add_text(Text("Привет", 10, 10))
    assert page.shell.rail.marked("redact") and page.shell.rail.marked("text")
    assert not page.shell.rail.marked("crop")
    assert "2" in page.effects_chip.text()
    page.effects_chip.open_list()
    popup = page.effects_chip._popup
    assert popup is not None and len(popup.rows) == 2
    popup.rows[0][2].click()  # убрать скрытие
    assert not page.session.project.effects.redacts
    assert not page.shell.rail.marked("redact") and page.shell.rail.marked("text")
    page.effects_chip.open_list()
    assert page.effects_chip._popup is not None
    page.effects_chip._popup.reset_all.click()
    assert page.session.project.effects.is_default
    assert page.effects_chip.text() == "Без эффектов"
    assert page.session.can_undo
    assert EffectEntry("text").tool == "text"
    page.shutdown()


def test_audio_mark_follows_the_audio_settings(qtbot: QtBot, tmp_path: Path) -> None:
    page, _fake = _page(qtbot, tmp_path)
    assert not page.shell.rail.marked("audio")
    page.session.set_mute(True)
    assert page.shell.rail.marked("audio")
    page.select_tool("audio")
    assert page.audio.isVisibleTo(page) or page.shell.context.current == "audio"
    page.shutdown()


def test_clip_strip_add_reorder_and_remove(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page, _fake = _page(qtbot, tmp_path)
    other = make_video(tmp_path / "b.mp4", seconds=2)
    page.session.add_clip(Clip(other, probe(other)))
    assert page.clip_strip.count() == 2
    page.clip_strip.moveRequested.emit(0, 1)  # перетаскивание
    assert [c.path.name for c in page.session.project.clips] == ["b.mp4", "a.mp4"]
    assert len(page.session.project.clips) == 2
    page.undo()  # перестановка отменяется одним шагом
    assert [c.path.name for c in page.session.project.clips] == ["a.mp4", "b.mp4"]
    page.clip_strip.removeRequested.emit(1)
    assert [c.path.name for c in page.session.project.clips] == ["a.mp4"]
    page.clip_strip.removeRequested.emit(0)  # последний клип остаётся
    assert len(page.session.project.clips) == 1
    page.shutdown()


def test_transport_buttons_are_reachable(qtbot: QtBot, tmp_path: Path) -> None:
    page, fake = _page(qtbot, tmp_path)
    fake.mpv.time_pos = 2.0
    page._set_in.click()
    fake.mpv.time_pos = 5.0
    page._set_out.click()
    clip = page.session.project.clips[0]
    assert (clip.start, clip.stop) == (2.0, 5.0)
    page._reset.click()
    assert not page.session.project.clips[0].is_trimmed
    page._step_forward.click()
    page._step_back.click()
    assert ("frame-step",) in fake.mpv.commands and ("frame-back-step",) in fake.mpv.commands
    fake.mpv.time_pos = 3.0
    page.step_seconds(1)
    assert fake.mpv.seeks[-1] == (4.0, "absolute", "exact")
    paused = fake.mpv.pause
    page._play.click()
    assert fake.mpv.pause is (not paused)
    fake.mpv.fire("time-pos", 1.0)
    fake.mpv.fire("pause", False)
    qtbot.waitUntil(lambda: "0:01" in page._time.text(), timeout=2000)
    page.shutdown()


def test_zoom_buttons_follow_the_trim_bar(qtbot: QtBot, tmp_path: Path) -> None:
    page, _fake = _page(qtbot, tmp_path)
    assert not page._zoom_out.isEnabled() and not page._zoom_fit.isEnabled()
    page._zoom_in.click()
    assert page.trim.zoom_level > 1.0
    assert page._zoom_out.isEnabled() and page._zoom_fit.isEnabled()
    page._zoom_fit.click()
    assert page.trim.zoom_level == 1.0 and not page._zoom_fit.isEnabled()
    page.shutdown()


def test_trim_height_is_remembered(qtbot: QtBot, tmp_path: Path) -> None:
    from chopchop.services.app_settings import AppSettings

    assert FFMPEG is not None and FFPROBE is not None
    source = make_video(tmp_path / "a.mp4", seconds=2)
    settings = AppSettings(None)
    settings.set("state.trim_height", 120)
    session = VideoSession(VideoProject((Clip(source, probe(source)),)))
    fake = FakeVideoPage()
    page = VideoEditorPage(session, fake.as_video_page(), FFMPEG, FFPROBE, settings=settings)
    qtbot.addWidget(page)
    page.resize(1100, 800)
    page.show()
    qtbot.waitUntil(lambda: page._sized and abs(page.trim.height() - 120) <= 2, timeout=3000)
    page.splitter.setSizes([100, 700])
    page._save_trim_height()
    assert settings.get_int("state.trim_height") == page.trim.height()
    page.shutdown()


def test_small_window_collapses_clip_strip_to_one_row(qtbot: QtBot, tmp_path: Path) -> None:
    page, _fake = _page(qtbot, tmp_path)
    page.resize(960, 600)
    assert page.clip_strip._compact
    page.resize(1200, 900)
    assert not page.clip_strip._compact
    page.shutdown()


def test_theme_switch_recolours_the_editor(qtbot: QtBot, tmp_path: Path) -> None:
    page, _fake = _page(qtbot, tmp_path)
    page.refresh_theme()  # не падает и перекрашивает значки
    assert page.shell.rail.button("crop").icon().isNull() is False
    page.shutdown()
