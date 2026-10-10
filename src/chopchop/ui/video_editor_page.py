"""Страница редактора видео на общей оболочке: превью, рейка, транспорт, блоки, экспорт.

Сверху вниз: верхняя панель, контекстная панель параметров (только при выбранном инструменте),
рейка и превью, строка транспорта, полоса блоков, строка состояния. Никаких плавающих панелей
плеера поверх кадра.

Ролик это список блоков (`Clip`): непрерывные куски исходных файлов подряд. Плеер играет этот
список целиком (EDL mpv), поэтому его время равно времени итога, и позиция, полоса блоков и время
показа эффектов считаются в одной шкале.
"""

import contextlib
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QShowEvent
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

from chopchop import i18n
from chopchop.core.document import MediaInfo
from chopchop.core.keyframes import junctions, precise_count
from chopchop.core.operations import Adjust, FilterName
from chopchop.core.timing import TimeNote, map_position
from chopchop.core.tr_marks import QT_TRANSLATE_NOOP
from chopchop.core.video import (
    Clip,
    EffectEntry,
    MoveBlock,
    RemoveBlock,
    RemoveRange,
    SplitAt,
    TrimBlock,
    VideoEffects,
    VideoProject,
    cut_summary,
    effect_entries,
    incompatibility,
)
from chopchop.editor.video_session import VideoSession
from chopchop.engines.edl import edl_source
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
from chopchop.ui.actions import ActionRegistry
from chopchop.ui.audio_panel import AudioPanel
from chopchop.ui.editor_shell import EditorShell
from chopchop.ui.effects_chip import EffectsChip
from chopchop.ui.export_strip import ExportStrip
from chopchop.ui.player_controls import format_time
from chopchop.ui.theme import tokens
from chopchop.ui.timeline import Timeline, TimelineBlock, range_label
from chopchop.ui.toast import Toast
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
TOOLS_DELAY_MS = 40
SECOND_STEP = 1.0  # Shift + стрелки
MIN_PREVIEW_HEIGHT = 160
SAVE_TRIM_HEIGHT_MS = 300
SEAM_EPS = 0.02  # ближе этого к шву разрезать нечего

_REASONS = {
    "codec": QT_TRANSLATE_NOOP("VideoEditorPage", "видеокодек"),
    "resolution": QT_TRANSLATE_NOOP("VideoEditorPage", "разрешение или поворот"),
    "fps": QT_TRANSLATE_NOOP("VideoEditorPage", "частота кадров"),
    "pixel format": QT_TRANSLATE_NOOP("VideoEditorPage", "формат пикселей"),
    "audio": QT_TRANSLATE_NOOP("VideoEditorPage", "параметры звука"),
}

_FRAGMENT_FORMS = (
    QT_TRANSLATE_NOOP("VideoEditorPage", "фрагмент"),
    QT_TRANSLATE_NOOP("VideoEditorPage", "фрагмента"),
    QT_TRANSLATE_NOOP("VideoEditorPage", "фрагментов"),
)


def plural_form(count: int, language: str) -> int:
    """Номер формы слова: русский (1 фрагмент, 2 фрагмента, 5 фрагментов), иначе ед. и мн. число."""
    if language == "ru":
        if count % 10 == 1 and count % 100 != 11:
            return 0
        if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
            return 1
        return 2
    return 0 if count == 1 else 2


def cut_text(
    count: int, seconds: float, language: str, translate: Callable[[str], str] | None = None
) -> str:
    """«2 фрагмента, −0:12»; пустая строка, если ничего не вырезано."""
    if count <= 0:
        return ""
    word = _FRAGMENT_FORMS[plural_form(count, language)]
    if translate is not None:
        word = translate(word)
    return f"{count} {word}, −{format_time(round(seconds))}"


