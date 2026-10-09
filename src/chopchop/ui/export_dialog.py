"""Диалог «Сохранить как»: формат, качество, метаданные и путь."""

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from chopchop.engines.image_engine import FORMATS, default_output_path
from chopchop.services.app_settings import AppSettings


@dataclass(frozen=True)
class ExportChoice:
    path: Path
    fmt: str
    quality: int
    keep_metadata: bool


class ExportDialog(QDialog):
    def __init__(
        self,
        source: Path | None,
        default_format: str,
        parent: QWidget | None = None,
        settings: AppSettings | None = None,
    ):
        super().__init__(parent)
        self._app = settings or AppSettings(None)
        self.setWindowTitle(self.tr("Сохранить как"))
        self._source = source

        self._format = QComboBox()
        for key in FORMATS:
            self._format.addItem(key.upper(), key)
        self._format.setCurrentIndex(max(self._format.findData(default_format), 0))
        self._format.currentIndexChanged.connect(self._on_format_changed)

        self._quality = QSpinBox()
        self._quality.setRange(1, 100)
        self._quality.setValue(self._quality_default(default_format))

        self._keep = QCheckBox(self.tr("Сохранить метаданные (EXIF, GPS)"))
        self._keep.setChecked(not self._app.get_bool("editor.strip_metadata"))
        self._keep.setToolTip(self.tr("По умолчанию метаданные удаляются"))

        folder = self._app.get_str("editor.output_dir")
        self._path = QLineEdit(
            str(
                default_output_path(
                    source,
                    default_format,
                    Path(folder) if folder else None,
                    self._app.get_str("editor.output_template"),
                )
            )
        )
        browse = QPushButton(self.tr("Обзор…"))
        browse.clicked.connect(self._browse)
        path_row = QHBoxLayout()
        path_row.addWidget(self._path, 1)
        path_row.addWidget(browse)

        form = QFormLayout()
        form.addRow(self.tr("Формат"), self._format)
        form.addRow(self.tr("Качество (JPEG, WebP)"), self._quality)
        form.addRow("", self._keep)
        form.addRow(self.tr("Файл"), path_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self._on_format_changed()
        self.setMinimumWidth(460)

    def _quality_default(self, fmt: str) -> int:
        key = {"jpeg": "editor.jpeg_quality", "webp": "editor.webp_quality"}.get(fmt)
        return self._app.get_int(key) if key else 92

    def _fmt(self) -> str:
        return str(self._format.currentData())

    def _on_format_changed(self) -> None:
        self._quality.setEnabled(self._fmt() != "png")
        self._quality.setValue(self._quality_default(self._fmt()))
        current = Path(self._path.text())
        extension = FORMATS[self._fmt()][0]
        if current.suffix.lower() != extension:
            self._path.setText(str(current.with_suffix(extension)))

    def _browse(self) -> None:
        name, _ = QFileDialog.getSaveFileName(self, self.tr("Сохранить как"), self._path.text())
        if name:
            self._path.setText(name)

    def choice(self) -> ExportChoice:
        return ExportChoice(
            Path(self._path.text()), self._fmt(), self._quality.value(), self._keep.isChecked()
        )
