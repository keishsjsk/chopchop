# QuickEdit

Лёгкий просмотрщик фото и плеер видео со встроенным режимом быстрого редактирования.
Офлайн, без регистрации, исходный файл никогда не меняется. Windows и Linux.

Статус: этап 1 из плана (основа проекта). Подробности — в `architecture.md`.

## Разработка

```bash
python -m venv .venv
.venv/Scripts/activate        # Linux: source .venv/bin/activate
pip install -e ".[dev]"
python -m quickedit [путь к файлу]
```

Проверки:

```bash
ruff check . && ruff format --check .
mypy
pytest
```

## ffmpeg и libmpv

Программа ищет `ffmpeg`, `ffprobe` и `libmpv` сначала рядом с собой
(`resources/bin` при разработке, папка с exe в сборке), затем в системе (PATH).