class VideoEditorPage(QWidget):
    exitRequested = Signal()
    message = Signal(str)
    menuRequested = Signal(str, QPoint, object)  # вид меню, точка на экране, данные

    def __init__(
        self,
        session: VideoSession,
        video_page: VideoPage,
        ffmpeg: Path,
        ffprobe: Path,
        parent: QWidget | None = None,
        settings: AppSettings | None = None,
        actions: ActionRegistry | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self._actions = actions
        self._app = settings or AppSettings(None)
        self._export_args: tuple[Path, bool, EncodeOptions] | None = None
        self._video_page = video_page
        self._ffmpeg = ffmpeg
        self._ffprobe = ffprobe
        self._selected: int | None = None  # выбранный блок
        self.loaded_path: Path | None = session.project.clips[0].path  # исходный файл
        self._export_dir: Path | None = None
        self._progress: ExportStrip | None = None  # полоса экспорта, пока он идёт
        self._workspace = new_workspace()  # файлы текста для предпросмотра эффектов
        self._preview_key: str | None = None
        self._sized = False  # высота полосы блоков из настроек применена
        self._tools_ready = False  # панели эффектов и звука построены
        self._keyframes: dict[Path, tuple[float, ...]] = {}  # ключевые кадры открытых файлов
        self._edl: str | None = None  # что сейчас загружено в плеер
        self._seen: VideoProject = session.project  # проект при прошлом обновлении
        self._position = 0.0  # позиция плеера во времени итога
        self._loaders: dict[Path, ThumbnailLoader] = {}
        self._asked: set[Path] = set()  # файлы, ключевые кадры которых уже запрошены

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
        self._bind_actions()

        player = video_page.player
        player.positionChanged.connect(self._on_position)
        player.pausedChanged.connect(self._on_paused)
        player.fileLoaded.connect(self._on_file_loaded)
        session.changed.connect(self._on_session_changed)
        session.timeNotes.connect(self._on_time_notes)
        self._load_sources()
        self._reload_preview(initial=True)
        self._refresh()
        self._on_paused(True)
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
        self._video_page.contextMenuRequested.connect(self._on_preview_menu)
        self._overlay = VideoOverlay(self._video_page, self.session.project.frame_size)
        self.message.connect(shell.status.flash)

        # рейка инструментов; панели параметров строятся позже (`_ensure_tools`): открытие
        # редактора не должно ждать создания десятков виджетов, которые пока не нужны
        for key, icon, name, hotkey in RAIL_ITEMS:
            shell.rail.add_tool(key, icon, self.tr(name), hotkey)
        shell.rail.toolClicked.connect(self.select_tool)
        shell.rail.contextRequested.connect(self._on_rail_menu)

        # транспорт и полоса блоков
        self.transport = self._build_transport()
        self.timeline = Timeline()
        self.timeline.seekRequested.connect(self._video_page.player.seek_to)  # по ключевым кадрам
        self.timeline.seekFinished.connect(lambda s: self._video_page.player.seek_to(s, exact=True))
        self.timeline.blockSelected.connect(self._on_block_selected)
        self.timeline.selectionCleared.connect(self._on_selection_cleared)
        self.timeline.trimming.connect(self._on_block_trimming)
        self.timeline.trimCommitted.connect(self._on_block_trimmed)
        self.timeline.moveRequested.connect(self.move_block)
        self.timeline.zoomChanged.connect(self._on_zoom_changed)
        self.timeline.menuRequested.connect(
            lambda pos, data: self.menuRequested.emit("timeline", pos, data)
        )

        bottom = self._bottom = QWidget()
        column = QVBoxLayout(bottom)
        column.setContentsMargins(tokens.SPACE_3, 0, tokens.SPACE_3, tokens.SPACE_2)
        column.setSpacing(tokens.SPACE_1)
        column.addWidget(self.transport)
        column.addWidget(self.timeline, 1)
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

        # строка состояния
        self.effects_chip = EffectsChip()
        self.effects_chip.removeRequested.connect(self._remove_effect)
        self.effects_chip.clearRequested.connect(self.session.clear_effects)
        self.effects_chip.menuRequested.connect(self._on_effects_menu)
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
        self._range = QLabel()  # выбранный блок: «Блок 2 из 5 · 0:03.2 – 0:09.0 · 0:05.8»
        self._range.setProperty("muted", True)
        self._range.setToolTip(self.tr("Начало, конец и длина выбранного блока в исходном файле"))
        self._time.setMinimumWidth(8 * tokens.SPACE_2)
        self._set_in = icon_button(
            "mark_in", tip(self.tr("Обрезать начало блока здесь"), "I"), self.set_in
        )
        self._set_out = icon_button(
            "mark_out", tip(self.tr("Обрезать конец блока здесь"), "O"), self.set_out
        )
        self._reset = icon_button("reset_trim", self.tr("Вернуть блок целиком"), self._reset_trim)
        self._split = icon_button("scissors", tip(self.tr("Разрезать здесь"), "K"), self.split_here)
        self._delete = icon_button(
            "trash", tip(self.tr("Удалить выбранный блок"), "Delete"), self.delete_selected
        )
        self._delete.setEnabled(False)
        self._add = icon_button("add_clip", self.tr("Добавить клип…"), self.add_clip)
        self._mode = icon_button("mode_fast", "", self.cycle_cut_mode, text=self.tr("Быстрая"))
        self._zoom_out = icon_button(
            "zoom_out", self.tr("Уменьшить полосу"), lambda: self.timeline.zoom_out()
        )
        self._zoom_in = icon_button(
            "zoom_in", self.tr("Увеличить полосу"), lambda: self.timeline.zoom_in()
        )
        self._zoom_fit = icon_button(
            "fit", self.tr("Вписать полосу целиком"), lambda: self.timeline.fit()
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
        for widget in (self._split, self._delete, self._add):
            row.addWidget(widget)
        row.addSpacing(tokens.SPACE_3)
        row.addWidget(self._range)
        row.addStretch(1)
        row.addWidget(self._mode)
        for widget in (self._zoom_out, self._zoom_in, self._zoom_fit):
            row.addWidget(widget)
        return bar

    def _bind_actions(self) -> None:
        """Кнопки панелей запускают те же действия реестра, что и меню и горячие клавиши."""
        if self._actions is None:
            return
        pairs = (
            (self._back, "back_to_view"),
            (self._undo_button, "undo"),
            (self._redo_button, "redo"),
            (self._export_button, "export"),
            (self._play, "pause"),
            (self._step_back, "prev"),
            (self._step_forward, "next"),
            (self._set_in, "mark_in"),
            (self._set_out, "mark_out"),
            (self._reset, "reset_trim"),
            (self._split, "split"),
            (self._delete, "delete_segment"),
            (self._add, "add_clip"),
            (self._zoom_in, "trim_zoom_in"),
            (self._zoom_out, "trim_zoom_out"),
            (self._zoom_fit, "trim_fit"),
        )
        for widget, action_id in pairs:
            with contextlib.suppress(TypeError, RuntimeError):
                widget.clicked.disconnect()  # прямое подключение заменяется действием
            self._actions.bind(widget, action_id)

    # --- меню по правой кнопке ---------------------------------------------------------------

    def _on_preview_menu(self, pos: QPoint) -> None:
        self.menuRequested.emit("preview", pos, None)

    def _entries_with_labels(self, entries: list[EffectEntry]) -> list[tuple[EffectEntry, str]]:
        return [(entry, self.effects_chip.label_for(entry)) for entry in entries]

    def _on_rail_menu(self, key: str, pos: QPoint) -> None:
        """Точка-метка на инструменте: меню удаления его эффектов."""
        entries = [e for e in effect_entries(self.session.project.effects) if e.tool == key]
        if entries:
            self.menuRequested.emit("effects", pos, self._entries_with_labels(entries))

    def _on_effects_menu(self, entries: list[EffectEntry], pos: QPoint) -> None:
        self.menuRequested.emit("effects", pos, self._entries_with_labels(entries))

    # --- то, что нужно меню ------------------------------------------------------------------

    def has_pending(self) -> bool:
        """Есть ли незавершённое выделение; панели ради ответа не строятся."""
        return self._tools_ready and self._effects_panel.has_pending()

    def reset_selection(self) -> None:
        if self._tools_ready:
            tool = self._effects_panel._active_tool()
            if tool is not None:
                tool.reset()

    def session_can_undo(self) -> bool:
        return self.session.can_undo

    def session_can_redo(self) -> bool:
        return self.session.can_redo

    def block_count(self) -> int:
        return len(self.session.project.clips)

    def block_is_trimmed(self, index: int) -> bool:
        return self.session.project.clips[index].is_trimmed

    def move_block_by(self, index: int, delta: int) -> None:
        target = index + delta
        if 0 <= target < self.block_count():
            self.move_block(index, target)

    def reveal_block(self, index: int) -> None:
        reveal_in_folder(self.session.project.clips[index].path)

    def remove_effect(self, entry: EffectEntry) -> None:
        self.session.remove_effect(entry)

    def reset_trim(self) -> None:
        self._reset_trim()

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
            (self._video_page.contextMenuRequested, self._on_preview_menu),
        ):
            signal.disconnect(slot)
        player.set_video_filter(None)
        self._overlay.setParent(None)
        self._overlay.deleteLater()
        self._video_page.set_editor_mode(False)
        self._video_page.parentWidget().layout().removeWidget(self._video_page)  # type: ignore[union-attr]
        self._video_page.setParent(None)
        if self.loaded_path is not None:
            player.load(self.loaded_path)  # снова исходный файл, а не монтаж
        return self._video_page

    def refresh_theme(self) -> None:
        refresh_icons(self)
        self.shell.refresh_theme()
        self.timeline.invalidate()
        self._overlay.update()
        self.update()

    def shutdown(self) -> None:
        """Остановить фоновые задачи перед закрытием окна."""
        self._worker.cancel()
        self._worker.wait()
        for loader in self._loaders.values():
            loader.cancel()
            loader.wait()
        self._tasks.wait()
        remove_workspace(self._workspace)

    # --- размеры ----------------------------------------------------------------------------

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._sized:
            self._sized = True
            QTimer.singleShot(0, self._apply_trim_height)

    def _bottom_extras(self) -> int:
        """Высота нижней части без полосы блоков: транспорт и отступы."""
        margins = self.splitter.widget(1).layout().contentsMargins()  # type: ignore[union-attr]
        spacing = self.splitter.widget(1).layout().spacing()  # type: ignore[union-attr]
        return tokens.TRANSPORT_H + spacing + margins.top() + margins.bottom()

    def _limit_bottom(self) -> None:
        """Полоса блоков не выше предела: нижняя часть не растёт дальше него."""
        self._bottom.setMaximumHeight(tokens.TRIM_MAX_H + self._bottom_extras())

    def _apply_trim_height(self) -> None:
        self._limit_bottom()
        wanted = self._app.get_int("state.trim_height")
        wanted = min(max(wanted, tokens.TRIM_MIN_H), tokens.TRIM_MAX_H)
        total = sum(self.splitter.sizes())
        bottom = wanted + self._bottom_extras()
        self.splitter.setSizes([max(total - bottom, MIN_PREVIEW_HEIGHT), bottom])

    def _save_trim_height(self) -> None:
        self._app.set("state.trim_height", self.timeline.height())

    # --- исходные файлы: миниатюры и ключевые кадры ------------------------------------------

    def _load_sources(self) -> None:
        for clip in self.session.project.clips:
            if clip.path not in self._loaders:
                self._thumbs_for(clip)
            self._load_keyframes(clip)

    def _thumbs_for(self, clip: Clip) -> None:
        loader = ThumbnailLoader(
            self._ffmpeg, self, limit_bytes=self._app.get_int("advanced.thumb_cache_mb") * 1024**2
        )
        loader.thumbnail.connect(self._on_thumbnail)
        self._loaders[clip.path] = loader
        thumbs = loader.request(clip.path, clip.info.duration, THUMBNAILS)
        self.timeline.set_thumbs(clip.path, thumbs)

    def _on_thumbnail(self, path: str, index: int, image: QImage) -> None:
        self.timeline.set_thumbnail(Path(path), index, image)

    def _load_keyframes(self, clip: Clip) -> None:
        """Ключевые кадры файла в фоне: по ним показывается привязка быстрой резки."""
        if clip.path in self._keyframes or clip.path in self._asked:
            return
        self._asked.add(clip.path)
        path = clip.path
        self._tasks.run(
            lambda: read_keyframes(path, self._ffprobe),
            lambda frames: self._on_keyframes(path, frames),
            lambda _error: None,  # без ключевых кадров быстрая резка работает, но не предупреждает
        )

    def _on_keyframes(self, path: Path, frames: tuple[float, ...]) -> None:
        self._keyframes[path] = frames
        self._refresh_blocks()
        self._refresh_mode()

    def precise_junctions(self) -> int:
        """Сколько стыков итога начинается не на ключевом кадре (нужна точная резка)."""
        return precise_count(self.session.project, self._keyframes)

    # --- блоки: выбор и правки ---------------------------------------------------------------

    @property
    def selected_block(self) -> int | None:
        return self._selected

    def select_block(self, index: int | None) -> None:
        count = self.block_count()
        self._selected = None if index is None or not 0 <= index < count else index
        self.timeline.set_selected(self._selected)
        self._refresh_selection()

    def _on_block_selected(self, index: int) -> None:
        self._selected = index
        self._refresh_selection()

    def _on_selection_cleared(self) -> None:
        self._selected = None
        self._refresh_selection()

    def _refresh_selection(self) -> None:
        project = self.session.project
        index = self._selected
        self._delete.setEnabled(index is not None and len(project.clips) > 1)
        if index is None or index >= len(project.clips):
            self._range.setText("")
            return
        clip = project.clips[index]
        self._range.setText(
            self.tr("Блок {0} из {1} · ").format(index + 1, len(project.clips))
            + range_label(clip.start, clip.stop)
        )

    def _on_block_trimming(self, index: int, start: float, stop: float) -> None:
        self._range.setText(
            self.tr("Блок {0} из {1} · ").format(index + 1, self.block_count())
            + range_label(start, stop)
        )

    def _on_block_trimmed(self, index: int, start: float, stop: float) -> None:
        self._selected = index
        self.session.cut(TrimBlock(index, start, stop))

    def move_block(self, index: int, target: int) -> None:
        """Блок на новое место; выбор следует за ним."""
        if self._selected == index:
            self._selected = target
        elif self._selected is not None:
            if index < self._selected <= target:
                self._selected -= 1
            elif target <= self._selected < index:
                self._selected += 1
        self.session.cut(MoveBlock(index, target))

    def _hover_time(self) -> float | None:
        """Время итога под указателем, если мышь над блоком полосы."""
        timeline = self.timeline
        if timeline.underMouse():
            point = timeline.mapFromGlobal(timeline.cursor().pos())
            if timeline.block_at(point.x()) is not None:
                return timeline.time_at(point.x())
        return None

    def split_here(self) -> None:
        """K: разрезать там, где указатель мыши над полосой, иначе в позиции воспроизведения."""
        seconds = self._hover_time()
        self.split_at(self._position if seconds is None else seconds)

    def split_at(self, seconds: float) -> None:
        project = self.session.project
        index, _source = project.locate(seconds)
        local = seconds - project.offsets()[index]
        if local < SEAM_EPS or project.clips[index].length - local < SEAM_EPS:
            self.message.emit(self.tr("Здесь уже шов между блоками"))
            return
        self.session.cut(SplitAt(seconds))

    def delete_selected(self) -> None:
        """Delete: удалить выбранный блок, остальные сдвигаются."""
        if self._selected is None:
            self.message.emit(self.tr("Выберите блок на полосе"))
            return
        self.delete_block(self._selected)

    def delete_block(self, index: int) -> None:
        if self.block_count() <= 1:
            self.message.emit(self.tr("Последний блок удалить нельзя"))
            return
        if self._selected is not None and self._selected >= index:
            self._selected = None if self._selected == index else self._selected - 1
        self.session.cut(RemoveBlock(index))

    def cut_range(self, start: float, stop: float) -> None:
        self.session.cut(RemoveRange(start, stop))

    def set_in(self) -> None:
        """I: обрезать начало блока до позиции воспроизведения."""
        index, source = self._block_under_position()
        clip = self.session.project.clips[index]
        self.session.cut(TrimBlock(index, source, clip.stop))

    def set_out(self) -> None:
        """O: обрезать конец блока до позиции воспроизведения."""
        index, source = self._block_under_position()
        clip = self.session.project.clips[index]
        self.session.cut(TrimBlock(index, clip.start, source))

    def _block_under_position(self) -> tuple[int, float]:
        """Блок и момент его файла: выбранный блок важнее блока под позицией."""
        project = self.session.project
        index, source = project.locate(self._position)
        if self._selected is not None and self._selected != index:
            index = self._selected
            clip = project.clips[index]
            source = min(max(source, clip.start), clip.stop)
        return index, source

    def _reset_trim(self) -> None:
        """Вернуть выбранный блок целым: границы исходного файла."""
        index = self._selected if self._selected is not None else self._block_under_position()[0]
        self.reset_block(index)

    def reset_block(self, index: int) -> None:
        self.session.reset_clip(index)

    def playhead(self) -> float:
        """Позиция воспроизведения во времени итога."""
        return self._position

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
            str(self.session.project.clips[-1].path.parent),
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
        self.select_block(self.block_count() - 1)
        if reason is None:
            self.message.emit(self.tr("Клип добавлен: ") + path.name)
        else:
            self.message.emit(
                self.tr(
                    "Клип добавлен. Отличается: {0}, при экспорте видео будет перекодировано"
                ).format(self.tr(_REASONS.get(reason, reason)))
            )

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

    # --- транспорт ---------------------------------------------------------------------------

    def _toggle_pause(self) -> None:
        self._video_page.player.toggle_pause()

    def step_frame(self, direction: int) -> None:
        """Стрелки: один кадр назад или вперёд."""
        self._video_page.player.step_frame(direction)

    def step_seconds(self, direction: int) -> None:
        """Shift + стрелки: на секунду, точно."""
        player = self._video_page.player
        player.seek_to(max(self._position + direction * SECOND_STEP, 0.0), exact=True)

    def _on_position(self, seconds: float) -> None:
        self._position = seconds
        self.timeline.set_position(seconds)
        total = self.session.project.duration
        self._time.setText(f"{format_time(round(seconds))} / {format_time(round(total))}")

    def _on_paused(self, paused: bool) -> None:
        set_icon(self._play, "play" if paused else "pause")
        label = self.tr("Воспроизвести") if paused else self.tr("Пауза")
        self._play.setToolTip(tip(label, "Space"))

    def _on_zoom_changed(self, level: float) -> None:
        zoomed = level > 1.0
        self._zoom_out.setEnabled(zoomed)
        self._zoom_fit.setEnabled(zoomed)

    def _on_time_notes(self, notes: list[TimeNote]) -> None:
        """После правки блоков время показа пересчитано; что не вышло, говорим прямо."""
        collapsed = [n.label for n in notes if n.kind == "collapsed"]
        clamped = [n.label for n in notes if n.kind == "clamped"]
        if collapsed:
            self.message.emit(
                self.tr("Время показа сжалось до нуля, эффект не виден: ") + ", ".join(collapsed)
            )
        elif clamped:
            text = self.tr("Время показа обрезано по длине итога: ")
            self.message.emit(text + ", ".join(clamped))

    # --- предпросмотр: EDL ------------------------------------------------------------------

    def _reload_preview(self, initial: bool = False) -> None:
        """Плеер играет ролик из блоков; перезагрузка только если сам монтаж изменился."""
        project = self.session.project
        source = edl_source(project)
        if source == self._edl:
            return
        player = self._video_page.player
        position = 0.0
        paused = True
        if not initial:
            position = map_position(self._seen, project, self._position)
            paused = player.paused
        self._edl = source
        player.load_source(source, project.clips[0].path, position=position, paused=paused)
        self._position = position

    def _on_file_loaded(self) -> None:
        """Монтаж загружен: эффекты предпросмотра поверх него и позиция на месте."""
        self._preview_key = None
        self._apply_preview()
        self.timeline.set_position(self._position)

    # --- обновление --------------------------------------------------------------------------

    def _on_session_changed(self) -> None:
        self._load_sources()
        count = self.block_count()
        if self._selected is not None and self._selected >= count:
            self._selected = count - 1
        self._reload_preview()
        self._seen = self.session.project
        self._refresh()

    def _refresh(self) -> None:
        project = self.session.project
        clips = project.clips
        self._undo_button.setEnabled(self.session.can_undo)
        self._redo_button.setEnabled(self.session.can_redo)
        marker = " *" if self.session.modified else ""
        width, height = output_frame_size(project.effects, project.frame_size)
        count, seconds = cut_summary(project)
        cut = cut_text(count, seconds, i18n.current_language(), self.tr)
        summary = self.tr("Итог {0} · {1}×{2} · блоков {3}").format(
            format_time(project.duration), width, height, len(clips)
        )
        if cut:
            summary += " · " + self.tr("Вырезано: ") + cut
        self.shell.status.set_summary(summary + marker)
        self.shell.status.summary_label.setToolTip(
            self.tr("Звёздочка: есть несохранённые изменения") if marker else ""
        )
        self.effects_chip.set_effects(project.effects)
        self._refresh_marks(project.effects)

        if self._tools_ready:
            self._audio.refresh()
        self._refresh_blocks()
        if self._tools_ready:
            self._effects_panel.refresh()
        self._apply_preview()
        self._refresh_mode()

    def _refresh_marks(self, effects: VideoEffects) -> None:
        marked = {entry.tool for entry in effect_entries(effects)}
        audio = self.session.project.audio
        customised = audio.volume != 1.0 or audio.mute or audio.replacement is not None
        for key in self.shell.rail.names():
            on = key in marked or (key == "audio" and customised)
            self.shell.rail.set_marked(key, on)

    def _refresh_blocks(self) -> None:
        project = self.session.project
        found = junctions(project, self._keyframes)
        blocks = [
            TimelineBlock(
                clip.path,
                clip.info.duration,
                clip.start,
                clip.stop,
                precise=junction.precise,
                shift=junction.shift,
            )
            for clip, junction in zip(project.clips, found, strict=True)
        ]
        self.timeline.set_blocks(blocks, self._selected)
        self._refresh_selection()

    # --- предпросмотр эффектов в mpv ---------------------------------------------------------

    def _preview_graph(self, effects: VideoEffects) -> str | None:
        """Тот же граф, что и при экспорте, но без кадра и поворота (их показывает слой).

        Плеер играет итог, а окна показа хранятся во времени итога: пересчёт не нужен.
        """
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
