import time
from pathlib import Path

import pytest

from chopchop.engines.image_engine import default_output_path
from chopchop.engines.video_engine import default_video_output
from chopchop.services.output import render_name

MOMENT = time.struct_time((2026, 10, 9, 14, 5, 7, 0, 0, -1))


def test_default_template_keeps_the_old_naming() -> None:
    assert render_name("{name}_edited", "photo") == "photo_edited"


def test_date_and_time_fields() -> None:
    assert render_name("{name} {date} {time}", "trip", MOMENT) == "trip 2026-10-09 14-05-07"


@pytest.mark.parametrize("template", ["{name", "{missing}", "{0}", "{name.__class__}"])
def test_broken_template_falls_back_instead_of_failing(template: str) -> None:
    assert render_name(template, "photo") == "photo_edited"


def test_forbidden_characters_are_replaced() -> None:
    assert render_name("{name}", 'a:b*c?"d') == "a_b_c__d"
    assert render_name("{name}", "...") == "output"


def test_very_long_names_are_cut() -> None:
    assert len(render_name("{name}", "x" * 400)) == 150


def test_photo_path_uses_folder_and_template(tmp_path: Path) -> None:
    source = tmp_path / "a" / "cat.png"
    out = default_output_path(source, "jpeg", tmp_path / "out", "{name}-v2")
    assert out == tmp_path / "out" / "cat-v2.jpg"
    (tmp_path / "out").mkdir()
    out.write_bytes(b"x")
    assert (
        default_output_path(source, "jpeg", tmp_path / "out", "{name}-v2").name == "cat-v2 (2).jpg"
    )


def test_video_path_uses_folder_and_template(tmp_path: Path) -> None:
    source = tmp_path / "clip.mp4"
    assert default_video_output(source, None, tmp_path / "o", "{name}_cut") == (
        tmp_path / "o" / "clip_cut.mp4"
    )
