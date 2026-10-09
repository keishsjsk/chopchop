"""Окно настроек: разделы слева, значения справа. Изменения применяются сразу.

Окно строится из схемы (`core/settings_schema.py`): добавить настройку значит добавить строку
в схему. Каждое изменение уходит в `AppSettings` немедленно, подписчики обновляются на лету;
у настроек, которые действуют только после перезапуска, есть пометка.
"""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QCoreApplication, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from chopchop.core import settings_schema as schema
from chopchop.core.settings import SettingsFileError
from chopchop.core.settings_schema import Spec
from chopchop.services import cache, logs
from chopchop.services.app_settings import AppSettings, config_dir
from chopchop.ui.color_button import ColorButton, color_to_hex, hex_to_color

SETTINGS_FILTER = "TOML (*.toml)"
NUMBER_WIDTH = 140  # числа и цвет не растягиваются на всю ширину окна


def _tr(text: str) -> str:
    return QCoreApplication.translate("Settings", text) if text else ""


class _Row:
    """Один элемент управления: умеет показать значение и сообщить о своём изменении."""

    def __init__(self, spec: Spec, widget: QWidget, show: Callable[[object], None]) -> None:
        self.spec = spec
        self.widget = widget
        self.show = show


class SettingsDialog(QDialog):
    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Настройки"))
        self.setMinimumSize(720, 520)
        self._settings = settings
        self._rows: dict[str, _Row] = {}
        self._errors: dict[str, QLabel] = {}
        self._updating = False

        self._sections = QListWidget()
        self._sections.setFixedWidth(170)
        self._pages = QStackedWidget()
        self._page_sections: list[str] = []
        for section, title in schema.SECTIONS:
            specs = [s for s in schema.specs_of(section) if s.shown]
            if not specs:
                continue
            self._sections.addItem(_tr(title))
            self._pages.addWidget(self._build_page(section, specs))
            self._page_sections.append(section)
        self._sections.currentRowChanged.connect(self._pages.setCurrentIndex)
        self._sections.setCurrentRow(0)

        self._restart_note = QLabel(self.tr("Часть изменений вступит в силу после перезапуска."))
        self._restart_note.setWordWrap(True)
        self._restart_note.setVisible(bool(settings.restart_pending))
        self._status = QLabel()
        self._status.setWordWrap(True)

        body = QHBoxLayout()
        body.addWidget(self._sections)
        body.addWidget(self._pages, 1)

        import_button = QPushButton(self.tr("Импорт…"))
        import_button.clicked.connect(self._import)
        export_button = QPushButton(self.tr("Экспорт…"))
        export_button.clicked.connect(self._export)
        reset_all = QPushButton(self.tr("Сбросить всё…"))
        reset_all.clicked.connect(self._reset_all)
        close = QPushButton(self.tr("Закрыть"))
        close.setDefault(True)
        close.clicked.connect(self.accept)
        footer = QHBoxLayout()
        for button in (import_button, export_button, reset_all):
            footer.addWidget(button)
        footer.addStretch(1)
        footer.addWidget(close)

        layout = QVBoxLayout(self)
        layout.addLayout(body, 1)
        layout.addWidget(self._restart_note)
        layout.addWidget(self._status)
        layout.addLayout(footer)

        settings.changed.connect(self._on_changed)
        settings.reloaded.connect(self._refresh_all)

    # --- построение --------------------------------------------------------------------------

    def _build_page(self, section: str, specs: list[Spec]) -> QWidget:
        """Страница раздела: настройки одна под другой (название, элемент, пояснение)."""
        content = QWidget()
        outer = QVBoxLayout(content)
        main = QVBoxLayout()
        main.setSpacing(12)
        advanced = QWidget()
        extra = QVBoxLayout(advanced)
        extra.setContentsMargins(0, 0, 0, 0)
        extra.setSpacing(12)
        for spec in specs:
            (extra if spec.advanced else main).addWidget(self._block(spec))
        outer.addLayout(main)
        if extra.count() or section == "advanced":
            if section == "advanced":
                extra.addWidget(self._advanced_buttons())
            toggle = QToolButton()
            toggle.setText(
                self.tr("Показать дополнительные настройки")
                if section == "advanced"
                else self.tr("Дополнительно")
            )
            toggle.setCheckable(True)
            toggle.setArrowType(Qt.ArrowType.RightArrow)
            toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            advanced.hide()

            def expand(open_: bool) -> None:
                advanced.setVisible(open_)
                toggle.setArrowType(Qt.ArrowType.DownArrow if open_ else Qt.ArrowType.RightArrow)

            toggle.toggled.connect(expand)
            outer.addWidget(toggle)
            outer.addWidget(advanced)
        outer.addStretch(1)
        reset = QPushButton(self.tr("Сбросить раздел"))
        reset.clicked.connect(lambda: self._settings.reset_section(section))
        row_end = QHBoxLayout()
        row_end.addStretch(1)
        row_end.addWidget(reset)
        outer.addLayout(row_end)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        return scroll

    def _block(self, spec: Spec) -> QWidget:
        """Одна настройка: подпись, элемент управления, сообщение об ошибке и пояснение."""
        row = self._make_row(spec)
        self._rows[spec.key] = row
        hint = _tr(spec.hint)
        row.widget.setToolTip(hint)
        block = QWidget()
        column = QVBoxLayout(block)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(3)
        if spec.kind != "bool":  # у флажка подпись — его собственный текст
            label = _tr(spec.label)
            if spec.apply == "restart":
                label += " " + self.tr("(после перезапуска)")
            column.addWidget(QLabel(label))
        elif spec.apply == "restart":
            assert isinstance(row.widget, QCheckBox)
            row.widget.setText(row.widget.text() + " " + self.tr("(после перезапуска)"))
        column.addWidget(row.widget)
        error = QLabel()
        error.setStyleSheet("color: #c0392b;")
        error.hide()
        self._errors[spec.key] = error
        column.addWidget(error)
        if hint:
            note = QLabel(hint)
            note.setWordWrap(True)
            note.setStyleSheet("color: gray;")
            column.addWidget(note)
        return block

    def _advanced_buttons(self) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        clear = QPushButton(self.tr("Очистить кэш миниатюр"))
        clear.clicked.connect(self._clear_cache)
        logs_button = QPushButton(self.tr("Открыть папку журналов"))
        logs_button.clicked.connect(lambda: self._open_folder(logs.log_dir()))
        config_button = QPushButton(self.tr("Открыть папку настроек"))
        config_button.clicked.connect(lambda: self._open_folder(config_dir()))
        for button in (clear, logs_button, config_button):
            row.addWidget(button)
        row.addStretch(1)
        return box

    def _make_row(self, spec: Spec) -> _Row:
        settings = self._settings
        key = spec.key

        def push(value: object) -> None:
            if self._updating:
                return
            try:
                settings.set(key, value)
            except ValueError as error:
                self._show_error(key, str(error))
            else:
                self._show_error(key, "")

        current = settings.get(key)
        match spec.kind:
            case "bool":
                box = QCheckBox(_tr(spec.label))
                box.setChecked(bool(current))
                box.toggled.connect(push)
                return _Row(spec, box, lambda v: box.setChecked(bool(v)))
            case "int":
                spin = QSpinBox()
                spin.setRange(int(spec.low or 0), int(spec.high or 0))
                spin.setSingleStep(int(spec.step))
                spin.setMaximumWidth(NUMBER_WIDTH)
                spin.setValue(int(str(current)))
                spin.valueChanged.connect(push)
                return _Row(spec, spin, lambda v: spin.setValue(int(str(v))))
            case "float":
                dspin = QDoubleSpinBox()
                dspin.setRange(spec.low or 0.0, spec.high or 0.0)
                dspin.setSingleStep(spec.step)
                dspin.setDecimals(2)
                dspin.setMaximumWidth(NUMBER_WIDTH)
                dspin.setValue(float(str(current)))
                dspin.valueChanged.connect(push)
                return _Row(spec, dspin, lambda v: dspin.setValue(float(str(v))))
            case "choice":
                combo = QComboBox()
                for value, title in spec.choices:
                    combo.addItem(_tr(title), value)
                combo.setCurrentIndex(max(combo.findData(current), 0))
                combo.currentIndexChanged.connect(lambda _i: push(combo.currentData()))
                return _Row(spec, combo, lambda v: combo.setCurrentIndex(max(combo.findData(v), 0)))
            case "color":
                button = ColorButton(hex_to_color(str(current)))
                button.setMaximumWidth(NUMBER_WIDTH)
                button.colorChanged.connect(lambda c: push(color_to_hex(c)))
                return _Row(spec, button, lambda v: button.set_color(hex_to_color(str(v))))
            case "path":
                return self._path_row(spec, push)
            case _:  # str, langs
                edit = QLineEdit(str(current))
                edit.editingFinished.connect(lambda: push(edit.text()))
                if spec.kind == "langs":
                    edit.setPlaceholderText("rus,eng")
                return _Row(spec, edit, lambda v: edit.setText(str(v)))

    def _path_row(self, spec: Spec, push: Callable[[object], None]) -> _Row:
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        edit = QLineEdit(str(self._settings.get(spec.key)))
        edit.editingFinished.connect(lambda: push(edit.text()))
        browse = QPushButton(self.tr("Обзор…"))

        def choose() -> None:
            folder = QFileDialog.getExistingDirectory(self, _tr(spec.label), edit.text())
            if folder:
                edit.setText(folder)
                push(folder)

        browse.clicked.connect(choose)
        row.addWidget(edit, 1)
        row.addWidget(browse)
        return _Row(spec, holder, lambda v: edit.setText(str(v)))

    # --- реакции -----------------------------------------------------------------------------

    def _on_changed(self, key: str, value: object) -> None:
        row = self._rows.get(key)
        if row is not None:
            self._updating = True
            try:
                row.show(value)
            finally:
                self._updating = False
        self._restart_note.setVisible(bool(self._settings.restart_pending))

    def _refresh_all(self) -> None:
        for key in self._rows:
            self._on_changed(key, self._settings.get(key))

    def _show_error(self, key: str, message: str) -> None:
        label = self._errors.get(key)
        if label is not None:
            label.setText(self.tr("Недопустимое значение: ") + message if message else "")
            label.setVisible(bool(message))

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
