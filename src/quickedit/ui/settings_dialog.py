"""Настройки плеера: предпочитаемые языки и вид субтитров."""

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from quickedit.services.settings import PlayerPrefs, clean_langs


class SettingsDialog(QDialog):
    def __init__(self, prefs: PlayerPrefs, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Настройки"))

        self._audio = QLineEdit(prefs.audio_langs)
        self._audio.setPlaceholderText("rus,eng")
        self._subs = QLineEdit(prefs.sub_langs)
        self._subs.setPlaceholderText("rus,eng")
        self._font = QSpinBox()
        self._font.setRange(10, 150)
        self._font.setValue(prefs.sub_font_size)
        self._margin = QSpinBox()
        self._margin.setRange(0, 300)
        self._margin.setValue(prefs.sub_margin)

        form = QFormLayout()
        form.addRow(self.tr("Языки аудио (коды через запятую)"), self._audio)
        form.addRow(self.tr("Языки субтитров"), self._subs)
        form.addRow(self.tr("Размер шрифта субтитров"), self._font)
        form.addRow(self.tr("Отступ субтитров снизу"), self._margin)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def prefs(self) -> PlayerPrefs:
        return PlayerPrefs(
            audio_langs=clean_langs(self._audio.text()),
            sub_langs=clean_langs(self._subs.text()),
            sub_font_size=self._font.value(),
            sub_margin=self._margin.value(),
        )
