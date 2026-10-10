"""Скачивает ffmpeg и libmpv для сборки с проверкой SHA-256: python packaging/fetch_binaries.py.

Версии зафиксированы по датированным релизам (а не «latest»), чтобы сборка была повторяемой.
Результат: <папка>/bin (ffmpeg, ffprobe, DLL) и <папка>/lib (общие библиотеки ffmpeg на Linux).
"""

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

FFMPEG_TAG = "autobuild-2026-10-07-13-07"
FFMPEG_BASE = f"https://github.com/BtbN/FFmpeg-Builds/releases/download/{FFMPEG_TAG}/"
MPV_BASE = "https://github.com/shinchiro/mpv-winbuild-cmake/releases/download/20261008/"


@dataclass(frozen=True)
class Asset:
    url: str
    sha256: str


FFMPEG_WINDOWS = Asset(
    FFMPEG_BASE + "ffmpeg-n8.1.3-14-g330caae0c1-win64-gpl-shared-8.1.zip",
    "c8806f80b5e7b192a1d456b615e7066901a597285291a60c52b289927bbe20c6",
)
FFMPEG_LINUX = Asset(
    FFMPEG_BASE + "ffmpeg-n8.1.3-14-g330caae0c1-linux64-gpl-shared-8.1.tar.xz",
    "c17170c3f8cd58f45acabb1695860662799757be885098a0dd6f29236bf9f385",
)
MPV_WINDOWS = Asset(
    MPV_BASE + "mpv-dev-x86_64-20261008-git-36bf3d5290.7z",
    "1e94b722d9d1b701406250c73ee37d73cd0045cdf47bdd7a54f2bea1b513465f",
)
CHUNK = 1 << 20
SONAME = re.compile(r"\.so\.\d+$")  # libavcodec.so.62: имя, по которому библиотеку ищет загрузчик

if hasattr(sys.stdout, "reconfigure"):
    # на раннерах Windows кодировка вывода cp1252: русский текст не должен ронять скрипт
    sys.stdout.reconfigure(errors="replace")  # type: ignore[union-attr]


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def download(asset: Asset, directory: Path) -> Path:
    if not asset.url.startswith("https://"):
        raise SystemExit(f"разрешён только https: {asset.url}")
    target = directory / PurePosixPath(asset.url).name
    print(f"скачиваю {asset.url}")
    # Причина nosec: схема проверена выше, адреса закреплены в этом файле, а результат
    # принимается только при совпадении SHA-256 с закреплённым значением.
    with (
        urllib.request.urlopen(asset.url, timeout=120) as response,  # noqa: S310  # nosec B310
        target.open("wb") as out,
    ):
        shutil.copyfileobj(response, out, CHUNK)
    actual = sha256_of(target)
    if actual != asset.sha256:
        raise SystemExit(f"контрольная сумма не совпала для {target.name}: {actual}")
    print(f"  контрольная сумма совпала ({actual[:12]}…)")
    return target


def _safe_name(name: str) -> PurePosixPath | None:
    """Путь внутри архива без выхода за пределы папки (защита от ../ и абсолютных путей)."""
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        return None
    return path


def extract_zip(archive: Path, wanted_dir: str, dest: Path) -> None:
    """Файлы из <корень>/<wanted_dir>/ архива кладёт в dest, плоско."""
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            path = _safe_name(info.filename)
            if path is None or info.is_dir() or len(path.parts) < 3 or path.parts[1] != wanted_dir:
                continue
            (dest / path.name).write_bytes(bundle.read(info))


def _library_names(real: str, aliases: dict[str, list[str]]) -> list[str]:
    """Все имена файла через цепочку ссылок: libx.so.62.1.2 ← libx.so.62 ← libx.so."""
    names, queue = [], [real]
    while queue:
        for link in aliases.get(queue.pop(), []):
            names.append(link)
            queue.append(link)
    return names


def extract_tar(archive: Path, wanted_dir: str, dest: Path) -> None:
    """Файлы из <корень>/<wanted_dir>/ архива кладёт в dest, плоско.

    Общие библиотеки в архиве — это файл с полной версией и ссылки на него. Загрузчик ищет
    библиотеку по имени вида libx.so.62, поэтому файл сохраняется под этим именем (одна копия).
    """
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as bundle:
        members = []
        for member in bundle.getmembers():
            path = _safe_name(member.name)
            if path is not None and len(path.parts) >= 3 and path.parts[1] == wanted_dir:
                members.append(member)
        aliases: dict[str, list[str]] = {}
        for member in members:
            target = PurePosixPath(member.linkname)
            if member.issym() and len(target.parts) == 1:  # только ссылки внутри той же папки
                aliases.setdefault(target.name, []).append(PurePosixPath(member.name).name)
        for member in members:
            source = bundle.extractfile(member) if member.isfile() else None
            if source is None:
                continue
            name = PurePosixPath(member.name).name
            name = next((n for n in _library_names(name, aliases) if SONAME.search(n)), name)
            target_file = dest / name
            with source, target_file.open("wb") as out:
                shutil.copyfileobj(source, out)
            target_file.chmod(member.mode & 0o755 | 0o444)


def extract_libmpv(archive: Path, dest: Path) -> None:
    """libmpv-2.dll лежит в 7z с фильтром BCJ2: его читают 7z или bsdtar (tar в Windows 11)."""
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        for tool in (
            ["7z", "x", "-y", f"-o{temp}", str(archive)],
            ["tar", "-xf", str(archive), "-C", temp],
        ):
            if shutil.which(tool[0]) is None:
                continue
            if subprocess.run(tool, capture_output=True, check=False).returncode == 0:
                break
        else:
            raise SystemExit("нужен 7z или tar с поддержкой 7z, чтобы распаковать libmpv")
        shutil.copy2(Path(temp) / "libmpv-2.dll", dest / "libmpv-2.dll")


def fetch(platform: str, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        temp_dir = Path(temp)
        if platform == "windows":
            extract_zip(download(FFMPEG_WINDOWS, temp_dir), "bin", out / "bin")
            extract_libmpv(download(MPV_WINDOWS, temp_dir), out / "bin")
            keep = {"ffplay.exe"}
            for name in keep:
                (out / "bin" / name).unlink(missing_ok=True)  # проигрыватель ffplay не нужен
        else:
            archive = download(FFMPEG_LINUX, temp_dir)
            extract_tar(archive, "bin", out / "bin")
            extract_tar(archive, "lib", out / "lib")
            (out / "bin" / "ffplay").unlink(missing_ok=True)
    print("готово:", out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=["windows", "linux"], required=True)
    parser.add_argument("--out", type=Path, default=Path("build/binaries"))
    args = parser.parse_args()
    fetch(args.platform, args.out)


if __name__ == "__main__":
    sys.exit(main())
