"""Небольшие окна для файла: переименование и свойства."""

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from chopchop.core.tr_marks import QT_TRANSLATE_NOOP
from chopchop.services import file_ops
from chopchop.ui.theme import tokens

ERRORS = {
    file_ops.EMPTY: QT_TRANSLATE_NOOP("RenameDialog", "Имя не может быть пустым"),
    file_ops.INVALID: QT_TRANSLATE_NOOP(
        "RenameDialog",
        "В имени нельзя использовать символы < > : / | ? *, кавычки и обратную косую черту",
    ),
    file_ops.RESERVED: QT_TRANSLATE_NOOP("RenameDialog", "Это имя зарезервировано системой"),
    file_ops.TOO_LONG: QT_TRANSLATE_NOOP("RenameDialog", "Имя слишком длинное"),
    file_ops.EXISTS: QT_TRANSLATE_NOOP("RenameDialog", "Файл с таким именем уже есть"),
    file_ops.UNCHANGED: QT_TRANSLATE_NOOP("RenameDialog", "Имя не изменилось"),
}


class RenameDialog(QDialog):
    """Поле с именем без расширения: расширение остаётся прежним и не выделяется."""

    def __init__(self, path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Переименовать"))
        self._path = path
        self._edit = QLineEdit(path.stem)
        self._edit.setAccessibleName(self.tr("Новое имя"))
        self._edit.textChanged.connect(self._validate)
        suffix = QLabel(path.suffix)
        suffix.setProperty("muted", True)
        self._error = QLabel()
        self._error.setProperty("error", True)
        self._error.setWordWrap(True)
        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        row = QHBoxLayout()
        row.addWidget(self._edit, 1)
        row.addWidget(suffix)
        layout = QVBoxLayout(self)
        layout.setSpacing(tokens.SPACE_2)
        layout.addWidget(QLabel(self.tr("Новое имя файла")))
        layout.addLayout(row)
        layout.addWidget(self._error)
        layout.addWidget(self._buttons)
        self.setMinimumWidth(420)
        self._validate()
        self._edit.setFocus()
        self._edit.selectAll()  # выделено только имя: расширения в поле нет

    def new_stem(self) -> str:
        return self._edit.text().strip()

    def error_code(self) -> str | None:
        return file_ops.validate_name(self._edit.text(), self._path)

    def _validate(self) -> None:
        code = self.error_code()
        self._error.setText(self.tr(ERRORS[code]) if code else "")
        self._error.setVisible(code is not None and code != file_ops.UNCHANGED)
        ok = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(code is None)


class PropertiesDialog(QDialog):
    """Имя, путь, размер, дата и всё, что известно о файле; для фото — про метаданные."""

    cleanRequested = Signal()

    def __init__(
        self,
        rows: list[tuple[str, str]],
        metadata: str | None = None,
        can_clean: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Свойства"))
        self.rows = rows
        form = QFormLayout()
        form.setSpacing(tokens.SPACE_2)
        for label, value in rows:
            shown = QLabel(value)
            shown.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            shown.setWordWrap(True)
            caption = QLabel(label)
            caption.setProperty("muted", True)
            form.addRow(caption, shown)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        self.metadata_label = QLabel(metadata or "")
        self.metadata_label.setWordWrap(True)
        self.metadata_label.setVisible(metadata is not None)
        layout.addWidget(self.metadata_label)
        self.clean_button = QPushButton(self.tr("Очистить и сохранить копию"))
        self.clean_button.setVisible(can_clean)
        self.clean_button.clicked.connect(self.cleanRequested)
        close = QPushButton(self.tr("Закрыть"))
        close.setDefault(True)
        close.clicked.connect(self.accept)
        footer = QHBoxLayout()
        footer.addWidget(self.clean_button)
        footer.addStretch(1)
        footer.addWidget(close)
        layout.addLayout(footer)
        self.setMinimumWidth(460)
