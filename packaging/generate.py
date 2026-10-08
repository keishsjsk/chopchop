"""Генерирует файлы ассоциаций из списка форматов программы: python packaging/generate.py.

Список расширений один (core/document.py), поэтому «Открыть с помощью» в установщике Windows
и в .desktop-файле Linux не расходится с тем, что программа умеет открывать.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from quickedit.core.document import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS  # noqa: E402

HERE = Path(__file__).resolve().parent

MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".gif": "image/gif",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".mp4": "video/mp4",
    ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".m4v": "video/x-m4v",
    ".wmv": "video/x-ms-wmv",
    ".flv": "video/x-flv",
    ".mpg": "video/mpeg",
    ".mpeg": "video/mpeg",
    ".ts": "video/mp2t",
}

IMAGE_PROGID = "QuickEdit.Image"
VIDEO_PROGID = "QuickEdit.Video"


def mime_list() -> list[str]:
    return sorted({MIME_TYPES[ext] for ext in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS})


def desktop_file() -> str:
    mimes = ";".join(mime_list()) + ";"
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=QuickEdit\n"
        "GenericName=Photo and video viewer\n"
        "GenericName[ru]=Просмотр и редактор фото и видео\n"
        "Comment=Light photo viewer and video player with quick editing\n"
        "Comment[ru]=Лёгкий просмотрщик фото, плеер видео и быстрый редактор\n"
        "Exec=quickedit %F\n"
        "Icon=quickedit\n"
        "Terminal=false\n"
        "Categories=AudioVideo;Video;Graphics;Viewer;\n"
        f"MimeType={mimes}\n"
        "StartupWMClass=quickedit\n"
    )


def _registry_line(subkey: str, name: str | None, data: str, flags: str) -> str:
    parts = [f'Root: HKA; Subkey: "{subkey}"; ValueType: string']
    if name is not None:
        parts.append(f'ValueName: "{name}"')
    parts.append(f'ValueData: "{data}"')
    parts.append(f"Flags: {flags}")
    return "; ".join(parts)


def inno_registry() -> str:
    """Секция [Registry] установщика: «Открыть с помощью» и «Приложения по умолчанию»."""
    lines = [
        "; Создано packaging/generate.py, не править вручную",
    ]
    exe = "{app}\\QuickEdit.exe"
    for progid, title in ((IMAGE_PROGID, "Фото"), (VIDEO_PROGID, "Видео")):
        base = f"Software\\Classes\\{progid}"
        lines.append(_registry_line(base, "", f"{title} QuickEdit", "uninsdeletekey"))
        lines.append(_registry_line(f"{base}\\DefaultIcon", "", f"{exe},0", "uninsdeletekey"))
        command = f'""{exe}"" ""%1""'
        lines.append(_registry_line(f"{base}\\shell\\open\\command", "", command, "uninsdeletekey"))

    app = "Software\\Classes\\Applications\\QuickEdit.exe"
    lines.append(_registry_line(app, "FriendlyAppName", "QuickEdit", "uninsdeletekey"))
    lines.append(
        _registry_line(f"{app}\\shell\\open\\command", "", f'""{exe}"" ""%1""', "uninsdeletekey")
    )
    capabilities = "Software\\QuickEdit\\Capabilities"
    lines.append(_registry_line(capabilities, "ApplicationName", "QuickEdit", "uninsdeletekey"))
    lines.append(
        _registry_line(
            capabilities,
            "ApplicationDescription",
            "Лёгкий просмотрщик фото, плеер видео и быстрый редактор",
            "uninsdeletekey",
        )
    )
    for extension in sorted(IMAGE_EXTENSIONS | VIDEO_EXTENSIONS):
        progid = IMAGE_PROGID if extension in IMAGE_EXTENSIONS else VIDEO_PROGID
        lines.append(_registry_line(f"{app}\\SupportedTypes", extension, "", "uninsdeletekey"))
        lines.append(
            _registry_line(
                f"Software\\Classes\\{extension}\\OpenWithProgids", progid, "", "uninsdeletevalue"
            )
        )
        lines.append(
            _registry_line(f"{capabilities}\\FileAssociations", extension, progid, "uninsdeletekey")
        )
    lines.append(
        _registry_line(
            "Software\\RegisteredApplications",
            "QuickEdit",
            "Software\\QuickEdit\\Capabilities",
            "uninsdeletevalue",
        )
    )
    return "\n".join(lines) + "\n"


GENERATED = {
    "file_associations.iss": inno_registry,
    "quickedit.desktop": desktop_file,
}


def encoding_for(name: str) -> str:
    """Inno Setup читает .iss как ANSI, если нет BOM; поэтому русский текст пишем с ним."""
    return "utf-8-sig" if name.endswith(".iss") else "utf-8"


def main() -> None:
    for name, produce in GENERATED.items():
        (HERE / name).write_text(produce(), encoding=encoding_for(name), newline="\n")
        print("создан", name)


if __name__ == "__main__":
    main()
