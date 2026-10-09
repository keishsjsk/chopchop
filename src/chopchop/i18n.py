"""Переводы интерфейса. Исходный язык — русский; английский берётся из resources/i18n/*.ts.

Каталог .ts читается прямо при запуске (несколько миллисекунд): отдельной сборки .qm не нужно,
и каталог одинаково работает из репозитория, PyInstaller и AppImage.
"""

from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLibraryInfo, QTranslator, QXmlStreamReader

from chopchop.services.paths import resource_dir

SOURCE_LANGUAGE = "ru"
LANGUAGES = ("ru", "en")

Catalog = dict[tuple[str, str, str], str]


def parse_ts(text: str) -> Catalog:
    """(контекст, исходный текст, пояснение) -> перевод; недопереведённые записи пропускаются."""
    reader = QXmlStreamReader(text)
    catalog: Catalog = {}
    context = ""
    source = comment = translation = ""
    finished = True
    in_message = False
    while not reader.atEnd():
        token = reader.readNext()
        if token == QXmlStreamReader.TokenType.StartElement:
            name = reader.name()
            if name == "name" and not in_message:
                context = reader.readElementText()
            elif name == "message":
                in_message = True
                source = comment = translation = ""
                finished = True
            elif name == "source":
                source = reader.readElementText()
            elif name == "comment":
                comment = reader.readElementText()
            elif name == "translation":
                finished = reader.attributes().value("type") not in ("unfinished", "obsolete")
                translation = reader.readElementText()
        elif token == QXmlStreamReader.TokenType.EndElement and reader.name() == "message":
            in_message = False
            if finished and translation:
                catalog[(context, source, comment)] = translation
    if reader.hasError():
        raise ValueError(f"каталог переводов повреждён: {reader.errorString()}")
    return catalog


class CatalogTranslator(QTranslator):
    """QTranslator поверх словаря: подставляет перевод, а при его отсутствии — исходный текст."""

    def __init__(self, catalog: Catalog) -> None:
        super().__init__()
        self._catalog = catalog

    def isEmpty(self) -> bool:  # noqa: N802
        return not self._catalog

    def translate(
        self,
        context: str,
        sourceText: str,  # noqa: N803
        disambiguation: str | None = None,
        n: int = -1,
    ) -> str | None:
        """Перевод или None: пустая строка Qt сочтёт найденным переводом без текста."""
        found = self._catalog.get((context, sourceText, disambiguation or ""))
        return found or self._catalog.get((context, sourceText, "")) or None


def catalog_path(language: str) -> Path:
    return resource_dir() / "i18n" / f"chopchop_{language}.ts"


def load_catalog(language: str) -> Catalog:
    path = catalog_path(language)
    if not path.is_file():
        return {}
    return parse_ts(path.read_text(encoding="utf-8"))


def install_language(app: QCoreApplication, language: str) -> list[QTranslator]:
    """Устанавливает переводы для языка; для исходного (русского) только стандартные диалоги Qt."""
    installed: list[QTranslator] = []
    qt = QTranslator()
    folder = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    for name in ("qtbase", "qt"):
        if qt.load(f"{name}_{language}", folder):
            app.installTranslator(qt)
            installed.append(qt)
            break
    if language != SOURCE_LANGUAGE:
        translator = CatalogTranslator(load_catalog(language))
        app.installTranslator(translator)
        installed.append(translator)
    return installed
