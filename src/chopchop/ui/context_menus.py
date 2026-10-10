"""Состав контекстных меню (ПКМ, клавиша Menu, Shift+F10) для открытого файла.

Меню строится при открытии из текущего состояния (дорожки берутся из mpv в этот момент),
а пункты берутся из единого реестра действий: тот же текст, значок, клавиша и обработчик, что
у строки меню и горячих клавиш. Неприменимое не добавляется, временно недоступное серое.
"""

from collections.abc import Callable
from functools import partial
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import QObject
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import QFileDialog, QMenu

from chopchop.core.tracks import Track, of_kind
from chopchop.core.video import EffectEntry
from chopchop.ui.actions import (
    PHOTO,
    PHOTO_EDITOR,
    VIDEO,
    VIDEO_EDITOR,
)
from chopchop.ui.themed_menu import ThemedMenu

if TYPE_CHECKING:
    from chopchop.ui.main_window import MainWindow

SPEEDS = (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0)
SUBTITLE_FILTER = "*.srt *.ass *.ssa *.vtt *.sub"


def ids(menu: ThemedMenu) -> list[str]:
    """Идентификаторы действий меню по порядку (подменю помечены как `menu:название`)."""
    found: list[str] = []
    for action in menu.actions():
        if action.isSeparator():
            found.append("-")
        elif action.menu() is not None:
            found.append("menu:" + cast(QMenu, action.menu()).title())
        else:
            found.append(action.objectName() or action.text())
    return found


