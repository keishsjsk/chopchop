"""Страница редактора видео на общей оболочке: превью, рейка, транспорт, обрезка, клипы, экспорт.

Сверху вниз: верхняя панель, контекстная панель параметров (только при выбранном инструменте),
рейка и превью, строка транспорта, полоса обрезки, полоса клипов, строка состояния. Никаких
плавающих панелей плеера поверх кадра.
"""

import contextlib
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QResizeEvent, QShowEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from chopchop.core.document import MediaInfo
from chopchop.core.keyframes import junctions, precise_count
from chopchop.core.operations import Adjust, FilterName
from chopchop.core.timing import TimeNote, result_windows_to_source
from chopchop.core.tr_marks import QT_TRANSLATE_NOOP
from chopchop.core.video import (
    Clip,
    EffectEntry,
    RemoveRange,
    RestoreRange,
    SplitAt,
    VideoEffects,
    effect_entries,
    incompatibility,
)
from chopchop.editor.video_session import VideoSession
from chopchop.engines.encoders import available_hw_encoders
from chopchop.engines.fonts import find_font_path
from chopchop.engines.keyframes import read_keyframes
from chopchop.engines.probe import ProbeError, probe
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
from chopchop.ui.audio_panel import AudioPanel
from chopchop.ui.clip_strip import ClipInfo, ClipStrip
from chopchop.ui.editor_shell import EditorShell
from chopchop.ui.effects_chip import EffectsChip
from chopchop.ui.export_strip import ExportStrip
from chopchop.ui.player_controls import format_time
from chopchop.ui.theme import tokens
from chopchop.ui.toast import Toast
from chopchop.ui.trim_bar import TrimBar, range_label
from chopchop.ui.video_effects_panel import IDLE_HINT, RAIL_ITEMS, VideoEffectsPanel
from chopchop.ui.video_export_dialog import VideoExportDialog
from chopchop.ui.video_overlay import VideoOverlay
from chopchop.ui.video_page import VideoPage
from chopchop.ui.widgets import PixelToggle, button, icon_button, refresh_icons, set_icon, tip
from chopchop.workers.export_worker import ExportWorker
from chopchop.workers.tasks import TaskRunner
from chopchop.workers.thumbs_worker import ThumbnailLoader

