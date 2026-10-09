import json
import sys
from pathlib import Path

import pytest

from chopchop import __version__, selfcheck
from chopchop.__main__ import main
from chopchop.services import paths


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == f"CHOPCHOP {__version__}"


def test_self_check_report_has_all_checks(tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    code = main(["--self-check", str(report_path)])
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["version"] == __version__
    assert set(report["checks"]) == {"qt", "pillow", "ffmpeg", "ffprobe", "libmpv"}
    assert report["checks"]["qt"]["ok"] and report["checks"]["pillow"]["ok"]
    assert code == (0 if report["ok"] else 1)  # код выхода отражает итог


def test_self_check_fails_when_something_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(selfcheck, "_check_ffmpeg", lambda: {"ok": False, "detail": "не найден"})
    report_path = tmp_path / "report.json"
    assert selfcheck.run(report_path) == 1
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["checks"]["ffmpeg"]["detail"] == "не найден"


def test_self_check_prints_when_no_file_given(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(selfcheck, "_check_ffmpeg", lambda: {"ok": True, "detail": ""})
    monkeypatch.setattr(selfcheck, "_check_ffprobe", lambda: {"ok": True, "detail": ""})
    monkeypatch.setattr(selfcheck, "_check_libmpv", lambda: {"ok": True, "detail": ""})
    assert selfcheck.run(None) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_development_paths_point_to_resources() -> None:
    assert not paths.is_frozen()
    assert paths.bundled_dirs()[0].parts[-2:] == ("resources", "bin")
    assert paths.resource_dir().name == "resources"
    assert (paths.resource_dir() / "icons" / "chopchop.png").is_file()


def test_frozen_layout_searches_next_to_exe_and_in_internal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exe = tmp_path / "CHOPCHOP.exe"
    internal = tmp_path / "_internal"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.setattr(sys, "_MEIPASS", str(internal), raising=False)
    dirs = paths.bundled_dirs()
    assert dirs == [tmp_path.resolve(), tmp_path.resolve() / "bin", internal, internal / "bin"]
    assert paths.resource_dir() == internal / "resources"


def test_ffmpeg_is_found_in_the_frozen_internal_bin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from chopchop.engines.ffmpeg import find_ffmpeg

    internal = tmp_path / "_internal"
    (internal / "bin").mkdir(parents=True)
    name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    (internal / "bin" / name).write_bytes(b"")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "CHOPCHOP.exe"))
    monkeypatch.setattr(sys, "_MEIPASS", str(internal), raising=False)
    assert find_ffmpeg() == internal / "bin" / name


def test_first_run_picks_language_and_imports_old_values(tmp_path: Path) -> None:
    from PySide6.QtCore import QSettings

    from chopchop.app import load_settings

    old = QSettings(str(tmp_path / "old.ini"), QSettings.Format.IniFormat)
    old.setValue("player/audio_langs", "jpn")
    path = tmp_path / "cfg" / "settings.toml"
    settings = load_settings(path, old)
    assert settings.get_str("general.language") in ("ru", "en")
    assert settings.get_str("playback.audio_langs") == "jpn"
    assert not settings.restart_pending
    assert path.exists()  # первый запуск сразу создаёт читаемый файл
    again = load_settings(path, old)
    assert not again.first_run


def test_existing_file_wins_over_old_values(tmp_path: Path) -> None:
    from PySide6.QtCore import QSettings

    from chopchop.app import load_settings

    old = QSettings(str(tmp_path / "old.ini"), QSettings.Format.IniFormat)
    old.setValue("player/audio_langs", "jpn")
    path = tmp_path / "settings.toml"
    path.write_text('[playback]\naudio_langs = "fra"\n', encoding="utf-8")
    assert load_settings(path, old).get_str("playback.audio_langs") == "fra"
