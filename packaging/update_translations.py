"""Обновляет каталог переводов resources/i18n/chopchop_en.ts по исходникам.

Запуск:  python packaging/update_translations.py
Новые строки появятся в каталоге с пометкой «unfinished»: их нужно перевести вручную;
тест tests/app/test_translations.py не пропустит каталог с непереведёнными строками.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "resources" / "i18n" / "chopchop_en.ts"


def lupdate_path() -> Path | None:
    import PySide6

    folder = Path(PySide6.__file__).resolve().parent
    for name in ("lupdate.exe", "lupdate"):
        if (folder / name).is_file():
            return folder / name
    return None


def sources() -> list[str]:
    return sorted(str(path.relative_to(ROOT)) for path in (ROOT / "src").rglob("*.py"))


def update(target: Path = CATALOG) -> int:
    tool = lupdate_path()
    if tool is None:
        print("lupdate не найден в PySide6", file=sys.stderr)
        return 1
    command = [str(tool), *sources(), "-ts", str(target), "-no-obsolete", "-locations", "none"]
    return subprocess.run(command, cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(update())