class ContextMenus(QObject):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.w = window

    # --- общее -------------------------------------------------------------------------------

    def _menu(self) -> ThemedMenu:
        return ThemedMenu(self.w)

    def _add(self, menu: ThemedMenu, action_id: str, **kwargs: object) -> None:
        menu.add_action(self.w.registry[action_id], **kwargs)  # type: ignore[arg-type]

    def _file_group(self, menu: ThemedMenu) -> None:
        menu.addSeparator()
        for action_id in ("reveal", "copy_path", "rename", "delete_file", "properties"):
            self._add(menu, action_id)

    def for_context(self) -> ThemedMenu | None:
        """Меню для текущего экрана (клавиша Menu): там, где мыши нет, — основное меню экрана."""
        context = self.w.registry.context
        if context == PHOTO:
            return self.photo()
        if context == VIDEO:
            return self.video()
        if context == VIDEO_EDITOR and self.w.video_editor is not None:
            editor = self.w.video_editor
            if editor.timeline.hasFocus():
                return self.timeline(None)
            return self.editor_preview()
        if context in (PHOTO_EDITOR, VIDEO_EDITOR):
            return self.editor_preview()
        return None

    # --- просмотр фото -----------------------------------------------------------------------

    def photo(self) -> ThemedMenu:
        menu = self._menu()
        self._add(menu, "next")
        self._add(menu, "prev")
        zoom = menu.submenu(self.tr("Масштаб"), "fit")
        for action_id in ("fit", "actual", "fill"):
            self._add(zoom, action_id)
        menu.addSeparator()
        for action_id in ("copy_image", "copy_file", "clean_copy", "edit", "fullscreen"):
            self._add(menu, action_id)
        self._file_group(menu)
        return menu

    # --- плеер видео -------------------------------------------------------------------------

    def video(self) -> ThemedMenu:
        menu = self._menu()
        page = self.w.video_page
        player = page.player if page is not None else None
        self._add(menu, "pause")
        speed = menu.submenu(self.tr("Скорость"), "next")
        current = player.speed if player is not None else 1.0
        group = QActionGroup(speed)
        for value in SPEEDS:
            speed.add_item(
                f"{value:g}×",
                partial(self._set_speed, value),
                checked=abs(value - current) < 1e-6,
                group=group,
            )
        tracks = player.tracks() if player is not None else []
        self._audio_menu(menu, tracks)
        self._subtitle_menu(menu, tracks, second=False)
        self._subtitle_menu(menu, tracks, second=True)
        self._add(menu, "loop", checked=bool(player and player.looping))
        shot = menu.submenu(self.tr("Снимок кадра"), "copy")
        self._add(shot, "screenshot_copy")
        self._add(shot, "screenshot_save")
        menu.addSeparator()
        self._add(menu, "edit")
        self._add(menu, "fullscreen")
        self._file_group(menu)
        return menu

    def _set_speed(self, value: float) -> None:
        if self.w.video_page is not None:
            self.w.video_page.player.set_speed(value)

    def _audio_menu(self, menu: ThemedMenu, tracks: list[Track]) -> None:
        sub = menu.submenu(self.tr("Аудиодорожка"), "audio_track")
        player = self.w.video_page.player if self.w.video_page is not None else None
        audio = of_kind(tracks, "audio")
        if not audio or player is None:
            sub.add_item(self.tr("Нет дорожек"), enabled=False)
            return
        group = QActionGroup(sub)
        current = player.audio_id()
        for track in audio:
            sub.add_item(
                track.label,
                partial(player.set_audio, track.id),
                checked=track.id == current,
                group=group,
            )

    def _subtitle_menu(self, menu: ThemedMenu, tracks: list[Track], *, second: bool) -> None:
        title = self.tr("Субтитры 2") if second else self.tr("Субтитры 1")
        sub = menu.submenu(title, "subtitles")
        player = self.w.video_page.player if self.w.video_page is not None else None
        if player is None:
            return
        current = player.sub2_id() if second else player.sub_id()
        other = player.sub_id() if second else player.sub2_id()
        apply: Callable[[int | None], None] = player.set_sub2 if second else player.set_sub
        group = QActionGroup(sub)
        sub.add_item(
            self.tr("Выключить"), (lambda: apply(None)), checked=current is None, group=group
        )
        for track in of_kind(tracks, "sub"):
            sub.add_item(
                track.label,
                partial(apply, track.id),
                checked=track.id == current,
                enabled=track.id != other,  # mpv не показывает одну дорожку в обеих строках
                group=group,
            )
        sub.addSeparator()
        sub.add_item(self.tr("Загрузить из файла…"), lambda: self._load_subtitles(second))

    def _load_subtitles(self, second: bool) -> None:
        page = self.w.video_page
        if page is None:
            return
        name, _ = QFileDialog.getOpenFileName(
            self.w,
            self.tr("Субтитры"),
            "",
            self.tr("Субтитры (%1)").replace("%1", SUBTITLE_FILTER),
        )
        if not name:
            return
        from pathlib import Path

        page.player.add_subtitle(Path(name), second=second)

    # --- редакторы ---------------------------------------------------------------------------

    def editor_preview(self) -> ThemedMenu:
        """Над превью: выделение (если есть), затем отмена, повтор, выход и сохранение."""
        menu = self._menu()
        w = self.w
        editor = w.editor if w.registry.context == PHOTO_EDITOR else w.video_editor
        if editor is None:
            return menu
        if editor.has_pending():
            self._add(menu, "apply")
            menu.add_item(self.tr("Отмена\tEsc"), editor.escape, icon="close")
            menu.add_item(self.tr("Сбросить выделение"), editor.reset_selection, icon="reset_trim")
            menu.addSeparator()
        self._add(menu, "undo", enabled=editor.session_can_undo())
        self._add(menu, "redo", enabled=editor.session_can_redo())
        menu.addSeparator()
        self._add(menu, "back_to_view")
        self._add(menu, "export" if w.registry.context == VIDEO_EDITOR else "save")
        return menu

    def timeline(self, payload: tuple[int | None, float | None] | None) -> ThemedMenu:
        """На полосе блоков: разрез, удаление, перестановка, возврат краёв, масштаб."""
        menu = self._menu()
        editor = self.w.video_editor
        if editor is None:
            return menu
        index, seconds = payload if payload is not None else (editor.selected_block, None)
        count = editor.block_count()
        menu.add_item(
            self.tr("Разрезать здесь") + "	K",
            lambda: editor.split_at(editor.playhead() if seconds is None else seconds),
            icon="scissors",
        )
        if index is not None:
            menu.add_item(
                self.tr("Удалить блок") + "	Del",
                lambda: editor.delete_block(index),
                icon="trash",
                enabled=count > 1,
            )
            menu.addSeparator()
            menu.add_item(
                self.tr("Влево"), lambda: editor.move_block_by(index, -1), icon="chevron_left",
                enabled=index > 0,
            )  # fmt: skip
            menu.add_item(
                self.tr("Вправо"), lambda: editor.move_block_by(index, 1), icon="chevron_right",
                enabled=index < count - 1,
            )  # fmt: skip
            menu.add_item(
                self.tr("Вернуть блок целиком"),
                lambda: editor.reset_block(index),
                icon="reset_trim",
                enabled=editor.block_is_trimmed(index),
            )
        menu.addSeparator()
        self._add(menu, "mark_in")
        self._add(menu, "mark_out")
        self._add(menu, "add_clip")
        if index is not None:
            menu.addSeparator()
            menu.add_item(
                self.tr("Показать в папке"), lambda: editor.reveal_block(index), icon="folder"
            )
        zoom = menu.submenu(self.tr("Масштаб полосы"), "zoom_in")
        for action_id in ("trim_zoom_in", "trim_zoom_out", "trim_fit"):
            self._add(zoom, action_id)
        return menu

    def effects(self, entries: list[tuple[EffectEntry, str]]) -> ThemedMenu:
        """На точке эффекта или в списке эффектов: удалить эффект."""
        menu = self._menu()
        editor = self.w.video_editor
        if editor is None:
            return menu
        if len(entries) == 1:
            entry, label = entries[0]
            menu.add_item(
                self.tr("Удалить эффект"), lambda: editor.remove_effect(entry), icon="trash"
            )
            return menu
        for entry, label in entries:
            menu.add_item(
                self.tr("Удалить: {0}").format(label),
                partial(editor.remove_effect, entry),
                icon="trash",
            )
        return menu
