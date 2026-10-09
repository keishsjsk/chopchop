"""Значения настроек и их файл TOML: чтение с проверкой, миграции, запись. Чистый Python.

Файл ничего не исполняет: разбирается `tomllib`, каждое значение проверяется по схеме, неверное
заменяется значением по умолчанию (с предупреждением), неизвестные ключи сохраняются как есть,
чтобы настройки более новой версии не пропадали при записи.
"""

import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field

from chopchop.core import settings_schema as schema
from chopchop.core.settings_schema import Spec

Value = object
Migration = Callable[[dict[str, dict[str, Value]]], dict[str, dict[str, Value]]]

# версия N -> функция, превращающая данные версии N в данные версии N + 1
MIGRATIONS: dict[int, Migration] = {}


class SettingsFileError(ValueError):
    """Файл настроек не разобрать целиком: нужна резервная копия и значения по умолчанию."""


@dataclass
class LoadResult:
    values: dict[str, Value]
    extra: dict[str, dict[str, Value]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    version: int = schema.SCHEMA_VERSION


def parse(text: str) -> LoadResult:
    """Разбирает файл. SettingsFileError, если это не TOML или версия из будущего."""
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise SettingsFileError(f"не TOML: {error}") from error
    version = raw.pop("version", schema.SCHEMA_VERSION)
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise SettingsFileError(f"неверная версия схемы: {version!r}")
    if version > schema.SCHEMA_VERSION:
        raise SettingsFileError(
            f"файл создан более новой версией (схема {version}, поддерживается "
            f"{schema.SCHEMA_VERSION})"
        )
    sections = {name: dict(body) for name, body in raw.items() if isinstance(body, dict)}
    for current in range(version, schema.SCHEMA_VERSION):
        sections = MIGRATIONS[current](sections)
    result = LoadResult(values=schema.defaults(), version=schema.SCHEMA_VERSION)
    for spec in schema.SPECS:
        body = sections.get(spec.section, {})
        if spec.name not in body:
            continue
        try:
            result.values[spec.key] = schema.coerce(spec, body[spec.name])
        except ValueError as error:
            result.warnings.append(str(error))
    known = {(spec.section, spec.name) for spec in schema.SPECS}
    for name, body in sections.items():
        for key, value in body.items():
            if (name, key) not in known:
                result.extra.setdefault(name, {})[key] = value
    return result


def dumps(values: dict[str, Value], extra: dict[str, dict[str, Value]] | None = None) -> str:
    """Читаемый TOML: по разделу на группу, с подписью каждой настройки в комментарии."""
    lines = [f"version = {schema.SCHEMA_VERSION}", ""]
    for section, _ in schema.SECTIONS + (("state", ""),):
        specs = schema.specs_of(section)
        body = (extra or {}).get(section, {})
        if not specs and not body:
            continue
        lines.append(f"[{section}]")
        for spec in specs:
            lines.append(f"{spec.name} = {_literal(values.get(spec.key, spec.default))}")
        for key, value in body.items():
            lines.append(f"{_key(key)} = {_literal(value)}")
        lines.append("")
    for section, body in (extra or {}).items():
        if section in {name for name, _ in schema.SECTIONS} | {"state"}:
            continue
        lines.append(f"[{_key(section)}]")
        lines.extend(f"{_key(key)} = {_literal(value)}" for key, value in body.items())
        lines.append("")
    return "\n".join(lines)


def _key(key: str) -> str:
    return key if key.replace("_", "").replace("-", "").isalnum() else _literal(key)


def _literal(value: Value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(round(value, 6))
    if isinstance(value, list):
        return "[" + ", ".join(_literal(item) for item in value) + "]"
    text = str(value)
    escaped = []
    for char in text:
        if char == "\\":
            escaped.append("\\\\")
        elif char == '"':
            escaped.append('\\"')
        elif ord(char) < 0x20 or ord(char) == 0x7F:
            escaped.append(f"\\u{ord(char):04x}")
        else:
            escaped.append(char)
    return '"' + "".join(escaped) + '"'


def spec_of(key: str) -> Spec:
    try:
        return schema.BY_KEY[key]
    except KeyError:
        raise KeyError(f"неизвестная настройка: {key}") from None
