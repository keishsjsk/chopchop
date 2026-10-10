# Сторонние компоненты

CHOPCHOP распространяется под лицензией GNU GPL версии 3 или новее (файл `LICENSE`).
Сборки для Windows и Linux содержат следующие компоненты; их исходный код доступен по ссылкам.

| Компонент | Лицензия | Где взять исходный код |
| --- | --- | --- |
| FFmpeg (сборка GPL с x264, x265 и др.) | GPL 3 | https://ffmpeg.org/ , сборки: https://github.com/BtbN/FFmpeg-Builds |
| mpv / libmpv | GPL 2+ (в этой сборке) | https://mpv.io/ , сборки: https://github.com/shinchiro/mpv-winbuild-cmake |
| python-mpv | GPL 2+ / LGPL 2.1+ | https://github.com/jaseg/python-mpv |
| Qt 6 и PySide6 | LGPL 3 | https://code.qt.io/ , https://pypi.org/project/PySide6/ |
| Pillow | HPND | https://github.com/python-pillow/Pillow |
| pillow-heif, libheif | BSD 3-Clause, LGPL 3 | https://github.com/bigcat88/pillow_heif |
| x265 (в составе pillow-heif) | GPL 2 | https://www.videolan.org/developers/x265.html |
| Python | PSF | https://www.python.org/ |
| Monocraft, пиксельный шрифт интерфейса (© 2022 Idrees Hassan) | SIL OFL 1.1 (`resources/fonts/Monocraft-LICENSE.txt`, `docs/licenses/`) | https://github.com/IdreesInc/Monocraft |
| PyInstaller (загрузчик) | GPL 2 с исключением для собираемых программ | https://pyinstaller.org/ |

Версии и контрольные суммы загружаемых при сборке бинарников зафиксированы в `packaging/fetch_binaries.py`.
Полный список зависимостей Python в формате CycloneDX прикладывается к каждому релизу (`sbom.cdx.json`).
