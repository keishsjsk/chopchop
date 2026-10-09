"""Настройки действительно влияют на программу: на лету, без перезапуска."""

from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtCore import QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QColor, QImage, QWheelEvent
from pytestqt.qtbot import QtBot

from chopchop.services import logs, temp_files
from chopchop.services.app_settings import AppSettings
from chopchop.ui.main_window import MainWindow
from chopchop.ui.tools.crop_tool import ratio_from_setting
from fakes import FakeVideoPage


def _window(qtbot: QtBot, tmp_path: Path) -> tuple[MainWindow, AppSettings]:
    settings = AppSettings(None)
    window = MainWindow(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat), settings)
    qtbot.addWidget(window)
    window.show()
    return window, settings


def _png(folder: Path, name: str, size: tuple[int, int]) -> Path:
    path = folder / name
    Image.new("RGB", size, "red").save(path)
    return path


def _video_window(
    qtbot: QtBot, tmp_path: Path
) -> tuple[MainWindow, AppSettings, FakeVideoPage, list[Path]]:
    window, settings = _window(qtbot, tmp_path)
    clips = []
    for name in ("a.mp4", "b.mp4", "c.mp4"):
        clip = tmp_path / name
        clip.write_bytes(b"x")
        clips.append(clip)
    fake = FakeVideoPage()
    window.video_page = fake.as_video_page()
    window._stack.addWidget(fake)
    window._stack.setCurrentWidget(fake)
    window._video_path = window.current_path = clips[0]
    from chopchop.core.document import VIDEO_EXTENSIONS
    from chopchop.viewer.folder_nav import FolderNav

    window._video_nav = FolderNav(clips[0], VIDEO_EXTENSIONS)
    return window, settings, fake, clips


