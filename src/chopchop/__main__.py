"""Точка входа: ``python -m chopchop [путь к файлу]``.

Служебные ключи: ``--version`` и ``--self-check [файл-отчёт.json]``.
"""

import sys
from pathlib import Path

from chopchop import __version__


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["--version"]:
        if sys.stdout is not None:
            print(f"CHOPCHOP {__version__}")
        return 0
    if args[:1] == ["--self-check"]:
        from chopchop import selfcheck

        return selfcheck.run(Path(args[1]) if len(args) > 1 else None)

    initial = Path(args[0]) if args else None

    from chopchop.app import run

    return run(initial)


if __name__ == "__main__":
    sys.exit(main())
