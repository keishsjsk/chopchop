"""Страница редактора видео: превью, полоса обрезки, клипы, звук, экспорт."""

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from chopchop.core.document import MediaInfo
from chopchop.core.operations import Adjust, FilterName
from chopchop.core.tr_marks import QT_TRANSLATE_NOOP
from chopchop.core.video import Clip, VideoEffects, incompatibility
from chopchop.editor.video_session import VideoSession
from chopchop.engines.encoders import available_hw_encoders
from chopchop.engines.fonts import find_font_path
from chopchop.engines.probe import probe
from chopchop.engines.video_engine import (
    EncodeOptions,
    ExportPlanError,
    build_plan,
    pick_encoder,
    write_text_files,
)
from chopchop.engines.video_filters import build_effects_graph, output_frame_size
from chopchop.services.app_settings import AppSettings
from chopchop.services.reveal import reveal_in_folder
from chopchop.services.temp_files import new_workspace, remove_workspace
from chopchop.ui.click_slider import ClickSlider
from chopchop.ui.export_strip import ExportStrip
from chopchop.ui.player_controls import format_time
from chopchop.ui.toast import Toast
from chopchop.ui.trim_bar import TrimBar, format_precise
from chopchop.ui.video_effects_panel import VideoEffectsPanel
from chopchop.ui.video_export_dialog import VideoExportDialog
from chopchop.ui.video_overlay import VideoOverlay
from chopchop.ui.video_page import VideoPage
from chopchop.workers.export_worker import ExportWorker
from chopchop.workers.tasks import TaskRunner
from chopchop.workers.thumbs_worker import ThumbnailLoader

THUMBNAILS = 14
VOLUME_COMMIT_MS = 350
AUDIO_FILTER = "*.mp3 *.wav *.m4a *.aac *.flac *.ogg *.opus"
VIDEO_FILTER = "*.mp4 *.mkv *.avi *.mov *.webm *.m4v *.mpg *.mpeg *.ts"

_REASONS = {
    "codec": QT_TRANSLATE_NOOP("VideoEditorPage", "видеокодек"),
    "resolution": QT_TRANSLATE_NOOP("VideoEditorPage", "разрешение или поворот"),
    "fps": QT_TRANSLATE_NOOP("VideoEditorPage", "частота кадров"),
    "pixel format": QT_TRANSLATE_NOOP("VideoEditorPage", "формат пикселей"),
    "audio": QT_TRANSLATE_NOOP("VideoEditorPage", "параметры звука"),
}


