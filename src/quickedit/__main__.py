"""Точка входа: ``python -m quickedit [путь к файлу]``."""

import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    initial = Path(args[0]) if args else None

    from quickedit.app import run

    return run(initial)


if __name__ == "__main__":
    sys.exit(main())
