"""Каталог английских переводов полон и соответствует исходникам."""

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from chopchop import i18n

ROOT = Path(__file__).resolve().parents[2]


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "update_translations", ROOT / "packaging" / "update_translations.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


update_translations = _load_script()
CATALOG: Path = update_translations.CATALOG


def _messages(text: str) -> dict[tuple[str, str], str]:
    found: dict[tuple[str, str], str] = {}
    for context in re.findall(r"<context>(.*?)</context>", text, re.S):
        name = re.search(r"<name>(.*?)</name>", context).group(1)  # type: ignore[union-attr]
        for message in re.findall(r"<message.*?</message>", context, re.S):
            source = re.search(r"<source>(.*?)</source>", message, re.S).group(1)  # type: ignore[union-attr]
            translation = re.search(r"<translation([^>]*)>(.*?)</translation>", message, re.S)
            assert translation is not None
            marker = "unfinished" if "unfinished" in translation.group(1) else translation.group(2)
            found[(name, source)] = marker
    return found


def test_every_message_is_translated() -> None:
    messages = _messages(CATALOG.read_text(encoding="utf-8"))
    assert len(messages) > 300
    untranslated = [key for key, value in messages.items() if value in ("unfinished", "")]
    assert untranslated == []


def test_catalog_matches_the_sources(tmp_path: Path) -> None:
    if update_translations.lupdate_path() is None:
        pytest.skip("lupdate недоступен")
    scratch = tmp_path / "fresh.ts"
    scratch.write_text(CATALOG.read_text(encoding="utf-8"), encoding="utf-8")
    assert update_translations.update(scratch) == 0
    fresh = set(_messages(scratch.read_text(encoding="utf-8")))
    committed = set(_messages(CATALOG.read_text(encoding="utf-8")))
    assert fresh - committed == set(), (
        "в коде есть строки без перевода: python packaging/update_translations.py"
    )
    assert committed - fresh == set(), (
        "в каталоге лишние строки: python packaging/update_translations.py"
    )


def test_placeholders_survive_translation() -> None:
    text = CATALOG.read_text(encoding="utf-8")
    for context in re.findall(r"<message.*?</message>", text, re.S):
        source = re.search(r"<source>(.*?)</source>", context, re.S).group(1)  # type: ignore[union-attr]
        translation = re.search(r"<translation[^>]*>(.*?)</translation>", context, re.S).group(1)  # type: ignore[union-attr]
        for token in re.findall(r"\{\d?\w*\}|%1|%n", source):
            assert token in translation, (source, translation)


def test_english_catalog_translates_in_the_application(qtbot: object) -> None:
    app = QApplication.instance() or QApplication([])
    installed = i18n.install_language(app, "en")
    try:
        assert QCoreApplication.translate("EditorPage", "Отменить  Ctrl+Z") == "Undo  Ctrl+Z"
        assert QCoreApplication.translate("Settings", "Основные") == "General"
        assert QCoreApplication.translate("EditorPage", "нет такой строки") == "нет такой строки"
    finally:
        for translator in installed:
            app.removeTranslator(translator)
    assert QCoreApplication.translate("EditorPage", "Отменить") == "Отменить"


def test_russian_is_the_source_language() -> None:
    app = QApplication.instance() or QApplication([])
    installed = i18n.install_language(app, "ru")
    try:
        assert QCoreApplication.translate("EditorPage", "Отменить") == "Отменить"
    finally:
        for translator in installed:
            app.removeTranslator(translator)


def test_ts_parser_skips_unfinished_entries() -> None:
    text = (
        "<TS><context><name>A</name>"
        "<message><source>раз</source><translation>one</translation></message>"
        '<message><source>два</source><translation type="unfinished"></translation></message>'
        "</context></TS>"
    )
    assert i18n.parse_ts(text) == {("A", "раз", ""): "one"}
    with pytest.raises(ValueError):
        i18n.parse_ts("<TS><context>")
