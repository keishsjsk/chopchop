"""Все строки интерфейса (ru и en) рисуются Monocraft: символы без глифа известны и заменены."""

import html
import re
from pathlib import Path

import pytest

from chopchop.core import settings_schema as schema
from chopchop.ui.theme import fonts

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "resources" / "i18n" / "chopchop_en.ts"
FONT = ROOT / "resources" / "fonts" / "Monocraft.ttf"


def _cmap() -> set[int]:
    ttlib = pytest.importorskip("fontTools.ttLib")
    return set(ttlib.TTFont(FONT).getBestCmap())


def _all_strings() -> list[str]:
    text = CATALOG.read_text(encoding="utf-8")
    found = re.findall(r"<(?:source|translation)[^>]*>(.*?)</(?:source|translation)>", text, re.S)
    strings = [html.unescape(item) for item in found]
    for spec in schema.SPECS:  # подписи, пояснения и варианты настроек на русском (исходный язык)
        strings += [spec.label, spec.hint, *(title for _value, title in spec.choices)]
    return strings


def test_every_interface_string_is_drawable_or_has_a_known_fallback() -> None:
    cmap = _cmap()
    missing: dict[str, str] = {}
    for string in _all_strings():
        for char in string:
            if char.isspace() or char < " " or ord(char) in cmap:
                continue
            missing.setdefault(char, string[:50])
    unknown = {c: s for c, s in missing.items() if c not in fonts.FALLBACK_CHARS}
    assert unknown == {}, (
        "в строках есть символы без глифа Monocraft и без записи в fonts.FALLBACK_CHARS: "
        + ", ".join(f"{c!r} ({hex(ord(c))}) в «{s}»" for c, s in unknown.items())
    )


def test_ui_strings_avoid_the_symbols_monocraft_lacks() -> None:
    """Сейчас таких символов в строках нет вовсе: № заменён на «N°», вместо ✓ значок из набора."""
    cmap = _cmap()
    offenders = sorted(
        {
            c
            for s in _all_strings()
            for c in s
            if not c.isspace() and c >= " " and ord(c) not in cmap
        }
    )
    assert offenders == []


def test_fallback_chars_really_lack_a_glyph_so_the_list_stays_honest() -> None:
    cmap = _cmap()
    present = [c for c in fonts.FALLBACK_CHARS if ord(c) in cmap]
    assert present == [], f"эти символы в шрифте есть, из списка их можно убрать: {present}"


def test_fallback_families_are_registered_as_substitutes(qtbot) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtGui import QFont

    assert fonts.load_fonts()
    assert [s.lower() for s in QFont.substitutes(fonts.family())] == [
        f.lower() for f in fonts.FALLBACK_FAMILIES
    ]
