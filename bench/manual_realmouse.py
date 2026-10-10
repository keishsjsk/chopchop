"""Ручной прогон с настоящей мышью: запускает только владелец компьютера.

    python bench/manual_realmouse.py [--sizes 1080p] [--scenarios drag_seek,editor_drag_trim]

Что происходит: на экране показывается окно программы, и скрипт двигает настоящий курсор и жмёт
левую кнопку (`SetCursorPos`, `mouse_event`). Пока идёт прогон (несколько минут), мышью
пользоваться нельзя, а закрыть окно или остановить скрипт можно только сочетанием Ctrl+C в
терминале. Закройте игры и другие программы, которые читают мышь.

Перед запуском скрипт просит ввести фразу подтверждения и отсчитывает 10 секунд. Сам по себе
`bench_realtime.py` без этого скрипта не работает: он отказывается трогать курсор.
Результаты: `bench/results/realtime-<метка>.json`. Замеры без мыши (события Qt): `bench_render.py`.
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

PHRASE = "можно, компьютер свободен"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="manual")
    parser.add_argument("--sizes", default="1080p")
    parser.add_argument("--scenarios", default="drag_seek,editor_drag_trim,hover_seek")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--seconds", type=float, default=6.0)
    args = parser.parse_args()
    print(__doc__)
    answer = input(f"Чтобы продолжить, введите «{PHRASE}»: ").strip().lower()
    if answer != PHRASE:
        print("Не подтверждено, ничего не запущено.")
        return 1
    for left in range(10, 0, -1):
        print(f"Старт через {left} с. Уберите руку с мыши. Остановить: Ctrl+C.", end="\r")
        time.sleep(1)
    print()
    command = [sys.executable, "-u", str(Path(__file__).with_name("bench_realtime.py"))]
    command += ["--label", args.label, "--sizes", args.sizes, "--scenarios", args.scenarios]
    command += ["--repeat", str(args.repeat), "--seconds", str(args.seconds)]
    env = dict(os.environ, CHOPCHOP_REAL_MOUSE_OK="1")
    return subprocess.run(command, env=env, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
