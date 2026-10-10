"""Добавляет поставляемые шрифты (с лицензиями) в SBOM CycloneDX.

    python packaging/font_components.py sbom.cdx.json

`cyclonedx-py environment` видит только пакеты Python, а шрифт лежит в `resources/fonts`
файлом, поэтому его описываем сами: имя, версия, лицензия SPDX, хэш файла и текст лицензии.
"""

import base64
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FONTS = ROOT / "resources" / "fonts"

# файл → описание; новый шрифт добавляется сюда вместе с текстом лицензии рядом
FONT_INFO: dict[str, dict[str, str]] = {
    "Tiny5.ttf": {
        "name": "Tiny5",
        "version": "1.0",
        "license": "OFL-1.1",
        "license_file": "OFL-Tiny5.txt",
        "author": "The Tiny5 Project Authors",
        "url": "https://github.com/Gissio/font_tiny5",
    }
}


def font_components(fonts_dir: Path = FONTS) -> list[dict[str, object]]:
    components: list[dict[str, object]] = []
    for name, info in FONT_INFO.items():
        font = fonts_dir / name
        licence = fonts_dir / info["license_file"]
        if not font.is_file() or not licence.is_file():
            raise FileNotFoundError(f"нет шрифта или его лицензии: {font}, {licence}")
        text = licence.read_bytes()
        components.append(
            {
                "type": "data",
                "bom-ref": f"font:{info['name']}@{info['version']}",
                "name": info["name"],
                "version": info["version"],
                "author": info["author"],
                "description": "Пиксельный шрифт заголовков (resources/fonts/" + name + ")",
                "hashes": [
                    {"alg": "SHA-256", "content": hashlib.sha256(font.read_bytes()).hexdigest()}
                ],
                "licenses": [
                    {
                        "license": {
                            "id": info["license"],
                            "text": {
                                "contentType": "text/plain",
                                "encoding": "base64",
                                "content": base64.b64encode(text).decode("ascii"),
                            },
                        }
                    }
                ],
                "externalReferences": [{"type": "website", "url": info["url"]}],
            }
        )
    return components


def add_fonts(sbom: dict[str, object]) -> dict[str, object]:
    """Дописывает шрифты в `components`, не дублируя уже добавленные."""
    existing = sbom.setdefault("components", [])
    assert isinstance(existing, list)
    known = {item.get("bom-ref") for item in existing if isinstance(item, dict)}
    existing.extend(item for item in font_components() if item["bom-ref"] not in known)
    return sbom


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    path = Path(argv[1])
    sbom = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps(add_fonts(sbom), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"шрифты добавлены в {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
