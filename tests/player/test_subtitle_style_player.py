from typing import Any

from chopchop.core.subtitle_style import SubtitleStyle, to_mpv
from chopchop.core.tracks import parse_tracks
from chopchop.player.player import Player
from chopchop.services.settings import PlayerPrefs
from fakes import FakeMpv


class _OldMpv(FakeMpv):
    """libmpv, в котором нет некоторых свойств оформления (например, межстрочного интервала)."""

    MISSING = {"sub_line_spacing", "secondary_sub_pos"}

    ready = False

    def __init__(self) -> None:
        super().__init__()
        self.ready = True

    def __setattr__(self, name: str, value: Any) -> None:
        if self.ready and name in self.MISSING:
            raise AttributeError("mpv property does not exist")
        super().__setattr__(name, value)


def test_style_goes_to_mpv_property_by_property() -> None:
    fake = FakeMpv()
    player = Player(fake)
    style = SubtitleStyle(font="Arial", font_size=70, bold=True, ass_mode="mine", align_y="top")
    player.apply_style(style, "cp1251", 40)
    for name, value in to_mpv(style).items():
        assert getattr(fake, name) == value, name
    assert fake.sub_codepage == "cp1251" and fake.secondary_sub_pos == 40
    assert player.unsupported_style == set()


def test_missing_properties_are_reported_not_hidden() -> None:
    fake = _OldMpv()
    player = Player(fake)
    player.apply_style(SubtitleStyle(line_spacing=5), "auto", 10)
    assert player.unsupported_style == {"sub_line_spacing", "secondary_sub_pos"}
    assert fake.sub_font_size == 55  # остальное применилось


def test_prefs_apply_style_and_reload_subtitles_when_codepage_changes() -> None:
    fake = FakeMpv()
    player = Player(fake)
    player.load(__import__("pathlib").Path("m.mkv"))
    prefs = PlayerPrefs(style=SubtitleStyle(font_size=33), codepage="cp1251")
    player.apply_prefs(prefs)
    assert fake.sub_font_size == 33
    assert ("sub-reload",) in fake.commands
    count = len(fake.commands)
    player.apply_prefs(prefs)  # кодировка та же: субтитры заново не читаются
    assert len(fake.commands) == count


def test_track_codec_is_parsed() -> None:
    tracks = parse_tracks(
        [
            {"id": 1, "type": "sub", "codec": "hdmv_pgs_subtitle"},
            {"id": 2, "type": "sub", "codec": "subrip"},
            {"id": 3, "type": "sub"},
        ]
    )
    assert [t.codec for t in tracks] == ["hdmv_pgs_subtitle", "subrip", None]