def _wheel(viewer: object, delta: int, ctrl: bool = False) -> None:
    modifier = Qt.KeyboardModifier.ControlModifier if ctrl else Qt.KeyboardModifier.NoModifier
    event = QWheelEvent(
        QPointF(10, 10),
        QPointF(10, 10),
        QPoint(0, 0),
        QPoint(0, delta),
        Qt.MouseButton.NoButton,
        modifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    viewer.wheelEvent(event)  # type: ignore[attr-defined]


# --- фото ------------------------------------------------------------------------------------


def test_fit_mode_decides_the_initial_zoom(qtbot: QtBot, tmp_path: Path) -> None:
    window, settings = _window(qtbot, tmp_path)
    window.resize(600, 400)
    small = QImage(40, 20, QImage.Format.Format_RGB32)
    small.fill(QColor("red"))
    window.viewer.set_image(small)
    assert window.viewer.zoom() == pytest.approx(1.0)  # маленькое фото не растягивается
    settings.set("photo.fit_mode", "fit_all")
    window.viewer.set_image(small)
    assert window.viewer.zoom() > 3  # растягивается по окну
    big = QImage(4000, 3000, QImage.Format.Format_RGB32)
    big.fill(QColor("red"))
    settings.set("photo.fit_mode", "actual")
    window.viewer.set_image(big)
    assert window.viewer.zoom() == pytest.approx(1.0)


def test_zoom_step_and_wheel_action(qtbot: QtBot, tmp_path: Path) -> None:
    window, settings = _window(qtbot, tmp_path)
    window.resize(600, 400)
    image = QImage(4000, 3000, QImage.Format.Format_RGB32)
    image.fill(QColor("red"))
    window.viewer.set_image(image)
    window.viewer.actual_size()
    settings.set("photo.zoom_step", 2.0)
    _wheel(window.viewer, 120)
    assert window.viewer.zoom() == pytest.approx(2.0)
    steps: list[int] = []
    window.viewer.navigateRequested.connect(steps.append)
    settings.set("photo.wheel_action", "navigate")
    _wheel(window.viewer, -120)
    _wheel(window.viewer, 120)
    assert steps == [1, -1]  # колесо вниз — следующее фото
    before = window.viewer.zoom()
    _wheel(window.viewer, 120, ctrl=True)  # Ctrl в режиме листания масштабирует
    assert window.viewer.zoom() == pytest.approx(before * 2.0)


def test_background_and_pixel_smoothing_apply_immediately(qtbot: QtBot, tmp_path: Path) -> None:
    window, settings = _window(qtbot, tmp_path)
    window.resize(600, 400)
    image = QImage(100, 100, QImage.Format.Format_RGB32)
    image.fill(QColor("red"))
    window.viewer.set_image(image)
    settings.set("photo.background", "#112233")
    assert window.viewer.backgroundBrush().color().name() == "#112233"
    window.viewer.actual_size()
    window.viewer.zoom_by(3)
    smooth = window.viewer._item.transformationMode()
    settings.set("photo.smoothing", "pixel")
    assert window.viewer._item.transformationMode() != smooth
    window.viewer.fit_to_window()  # уменьшенное изображение сглаживается и в пиксельном режиме
    assert window.viewer._item.transformationMode() == smooth or window.viewer.zoom() >= 1


def test_preload_setting_limits_neighbours(qtbot: QtBot, tmp_path: Path) -> None:
    from chopchop.viewer.folder_nav import FolderNav

    window, settings = _window(qtbot, tmp_path)
    photos = tmp_path / "p"
    photos.mkdir()
    files = [_png(photos, f"{i}.png", (8, 8)) for i in range(6)]
    window._nav = FolderNav(files[0])
    window.current_path = files[0]
    image = QImage(8, 8, QImage.Format.Format_RGB32)
    requested: list[Path] = []
    window._cache.request = requested.append  # type: ignore[method-assign,assignment]
    settings.set("photo.preload", 0)
    window._display(image)
    assert requested == []  # ничего заранее не готовим
    settings.set("photo.preload", 3)
    window._display(image)
    assert {files[1], files[2], files[3]} <= set(requested)
    assert files[4] not in requested


# --- плеер -----------------------------------------------------------------------------------


def _last_seek(fake: FakeVideoPage) -> object:
    return fake.mpv.seeks[-1][0]


def test_seek_and_volume_steps_come_from_settings(qtbot: QtBot, tmp_path: Path) -> None:
    window, settings, fake, _clips = _video_window(qtbot, tmp_path)
    settings.set("playback.seek_short", 7)
    settings.set("playback.seek_long", 45)
    settings.set("playback.volume_step", 10)
    window._horizontal(1)
    assert _last_seek(fake) == 7
    window._horizontal(-1)
    assert _last_seek(fake) == -7
    window._seek_long(1)
    assert _last_seek(fake) == 45
    fake.mpv.volume = 50.0
    window._volume(settings.get_int("playback.volume_step"))
    assert fake.mpv.volume == 60.0


def test_speed_keys_use_the_speed_step(qtbot: QtBot, tmp_path: Path) -> None:
    window, settings, fake, _clips = _video_window(qtbot, tmp_path)
    settings.set("playback.speed_step", 0.5)
    window._change_speed(window.video_page.player, 1)  # type: ignore[union-attr]
    assert fake.mpv.speed == 1.5
    window._change_speed(window.video_page.player, -1)  # type: ignore[union-attr]
    window._change_speed(window.video_page.player, -1)  # type: ignore[union-attr]
    assert fake.mpv.speed == 0.5
    window._reset_speed(window.video_page.player)  # type: ignore[union-attr]
    assert fake.mpv.speed == 1.0


def test_speed_is_limited(qtbot: QtBot, tmp_path: Path) -> None:
    _window_, _settings, fake, _clips = _video_window(qtbot, tmp_path)
    fake.player.set_speed(100)
    assert fake.mpv.speed == 4.0
    fake.player.set_speed(0)
    assert fake.mpv.speed == 0.25


def test_playback_settings_reach_the_player_live(qtbot: QtBot, tmp_path: Path) -> None:
    window, settings, fake, _clips = _video_window(qtbot, tmp_path)
    settings.set("playback.audio_langs", "jpn,eng")
    assert fake.mpv.alang == "jpn,eng"
    settings.set("subtitles.font_size", 70)
    assert fake.mpv.sub_font_size == 70
    settings.set("playback.hwdec", "off")
    assert fake.mpv.hwdec == "no"
    settings.set("playback.volume_default", 60)
    fake.player.load(Path("x.mkv"))  # у файла своей громкости нет — берётся из настроек
    assert fake.mpv.volume == 60.0


def test_end_of_file_goes_to_the_next_video_when_enabled(qtbot: QtBot, tmp_path: Path) -> None:
    window, settings, fake, clips = _video_window(qtbot, tmp_path)
    fake.mpv.loaded.clear()
    window._on_video_ended()  # выключено: остаёмся на последнем кадре
    assert fake.mpv.loaded == []
    settings.set("playback.autoplay_next", True)
    window._on_video_ended()
    assert fake.mpv.loaded[-1][0] == str(clips[1])
    assert window._video_path == clips[1]


def test_last_video_follows_the_end_action(qtbot: QtBot, tmp_path: Path) -> None:
    window, settings, fake, clips = _video_window(qtbot, tmp_path)
    settings.set("playback.autoplay_next", True)
    window._video_nav.index = 2  # type: ignore[union-attr]
    settings.set("playback.end_action", "loop")
    fake.mpv.pause = True
    window._on_video_ended()
    assert fake.mpv.seeks[-1][:3] == (0.0, "absolute", "exact")
    assert fake.mpv.pause is False
    settings.set("playback.end_action", "close")
    window._on_video_ended()
    assert window._stack.currentWidget() is window._drop_zone


def test_remember_position_can_be_switched_off(qtbot: QtBot, tmp_path: Path) -> None:
    from chopchop.player.resume import ResumeState

    window, settings, fake, clips = _video_window(qtbot, tmp_path)
    window._resume.save(clips[1], ResumeState(position=120.0), 600.0)
    fake.mpv.loaded.clear()
    window._open_video(clips[1])
    assert fake.mpv.loaded[-1][1]["start"] == "120.000"
    settings.set("playback.remember_position", False)
    fake.mpv.loaded.clear()
    window._open_video(clips[1])
    assert "start" not in fake.mpv.loaded[-1][1]


# --- окно и открытие файлов -----------------------------------------------------------------


def test_open_mode_edit_goes_straight_to_the_editor(qtbot: QtBot, tmp_path: Path) -> None:
    window, settings = _window(qtbot, tmp_path)
    settings.set("general.open_mode", "edit")
    path = _png(tmp_path, "a.png", (40, 30))
    window.open_file(path)
    qtbot.waitUntil(lambda: window.editor is not None, timeout=10000)
    assert window._on_editor()
    window._escape()  # возврат в просмотр показывает то же фото
    qtbot.waitUntil(window.viewer.has_image, timeout=5000)
    assert window.current_path == path


def test_open_in_new_window_starts_another_process(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window, settings = _window(qtbot, tmp_path)
    first = _png(tmp_path, "a.png", (10, 10))
    second = _png(tmp_path, "b.png", (10, 10))
    started: list[tuple[str, list[str]]] = []

    def fake_start(program: str, args: list[str]) -> bool:
        started.append((program, args))
        return True

    monkeypatch.setattr("chopchop.ui.main_window.QProcess.startDetached", fake_start)
    settings.set("general.open_in", "new")
    window.open_file(first)  # окно пустое: открываем в нём
    assert started == []
    qtbot.waitUntil(window.viewer.has_image, timeout=5000)
    window.open_file(second)
    assert len(started) == 1 and started[0][1][-1] == str(second)
    assert window.current_path == first
    settings.set("general.open_in", "same")
    window.open_file(second)
    assert window.current_path == second


def test_window_geometry_is_remembered(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window, settings = _window(qtbot, tmp_path)
    window.resize(1011, 655)
    window._remember_window()
    assert settings.get_str("state.window")
    other_settings = AppSettings(None)
    other_settings.set("state.window", settings.get_str("state.window"))
    restored: list[bytes] = []
    original = MainWindow.restoreGeometry

    def spy(self: MainWindow, data: object) -> bool:
        restored.append(bytes(data))  # type: ignore[call-overload]
        return original(self, data)  # type: ignore[arg-type]

    monkeypatch.setattr(MainWindow, "restoreGeometry", spy)
    other = MainWindow(
        QSettings(str(tmp_path / "o.ini"), QSettings.Format.IniFormat), other_settings
    )
    qtbot.addWidget(other)
    # размер окна не меньше 960×600, а экран offscreen меньше, поэтому проверяем сам вызов
    assert restored and restored[0] == window.saveGeometry().data()
    settings.set("general.remember_window", False)
    settings.set("state.window", "")
    window._remember_window()
    assert settings.get_str("state.window") == ""


def test_temp_dir_and_log_level_apply_live(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window, settings = _window(qtbot, tmp_path)
    monkeypatch.setenv(logs.LOG_ENV, str(tmp_path / "logs"))
    logs.setup("error")
    try:
        settings.set("advanced.log_level", "debug")
        assert logs.log.level == 10
        settings.set("advanced.temp_dir", str(tmp_path / "scratch"))
        assert temp_files.temp_root() == tmp_path / "scratch"
        settings.set("advanced.temp_dir", "")
        assert temp_files.temp_root() != tmp_path / "scratch"
    finally:
        temp_files.set_root(None)
        logs.shutdown()


def test_settings_dialog_opens_from_the_menu_action(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window, _settings = _window(qtbot, tmp_path)
    opened: list[bool] = []

    def fake_exec(_dialog: object) -> int:
        opened.append(True)
        return 0

    monkeypatch.setattr("chopchop.ui.main_window.SettingsDialog.exec", fake_exec)
    window.show_settings()
    assert opened == [True]


# --- редактор --------------------------------------------------------------------------------


def test_crop_ratio_setting_parses() -> None:
    assert ratio_from_setting("free") is None
    assert ratio_from_setting("original") == "original"
    assert ratio_from_setting("16:9") == pytest.approx(16 / 9)
    assert ratio_from_setting("garbage:") is None
    assert ratio_from_setting("1:0") is None


def _photo_editor(qtbot: QtBot, tmp_path: Path, settings: AppSettings):  # type: ignore[no-untyped-def]
    from chopchop.editor.session import EditSession
    from chopchop.ui.editor_page import EditorPage

    path = tmp_path / "photo.jpg"
    Image.new("RGB", (200, 100), (200, 30, 30)).save(path)
    session = EditSession(path)
    with qtbot.waitSignal(session.loaded, timeout=10000):
        session.start()
    page = EditorPage(session, settings)
    qtbot.addWidget(page)
    page.show()
    return page, path


def test_editor_starts_with_the_configured_brush_and_ratio(qtbot: QtBot, tmp_path: Path) -> None:
    settings = AppSettings(None)
    settings.set("editor.brush_color", "#00ff80")
    settings.set("editor.brush_width", 9)
    settings.set("editor.crop_ratio", "1:1")
    page, _ = _photo_editor(qtbot, tmp_path, settings)
    assert page._draw_color.color == (0, 255, 128)
    assert page._thickness.value() == 9
    assert page._ratio_bar.value() == pytest.approx(1.0)
    page.session.wait()


def test_quick_save_uses_quality_folder_template_and_metadata_setting(
    qtbot: QtBot, tmp_path: Path
) -> None:
    settings = AppSettings(None)
    out = tmp_path / "results"
    settings.set("editor.output_dir", str(out))
    settings.set("editor.output_template", "{name}-final")
    settings.set("editor.jpeg_quality", 30)
    page, _ = _photo_editor(qtbot, tmp_path, settings)
    from chopchop.core.operations import Flip

    page.session.add_full(Flip(True))
    with qtbot.waitSignal(page.session.exported, timeout=10000):
        page.save_quick()
    result = out / "photo-final.jpg"
    assert result.exists()
    low = result.stat().st_size
    settings.set("editor.jpeg_quality", 95)
    page.session.add_full(Flip(False))
    with qtbot.waitSignal(page.session.exported, timeout=10000):
        page.save_quick()
    assert (out / "photo-final (2).jpg").stat().st_size > low  # качество действительно выше
    page.session.wait()


def test_export_dialog_defaults_follow_the_settings(qtbot: QtBot, tmp_path: Path) -> None:
    from chopchop.ui.export_dialog import ExportDialog

    settings = AppSettings(None)
    settings.set("editor.webp_quality", 41)
    settings.set("editor.jpeg_quality", 77)
    settings.set("editor.strip_metadata", False)
    dialog = ExportDialog(tmp_path / "a.png", "jpeg", None, settings)
    qtbot.addWidget(dialog)
    assert dialog._quality.value() == 77
    assert dialog._keep.isChecked()  # метаданные не удаляются, если так настроено
    dialog._format.setCurrentIndex(dialog._format.findData("webp"))
    assert dialog._quality.value() == 41


def test_video_export_dialog_defaults_follow_the_settings(qtbot: QtBot, tmp_path: Path) -> None:
    from chopchop.core.document import MediaInfo
    from chopchop.core.video import Clip, VideoProject
    from chopchop.ui.video_export_dialog import VideoExportDialog

    info = MediaInfo(1280, 720, 10.0, 30.0, "h264", "yuv420p", 0, None)
    clip = Clip(tmp_path / "m.mp4", info, start=2.0)
    settings = AppSettings(None)
    plain = VideoExportDialog(VideoProject((clip,)), None, settings)
    qtbot.addWidget(plain)
    assert not plain.precise()
    settings.set("editor.cut_mode", "precise")
    settings.set("editor.output_template", "{name}_cut")
    settings.set("editor.output_dir", str(tmp_path / "o"))
    precise = VideoExportDialog(VideoProject((clip,)), None, settings)
    qtbot.addWidget(precise)
    assert precise.precise()
    assert precise.path() == tmp_path / "o" / "m_cut.mp4"
    untrimmed = VideoExportDialog(VideoProject((Clip(tmp_path / "m.mp4", info),)), None, settings)
    qtbot.addWidget(untrimmed)
    assert not untrimmed.precise()  # резать нечего: точный режим недоступен
