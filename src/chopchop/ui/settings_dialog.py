"""Окно настроек: слева разделы и поиск, справа карточки со строками. Всё применяется сразу.

Окно строится из схемы (`core/settings_schema.py`): добавить настройку значит добавить строку в
схему и в таблицу групп `GROUPS`. Каждое изменение уходит в `AppSettings` немедленно, подписчики
обновляются на лету; у настроек, которые действуют только после перезапуска, на строке есть ярлык.
Окон «OK» и «Отмена» нет. Элементы управления свои (`settings_widgets.py`), цвета и размеры из темы.
"""

from pathlib import Path

from PySide6.QtCore import QCoreApplication, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence, QResizeEvent, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from chopchop.core import settings_schema as schema
from chopchop.core.settings import SettingsFileError
from chopchop.core.settings_schema import Spec
from chopchop.core.tr_marks import QT_TRANSLATE_NOOP
from chopchop.services import cache, logs, sub_presets
from chopchop.services.app_settings import AppSettings, config_dir
from chopchop.services.sub_presets import PresetStore
from chopchop.ui.settings_widgets import (
    SEARCH_DELAY_MS,
    SectionNav,
    SettingCard,
    SettingRow,
    make_control,
)
from chopchop.ui.subtitle_style_editor import SubtitleStyleEditor
from chopchop.ui.theme import fonts, tokens

SETTINGS_FILTER = "TOML (*.toml)"
DEFAULT_SIZE = (860, 600)
MIN_SIZE = (720, 480)
SAVE_SIZE_MS = 400

SECTION_ICONS = {
    "general": "settings",
    "playback": "play",
    "photo": "fit",
    "subtitles": "subtitles",
    "appearance": "adjust",
    "editor": "scissors",
    "advanced": "sliders",
}

# карточки раздела: название и ключи настроек по порядку; не названные попадают в «Прочее»
GROUPS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "general": (
        (
            QT_TRANSLATE_NOOP("Settings", "Язык и окно"),
            ("general.language", "general.remember_window"),
        ),
        (
            QT_TRANSLATE_NOOP("Settings", "Открытие файлов"),
            ("general.open_mode", "general.open_in"),
        ),
        (
            QT_TRANSLATE_NOOP("Settings", "Файлы"),
            ("general.confirm_delete", "general.screenshot_subtitles"),
        ),
    ),
    "playback": (
        (
            QT_TRANSLATE_NOOP("Settings", "Громкость и перемотка"),
            (
                "playback.volume_default",
                "playback.volume_step",
                "playback.seek_short",
                "playback.seek_long",
                "playback.speed_step",
            ),
        ),
        (
            QT_TRANSLATE_NOOP("Settings", "Поведение"),
            ("playback.remember_position", "playback.autoplay_next", "playback.end_action"),
        ),
        (
            QT_TRANSLATE_NOOP("Settings", "Языки дорожек"),
            ("playback.audio_langs", "playback.sub_langs"),
        ),
        (QT_TRANSLATE_NOOP("Settings", "Декодирование"), ("playback.hwdec",)),
        (
            QT_TRANSLATE_NOOP("Settings", "Панели"),
            ("playback.hide_delay", "playback.fs_panel", "playback.fs_progress_line"),
        ),
    ),
    "photo": (
        (
            QT_TRANSLATE_NOOP("Settings", "Просмотр"),
            ("photo.fit_mode", "photo.zoom_step", "photo.wheel_action", "photo.smoothing"),
        ),
        (QT_TRANSLATE_NOOP("Settings", "Вид"), ("photo.background",)),
        (QT_TRANSLATE_NOOP("Settings", "Скорость"), ("photo.preload",)),
    ),
    "appearance": (
        (QT_TRANSLATE_NOOP("Settings", "Тема"), ("appearance.theme", "appearance.accent")),
        (
            QT_TRANSLATE_NOOP("Settings", "Размер"),
            ("appearance.ui_scale", "appearance.compact"),
        ),
        (
            QT_TRANSLATE_NOOP("Settings", "Шрифт и движение"),
            ("appearance.font", "appearance.animations"),
        ),
    ),
    "editor": (
        (
            QT_TRANSLATE_NOOP("Settings", "Сохранение результата"),
            (
                "editor.output_dir",
                "editor.output_template",
                "editor.strip_metadata",
                "editor.jpeg_quality",
                "editor.webp_quality",
            ),
        ),
        (
            QT_TRANSLATE_NOOP("Settings", "Видео"),
            ("editor.x264_crf", "editor.x264_preset", "editor.hw_encoder", "editor.cut_mode"),
        ),
        (
            QT_TRANSLATE_NOOP("Settings", "Инструменты фото"),
            ("editor.brush_color", "editor.brush_width", "editor.crop_ratio"),
        ),
    ),
    "advanced": (
        (
            QT_TRANSLATE_NOOP("Settings", "Файлы и кэш"),
            ("advanced.temp_dir", "advanced.thumb_cache_mb"),
        ),
        (QT_TRANSLATE_NOOP("Settings", "Производительность"), ("advanced.threads",)),
        (QT_TRANSLATE_NOOP("Settings", "Журнал"), ("advanced.log_level",)),
    ),
}


