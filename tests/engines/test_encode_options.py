from pathlib import Path

import pytest

from chopchop.engines.encoders import available_hw_encoders
from chopchop.engines.video_engine import (
    EncodeOptions,
    parse_encoder_names,
    pick_encoder,
)
from media import FFMPEG, HAS_FFMPEG

ENCODERS_OUTPUT = """Encoders:
 V....D libx264              libx264 H.264 / AVC
 V....D h264_nvenc           NVIDIA NVENC H.264 encoder (codec h264)
 V....D h264_qsv             H.264 / AVC (Intel Quick Sync Video acceleration)
 V....D hevc_nvenc           NVIDIA NVENC hevc encoder
 A....D aac                  AAC (Advanced Audio Coding)
"""


def test_default_matches_the_previous_hard_coded_arguments() -> None:
    assert EncodeOptions().video_args() == [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
    ]  # fmt: skip


def test_quality_preset_and_threads_reach_x264() -> None:
    args = EncodeOptions(crf=18, preset="slow", threads=4).video_args()
    assert args[2:4] == ["-preset", "slow"]
    assert args[4:6] == ["-crf", "18"]
    assert args[6:8] == ["-threads", "4"]
    assert "-threads" not in EncodeOptions().video_args()


@pytest.mark.parametrize(
    ("encoder", "codec", "quality_flag"),
    [
        ("nvenc", "h264_nvenc", "-cq"),
        ("qsv", "h264_qsv", "-global_quality"),
        ("amf", "h264_amf", "-qp_i"),
    ],
)
def test_hardware_encoders_use_their_own_quality_flags(
    encoder: str, codec: str, quality_flag: str
) -> None:
    args = EncodeOptions(crf=22, encoder=encoder).video_args()
    assert args[args.index("-c:v") + 1] == codec
    assert args[args.index(quality_flag) + 1] == "22"
    assert args[-2:] == ["-pix_fmt", "yuv420p"]
    assert "libx264" not in args
    assert EncodeOptions(encoder=encoder).is_hardware


def test_fallback_options_keep_quality_but_use_the_processor() -> None:
    options = EncodeOptions(crf=19, preset="fast", encoder="nvenc", threads=2).on_cpu()
    assert (options.crf, options.preset, options.encoder, options.threads) == (19, "fast", "cpu", 2)


def test_encoder_names_are_parsed_from_ffmpeg_output() -> None:
    assert parse_encoder_names(ENCODERS_OUTPUT) == ["h264_nvenc", "h264_qsv"]
    assert parse_encoder_names("") == []


def test_encoder_choice_depends_on_what_is_available() -> None:
    available = ["h264_qsv", "h264_amf"]
    assert pick_encoder("cpu", available) == "cpu"
    assert pick_encoder("auto", available) == "qsv"
    assert pick_encoder("amf", available) == "amf"
    assert pick_encoder("nvenc", available) == "cpu"  # выбранного кодера нет
    assert pick_encoder("auto", []) == "cpu"
    assert pick_encoder("bogus", available) == "cpu"


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg не установлен")
def test_real_ffmpeg_lists_only_known_encoders() -> None:
    assert FFMPEG is not None
    found = available_hw_encoders(FFMPEG)
    assert set(found) <= {"h264_nvenc", "h264_qsv", "h264_amf"}
    assert available_hw_encoders(Path("definitely-missing-ffmpeg")) == ()