THUMBNAILS = 14
VIDEO_FILTER = "*.mp4 *.mkv *.avi *.mov *.webm *.m4v *.mpg *.mpeg *.ts"
SKIP_LEAD = 0.03  # прыгать чуть раньше конца оставленного куска
TOOLS_DELAY_MS = 40
COMPACT_HEIGHT = 700  # ниже этого окна полоса клипов сворачивается в одну строку
SECOND_STEP = 1.0  # Shift + стрелки
MIN_PREVIEW_HEIGHT = 160
SAVE_TRIM_HEIGHT_MS = 300

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
        self._sized = False  # высота полосы обрезки из настроек применена
        self._tools_ready = False  # панели эффектов и звука построены
        self._keyframes: dict[Path, tuple[float, ...]] = {}  # ключевые кадры открытых файлов
        self._segment: tuple[float, float] | None = None  # выбранный сегмент (время файла)
        self._skipping_to: float | None = None  # куда уже перепрыгнули в предпросмотре
        self._strip_height = tokens.CLIP_STRIP_H

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
        self._height_timer = QTimer(self)
        self._height_timer.setSingleShot(True)
        self._height_timer.setInterval(SAVE_TRIM_HEIGHT_MS)
        self._height_timer.timeout.connect(self._save_trim_height)

        self._build_ui()

        player = video_page.player
        player.positionChanged.connect(self._on_position)
        player.pausedChanged.connect(self._on_paused)
        player.fileLoaded.connect(self._on_file_loaded)
        session.changed.connect(self._on_session_changed)
        session.timeNotes.connect(self._on_time_notes)
        self._load_current_clip()
        self._refresh()
        self._on_paused(player.paused)
        QTimer.singleShot(TOOLS_DELAY_MS, self._ensure_tools)  # после первого кадра

    # --- интерфейс ---------------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.shell = EditorShell(self)
        shell = self.shell
        self.export_strip = shell.export_strip
        self.export_strip.cancelRequested.connect(self._cancel_export)

        # верхняя панель
        self._back = button(
            self.tr("К просмотру"),
            "ghost",
            icon="back_to_view",
            tooltip=tip(self.tr("Вернуться к просмотру"), "Esc"),
            slot=self.request_exit,
        )
        self._undo_button = icon_button(
            "undo", tip(self.tr("Отменить"), "Ctrl+Z"), self.undo, text=self.tr("Отменить")
        )
        self._redo_button = icon_button(
            "redo", tip(self.tr("Повторить"), "Ctrl+Y"), self.redo, text=self.tr("Повторить")
        )
        self._export_button = button(
            self.tr("Экспорт…"),
            "primary",
            tooltip=tip(self.tr("Экспорт видео"), "Ctrl+S"),
            slot=self.export,
        )
        shell.top.left.addWidget(self._back)
        shell.top.left.addWidget(self._undo_button)
        shell.top.left.addWidget(self._redo_button)
        shell.top.right.addWidget(self._export_button)

        # превью: плеер без плавающих панелей и слой инструментов поверх кадра
        self._video_page.show()  # removeWidget в главном окне скрыл плеер
        self._video_page.set_editor_mode(True)
        self._overlay = VideoOverlay(self._video_page, self.session.project.frame_size)
        self.message.connect(shell.status.flash)

        # рейка инструментов; панели параметров строятся позже (`_ensure_tools`): открытие
        # редактора не должно ждать создания десятков виджетов, которые пока не нужны
        for key, icon, name, hotkey in RAIL_ITEMS:
            shell.rail.add_tool(key, icon, self.tr(name), hotkey)
        shell.rail.toolClicked.connect(self.select_tool)

        # транспорт, полоса обрезки, клипы
        self.transport = self._build_transport()
        self.trim = TrimBar()
        self.trim.seekRequested.connect(self._video_page.player.seek_to)  # по ключевым кадрам
        self.trim.seekFinished.connect(lambda s: self._video_page.player.seek_to(s, exact=True))
        self.trim.trimCommitted.connect(self._on_trim_committed)
        self.trim.trimming.connect(lambda a, b: self._range.setText(range_label(a, b)))
        self.trim.zoomChanged.connect(self._on_zoom_changed)
        self.trim.ghostClicked.connect(self._restore_range)
        self.trim.segmentPicked.connect(self._on_segment_picked)
        self.trim.selectionCleared.connect(self._on_selection_cleared)
        self.trim.rangeMarked.connect(self._on_range_marked)
        self.clip_strip = ClipStrip()
        self.clip_strip.currentChanged.connect(self._on_row_changed)
        self.clip_strip.moveRequested.connect(self._on_move_requested)
        self.clip_strip.removeRequested.connect(self._remove_clip_at)
        self.clip_strip.addRequested.connect(self.add_clip)

        bottom = self._bottom = QWidget()
        column = QVBoxLayout(bottom)
        column.setContentsMargins(tokens.SPACE_3, 0, tokens.SPACE_3, tokens.SPACE_2)
        column.setSpacing(tokens.SPACE_1)
        column.addWidget(self.transport)
        column.addWidget(self.trim, 1)
        column.addWidget(self.clip_strip)
        preview = QWidget()
        holder = QVBoxLayout(preview)
        holder.setContentsMargins(0, 0, 0, 0)
        holder.addWidget(self._video_page)
        preview.setMinimumHeight(MIN_PREVIEW_HEIGHT)
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(preview)
        self.splitter.addWidget(bottom)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.splitterMoved.connect(lambda *_: self._height_timer.start())
        shell.set_content(self.splitter)
        self.clip_strip.installEventFilter(self)

        # строка состояния
        self.effects_chip = EffectsChip()
        self.effects_chip.removeRequested.connect(self._remove_effect)
        self.effects_chip.clearRequested.connect(self.session.clear_effects)
        shell.status.right.addWidget(self.effects_chip)
        shell.status.set_hint(QCoreApplication.translate("VideoEffectsPanel", IDLE_HINT))
        self._summary = shell.status.summary_label

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(shell)
        self.toast = Toast(self)

    def _build_transport(self) -> QWidget:
        self._play = icon_button(
            "play", tip(self.tr("Пауза и воспроизведение"), "Space"), self._toggle_pause
        )
        self._step_back = icon_button(
            "step_back", tip(self.tr("Кадр назад"), "←"), lambda: self.step_frame(-1)
        )
        self._step_forward = icon_button(
            "step_forward", tip(self.tr("Кадр вперёд"), "→"), lambda: self.step_frame(1)
        )
        self._time = QLabel("0:00 / 0:00")
        self._range = QLabel()  # границы фрагмента и его длина: «0:00.0 – 0:06.9 · 0:06.9»
        self._range.setProperty("muted", True)
        self._range.setToolTip(self.tr("Начало, конец и длина фрагмента"))
        self._time.setMinimumWidth(8 * tokens.SPACE_2)
        self._set_in = icon_button(
            "mark_in", tip(self.tr("Начало фрагмента здесь"), "I"), self.set_in
        )
        self._set_out = icon_button(
            "mark_out", tip(self.tr("Конец фрагмента здесь"), "O"), self.set_out
        )
        self._reset = icon_button("reset_trim", self.tr("Сбросить обрезку"), self._reset_trim)
        self._split = icon_button("scissors", tip(self.tr("Разрезать здесь"), "K"), self.split_here)
        self._delete = icon_button(
            "trash", tip(self.tr("Удалить выбранное"), "Delete"), self.delete_selected
        )
        self._delete.setEnabled(False)
        self._mode = icon_button("mode_fast", "", self.cycle_cut_mode, text=self.tr("Быстрая"))
        self._zoom_out = icon_button(
            "zoom_out", self.tr("Уменьшить полосу"), lambda: self.trim.zoom_out()
        )
        self._zoom_in = icon_button(
            "zoom_in", self.tr("Увеличить полосу"), lambda: self.trim.zoom_in()
        )
        self._zoom_fit = icon_button(
            "fit", self.tr("Вписать полосу целиком"), lambda: self.trim.fit()
        )
        self._zoom_out.setEnabled(False)
        self._zoom_fit.setEnabled(False)
        bar = QWidget()
        bar.setFixedHeight(tokens.TRANSPORT_H)
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(tokens.SPACE_1)
        for widget in (self._play, self._step_back, self._step_forward, self._time):
            row.addWidget(widget)
        row.addSpacing(tokens.SPACE_4)
        for widget in (self._set_in, self._set_out, self._reset):
            row.addWidget(widget)
        row.addSpacing(tokens.SPACE_3)
        for widget in (self._split, self._delete):
            row.addWidget(widget)
        row.addSpacing(tokens.SPACE_3)
        row.addWidget(self._range)
        row.addStretch(1)
        row.addWidget(self._mode)
        for widget in (self._zoom_out, self._zoom_in, self._zoom_fit):
            row.addWidget(widget)
        return bar

    # --- панели инструментов: строятся по требованию -----------------------------------------

    def _ensure_tools(self) -> None:
        """Эффекты и звук: создаются после первого кадра или при первом обращении."""
        if self._tools_ready:
            return
        self._tools_ready = True
        shell = self.shell
        panel = VideoEffectsPanel(self.session, self._overlay, self)
        self._effects_panel = panel
        panel.message.connect(self.message)
        panel.colorPreview.connect(self._on_color_preview)
        panel.colorPreviewEnded.connect(self._on_color_preview_ended)
        panel.selectionChanged.connect(self._on_tool_selected)
        panel.hintChanged.connect(shell.status.set_hint)
        self._audio = AudioPanel(self.session)
        for key, *_rest in RAIL_ITEMS:
            shell.context.add_panel(key, self._audio if key == "audio" else panel.panels[key])
        self._audio.refresh()
        panel.refresh()

    @property
    def effects_panel(self) -> VideoEffectsPanel:
        self._ensure_tools()
        return self._effects_panel

    @property
    def audio(self) -> AudioPanel:
        self._ensure_tools()
        return self._audio

    @property
    def _volume(self) -> QSlider:
        return self.audio._volume

    @property
    def _volume_label(self) -> QLabel:
        return self.audio._volume_label

    @property
    def _mute(self) -> PixelToggle:
        return self.audio._mute

    @property
    def _original_audio(self) -> QPushButton:
        return self.audio._original_audio

    def release_video_page(self) -> VideoPage:
        """Возвращает плеер владельцу (главному окну) при выходе из редактора."""
        player = self._video_page.player
        for signal, slot in (
            (player.positionChanged, self._on_position),
            (player.pausedChanged, self._on_paused),
            (player.fileLoaded, self._on_file_loaded),
        ):
            signal.disconnect(slot)
        player.set_video_filter(None)
        self._overlay.setParent(None)
        self._overlay.deleteLater()
        self._video_page.set_editor_mode(False)
        self._video_page.parentWidget().layout().removeWidget(self._video_page)  # type: ignore[union-attr]
        self._video_page.setParent(None)
        return self._video_page

    def refresh_theme(self) -> None:
        refresh_icons(self)
        self.shell.refresh_theme()
        self.clip_strip.refresh_theme()
        self._overlay.update()
        self.update()

    def shutdown(self) -> None:
        """Остановить фоновые задачи перед закрытием окна."""
        self._worker.cancel()
        self._worker.wait()
        self._thumbs.wait()
        self._tasks.wait()
        remove_workspace(self._workspace)

    # --- размеры ----------------------------------------------------------------------------

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._sized:
            self._sized = True
            QTimer.singleShot(0, self._apply_trim_height)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.clip_strip.set_compact(self.height() < COMPACT_HEIGHT)

    def eventFilter(self, watched: object, event: QEvent) -> bool:  # noqa: N802
        """Полоса клипов выросла или сжалась: высота полосы обрезки остаётся прежней."""
        if watched is self.clip_strip and event.type() == QEvent.Type.Resize:
            new = self.clip_strip.height()
            delta, self._strip_height = new - self._strip_height, new
            self._limit_bottom()
            if delta and self._sized:
                top, bottom = self.splitter.sizes()
                self.splitter.setSizes([max(top - delta, MIN_PREVIEW_HEIGHT), bottom + delta])
        return False

    def _bottom_extras(self) -> int:
        """Высота нижней части без полосы обрезки: транспорт, клипы и отступы."""
        margins = self.splitter.widget(1).layout().contentsMargins()  # type: ignore[union-attr]
        spacing = self.splitter.widget(1).layout().spacing()  # type: ignore[union-attr]
        return (
            tokens.TRANSPORT_H
            + self.clip_strip.height()
            + 2 * spacing
            + margins.top()
            + margins.bottom()
        )

    def _limit_bottom(self) -> None:
        """Полоса обрезки не выше предела: нижняя часть не растёт дальше него."""
        self._bottom.setMaximumHeight(tokens.TRIM_MAX_H + self._bottom_extras())

    def _apply_trim_height(self) -> None:
        self._limit_bottom()
        wanted = self._app.get_int("state.trim_height")
        wanted = min(max(wanted, tokens.TRIM_MIN_H), tokens.TRIM_MAX_H)
        if self.height() < COMPACT_HEIGHT:
            wanted = tokens.TRIM_MIN_H  # низкое окно: превью важнее высокой полосы
        total = sum(self.splitter.sizes())
        bottom = wanted + self._bottom_extras()
        self.splitter.setSizes([max(total - bottom, MIN_PREVIEW_HEIGHT), bottom])

    def _save_trim_height(self) -> None:
        self._app.set("state.trim_height", self.trim.height())

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

    def _load_keyframes(self, clip: Clip) -> None:
        """Ключевые кадры файла в фоне: по ним показывается привязка быстрой резки."""
        if clip.path in self._keyframes:
            self._show_keyframes()
            return
        path = clip.path
        self._tasks.run(
            lambda: read_keyframes(path, self._ffprobe),
            lambda frames: self._on_keyframes(path, frames),
            lambda _error: None,  # без ключевых кадров быстрая резка работает, но не предупреждает
        )

    def _on_keyframes(self, path: Path, frames: tuple[float, ...]) -> None:
        self._keyframes[path] = frames
        self._show_keyframes()

    def _show_keyframes(self) -> None:
        clip = self.clip
        self.trim.set_keyframes(self._keyframes.get(clip.path, ()))
        self._update_junctions()

    def precise_junctions(self) -> int:
        """Сколько стыков итога начинается не на ключевом кадре (нужна точная резка)."""
        return precise_count(self.session.project, self._keyframes)

    def _update_junctions(self) -> None:
        project = self.session.project
        found = junctions(project, self._keyframes)
        flat = project.flat_ranges()
        mine = [
            (j.start, j.snapped, j.precise)
            for j, item in zip(found, flat, strict=True)
            if item.clip_index == self._index
        ]
        self.trim.set_junctions(tuple(mine))
        self._refresh_mode()

    def _thumbs_for(self, clip: Clip) -> None:
        self._load_keyframes(clip)
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

    # --- транспорт ---------------------------------------------------------------------------

    def _toggle_pause(self) -> None:
        self._video_page.player.toggle_pause()

    def step_frame(self, direction: int) -> None:
        """Стрелки: один кадр назад или вперёд."""
        self._video_page.player.step_frame(direction)

    def step_seconds(self, direction: int) -> None:
        """Shift + стрелки: на секунду, точно."""
        player = self._video_page.player
        player.seek_to(max(player.position + direction * SECOND_STEP, 0.0), exact=True)

    def _on_position(self, seconds: float) -> None:
        self.trim.set_position(seconds)
        self._skip_cuts(seconds)
        total = self.clip.info.duration
        self._time.setText(f"{format_time(round(seconds))} / {format_time(round(total))}")

    def _on_paused(self, paused: bool) -> None:
        set_icon(self._play, "play" if paused else "pause")
        label = self.tr("Воспроизвести") if paused else self.tr("Пауза")
        self._play.setToolTip(tip(label, "Space"))

    def _on_zoom_changed(self, level: float) -> None:
        zoomed = level > 1.0
        self._zoom_out.setEnabled(zoomed)
        self._zoom_fit.setEnabled(zoomed)

    # --- обрезка -----------------------------------------------------------------------------

    def _on_trim_committed(self, start: float, end: float) -> None:
        self.session.set_trim(self._index, start, end)

    def set_in(self) -> None:
        self.session.set_trim(self._index, self._video_page.player.position, self.clip.stop)

    def set_out(self) -> None:
        self.session.set_trim(self._index, self.clip.start, self._video_page.player.position)

    def _reset_trim(self) -> None:
        self.session.reset_clip(self._index)

    def _on_time_notes(self, notes: list[TimeNote]) -> None:
        """После правки вырезов время показа пересчитано; что не вышло, говорим прямо."""
        collapsed = [n.label for n in notes if n.kind == "collapsed"]
        clamped = [n.label for n in notes if n.kind == "clamped"]
        if collapsed:
            self.message.emit(
                self.tr("Время показа сжалось до нуля, эффект не виден: ") + ", ".join(collapsed)
            )
        elif clamped:
            text = self.tr("Время показа обрезано по длине итога: ")
            self.message.emit(text + ", ".join(clamped))

    # --- разрезы и вырезы --------------------------------------------------------------------

    def _skip_cuts(self, seconds: float) -> None:
        """Предпросмотр играет только оставленное: дойдя до выреза, перепрыгивает через него.

        Выбран перескок по наблюдателю позиции, а не EDL mpv: время в плеере остаётся временем
        исходного файла, поэтому полоса обрезки, ручки и ключевые кадры не требуют пересчёта,
        а правка вырезов не перезагружает файл. Цена — короткий скачок на стыке.
        """
        player = self._video_page.player
        if player.paused or not self.clip.has_cuts:
            return
        for (_a, b), (c, _d) in zip(self.clip.ranges, self.clip.ranges[1:], strict=False):
            if b - SKIP_LEAD <= seconds < c:
                if self._skipping_to != c:  # один прыжок на один вырез
                    self._skipping_to = c
                    player.seek_to(c, exact=True)
                return
        self._skipping_to = None

    def split_here(self) -> None:
        """K: разрезать клип в позиции указателя (сегменты можно выбрать и удалить)."""
        self.session.cut(SplitAt(self._index, self._video_page.player.position))

    def delete_selected(self) -> None:
        """Delete: вырезать выделенный диапазон или выбранный сегмент (остаток сдвигается)."""
        target = self.trim.marks or self._segment
        if target is None:
            self.message.emit(self.tr("Выберите сегмент кликом или выделите диапазон с Shift"))
            return
        self._segment = None
        self.trim.set_marks(None)
        self.session.cut(RemoveRange(self._index, *target))

    def cut_marks(self) -> None:
        """Ctrl+X: вырезать выделенный диапазон между маркерами."""
        if self.trim.marks is None:
            self.message.emit(self.tr("Выделите диапазон на полосе с зажатым Shift"))
            return
        self.delete_selected()

    def _restore_range(self, start: float, stop: float) -> None:
        self.session.cut(RestoreRange(self._index, start, stop))

    def _on_segment_picked(self, start: float, stop: float) -> None:
        self._segment = (start, stop)
        self._delete.setEnabled(True)

    def _on_selection_cleared(self) -> None:
        self._segment = None
        self._delete.setEnabled(self.trim.marks is not None)

    def _on_range_marked(self, _start: float, _stop: float) -> None:
        self._segment = None
        self.trim.set_segment(None)
        self._delete.setEnabled(True)

    # --- режим резки -------------------------------------------------------------------------

    def cut_mode(self) -> str:
        return self._app.get_str("editor.cut_mode")

    def cycle_cut_mode(self) -> None:
        order = ("fast", "precise", "ask")
        mode = self.cut_mode()
        self._app.set(
            "editor.cut_mode", order[(order.index(mode) + 1) % 3] if mode in order else "ask"
        )
        self._refresh_mode()

    def _refresh_mode(self) -> None:
        """Значок режима резки: быстрая, точная или спросить; предупреждение о стыках."""
        mode = self.cut_mode()
        warn = mode == "fast" and self.precise_junctions() > 0
        icon, text, tooltip = {
            "fast": (
                "mode_fast",
                self.tr("Быстрая"),
                self.tr("Быстрая резка: без перекодирования, по ключевым кадрам"),
            ),
            "precise": (
                "mode_precise",
                self.tr("Точная"),
                self.tr("Точная резка: с перекодированием, границы до кадра"),
            ),
        }.get(
            mode,
            (
                "settings",
                self.tr("Спросить"),
                self.tr("Способ резки выбирается при экспорте"),
            ),
        )
        set_icon(self._mode, "warning" if warn else icon)
        self._mode.setText(text)
        extra = ""
        if warn:
            extra = "\n" + self.tr("На стыках ({0}) нужна точная резка: начало сдвинется").format(
                self.precise_junctions()
            )
        self._mode.setToolTip(tooltip + extra + "\n" + self.tr("Нажмите, чтобы сменить режим"))
        self._mode.setProperty("warn", warn)
        self._mode.style().unpolish(self._mode)
        self._mode.style().polish(self._mode)

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
        self.clip_strip.set_current(len(self.session.project.clips) - 1)
        self._on_row_changed(self.clip_strip.current)
        if reason is None:
            self.message.emit(self.tr("Клип добавлен: ") + path.name)
        else:
            self.message.emit(
                self.tr(
                    "Клип добавлен. Отличается: {0}, при экспорте видео будет перекодировано"
                ).format(self.tr(_REASONS.get(reason, reason)))
            )

    def _remove_clip(self) -> None:
        self._remove_clip_at(self._index)

    def _remove_clip_at(self, index: int) -> None:
        if len(self.session.project.clips) <= 1:
            self.message.emit(self.tr("Последний клип удалить нельзя"))
            return
        if index < self._index:
            self._index -= 1  # выбранный клип остаётся тем же
        self.session.remove_clip(index)

    def _move_clip(self, delta: int) -> None:
        target = self._index + delta
        if 0 <= target < len(self.session.project.clips):
            self._on_move_requested(self._index, target)

    def _on_move_requested(self, source: int, target: int) -> None:
        if source == self._index:
            self._index = target  # выбор следует за клипом
        elif source < self._index <= target:
            self._index -= 1
        elif target <= self._index < source:
            self._index += 1
        self.session.move_clip_to(source, target)

    # --- звук --------------------------------------------------------------------------------

    def _choose_replacement(self) -> None:
        self.audio.choose_replacement()

    # --- инструменты -------------------------------------------------------------------------

    def select_tool(self, name: str) -> None:
        self.effects_panel.select_tool(name)

    def _on_tool_selected(self, key: object) -> None:
        self.shell.select(key if isinstance(key, str) else None)

    def _remove_effect(self, entry: EffectEntry) -> None:
        self.session.remove_effect(entry)

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
        infos = [
            ClipInfo(
                clip.path.name,
                format_time(round(clip.length)),
                str(clip.path),
            )
            for clip in clips
        ]
        self.clip_strip.set_clips(infos, self._index)

        self._undo_button.setEnabled(self.session.can_undo)
        self._redo_button.setEnabled(self.session.can_redo)
        marker = " *" if self.session.modified else ""
        width, height = output_frame_size(project.effects, project.frame_size)
        self.shell.status.set_summary(
            self.tr("Итог {0} · {1}×{2} · клипов {3}").format(
                format_time(project.duration), width, height, len(clips)
            )
            + marker
        )
        self.shell.status.summary_label.setToolTip(
            self.tr("Звёздочка: есть несохранённые изменения") if marker else ""
        )
        self.effects_chip.set_effects(project.effects)
        self._refresh_marks(project.effects)

        if self._tools_ready:
            self._audio.refresh()
        self._refresh_trim()
        self._apply_loop()
        if self._tools_ready:
            self._effects_panel.refresh()
        self._apply_preview()

    def _refresh_marks(self, effects: VideoEffects) -> None:
        marked = {entry.tool for entry in effect_entries(effects)}
        audio = self.session.project.audio
        customised = audio.volume != 1.0 or audio.mute or audio.replacement is not None
        for key in self.shell.rail.names():
            on = key in marked or (key == "audio" and customised)
            self.shell.rail.set_marked(key, on)

    def _refresh_trim(self) -> None:
        clip = self.clip
        self.trim.set_range(clip.start, clip.stop)
        self.trim.set_cuts(clip.ghosts(), clip.splits, clip.segments())
        if self._segment is not None and self._segment not in clip.segments():
            self._segment = None  # выбранного сегмента больше нет (удалён или разрезан)
            self._delete.setEnabled(self.trim.marks is not None)
        self.trim.set_segment(self._segment)
        self._range.setText(range_label(clip.start, clip.stop))
        self._update_junctions()

    # --- предпросмотр эффектов в mpv ---------------------------------------------------------

    def _preview_graph(self, effects: VideoEffects) -> str | None:
        """Тот же граф, что и при экспорте, но без кадра и поворота (их показывает слой)."""
        files = write_text_files(effects.texts, self._workspace)
        project = self.session.project
        index = self._index

        def enable_for(show_from: float, show_to: float) -> str | None:
            """Окно показа — во времени итога, а плеер идёт по времени файла: переводим."""
            windows = result_windows_to_source(project, index, show_from, show_to)
            if not windows:
                return "0"  # в этом клипе эффект не показывается
            return "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in windows)

        graph = build_effects_graph(
            effects,
            project.frame_size,
            files,
            find_font_path(),
            geometry=False,
            in_label="vid1",
            out_label="vo",
            enable_for=enable_for,
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
        dialog = VideoExportDialog(self.session.project, self, self._app, self.precise_junctions())
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
                keyframes=self._export_keyframes(),
            )
        except ExportPlanError as error:
            remove_workspace(workdir)
            self.toast.show_message(self.tr("Экспорт невозможен: ") + str(error), "error")
            return
        self._export_dir = workdir
        self.export_strip.start(self.tr("Экспорт…"))
        self._progress = self.export_strip
        self._export_button.setEnabled(False)
        self._worker.start(plan, workdir)

    def _export_keyframes(self) -> dict[Path, tuple[float, ...]]:
        """Ключевые кадры всех клипов; недостающие читаются сейчас (быстро, без декодирования)."""
        for clip in self.session.project.clips:
            if clip.path not in self._keyframes:
                # без ключевых кадров копирование работает, но начала не привязываются
                with contextlib.suppress(ProbeError, OSError):
                    self._keyframes[clip.path] = read_keyframes(clip.path, self._ffprobe)
        return dict(self._keyframes)

    def _cancel_export(self) -> None:
        self.export_strip.cancelling()
        self._worker.cancel()

    def _close_progress(self) -> None:
        self.export_strip.finish()
        self._progress = None
        self._export_dir = None
        self._export_button.setEnabled(True)

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
