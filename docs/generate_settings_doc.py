"""Собирает docs/settings.md из схемы настроек (src/chopchop/core/settings_schema.py).

Запуск:  python docs/generate_settings_doc.py
Тест tests/core/test_settings_doc.py следит, чтобы файл не отставал от схемы.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chopchop.core import settings_schema as schema  # noqa: E402

OUTPUT = Path(__file__).resolve().parent / "settings.md"

HEADER = r"""# Настройки

Файл настроек — читаемый TOML, в папке настроек ОС:

- Настройки. Windows: `%LOCALAPPDATA%\CHOPCHOP\CHOPCHOP\settings.toml`.
  Linux: `~/.config/CHOPCHOP/CHOPCHOP/settings.toml`.
- Журнал. Windows: `%LOCALAPPDATA%\CHOPCHOP\CHOPCHOP\logs\chopchop.log`.
  Linux: `~/.local/share/CHOPCHOP/CHOPCHOP/logs/chopchop.log`.
- Кэш миниатюр. Windows: `%LOCALAPPDATA%\CHOPCHOP\CHOPCHOP\cache\thumbs`.
  Linux: `~/.cache/CHOPCHOP/CHOPCHOP/thumbs`.

Переменные окружения `CHOPCHOP_CONFIG_DIR`, `CHOPCHOP_LOG_DIR` и `CHOPCHOP_CACHE_DIR`
переопределяют эти папки.

- **Версия схемы** хранится в начале файла (`version = 1`); при смене схемы старые файлы
  переносятся функциями-миграциями. Файл более новой версии не читается: он сохраняется рядом
  и программа стартует с настройками по умолчанию.
- **Запись атомарная**: данные пишутся во временный файл рядом и подменяют основной, сбой
  посреди записи не оставит половину файла. Частые изменения (ползунки) пишутся одним разом.
- **Проверка значений**: тип и диапазон каждой настройки проверяются при чтении. Число вне
  диапазона ограничивается, недопустимое значение заменяется значением по умолчанию, об этом
  показывается сообщение. Неизвестные ключи сохраняются при записи.
- **Битый файл** не мешает запуску: он переименовывается в `settings.toml.broken-ДАТА`,
  программа стартует с настройками по умолчанию и сообщает об этом в строке состояния.
- Файл **никогда не исполняет код**: он разбирается `tomllib`, значения только данные.
- **Импорт, экспорт и сброс** — в окне настроек (Файл → Настройки…): сброс раздела, сброс всего,
  сохранение настроек в файл и загрузка из файла. Положение окна между компьютерами не
  переносится.
- **Применение**: «на лету» — сразу, без перезапуска; «после перезапуска» — помечено в окне.

Раздел «Дополнительно» в окне свёрнут. Настройки без пометки «в окне» ещё не показываются:
они появятся вместе с оформлением (фазы 3 и 4) и хранятся в файле уже сейчас.
"""


def describe_range(spec: schema.Spec) -> str:
    if spec.kind in ("int", "float"):
        return f"{spec.low:g} … {spec.high:g}"
    if spec.kind == "choice":
        return ", ".join(f"`{value}`" for value, _ in spec.choices)
    if spec.kind == "bool":
        return "да / нет"
    if spec.kind == "color":
        return "`#rrggbb`"
    if spec.kind == "langs":
        return "коды языков через запятую"
    if spec.kind == "path":
        return "путь к папке"
    return "текст"


def default_text(spec: schema.Spec) -> str:
    value = spec.default
    if isinstance(value, bool):
        return "да" if value else "нет"
    return f"`{value}`" if value != "" else "пусто"


def kind_text(spec: schema.Spec) -> str:
    return {
        "bool": "флажок",
        "int": "целое",
        "float": "дробное",
        "choice": "выбор",
        "str": "текст",
        "color": "цвет",
        "path": "папка",
        "langs": "список языков",
    }[spec.kind]


def build() -> str:
    lines = [HEADER]
    titles = dict(schema.SECTIONS)
    for section in [name for name, _ in schema.SECTIONS] + ["state"]:
        specs = schema.specs_of(section)
        if not specs:
            continue
        title = titles.get(section, "Служебное (не в окне настроек)")
        lines.append(f"## {title}\n")
        lines.append("| Ключ | Название | Тип | Допустимо | По умолчанию | Применение | В окне |")
        lines.append("|---|---|---|---|---|---|---|")
        for spec in specs:
            apply = "на лету" if spec.apply == "live" else "после перезапуска"
            shown = "да" if spec.shown else "нет"
            if spec.shown and spec.advanced:
                shown = "да (свёрнуто)"
            lines.append(
                f"| `{spec.key}` | {spec.label} | {kind_text(spec)} | {describe_range(spec)} "
                f"| {default_text(spec)} | {apply} | {shown} |"
            )
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    OUTPUT.write_text(build(), encoding="utf-8", newline="\n")
    print(f"записано: {OUTPUT}")
