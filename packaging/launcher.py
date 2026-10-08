"""Точка входа для PyInstaller: пакет quickedit запускается как обычная программа."""

import sys

from quickedit.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
