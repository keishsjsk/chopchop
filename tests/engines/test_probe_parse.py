from pathlib import Path

import pytest

from chopchop.core.document import MediaInfo
from chopchop.engines.ffmpeg import parse_progress_line
from chopchop.engines.probe import ProbeError, parse_probe

VIDEO = {
    "codec_type": "video",
    "codec_name": "h264",
    "width": 1920,
    "height": 1080,
    "pix_fmt": "yuv420p",
    "avg_frame_rate": "30000/1001",
    "duration": "10.5",
}
AUDIO = {"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000", "channels": 6}


def test_parses_video_and_audio() -> None:
    info = parse_probe({"streams": [VIDEO, AUDIO], "format": {"duration": "12.0"}})
    assert (info.width, info.height) == (1920, 1080)
    assert info.fps == pytest.approx(29.97, abs=0.01)
    assert info.duration == 12.0  # длительность контейнера важнее
    assert info.audio is not None
    assert (info.audio.codec, info.audio.sample_rate, info.audio.channels) == ("aac", 48000, 6)


def test_duration_falls_back_to_stream() -> None:
    assert parse_probe({"streams": [VIDEO], "format": {}}).duration == 10.5


def test_cover_art_is_not_a_video_stream() -> None:
    cover = {**VIDEO, "disposition": {"attached_pic": 1}}
    with pytest.raises(ProbeError):
        parse_probe({"streams": [cover, AUDIO], "format": {}})


def test_rotation_from_side_data_and_tags() -> None:
    rotated = {**VIDEO, "side_data_list": [{"rotation": -90}]}
    assert parse_probe({"streams": [rotated], "format": {}}).rotation == 270
    tagged = {**VIDEO, "tags": {"rotate": "90"}}
    assert parse_probe({"streams": [tagged], "format": {}}).rotation == 90


def test_bad_frame_rate_falls_back() -> None:
    odd = {**VIDEO, "avg_frame_rate": "0/0", "r_frame_rate": "25/1"}
    assert parse_probe({"streams": [odd], "format": {}}).fps == 25.0


def test_no_video_stream() -> None:
    with pytest.raises(ProbeError):
        parse_probe({"streams": [AUDIO], "format": {}})


def test_parse_progress_line() -> None:
    assert parse_progress_line("out_time_us=1500000\n") == 1.5
    assert parse_progress_line("out_time_us=N/A") is None
    assert parse_progress_line("frame=42") is None
    assert parse_progress_line("progress=end") is None


def test_probe_asks_ffprobe_once_per_unchanged_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from chopchop.engines import probe as probe_module

    calls: list[Path] = []

    def fake_run(path: Path, ffprobe: Path | None) -> MediaInfo:
        calls.append(path)
        return parse_probe({"streams": [VIDEO], "format": {}})

    monkeypatch.setattr(probe_module, "_run_probe", fake_run)
    probe_module.clear_memo()
    clip = tmp_path / "a.mp4"
    clip.write_bytes(b"1234")
    probe_module.probe(clip)
    probe_module.probe(clip)
    assert len(calls) == 1
    clip.write_bytes(b"12345678")  # файл изменился
    probe_module.probe(clip)
    assert len(calls) == 2
    probe_module.clear_memo()
