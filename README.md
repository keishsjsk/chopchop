# CHOPCHOP

Лёгкий просмотрщик фото и плеер видео со встроенным режимом быстрого редактирования.
Офлайн, без регистрации. Windows и Linux.

Статус: этапы 1–3 из плана (основа, просмотр фото, плеер видео). Подробности — в `architecture.md`.

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

Для плеера видео нужна libmpv:

- Windows: положите `libmpv-2.dll` (например, из `mpv-dev-x86_64-*.7z` с
  https://github.com/shinchiro/mpv-winbuild-cmake/releases) в `resources/bin`.
- Linux: `sudo apt install libmpv2` (или аналог в вашем дистрибутиве).

## Клавиши плеера

Пробел — пауза, ←/→ — перемотка на 5 с, ↑/↓ — громкость, A — следующая аудиодорожка,
S и Shift+S — субтитры 1 и 2, Z/X и Shift+Z/Shift+X — сдвиг субтитров 1 и 2 на 100 мс,
F — полный экран. Файл .srt/.ass можно перетащить на окно во время просмотра.