class VideoEditorPage(QWidget):
    exitRequested = Signal()
    message = Signal(str)

    def __init__(
        self,
        session: VideoSession,
        video_page: VideoPage,
        ffmpeg: Path,
        ffprobe: Path,
        parent: QWidget | None = None,
        settings: AppSettings | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self._app = settings or AppSettings(None)
        self._export_args: tuple[Path, bool, EncodeOptions] | None = None
        self._video_page = video_page
        self._ffmpeg = ffmpeg
        self._ffprobe = ffprobe
        self._index = 0
        self.loaded_path: Path | None = None
        self._export_dir: Path | None = None
        self._progress: ExportStrip | None = None  # полоса экспорта, пока он идёт
        self._workspace = new_workspace()  # файлы текста для предпросмотра эффектов
        self._preview_key: str | None = None

        self._thumbs = ThumbnailLoader(
            ffmpeg, self, limit_bytes=self._app.get_int("advanced.thumb_cache_mb") * 1024 * 1024
        )
        self._thumbs.thumbnail.connect(self._on_thumbnail)
        self._tasks = TaskRunner(self)
        self._worker = ExportWorker(self)
        self._worker.progress.connect(self._on_export_progress)
        self._worker.finished.connect(self._on_export_finished)
        self._worker.failed.connect(self._on_export_failed)
        self._worker.cancelled.connect(self._on_export_cancelled)
        self._volume_timer = QTimer(self)
        self._volume_timer.setSingleShot(True)
        self._volume_timer.setInterval(VOLUME_COMMIT_MS)
        self._volume_timer.timeout.connect(self._commit_volume)

        self._build_ui()

        player = video_page.player
        player.positionChanged.connect(self.trim.set_position)
        player.fileLoaded.connect(self._on_file_loaded)
        session.changed.connect(self._on_session_changed)
        self._load_current_clip()
        self._refresh()

    # --- интерфейс ---------------------------------------------------------------------------

    def _build_ui(self) -> None:
        back = QPushButton(self.tr("← К просмотру"))
        back.clicked.connect(self.request_exit)
        self._undo_button = QPushButton(self.tr("Отменить"))
        self._undo_button.clicked.connect(self.undo)
        self._redo_button = QPushButton(self.tr("Повторить"))
        self._redo_button.clicked.connect(self.redo)
        export = QPushButton(self.tr("Экспорт…"))
        export.clicked.connect(self.export)
        self._summary = QLabel()

        top = QHBoxLayout()
        for widget in (back, self._undo_button, self._redo_button, export):
            top.addWidget(widget)
        top.addStretch(1)
        top.addWidget(self._summary)

        self.trim = TrimBar()
        self.trim.seekRequested.connect(self._video_page.player.seek_to)  # по ключевым кадрам
        self.trim.seekFinished.connect(lambda s: self._video_page.player.seek_to(s, exact=True))
        self.trim.trimming.connect(self._on_trimming)
        self.trim.trimCommitted.connect(self._on_trim_committed)
        set_in = QPushButton(self.tr("Начало здесь [I]"))
        set_in.clicked.connect(self.set_in)
        set_out = QPushButton(self.tr("Конец здесь [O]"))
        set_out.clicked.connect(self.set_out)
        reset = QPushButton(self.tr("Сбросить обрезку"))
        reset.clicked.connect(self._reset_trim)
        self._trim_label = QLabel()
        trim_row = QHBoxLayout()
        for widget in (set_in, set_out, reset):
            trim_row.addWidget(widget)
        trim_row.addStretch(1)
        trim_row.addWidget(self._trim_label)

        self._clips = QListWidget()
        self._clips.setFlow(QListWidget.Flow.LeftToRight)
        self._clips.setWrapping(False)
        self._clips.setFixedHeight(64)
        self._clips.currentRowChanged.connect(self._on_row_changed)
        add = QPushButton(self.tr("Добавить клип…"))
        add.clicked.connect(self.add_clip)
        remove = QPushButton(self.tr("Удалить"))
        remove.clicked.connect(self._remove_clip)
        left = QPushButton("←")
        left.setToolTip(self.tr("Сдвинуть клип раньше"))
        left.clicked.connect(lambda: self._move_clip(-1))
        right = QPushButton("→")
        right.setToolTip(self.tr("Сдвинуть клип позже"))
        right.clicked.connect(lambda: self._move_clip(1))
        clip_buttons = QVBoxLayout()
        row = QHBoxLayout()
        row.addWidget(left)
        row.addWidget(right)
        clip_buttons.addWidget(add)
        clip_buttons.addWidget(remove)
        clip_buttons.addLayout(row)
        clips_row = QHBoxLayout()
        clips_row.addWidget(self._clips, 1)
        clips_row.addLayout(clip_buttons)

        self._volume = ClickSlider(Qt.Orientation.Horizontal)
        self._volume.setRange(0, 200)
        self._volume.setValue(100)
        self._volume.setFixedWidth(180)
        self._volume.valueChanged.connect(self._on_volume_changed)
        self._volume_label = QLabel("100%")
        self._mute = QCheckBox(self.tr("Убрать звук"))
        self._mute.toggled.connect(self.session.set_mute)
        replace = QPushButton(self.tr("Заменить звук…"))
        replace.clicked.connect(self._choose_replacement)
        self._original_audio = QPushButton(self.tr("Исходный звук"))
        self._original_audio.clicked.connect(lambda: self.session.set_replacement(None))
        self._audio_note = QLabel()
        audio_row = QHBoxLayout()
        audio_row.addWidget(QLabel(self.tr("Громкость")))
        audio_row.addWidget(self._volume)
        audio_row.addWidget(self._volume_label)
        audio_row.addWidget(self._mute)
        audio_row.addWidget(replace)
        audio_row.addWidget(self._original_audio)
        audio_row.addWidget(self._audio_note)
        audio_row.addStretch(1)

        self._overlay = VideoOverlay(self._video_page, self.session.project.frame_size)
        self._video_page.controls.raise_()  # панель плеера остаётся над слоем и кликабельна
        self.effects_panel = VideoEffectsPanel(self.session, self._overlay)
        self.effects_panel.message.connect(self.message)
        self.effects_panel.colorPreview.connect(self._on_color_preview)
        self.effects_panel.colorPreviewEnded.connect(self._on_color_preview_ended)

        self.export_strip = ExportStrip()
        self.export_strip.cancelRequested.connect(self._cancel_export)
        self._video_layout = QVBoxLayout(self)
        self._video_layout.addLayout(top)
        self._video_layout.addWidget(self.export_strip)
        self._video_layout.addWidget(self._video_page, 1)
        self._video_page.show()  # removeWidget в главном окне скрыл плеер
        self._video_page.set_editor_mode(True)
        self.toast = Toast(self)
        self._video_layout.addWidget(self.trim)
        self._video_layout.addLayout(trim_row)
        self._video_layout.addWidget(self.effects_panel)
        self._video_layout.addLayout(clips_row)
        self._video_layout.addLayout(audio_row)

    def release_video_page(self) -> VideoPage:
        """Возвращает плеер владельцу (главному окну) при выходе из редактора."""
        player = self._video_page.player
        for signal, slot in (
            (player.positionChanged, self.trim.set_position),
            (player.fileLoaded, self._on_file_loaded),
        ):
            signal.disconnect(slot)
        player.set_video_filter(None)
        self._overlay.setParent(None)
        self._overlay.deleteLater()
        self._video_layout.removeWidget(self._video_page)
        self._video_page.setParent(None)
        return self._video_page

    def shutdown(self) -> None:
        """Остановить фоновые задачи перед закрытием окна."""
        self._worker.cancel()
        self._worker.wait()
        self._thumbs.wait()
        self._tasks.wait()
        remove_workspace(self._workspace)

    # --- текущий клип ------------------------------------------------------------------------

    @property
    def clip(self) -> Clip:
        return self.session.project.clips[self._index]

    def _on_row_changed(self, row: int) -> None:
        if row < 0 or row == self._index and self.loaded_path == self.clip.path:
            return
        self._index = row
        self._load_current_clip()
        self._refresh_trim()

    def _load_current_clip(self) -> None:
        clip = self.clip
        self.loaded_path = clip.path
        self._video_page.player.load(clip.path)
        self._thumbs_for(clip)

    def _thumbs_for(self, clip: Clip) -> None:
        thumbs = self._thumbs.request(clip.path, clip.info.duration, THUMBNAILS)
        self.trim.set_clip(clip.info.duration, clip.start, clip.stop, thumbs)

    def _on_thumbnail(self, path: str, index: int, image: QImage) -> None:
        if path == str(self.clip.path):
            self.trim.set_thumbnail(index, image)

    def _on_file_loaded(self) -> None:
        """Файл открылся: ставим на паузу в точке начала и зацикливаем выбранный фрагмент."""
        player = self._video_page.player
        if not player.paused:
            player.toggle_pause()
        self._apply_loop()
        player.seek_to(self.clip.start, exact=True)

    def _apply_loop(self) -> None:
        clip = self.clip
        self._video_page.player.set_loop(clip.start, clip.stop)

    # --- обрезка -----------------------------------------------------------------------------

    def _on_trimming(self, start: float, end: float) -> None:
        self._trim_label.setText(self._trim_text(start, end))

    def _on_trim_committed(self, start: float, end: float) -> None:
        self.session.set_trim(self._index, start, end)

    def set_in(self) -> None:
        self.session.set_trim(self._index, self._video_page.player.position, self.clip.stop)

    def set_out(self) -> None:
        self.session.set_trim(self._index, self.clip.start, self._video_page.player.position)

    def _reset_trim(self) -> None:
        self.session.set_trim(self._index, 0.0, self.clip.info.duration)

    def _trim_text(self, start: float, end: float) -> str:
        return self.tr("Фрагмент: {0} – {1}, длина {2}").format(
            format_precise(start), format_precise(end), format_precise(end - start)
        )

    # --- клипы -------------------------------------------------------------------------------

    def add_clip(self) -> None:
        name, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Добавить клип"),
            str(self.clip.path.parent),
            self.tr("Видео (%1)").replace("%1", VIDEO_FILTER),
        )
        if not name:
            return
        path = Path(name)
        self.message.emit(self.tr("Анализ видео…"))
        self._tasks.run(
            lambda: probe(path, self._ffprobe),
            lambda info: self._on_clip_probed(path, info),
            lambda error: self.message.emit(self.tr("Не удалось прочитать видео: ") + error),
        )

    def _on_clip_probed(self, path: Path, info: MediaInfo) -> None:
        reason = incompatibility(self.session.project.clips[0].info, info)
        self.session.add_clip(Clip(path, info))
        self._clips.setCurrentRow(len(self.session.project.clips) - 1)
        if reason is None:
            self.message.emit(self.tr("Клип добавлен: ") + path.name)
        else:
            self.message.emit(
                self.tr(
                    "Клип добавлен. Отличается: {0}, при экспорте видео будет перекодировано"
                ).format(self.tr(_REASONS.get(reason, reason)))
            )

    def _remove_clip(self) -> None:
        if len(self.session.project.clips) <= 1:
            self.message.emit(self.tr("Последний клип удалить нельзя"))
            return
        self.session.remove_clip(self._index)

    def _move_clip(self, delta: int) -> None:
        target = self._index + delta
        if 0 <= target < len(self.session.project.clips):
            source = self._index
            self._index = target  # выбор следует за клипом
            self.session.move_clip(source, delta)

    # --- звук --------------------------------------------------------------------------------

    def _on_volume_changed(self, value: int) -> None:
        self._volume_label.setText(f"{value}%")
        self._volume_timer.start()  # в историю попадает только итоговое значение

    def _commit_volume(self) -> None:
        self.session.set_volume(self._volume.value() / 100)

    def _choose_replacement(self) -> None:
        name, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Заменить звук"),
            "",
            self.tr("Аудио (%1)").replace("%1", AUDIO_FILTER),
        )
        if name:
            self.session.set_replacement(Path(name))

    # --- обновление --------------------------------------------------------------------------

    def _on_session_changed(self) -> None:
        clips = self.session.project.clips
        self._index = min(self._index, len(clips) - 1)
        if self.clip.path != self.loaded_path:
            self._load_current_clip()
        self._refresh()

    def _refresh(self) -> None:
        project = self.session.project
        clips = project.clips
        blocker = QSignalBlocker(self._clips)
        self._clips.clear()
        for number, clip in enumerate(clips, start=1):
            span = f"{format_time(round(clip.start))}–{format_time(round(clip.stop))}"
            text = f"{number}. {clip.path.name}\n{span}"
            item = QListWidgetItem(text)
            item.setToolTip(str(clip.path))
            self._clips.addItem(item)
        self._clips.setCurrentRow(self._index)
        blocker.unblock()

        self._undo_button.setEnabled(self.session.can_undo)
        self._redo_button.setEnabled(self.session.can_redo)
        marker = " *" if self.session.modified else ""
        width, height = output_frame_size(project.effects, project.frame_size)
        self._summary.setText(
            self.tr("Итог: {0}, {1}×{2}, клипов: {3}").format(
                format_time(project.duration), width, height, len(clips)
            )
            + marker
        )

        audio = project.audio
        with QSignalBlocker(self._volume):
            self._volume.setValue(round(audio.volume * 100))
        self._volume_label.setText(f"{round(audio.volume * 100)}%")
        with QSignalBlocker(self._mute):
            self._mute.setChecked(audio.mute)
        self._original_audio.setEnabled(audio.replacement is not None)
        self._audio_note.setText(
            self.tr("Звук: ") + audio.replacement.name if audio.replacement else ""
        )
        self._refresh_trim()
        self._apply_loop()
        self.effects_panel.refresh()
        self._apply_preview()

    def _refresh_trim(self) -> None:
        clip = self.clip
        self.trim.set_range(clip.start, clip.stop)
        self._trim_label.setText(self._trim_text(clip.start, clip.stop))

    # --- предпросмотр эффектов в mpv ---------------------------------------------------------

    def _preview_graph(self, effects: VideoEffects) -> str | None:
        """Тот же граф, что и при экспорте, но без кадра и поворота (их показывает слой)."""
        files = write_text_files(effects.texts, self._workspace)
        graph = build_effects_graph(
            effects,
            self.session.project.frame_size,
            files,
            find_font_path(),
            geometry=False,
            in_label="vid1",
            out_label="vo",
        )
        return None if graph == "[vid1]null[vo]" else graph

    def _apply_preview(self, effects: VideoEffects | None = None) -> None:
        graph = self._preview_graph(effects or self.session.project.effects)
        if graph == self._preview_key:
            return
        if self._video_page.player.set_video_filter(graph):
            self._preview_key = graph
        else:
            self.message.emit(self.tr("Предпросмотр эффектов недоступен, но экспорт сработает"))

    def _on_color_preview(self, adjust: Adjust, filter_name: FilterName | None) -> None:
        current = self.session.project.effects
        self._apply_preview(replace(current, adjust=adjust, filter=filter_name))

    def _on_color_preview_ended(self) -> None:
        self._apply_preview()

    # --- отмена и повтор (общие имена с редактором фото) -------------------------------------

    def undo(self) -> None:
        self.session.undo()

    def redo(self) -> None:
        self.session.redo()

    def apply_pending(self) -> None:
        self.effects_panel.apply_pending()

    def select_tool(self, name: str) -> None:
        self.effects_panel.select_tool(name)

    def copy_result(self) -> None:
        self.message.emit(self.tr("Копирование в буфер доступно только для фото"))

    def save_quick(self) -> None:
        self.export()

    def save_as(self) -> None:
        self.export()

    def escape(self) -> None:
        if not self.effects_panel.escape():
            self.request_exit()

    # --- экспорт -----------------------------------------------------------------------------

    def export(self) -> None:
        if self._export_dir is not None:
            return  # предыдущий экспорт ещё идёт
        dialog = VideoExportDialog(self.session.project, self, self._app)
        if not dialog.exec():
            return
        self._start_export(dialog.path(), dialog.precise(), self._encode_options())

    def _encode_options(self) -> EncodeOptions:
        """Качество, скорость и кодер из настроек; аппаратный кодер — только если он есть."""
        app = self._app
        return EncodeOptions(
            crf=app.get_int("editor.x264_crf"),
            preset=app.get_str("editor.x264_preset"),
            encoder=pick_encoder(
                app.get_str("editor.hw_encoder"), available_hw_encoders(self._ffmpeg)
            ),
            threads=app.get_int("advanced.threads"),
        )

    def _start_export(self, dest: Path, precise: bool, encode: EncodeOptions) -> None:
        self._export_args = (dest, precise, encode)
        workdir = new_workspace()
        try:
            plan = build_plan(
                self.session.project,
                dest,
                self._ffmpeg,
                workdir,
                precise=precise,
                font=find_font_path(),
                encode=encode,
            )
        except ExportPlanError as error:
            remove_workspace(workdir)
            self.toast.show_message(self.tr("Экспорт невозможен: ") + str(error), "error")
            return
        self._export_dir = workdir
        self.export_strip.start(self.tr("Экспорт…"))
        self._progress = self.export_strip
        self._worker.start(plan, workdir)

    def _cancel_export(self) -> None:
        self.export_strip.cancelling()
        self._worker.cancel()

    def _close_progress(self) -> None:
        self.export_strip.finish()
        self._progress = None
        self._export_dir = None

    def _on_export_progress(self, fraction: float) -> None:
        if self._progress is not None:
            self._progress.set_fraction(fraction)

    def _on_export_finished(self, path: Path) -> None:
        self._close_progress()
        self.session.mark_saved()
        self.message.emit(self.tr("Сохранено: ") + str(path))
        self.toast.show_message(
            self.tr("Сохранено: ") + path.name,
            "success",
            self.tr("Показать в папке"),
            lambda: reveal_in_folder(path),
        )

    def _on_export_failed(self, error: str) -> None:
        self._close_progress()
        args = self._export_args
        if (
            args is not None
            and args[2].is_hardware
            and self.session.project.reencode_reason(args[1])
        ):
            # видеокарта не справилась (нет драйвера, формат не поддержан): повторяем на процессоре
            self.message.emit(
                self.tr("Аппаратный кодер не сработал, экспорт повторён на процессоре")
            )
            self._start_export(args[0], args[1], args[2].on_cpu())
            return
        self.message.emit(self.tr("Ошибка экспорта") + ": " + error)
        self.toast.show_message(self.tr("Ошибка экспорта") + ": " + error, "error")

    def _on_export_cancelled(self) -> None:
        self._close_progress()
        self.message.emit(self.tr("Экспорт отменён"))
        self.toast.show_message(self.tr("Экспорт отменён"), "info")

    # --- выход -------------------------------------------------------------------------------

    def request_exit(self) -> None:
        if self._export_dir is not None:
            return
        if self.session.modified:
            answer = QMessageBox.question(
                self,
                self.tr("Несохранённые правки"),
                self.tr("Выйти из редактора без экспорта? Изменения будут потеряны."),
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.exitRequested.emit()
