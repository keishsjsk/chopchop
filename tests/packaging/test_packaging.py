"""Файлы упаковки: ассоциации, загрузка бинарников, заметки релиза, согласованность версий."""

import importlib.util
import io
import re
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

from chopchop import __version__
from chopchop.core.document import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS

ROOT = Path(__file__).resolve().parents[2]
PACKAGING = ROOT / "packaging"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"packaging_{name}", PACKAGING / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


generate = _load("generate")
fetch = _load("fetch_binaries")
notes = _load("release_notes")

ALL_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS


# --- ассоциации файлов ----------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(generate.GENERATED))
def test_generated_files_are_up_to_date(name: str) -> None:
    """Забыли запустить packaging/generate.py после смены списка форматов — тест напомнит."""
    committed = (PACKAGING / name).read_bytes().replace(b"\r\n", b"\n")
    expected = generate.GENERATED[name]().encode(generate.encoding_for(name))
    if generate.encoding_for(name) == "utf-8-sig":
        assert committed.startswith(b"\xef\xbb\xbf"), "для Inno Setup нужен UTF-8 с BOM"
    assert committed.decode("utf-8-sig") == expected.decode("utf-8-sig")


def test_every_supported_extension_has_a_mime_type() -> None:
    for extension in IMAGE_EXTENSIONS:
        assert generate.MIME_TYPES[extension].startswith("image/")
    for extension in VIDEO_EXTENSIONS:
        assert generate.MIME_TYPES[extension].startswith("video/")


def test_desktop_file_lists_formats_and_command() -> None:
    text = generate.desktop_file()
    assert "Exec=chopchop %F" in text
    assert "Icon=chopchop" in text
    mime_line = next(line for line in text.splitlines() if line.startswith("MimeType="))
    assert mime_line.endswith(";")
    assert {"image/jpeg", "image/heic", "video/mp4", "video/x-matroska"} <= set(
        mime_line.removeprefix("MimeType=").split(";")
    )


def test_inno_registry_registers_each_extension_once() -> None:
    text = generate.inno_registry()
    for extension in ALL_EXTENSIONS:
        progid = "CHOPCHOP.Image" if extension in IMAGE_EXTENSIONS else "CHOPCHOP.Video"
        opens = f'Subkey: "Software\\Classes\\{extension}\\OpenWithProgids"; '
        assert text.count(opens) == 1
        assert f'ValueName: "{progid}"' in text.split(opens)[1].splitlines()[0]
        assert f'FileAssociations"; ValueType: string; ValueName: "{extension}"' in text
    assert '"""{app}\\CHOPCHOP.exe"" ""%1"""' in text  # путь с пробелами и аргумент в кавычках
    assert "RegisteredApplications" in text
    assert text.count("CHOPCHOP.Image\\shell\\open\\command") == 1


def test_installer_script_is_per_user_and_registers_associations() -> None:
    script = (PACKAGING / "chopchop.iss").read_bytes().decode("utf-8-sig")
    assert "PrivilegesRequired=lowest" in script
    assert "ChangesAssociations=yes" in script
    assert '#include "file_associations.iss"' in script
    assert "AppId={{" in script  # фигурная скобка в идентификаторе экранируется


# --- загрузка бинарников ----------------------------------------------------------------------


@pytest.mark.parametrize("asset", [fetch.FFMPEG_WINDOWS, fetch.FFMPEG_LINUX, fetch.MPV_WINDOWS])
def test_downloads_are_pinned_with_checksums(asset: object) -> None:
    assert re.fullmatch(r"[0-9a-f]{64}", asset.sha256)  # type: ignore[attr-defined]
    assert asset.url.startswith("https://github.com/")  # type: ignore[attr-defined]
    assert "/latest/" not in asset.url  # type: ignore[attr-defined]  # «плавающие» релизы ломают повторяемость


def test_sha256_of(tmp_path: Path) -> None:
    path = tmp_path / "data.bin"
    path.write_bytes(b"abc")
    assert (
        fetch.sha256_of(path) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


def test_zip_extraction_is_flat_and_ignores_unsafe_paths(tmp_path: Path) -> None:
    archive = tmp_path / "ffmpeg.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("ffmpeg-build/bin/ffmpeg.exe", b"exe")
        bundle.writestr("ffmpeg-build/bin/avcodec.dll", b"dll")
        bundle.writestr("ffmpeg-build/doc/readme.txt", b"doc")
        bundle.writestr("ffmpeg-build/../evil.dll", b"bad")
        bundle.writestr("/abs/bin/evil.dll", b"bad")
    out = tmp_path / "out"
    fetch.extract_zip(archive, "bin", out)
    assert sorted(p.name for p in out.iterdir()) == ["avcodec.dll", "ffmpeg.exe"]
    assert not (tmp_path / "evil.dll").exists()


def test_tar_extraction_keeps_binaries_executable(tmp_path: Path) -> None:
    archive = tmp_path / "ffmpeg.tar.xz"
    with tarfile.open(archive, "w:xz") as bundle:
        for name, data, mode in (
            ("build/bin/ffmpeg", b"elf", 0o755),
            ("build/lib/libavcodec.so.62", b"so", 0o644),
            ("build/../escape", b"bad", 0o644),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = mode
            bundle.addfile(info, io.BytesIO(data))
    out_bin, out_lib = tmp_path / "bin", tmp_path / "lib"
    fetch.extract_tar(archive, "bin", out_bin)
    fetch.extract_tar(archive, "lib", out_lib)
    assert [p.name for p in out_bin.iterdir()] == ["ffmpeg"]
    assert [p.name for p in out_lib.iterdir()] == ["libavcodec.so.62"]
    if sys.platform != "win32":
        assert (out_bin / "ffmpeg").stat().st_mode & 0o111


# --- заметки и версии релиза -----------------------------------------------------------------

SAMPLE = """# Изменения

## [0.2.0] — 2026-11-01

### Добавлено
- Новое.

## [0.1.0] — 2026-10-08

Первый релиз.
"""


def test_release_notes_pick_one_version() -> None:
    assert notes.notes_for("0.2.0", SAMPLE) == "### Добавлено\n- Новое.\n"
    assert notes.notes_for("0.1.0", SAMPLE) == "Первый релиз.\n"
    assert notes.notes_for("0.3.0", SAMPLE) == ""
    assert notes.latest_version(SAMPLE) == "0.2.0"


def test_versions_agree_everywhere() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert project["project"]["version"] == __version__
    assert notes.latest_version(changelog) == __version__
    assert notes.notes_for(__version__, changelog), "для текущей версии нет заметок релиза"


def test_license_and_notices_exist() -> None:
    assert "GNU GENERAL PUBLIC LICENSE" in (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "FFmpeg" in (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
