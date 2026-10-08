"""Точка входа для PyInstaller: пакет chopchop запускается как обычная программа."""

import sys

from chopchop.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