def _tr(text: str) -> str:
    return QCoreApplication.translate("Settings", text) if text else ""


def _scroll(content: QWidget) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setWidget(content)
    content.setAutoFillBackground(False)  # фон страницы — фон окна из темы, а не системный
    scroll.viewport().setAutoFillBackground(False)
    return scroll


class SettingsDialog(QDialog):
    def __init__(
        self,
        settings: AppSettings,
        parent: QWidget | None = None,
        presets: PresetStore | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Настройки"))
        self._presets = presets or PresetStore(config_dir() / sub_presets.FILE_NAME)
        self.setMinimumSize(*MIN_SIZE)
        self._settings = settings
        self.rows: dict[str, SettingRow] = {}  # строки разделов по ключу
        self._found: dict[str, list[SettingRow]] = {}  # копии строк на странице результатов
        self._scrolls: dict[str, QScrollArea] = {}
        self._group_of: dict[str, str] = {}
        self._remembered = settings.get_str("state.settings_size")
        self._size_timer = QTimer(self)
        self._size_timer.setSingleShot(True)
        self._size_timer.setInterval(SAVE_SIZE_MS)
        self._size_timer.timeout.connect(self._save_size)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(SEARCH_DELAY_MS)
        self._search_timer.timeout.connect(self._run_search)
        self._results_keys: list[str] = []
        self._before_search = ""

        self.nav = SectionNav()
        self.pages = QStackedWidget()
        self.page_sections: list[str] = []
        for section, title in schema.SECTIONS:
            specs = [s for s in schema.specs_of(section) if s.shown]
            if not specs and section != "subtitles":
                continue  # субтитры рисует свой виджет
            self.nav.add(
                section,
                _tr(title),
                SECTION_ICONS.get(section, "settings"),
                divider_before=section == "advanced",
            )
            scroll = _scroll(self._build_page(section, specs))
            self._scrolls[section] = scroll
            self.pages.addWidget(scroll)
            self.page_sections.append(section)
        self.nav.finish()
        self._results_scroll = _scroll(QWidget())
        self.pages.addWidget(self._results_scroll)
        self.nav.sectionChosen.connect(self._show_section)

        self.search = QLineEdit()
        self.search.setPlaceholderText(self.tr("Найти настройку"))
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName(self.tr("Найти настройку"))
        self.search.setProperty("textsize", "small")
        self.search.textChanged.connect(lambda _t: self._search_timer.start())
        self.search.returnPressed.connect(self._open_first_result)
        QShortcut(QKeySequence.StandardKey.Find, self, self.focus_search)
        left = QWidget()
        left.setObjectName("settingsnav")
        left.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        left.setFixedWidth(self.nav.width())
        column = QVBoxLayout(left)
        column.setContentsMargins(0, tokens.SPACE_3, 0, tokens.SPACE_3)
        column.setSpacing(tokens.SPACE_3)
        field = QHBoxLayout()
        field.setContentsMargins(tokens.SPACE_3, 0, tokens.SPACE_3, 0)
        field.addWidget(self.search)
        column.addLayout(field)
        column.addWidget(self.nav, 1)

        self._restart_note = QLabel(self.tr("Часть изменений вступит в силу после перезапуска."))
        self._restart_note.setWordWrap(True)
        self._restart_note.setProperty("chip", True)
        self._restart_note.setVisible(bool(settings.restart_pending))
        self._status = QLabel()
        self._status.setWordWrap(True)
        self._status.setProperty("muted", True)
        body = QHBoxLayout()
        body.setSpacing(0)
        body.addWidget(left)
        body.addWidget(self.pages, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(tokens.SPACE_3, tokens.SPACE_2, tokens.SPACE_3, tokens.SPACE_3)
        footer.setSpacing(tokens.SPACE_2)
        self.import_button = QPushButton(self.tr("Импорт…"))
        self.import_button.clicked.connect(self._import)
        self.export_button = QPushButton(self.tr("Экспорт…"))
        self.export_button.clicked.connect(self._export)
        self.reset_all_button = QPushButton(self.tr("Сбросить всё…"))
        self.reset_all_button.clicked.connect(self._reset_all)
        self.folder_button = QPushButton(self.tr("Открыть папку настроек"))
        self.folder_button.clicked.connect(lambda: self._open_folder(config_dir()))
        for small in (
            self.import_button,
            self.export_button,
            self.reset_all_button,
            self.folder_button,
        ):
            small.setProperty("textsize", "small")  # шрифт 9: пять кнопок в ряд иначе не помещаются
        self.close_button = QPushButton(self.tr("Закрыть"))
        self.close_button.setProperty("variant", "primary")
        self.close_button.setDefault(True)
        self.close_button.clicked.connect(self.accept)
        for button in (self.import_button, self.export_button, self.reset_all_button):
            footer.addWidget(button)
        footer.addWidget(self.folder_button)
        footer.addStretch(1)
        footer.addWidget(self.close_button)
        notes = QVBoxLayout()
        notes.setContentsMargins(tokens.SPACE_3, 0, tokens.SPACE_3, 0)
        notes.setSpacing(tokens.SPACE_1)
        notes.addWidget(self._restart_note)
        notes.addWidget(self._status)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(body, 1)
        layout.addLayout(notes)
        layout.addLayout(footer)

        self.nav.select(self.page_sections[0])
        self.pages.setCurrentIndex(0)
        self.resize(self._initial_size())
        settings.changed.connect(self._on_changed)
        settings.reloaded.connect(self._refresh_all)

    # --- размер окна -------------------------------------------------------------------------

    def _initial_size(self) -> QSize:
        try:
            width, height = (int(n) for n in self._remembered.split("x"))
        except ValueError:
            width, height = DEFAULT_SIZE
        return QSize(max(width, MIN_SIZE[0]), max(height, MIN_SIZE[1]))

    def _save_size(self) -> None:
        self._settings.set("state.settings_size", f"{self.width()}x{self.height()}")

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.isVisible():
            self._size_timer.start()

    def done(self, result: int) -> None:  # noqa: N802
        self._size_timer.stop()
        self._save_size()
        super().done(result)

    # --- построение --------------------------------------------------------------------------

    def _page_title(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("pagetitle", True)
        label.setFont(fonts.ui_font(fonts.TITLE))
        return label

    def _page_shell(self, title: str) -> tuple[QWidget, QVBoxLayout]:
        content = QWidget()
        column = QVBoxLayout(content)
        margin = tokens.SPACE_4 + tokens.SPACE_2
        column.setContentsMargins(margin, tokens.SPACE_4, margin, tokens.SPACE_4)
        column.setSpacing(tokens.SPACE_4)
        column.addWidget(self._page_title(title))
        return content, column

    def _reset_row(self, section: str) -> QHBoxLayout:
        reset = QPushButton(self.tr("Сбросить раздел"))
        reset.setProperty("variant", "danger-soft")
        reset.clicked.connect(lambda: self._settings.reset_section(section))
        end = QHBoxLayout()
        end.addStretch(1)
        end.addWidget(reset)
        return end

    def _build_page(self, section: str, specs: list[Spec]) -> QWidget:
        title = next(_tr(t) for s, t in schema.SECTIONS if s == section)
        content, column = self._page_shell(title)
        if section == "subtitles":
            self.subtitle_editor = SubtitleStyleEditor(self._settings, self._presets)
            column.addWidget(self.subtitle_editor)
        else:
            by_key = {s.key: s for s in specs}
            used: set[str] = set()
            for group_title, keys in GROUPS.get(section, ()):
                card = SettingCard(_tr(group_title))
                for key in keys:
                    spec = by_key.get(key)
                    if spec is not None:
                        card.add(self._make_row(spec))
                        self._group_of[key] = group_title
                        used.add(key)
                if card._rows:
                    column.addWidget(card)
            rest = [s for s in specs if s.key not in used]
            if rest:  # настройка без группы не теряется
                card = SettingCard(_tr(QT_TRANSLATE_NOOP("Settings", "Прочее")))
                for spec in rest:
                    card.add(self._make_row(spec))
                    self._group_of[spec.key] = QT_TRANSLATE_NOOP("Settings", "Прочее")
                column.addWidget(card)
            if section == "advanced":
                column.addWidget(self._danger_card())
        column.addStretch(1)
        column.addLayout(self._reset_row(section))
        return content

    def _danger_card(self) -> SettingCard:
        card = SettingCard(self.tr("Осторожно"), danger=True)
        clear = QPushButton(self.tr("Очистить кэш миниатюр"))
        clear.setProperty("variant", "danger-soft")
        clear.clicked.connect(self._clear_cache)
        card.add(
            SettingRow(
                None,
                clear,
                self.tr("Кэш миниатюр"),
                self.tr("Все готовые миниатюры удалятся и будут созданы заново при открытии видео"),
            )
        )
        everything = QPushButton(self.tr("Сбросить все настройки…"))
        everything.setProperty("variant", "danger-soft")
        everything.clicked.connect(self._reset_all)
        card.add(
            SettingRow(
                None,
                everything,
                self.tr("Все настройки"),
                self.tr("Вернуть значения по умолчанию во всех разделах"),
            )
        )
        logs_button = QPushButton(self.tr("Открыть папку журналов"))
        logs_button.clicked.connect(lambda: self._open_folder(logs.log_dir()))
        card.add(
            SettingRow(
                None,
                logs_button,
                self.tr("Журнал работы"),
                self.tr("Файлы журнала нужны, если программа работает неправильно"),
            )
        )
        return card

    def _make_row(self, spec: Spec, breadcrumb: str = "") -> SettingRow:
        control = make_control(spec, _tr, self.tr("Обзор…"))
        control.set_value(self._settings.get(spec.key))
        restart = self.tr("после перезапуска") if spec.apply == "restart" else ""
        row = SettingRow(spec, control, _tr(spec.label), _tr(spec.hint), restart, breadcrumb)
        control.edited.connect(lambda value, k=spec.key: self._push(k, value))
        if breadcrumb:
            self._found.setdefault(spec.key, []).append(row)
            row.activated.connect(lambda k=spec.key: self.go_to(k))
        else:
            self.rows[spec.key] = row
        return row

    # --- перемещение -------------------------------------------------------------------------

    def current_section(self) -> str:
        return self.nav.current_section()

    def _show_section(self, section: str) -> None:
        if section not in self.page_sections:
            return
        if self.search.text():
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
        self.nav.select(section)
        self.pages.setCurrentIndex(self.page_sections.index(section))

    def open_section(self, section: str) -> None:
        self._show_section(section)

    def go_to(self, key: str) -> None:
        """Перейти к настройке: раздел открывается, строка подсвечивается."""
        spec = next((s for s in schema.SPECS if s.key == key), None)
        if spec is None:
            return
        self._show_section(spec.section)
        row = self.rows.get(key)
        scroll = self._scrolls.get(spec.section)
        if row is not None and scroll is not None:
            QTimer.singleShot(0, lambda: self._reveal(scroll, row))

    def _reveal(self, scroll: QScrollArea, row: SettingRow) -> None:
        scroll.ensureWidgetVisible(row, 0, tokens.SPACE_6)
        row.flash()

    def focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    # --- поиск -------------------------------------------------------------------------------

    def search_for(self, text: str) -> list[str]:
        """Ключи настроек, подходящих под запрос (название, пояснение, раздел, группа, варианты)."""
        needle = text.strip().lower()
        if not needle:
            return []
        titles = {s: _tr(t) for s, t in schema.SECTIONS}
        found = []
        for spec in schema.SPECS:
            if not spec.shown and spec.section != "subtitles":
                continue
            if spec.key == "subtitles.preset":
                continue
            haystack = " ".join(
                [
                    _tr(spec.label),
                    _tr(spec.hint),
                    titles.get(spec.section, ""),
                    _tr(self._group_of.get(spec.key, "")),
                    *(_tr(title) for _v, title in spec.choices),
                ]
            ).lower()
            if needle in haystack:
                found.append(spec.key)
        return found

    def _run_search(self) -> None:
        text = self.search.text()
        if not text.strip():
            if self.pages.currentWidget() is self._results_scroll:
                self._show_section(self._before_search or self.page_sections[0])
            return
        if self.pages.currentWidget() is not self._results_scroll:
            self._before_search = self.nav.current_section()
        self._results_keys = self.search_for(text)
        self._found.clear()
        titles = {s: _tr(t) for s, t in schema.SECTIONS}
        content, column = self._page_shell(self.tr("Результаты поиска"))
        if not self._results_keys:
            empty = QLabel(self.tr("Ничего не найдено"))
            empty.setProperty("muted", True)
            column.addWidget(empty)
        else:
            card = SettingCard()
            for key in self._results_keys:
                spec = next(s for s in schema.SPECS if s.key == key)
                crumb = titles.get(spec.section, "")
                if spec.shown:
                    card.add(self._make_row(spec, crumb))
                else:
                    card.add(self._link_row(spec, crumb))
            column.addWidget(card)
        column.addStretch(1)
        old = self._results_scroll.takeWidget()
        self._results_scroll.setWidget(content)
        if old is not None:
            old.deleteLater()
        self.pages.setCurrentWidget(self._results_scroll)

    def _link_row(self, spec: Spec, crumb: str) -> SettingRow:
        """Настройка раздела «Субтитры»: её редактирует особый виджет, поэтому ссылка на раздел."""
        button = QPushButton(self.tr("Открыть раздел"))
        button.clicked.connect(lambda: self.open_section("subtitles"))
        row = SettingRow(None, button, _tr(spec.label), _tr(spec.hint), "", crumb)
        return row

    def _open_first_result(self) -> None:
        if self._results_keys:
            self.go_to(self._results_keys[0])

    # --- реакции -----------------------------------------------------------------------------

    def _push(self, key: str, value: object) -> None:
        try:
            self._settings.set(key, value)
        except ValueError as error:
            self._show_error(key, str(error))
        else:
            self._show_error(key, "")

    def _on_changed(self, key: str, value: object) -> None:
        for row in [self.rows.get(key), *self._found.get(key, [])]:
            if row is not None:
                row.control.set_value(value)  # type: ignore[attr-defined]
        self._restart_note.setVisible(bool(self._settings.restart_pending))

    def _refresh_all(self) -> None:
        for key in list(self.rows):
            self._on_changed(key, self._settings.get(key))

    def _show_error(self, key: str, message: str) -> None:
        text = self.tr("Недопустимое значение: ") + message if message else ""
        for row in [self.rows.get(key), *self._found.get(key, [])]:
            if row is not None:
                row.show_error(text)

    def _reset_all(self) -> None:
        answer = QMessageBox.question(
            self,
            self.tr("Сбросить всё"),
            self.tr("Вернуть все настройки к значениям по умолчанию?"),
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._settings.reset_all()
            self._refresh_all()

    def _export(self) -> None:
        name, _ = QFileDialog.getSaveFileName(
            self, self.tr("Экспорт настроек"), "chopchop-settings.toml", SETTINGS_FILTER
        )
        if not name:
            return
        try:
            self._settings.export_to(Path(name))
        except OSError as error:
            self._status.setText(self.tr("Не удалось сохранить файл: ") + str(error))
        else:
            self._status.setText(self.tr("Настройки сохранены: ") + name)

    def _import(self) -> None:
        name, _ = QFileDialog.getOpenFileName(self, self.tr("Импорт настроек"), "", SETTINGS_FILTER)
        if not name:
            return
        try:
            warnings = self._settings.import_from(Path(name))
        except (SettingsFileError, OSError, UnicodeDecodeError) as error:
            self._status.setText(self.tr("Не удалось прочитать файл настроек: ") + str(error))
            return
        self._refresh_all()
        message = self.tr("Настройки загружены.")
        if warnings:
            message += " " + self.tr("Заменены недопустимые значения: ") + "; ".join(warnings)
        self._status.setText(message)

    def _clear_cache(self) -> None:
        removed = cache.clear(cache.cache_dir() / "thumbs")
        self._status.setText(self.tr("Кэш миниатюр очищен: удалено файлов — {0}").format(removed))

    @staticmethod
    def _open_folder(folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
