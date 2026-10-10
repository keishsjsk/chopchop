"""Видеовиджет без OpenGL (`SoftwareMpvWidget`): настоящий libmpv, кадры идут в память."""

from pathlib import Path

import pytest
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from chopchop.player.libmpv import create_mpv, find_libmpv, load_mpv_module
from chopchop.player.mpv_widget import SoftwareMpvWidget
from chopchop.services.app_settings import AppSettings
from chopchop.services.settings import player_prefs
from media import HAS_FFMPEG, make_video

pytestmark = [
    pytest.mark.skipif(find_libmpv() is None, reason="libmpv не установлена"),
    pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg не установлен"),
]


def _widget(qtbot: QtBot) -> tuple[SoftwareMpvWidget, object]:
    module = load_mpv_module()
    mpv = create_mpv(module, player_prefs(AppSettings(None)))
    widget = SoftwareMpvWidget(module, mpv)
    qtbot.addWidget(widget)
    widget.resize(320, 180)
    widget.show()
    return widget, mpv


def test_software_widget_paints_playing_video_without_opengl(qtbot: QtBot, tmp_path: Path) -> None:
    video = make_video(tmp_path / "v.mp4", seconds=3, size=(320, 180))
    widget, mpv = _widget(qtbot)
    try:
        mpv.loadfile(str(video))  # type: ignore[attr-defined]
        QTest.qWait(1800)
        picture = widget.grab().toImage()
        colours = {
            picture.pixelColor(x, y).name() for x in range(0, 320, 40) for y in range(0, 180, 30)
        }
        assert len(colours) > 1, "кадр так и остался чёрным"  # тестовое видео не однотонное
        assert widget._has_frame
    finally:
        widget.release()
        mpv.terminate()  # type: ignore[attr-defined]
    assert widget._ctx is None


def test_software_widget_keeps_the_last_picture_until_a_new_frame(
    qtbot: QtBot, tmp_path: Path
) -> None:
    video = make_video(tmp_path / "v.mp4", seconds=3, size=(320, 180))
    widget, mpv = _widget(qtbot)
    try:
        mpv.loadfile(str(video), pause=True)  # type: ignore[attr-defined]
        QTest.qWait(1200)
        before = widget.grab().toImage()
        widget.update()  # перерисовка без нового кадра
        QTest.qWait(150)
        after = widget.grab().toImage()
        spread = {
            after.pixelColor(x, y).name() for x in range(0, 320, 40) for y in range(0, 180, 30)
        }
        assert len(spread) > 1, "после перерисовки без нового кадра картинка пропала"
        _ = before
    finally:
        widget.release()
        mpv.terminate()  # type: ignore[attr-defined]
