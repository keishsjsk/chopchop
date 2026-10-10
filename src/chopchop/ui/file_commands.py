"""Команды над открытым файлом: копирование, «Показать в папке», переименование, удаление.

Общие для меню, клавиш и кнопок. Удаление — только в корзину ОС. Видео перед переименованием
или удалением останавливается: пока плеер держит файл, Windows не даст его тронуть.
"""

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QByteArray, QMimeData, QObject, QUrl
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtWidgets import QMessageBox

from chopchop.core.document import IMAGE_EXTENSIONS
from chopchop.services import file_ops
from chopchop.services.output import unique_path
from chopchop.services.reveal import reveal_in_folder
from chopchop.ui.file_dialogs import PropertiesDialog, RenameDialog
from chopchop.ui.pil_qt import pil_to_qimage
from chopchop.viewer.folder_nav import FolderNav

if TYPE_CHECKING:
    from chopchop.ui.main_window import MainWindow

GNOME_COPIED_FILES = "x-special/gnome-copied-files"


class FileCommands(QObject):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.w = window

    # --- что открыто -------------------------------------------------------------------------

    def is_video(self) -> bool:
        return self.w._on_video_page() and self.w._video_path is not None

    def current_file(self) -> Path | None:
        w = self.w
        if self.is_video():
            return w._video_path
        return w.current_path if w._nav is not None else None

    def _nav(self) -> FolderNav | None:
        return self.w._video_nav if self.is_video() else self.w._nav

    def notify(
        self,
        text: str,
        kind: str = "info",
        action_text: str | None = None,
        action: Callable[[], None] | None = None,
    ) -> None:
        self.w.toast.show_message(text, kind, action_text, action)

    # --- буфер обмена ------------------------------------------------------------------------

    def copy_path(self) -> None:
        path = self.current_file()
        if path is None:
            return
        QGuiApplication.clipboard().setText(str(path))
        self.notify(self.tr("Путь скопирован"))

    def copy_file(self) -> None:
        """Файл в буфер как файл: его можно вставить в проводник или в письмо."""
        path = self.current_file()
        if path is None:
            return
        data = QMimeData()
        url = QUrl.fromLocalFile(str(path))
        data.setUrls([url])
        payload = "copy\n" + url.toString()  # так просит буфер GNOME и родственные
        data.setData(GNOME_COPIED_FILES, QByteArray(payload.encode("utf-8")))
        QGuiApplication.clipboard().setMimeData(data)
        self.notify(self.tr("Файл скопирован в буфер"))

    def copy_image(self) -> None:
        path = self.current_file()
        if path is None:
            return
        image = self.w._cache.get(path) if not self.is_video() else None
        if image is None:
            self.notify(self.tr("Изображение ещё не загружено"), "error")
            return
        QGuiApplication.clipboard().setImage(image)
        self.notify(self.tr("Изображение скопировано"))

    # --- папка -------------------------------------------------------------------------------

    def reveal(self) -> None:
        path = self.current_file()
        if path is not None:
            reveal_in_folder(path)

    # --- копия без метаданных ----------------------------------------------------------------

    def clean_copy(self) -> None:
        """Быстро: фото без метаданных (EXIF, GPS) рядом с исходником, без редактора."""
        path = self.current_file()
        if path is None or self.is_video():
            return
        app = self.w._app
        folder = app.get_str("editor.output_dir")
        template = app.get_str("editor.output_template")
        quality = {"jpeg": app.get_int("editor.jpeg_quality")}
        quality["webp"] = app.get_int("editor.webp_quality")

        def work() -> Path:
            from chopchop.engines.image_engine import (
                default_output_path,
                format_for_source,
                open_image,
                save_image,
            )

            fmt = format_for_source(path)
            image, _exif = open_image(path)
            dest = default_output_path(path, fmt, Path(folder) if folder else None, template)
            return save_image(
                image, dest, fmt, quality.get(fmt, 92), exif=None, keep_metadata=False
            )

        self.notify(self.tr("Сохраняю копию без метаданных…"))
        self.w._tasks.run(work, self._clean_done, self._clean_failed)

    def _clean_done(self, dest: Path) -> None:
        self.notify(
            self.tr("Сохранено: ") + dest.name,
            "success",
            self.tr("Показать в папке"),
            lambda: reveal_in_folder(dest),
        )

    def _clean_failed(self, error: str) -> None:
        self.notify(self.tr("Не удалось сохранить копию: ") + error, "error")

    # --- удаление ----------------------------------------------------------------------------

    def delete(self) -> None:
        """Файл в корзину (не безвозвратно), затем следующий файл папки или стартовый экран."""
        path = self.current_file()
        if path is None:
            return
        w = self.w
        if w._app.get_bool("general.confirm_delete"):
            answer = QMessageBox.question(
                w,
                self.tr("Удалить"),
                self.tr("Переместить в корзину файл «{0}»?").format(path.name),
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        was_video = self.is_video()
        nav = self._nav()
        if was_video:
            w._save_resume()
            w._stop_video()  # плеер держит файл
        try:
            file_ops.move_to_trash(path)
        except file_ops.TrashError as error:
            QMessageBox.warning(
                w,
                self.tr("Удалить"),
                self.tr("Не удалось переместить в корзину, файл не тронут: {0}").format(error),
            )
            if was_video:
                w._open_video(path)
            return
        w._cache.discard(path)
        w._resume.forget(path)
        w._recent.remove(path)
        w._drop_zone.set_recent(w._recent.items())
        following = nav.remove(path) if nav is not None else None
        if following is not None and following.exists():
            w.open_file(following)
        else:
            w.show_start()

    # --- переименование ----------------------------------------------------------------------

    def rename(self) -> None:
        path = self.current_file()
        if path is None:
            return
        w = self.w
        dialog = RenameDialog(path, w)
        if not dialog.exec():
            return
        was_video = self.is_video()
        if was_video:
            w._save_resume()
            w._stop_video()
        try:
            new = file_ops.rename_path(path, dialog.new_stem())
        except (OSError, ValueError) as error:
            QMessageBox.warning(
                w, self.tr("Переименовать"), self.tr("Не удалось переименовать: {0}").format(error)
            )
            if was_video:
                w._open_video(path)
            return
        w._resume.rename(path, new)
        w._recent.replace(path, new)
        w._drop_zone.set_recent(w._recent.items())
        w._cache.discard(path)
        nav = self._nav()
        if nav is not None:
            nav.rename(path, new)
        w.current_path = new
        if was_video:
            w._open_video(new)  # позиция и дорожки вернутся из запомненного под новым именем
        else:
            w._show(new)
        self.notify(self.tr("Переименовано: ") + new.name)

    # --- свойства ----------------------------------------------------------------------------

    def property_rows(self, path: Path) -> list[tuple[str, str]]:
        facts = file_ops.file_facts(path)
        rows = [
            (self.tr("Имя"), facts.name),
            (self.tr("Путь"), facts.folder),
            (self.tr("Размер"), file_ops.human_size(facts.size_bytes)),
            (self.tr("Изменён"), facts.modified),
        ]
        if self.is_video():
            rows += self._video_rows(path)
        elif path.suffix.lower() in IMAGE_EXTENSIONS:
            size = file_ops.photo_size(path)
            if size is not None:
                rows.append((self.tr("Разрешение"), f"{size[0]}×{size[1]}"))
        return rows

    def _video_rows(self, path: Path) -> list[tuple[str, str]]:
        from chopchop.engines.probe import ProbeError, probe
        from chopchop.ui.player_controls import format_time

        rows: list[tuple[str, str]] = []
        try:
            info = probe(path)
        except ProbeError:
            return rows
        rows += [
            (self.tr("Разрешение"), f"{info.width}×{info.height}"),
            (self.tr("Длительность"), format_time(round(info.duration))),
            (self.tr("Видеокодек"), info.video_codec),
            (self.tr("Частота кадров"), f"{info.fps:g}"),
        ]
        player = self.w.video_page.player if self.w.video_page is not None else None
        tracks = player.tracks() if player is not None else []
        audio = [t.label for t in tracks if t.kind == "audio"]
        subs = [t.label for t in tracks if t.kind == "sub"]
        rows.append((self.tr("Аудиодорожки"), "; ".join(audio) or self.tr("нет")))
        rows.append((self.tr("Субтитры"), "; ".join(subs) or self.tr("нет")))
        return rows

    def metadata_text(self, path: Path) -> str | None:
        """Для фото: есть ли EXIF и GPS; для остального None (строка не показывается)."""
        if self.is_video() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            return None
        flags = file_ops.photo_metadata(path)
        if not flags.any:
            return self.tr("Метаданных (EXIF, GPS) в файле нет")
        parts = []
        if flags.has_exif:
            parts.append("EXIF")
        if flags.has_gps:
            parts.append(self.tr("GPS (место съёмки)"))
        return self.tr("В файле есть метаданные: ") + ", ".join(parts)

    def properties(self) -> None:
        path = self.current_file()
        if path is None:
            return
        metadata = self.metadata_text(path)
        flags = None if metadata is None else file_ops.photo_metadata(path)
        dialog = PropertiesDialog(
            self.property_rows(path),
            metadata,
            can_clean=flags is not None,
            parent=self.w,
        )
        dialog.cleanRequested.connect(self.clean_copy)
        dialog.exec()

    # --- видео: повтор и снимок кадра --------------------------------------------------------

    def toggle_loop(self) -> None:
        page = self.w.video_page
        if page is not None:
            page.player.set_looping(not page.player.looping)

    def screenshot_image(self) -> QImage | None:
        page = self.w.video_page
        if page is None:
            return None
        with_subtitles = self.w._app.get_bool("general.screenshot_subtitles")
        shot = page.player.screenshot(with_subtitles)
        return pil_to_qimage(shot) if shot is not None else None

    def screenshot_copy(self) -> None:
        image = self.screenshot_image()
        if image is None:
            self.notify(self.tr("Не удалось получить кадр"), "error")
            return
        QGuiApplication.clipboard().setImage(image)
        self.notify(self.tr("Кадр скопирован"))

    def screenshot_save(self) -> None:
        path = self.current_file()
        image = self.screenshot_image()
        if path is None or image is None:
            self.notify(self.tr("Не удалось получить кадр"), "error")
            return
        folder = self.w._app.get_str("editor.output_dir")
        position = self.w.video_page.player.position if self.w.video_page is not None else 0.0
        label = f"{int(position // 60)}-{int(position % 60):02d}"
        dest = unique_path(
            Path(folder) if folder else path.parent, f"{path.stem}_кадр_{label}", ".png"
        )
        saved = image.save(str(dest), "PNG")  # type: ignore[call-overload]
        if saved:
            self.notify(
                self.tr("Кадр сохранён: ") + dest.name,
                "success",
                self.tr("Показать в папке"),
                lambda: reveal_in_folder(dest),
            )
        else:
            self.notify(self.tr("Не удалось сохранить кадр"), "error")
