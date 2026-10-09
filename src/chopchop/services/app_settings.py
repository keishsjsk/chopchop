"""Настройки приложения: читаемый TOML в папке настроек ОС, запись атомарно, сигналы об изменениях.

Файл не исполняет код. Битый файл не ломает запуск: рядом остаётся его копия, программа
стартует со значениями по умолчанию и сообщает об этом (сигнал `notice`).
"""

import contextlib
import os
import time
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject, QSettings, QStandardPaths, QTimer, Signal

from chopchop.core import settings as core
from chopchop.core import settings_schema as schema
from chopchop.core.settings import SettingsFileError, Value

CONFIG_ENV = "CHOPCHOP_CONFIG_DIR"
FILE_NAME = "settings.toml"
SAVE_DELAY_MS = 400  # частые изменения (ползунок) пишутся одним разом
MAX_FILE_BYTES = 256 * 1024  # настройки — несколько килобайт; больше значит, что это не наш файл

# значения воспроизведения -> режим декодирования mpv
HWDEC_FOR_MPV = {"auto": "auto-copy-safe", "off": "no"}


def config_dir() -> Path:
    override = os.environ.get(CONFIG_ENV)
    if override:
        return Path(override)
    location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
    return Path(location or Path.home() / ".config" / "chopchop")


def default_settings_path() -> Path:
    return config_dir() / FILE_NAME


class AppSettings(QObject):
    changed = Signal(str, object)  # ключ, новое значение
    reloaded = Signal()  # сразу много значений: сброс или импорт
    notice = Signal(str)  # сообщение пользователю (например, о битом файле)

    def __init__(self, path: Path | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._path = path
        self._values: dict[str, Value] = schema.defaults()
        self._extra: dict[str, dict[str, Value]] = {}
        self.first_run = True
        self.startup_notices: list[str] = []  # сообщения, возникшие до подключения окна
        self.restart_pending: set[str] = set()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(SAVE_DELAY_MS)
        self._timer.timeout.connect(self.flush)
        if path is not None:
            self._load(path)

    @property
    def path(self) -> Path | None:
        return self._path

    # --- чтение и запись значений ------------------------------------------------------------

    def get(self, key: str) -> Value:
        return self._values[core.spec_of(key).key]

    def get_int(self, key: str) -> int:
        return int(str(self.get(key)))

    def get_float(self, key: str) -> float:
        return float(str(self.get(key)))

    def get_bool(self, key: str) -> bool:
        return bool(self.get(key))

    def get_str(self, key: str) -> str:
        return f"{self.get(key)}"

    def set(self, key: str, value: Value) -> bool:
        """Меняет настройку; возвращает False, если значение осталось прежним."""
        spec = core.spec_of(key)
        clean = schema.coerce(spec, value)  # ValueError для недопустимого значения
        if clean == self._values[key]:
            return False
        self._values[key] = clean
        if spec.apply == "restart":
            self.restart_pending.add(key)
        self.changed.emit(key, clean)
        self._schedule_save()
        return True

    def is_default(self, key: str) -> bool:
        return self._values[key] == core.spec_of(key).default

    def reset(self, key: str) -> None:
        self.set(key, core.spec_of(key).default)

    def reset_section(self, section: str) -> None:
        for spec in schema.specs_of(section):
            self.reset(spec.key)

    def reset_all(self) -> None:
        for spec in schema.SPECS:
            if spec.section != "state":
                self.reset(spec.key)

    # --- файл --------------------------------------------------------------------------------

    def _load(self, path: Path) -> None:
        if not path.exists():
            return
        self.first_run = False
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                raise SettingsFileError("файл слишком большой")
            result = core.parse(path.read_text(encoding="utf-8"))
        except (SettingsFileError, UnicodeDecodeError, OSError) as error:
            self._keep_broken_copy(path)
            self._notify(
                QCoreApplication.translate(
                    "Settings",
                    "Файл настроек повреждён ({0}). Использованы значения по умолчанию, "
                    "старый файл сохранён рядом.",
                ).format(error)
            )
            return
        self._values, self._extra = result.values, result.extra
        if result.warnings:
            self._notify(
                QCoreApplication.translate(
                    "Settings", "Некоторые настройки в файле недопустимы и заменены: {0}"
                ).format("; ".join(result.warnings))
            )

    def _notify(self, text: str) -> None:
        self.startup_notices.append(text)
        self.notice.emit(text)

    @staticmethod
    def _keep_broken_copy(path: Path) -> None:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        with contextlib.suppress(OSError):
            os.replace(path, path.with_name(f"{path.name}.broken-{stamp}"))

    def _schedule_save(self) -> None:
        if self._path is not None:
            self._timer.start()

    def flush(self) -> None:
        """Записывает файл сейчас (при выходе из программы и по таймеру)."""
        self._timer.stop()
        if self._path is None:
            return
        try:
            self._write(self._path, core.dumps(self._values, self._extra))
        except OSError as error:
            self.notice.emit(
                QCoreApplication.translate(
                    "Settings", "Не удалось сохранить настройки: {0}"
                ).format(error)
            )

    @staticmethod
    def _write(path: Path, text: str) -> None:
        """Атомарно: пишем во временный файл рядом и подменяем; сбой не оставит половину файла."""
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + ".tmp")
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)

    # --- импорт и экспорт --------------------------------------------------------------------

    def export_to(self, path: Path) -> None:
        self._write(path, core.dumps(self._values, self._extra))

    def import_from(self, path: Path) -> list[str]:
        """Загружает настройки из файла; SettingsFileError, если файл негодный (без изменений)."""
        if path.stat().st_size > MAX_FILE_BYTES:
            raise SettingsFileError("файл слишком большой")
        result = core.parse(path.read_text(encoding="utf-8"))
        for key, value in result.values.items():
            if key == "state.window":
                continue  # положение окна не переносится между компьютерами
            self.set(key, value)
        self.reloaded.emit()
        return result.warnings

    def import_legacy(self, old: QSettings) -> None:
        """Переносит настройки плеера из прежнего хранилища (QSettings) при первом запуске."""
        text_keys = {
            "playback.audio_langs": "player/audio_langs",
            "playback.sub_langs": "player/sub_langs",
        }
        for key, old_key in text_keys.items():
            raw = old.value(old_key)
            if raw:
                self.set(key, f"{raw}")
        for key, old_key in (
            ("subtitles.font_size", "player/sub_font_size"),
            ("subtitles.margin", "player/sub_margin"),
        ):
            raw = old.value(old_key)
            if raw is not None:
                with contextlib.suppress(ValueError):
                    self.set(key, int(f"{raw}"))
        if f"{old.value('player/hwdec')}" == "no":
            self.set("playback.hwdec", "off")

    # --- удобные производные значения --------------------------------------------------------

    def mpv_hwdec(self) -> str:
        return HWDEC_FOR_MPV[self.get_str("playback.hwdec")]
