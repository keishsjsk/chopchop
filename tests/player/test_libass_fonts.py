"""libass внутри mpv находит шрифт по имени из Qt, в том числе для кириллицы.

Проверка с настоящим libmpv: на Windows шрифты ищет DirectWrite, на Linux fontconfig. Тест
читает журнал libass («fontselect») и пропускается, если libmpv нет или журнала нет.
"""

import contextlib
import time
from pathlib import Path

import pytest
from PySide6.QtGui import QFontDatabase
from pytestqt.qtbot import QtBot

from chopchop.player.libmpv import find_libmpv, load_mpv_module
from media import HAS_FFMPEG, make_video

pytestmark = [
    pytest.mark.skipif(find_libmpv() is None, reason="libmpv не установлена"),
    pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg не установлен"),
]

CANDIDATES = ("Arial", "Segoe UI", "DejaVu Sans", "Liberation Sans", "Noto Sans")
SRT = "1\n00:00:00,000 --> 00:00:03,000\nСъешь ещё этих мягких французских булок\n"


def _fontselect(font: str, video: Path, srt: Path) -> str | None:
    lines: list[str] = []

    def handler(_level: str, _prefix: str, text: str) -> None:
        if "fontselect" in text:
            lines.append(text.strip())

    module = load_mpv_module()
    mpv = module.MPV(
        vo="null",
        ao="null",
        config=False,
        load_scripts=False,
        terminal=False,
        log_handler=handler,
        loglevel="v",
        sub_font=font,
        sub_ass_override="force",
    )
    try:
        mpv.loadfile(str(video), sub_files=str(srt), pause=True)
        time.sleep(1.2)
        with contextlib.suppress(SystemError):  # важен не снимок, а подбор шрифта для строки
            mpv.command("screenshot-to-file", str(video.with_suffix(".png")), "subtitles")
        time.sleep(0.3)
    finally:
        mpv.terminate()
    return lines[-1] if lines else None


def test_libass_resolves_a_font_by_its_qt_family_name(qtbot: QtBot, tmp_path: Path) -> None:
    families = set(QFontDatabase.families())
    family = next((name for name in CANDIDATES if name in families), None)
    if family is None:
        pytest.skip("нет знакомого шрифта для проверки")
    video = make_video(tmp_path / "v.mp4", seconds=3, size=(320, 180))
    srt = tmp_path / "s.srt"
    srt.write_text(SRT, encoding="utf-8")
    line = _fontselect(family, video, srt)
    if line is None:
        pytest.skip("libass не пишет подбор шрифта в журнал")
    resolved = line.split("->", 1)[1].lower().replace(" ", "").replace("-", "")
    assert family.lower().replace(" ", "")[:6] in resolved, line
    unknown = _fontselect("NoSuchFontXYZ", video, srt)
    assert unknown is not None and "nosuchfontxyz" not in unknown.split("->", 1)[1].lower()
