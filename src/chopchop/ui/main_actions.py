"""Все действия главного окна в одном реестре: меню, клавиши, кнопки и контекстные меню."""

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QKeySequence

from chopchop.player.player import Player
from chopchop.ui.actions import (
    ALL,
    EDITORS,
    PHOTO,
    PHOTO_EDITOR,
    VIDEO,
    VIDEO_EDITOR,
    VIEWING,
    ActionRegistry,
)

if TYPE_CHECKING:
    from chopchop.ui.main_window import MainWindow


PLAYING = frozenset({VIDEO, VIDEO_EDITOR})
SEEKING = frozenset({PHOTO, VIDEO, VIDEO_EDITOR})


def build_registry(window: "MainWindow") -> ActionRegistry:
    """Создаёт и возвращает реестр; обработчики — методы окна, те же для меню и клавиш."""
    reg = ActionRegistry(window)
    w = window

    def player(do: Callable[[Player], object]) -> Callable[[], object]:
        return lambda: w._with_player(do)

    def editor(do: Callable[..., object]) -> Callable[[], object]:
        return lambda: w._with_editor(do)

    def video_editor(do: Callable[..., object]) -> Callable[[], object]:
        return lambda: w._with_video_editor(do)

    add = reg.add
    # --- файл
    add(
        "open",
        QCoreApplication.translate("MainWindow", "Открыть…"),
        QKeySequence.StandardKey.Open,
        w.choose_file,
        icon="open",
    )
    add(
        "settings",
        QCoreApplication.translate("MainWindow", "Настройки…"),
        "",
        w.show_settings,
        icon="settings",
    )
    add("quit", QCoreApplication.translate("MainWindow", "Выход"), "Ctrl+Q", w.close, icon="close")
    # --- переход между просмотром и редактором
    add(
        "edit",
        QCoreApplication.translate("MainWindow", "Редактировать"),
        "Ctrl+E",
        w.toggle_editor,
        icon="edit",
        contexts=VIEWING,
    )
    add(
        "back_to_view",
        QCoreApplication.translate("MainWindow", "К просмотру"),
        "Ctrl+E",
        w.toggle_editor,
        icon="back_to_view",
        contexts=EDITORS,
    )
    add(
        "paste_image",
        QCoreApplication.translate("MainWindow", "Вставить картинку из буфера"),
        "Ctrl+V",
        w.paste_image,
        icon="paste",
    )
    # --- правка
    add(
        "undo",
        QCoreApplication.translate("MainWindow", "Отменить"),
        "Ctrl+Z",
        editor(lambda e: e.undo()),
        icon="undo",
        contexts=EDITORS,
    )
    add(
        "redo",
        QCoreApplication.translate("MainWindow", "Повторить"),
        "Ctrl+Y",
        editor(lambda e: e.redo()),
        icon="redo",
        contexts=EDITORS,
    )
    add(
        "copy_result",
        QCoreApplication.translate("MainWindow", "Копировать результат"),
        "Ctrl+C",
        w._copy,
        icon="copy",
        contexts=EDITORS,
    )
    add(
        "save",
        QCoreApplication.translate("MainWindow", "Сохранить"),
        "Ctrl+S",
        editor(lambda e: e.save_quick()),
        icon="save",
        contexts={PHOTO_EDITOR},
    )
    add(
        "export",
        QCoreApplication.translate("MainWindow", "Экспорт…"),
        "Ctrl+S",
        editor(lambda e: e.save_quick()),
        icon="save",
        contexts={VIDEO_EDITOR},
    )
    add(
        "save_as",
        QCoreApplication.translate("MainWindow", "Сохранить как…"),
        "Ctrl+Shift+S",
        editor(lambda e: e.save_as()),
        icon="save_as",
        contexts=EDITORS,
    )
    add(
        "apply",
        QCoreApplication.translate("MainWindow", "Применить"),
        [Qt.Key.Key_Return, Qt.Key.Key_Enter],
        editor(lambda e: e.apply_pending()),
        icon="check",
        contexts=EDITORS,
    )
    for key, tool, name, icon in (
        ("C", "crop", QCoreApplication.translate("MainWindow", "Кадрировать"), "crop"),
        ("R", "rotate", QCoreApplication.translate("MainWindow", "Повернуть"), "rotate"),
        ("B", "redact", QCoreApplication.translate("MainWindow", "Скрыть область"), "redact"),
        ("D", "draw", QCoreApplication.translate("MainWindow", "Рисовать"), "brush"),
        ("T", "text", QCoreApplication.translate("MainWindow", "Текст"), "text"),
    ):
        add(f"tool_{tool}", name, key, w._tool_slot(tool), icon=icon, contexts=EDITORS)
    # --- листание и воспроизведение
    add(
        "next",
        QCoreApplication.translate("MainWindow", "Следующее"),
        Qt.Key.Key_Right,
        lambda: w._horizontal(1),
        icon="next",
        contexts=SEEKING,
    )
    add(
        "prev",
        QCoreApplication.translate("MainWindow", "Предыдущее"),
        Qt.Key.Key_Left,
        lambda: w._horizontal(-1),
        icon="previous",
        contexts=SEEKING,
    )
    step = w._app.get_int
    add(
        "vol_up",
        QCoreApplication.translate("MainWindow", "Громче"),
        Qt.Key.Key_Up,
        lambda: w._volume(step("playback.volume_step")),
        contexts=PLAYING,
    )
    add(
        "vol_down",
        QCoreApplication.translate("MainWindow", "Тише"),
        Qt.Key.Key_Down,
        lambda: w._volume(-step("playback.volume_step")),
        contexts=PLAYING,
    )
    add(
        "seek_fwd",
        QCoreApplication.translate("MainWindow", "Перемотка вперёд"),
        "Shift+Right",
        lambda: w._seek_long(1),
        contexts=PLAYING,
    )
    add(
        "seek_back",
        QCoreApplication.translate("MainWindow", "Перемотка назад"),
        "Shift+Left",
        lambda: w._seek_long(-1),
        contexts=PLAYING,
    )
    add(
        "slower",
        QCoreApplication.translate("MainWindow", "Медленнее"),
        "[",
        player(lambda p: w._change_speed(p, -1)),
        contexts=PLAYING,
    )
    add(
        "faster",
        QCoreApplication.translate("MainWindow", "Быстрее"),
        "]",
        player(lambda p: w._change_speed(p, 1)),
        contexts=PLAYING,
    )
    add(
        "speed_reset",
        QCoreApplication.translate("MainWindow", "Обычная скорость"),
        "Backspace",
        player(w._reset_speed),
        contexts=PLAYING,
    )
    add(
        "pause",
        QCoreApplication.translate("MainWindow", "Пауза и воспроизведение"),
        "Space",
        player(lambda p: p.toggle_pause()),
        icon="play",
        contexts=PLAYING,
    )
    add(
        "audio_cycle",
        QCoreApplication.translate("MainWindow", "Следующая аудиодорожка"),
        "A",
        player(lambda p: p.cycle_audio()),
        icon="audio_track",
        contexts=PLAYING,
    )
    add(
        "sub1",
        QCoreApplication.translate("MainWindow", "Субтитры 1"),
        "S",
        player(lambda p: p.cycle_sub()),
        icon="subtitles",
        contexts=PLAYING,
    )
    add(
        "sub2",
        QCoreApplication.translate("MainWindow", "Субтитры 2"),
        "Shift+S",
        player(lambda p: p.cycle_sub2()),
        icon="subtitles",
        contexts=PLAYING,
    )
    add(
        "sub1_earlier",
        QCoreApplication.translate("MainWindow", "Субтитры 1 раньше"),
        "Z",
        player(lambda p: p.shift_sub(-1)),
        contexts=PLAYING,
    )
    add(
        "sub1_later",
        QCoreApplication.translate("MainWindow", "Субтитры 1 позже"),
        "X",
        player(lambda p: p.shift_sub(1)),
        contexts=PLAYING,
    )
    add(
        "sub2_earlier",
        QCoreApplication.translate("MainWindow", "Субтитры 2 раньше"),
        "Shift+Z",
        player(lambda p: p.shift_sub2(-1)),
        contexts=PLAYING,
    )
    add(
        "sub2_later",
        QCoreApplication.translate("MainWindow", "Субтитры 2 позже"),
        "Shift+X",
        player(lambda p: p.shift_sub2(1)),
        contexts=PLAYING,
    )
    add(
        "loop",
        QCoreApplication.translate("MainWindow", "Повтор"),
        "L",
        w.files.toggle_loop,
        icon="rotate",
        contexts={VIDEO},
        checkable=True,
    )
    add(
        "fullscreen",
        QCoreApplication.translate("MainWindow", "Полный экран"),
        [Qt.Key.Key_F, Qt.Key.Key_F11],
        w.toggle_fullscreen,
        icon="fullscreen",
        contexts=VIEWING,
    )
    add(
        "escape",
        QCoreApplication.translate("MainWindow", "Выйти из полного экрана"),
        Qt.Key.Key_Escape,
        w._escape,
        contexts=ALL,
    )
    # --- масштаб фото
    add(
        "fit",
        QCoreApplication.translate("MainWindow", "Вписать в окно"),
        "Ctrl+0",
        lambda: w.viewer.fit_to_window(),
        icon="fit",
        contexts={PHOTO},
    )
    add(
        "actual",
        QCoreApplication.translate("MainWindow", "Масштаб 100%"),
        "Ctrl+1",
        w.viewer.actual_size,
        icon="zoom_in",
        contexts={PHOTO},
    )
    add(
        "fill",
        QCoreApplication.translate("MainWindow", "Заполнить окно"),
        "",
        lambda: w.viewer.fit_to_window(True),
        icon="zoom_out",
        contexts={PHOTO},
    )
    # --- обрезка и вырезы в видеоредакторе
    ve = video_editor
    add(
        "mark_in",
        QCoreApplication.translate("MainWindow", "Обрезать начало здесь"),
        "I",
        ve(lambda e: e.set_in()),
        icon="mark_in",
        contexts={VIDEO_EDITOR},
    )
    add(
        "mark_out",
        QCoreApplication.translate("MainWindow", "Обрезать конец здесь"),
        "O",
        ve(lambda e: e.set_out()),
        icon="mark_out",
        contexts={VIDEO_EDITOR},
    )
    add(
        "split",
        QCoreApplication.translate("MainWindow", "Разрезать здесь"),
        "K",
        ve(lambda e: e.split_here()),
        icon="scissors",
        contexts={VIDEO_EDITOR},
    )
    add(
        "delete_segment",
        QCoreApplication.translate("MainWindow", "Удалить блок"),
        Qt.Key.Key_Delete,
        ve(lambda e: e.delete_selected()),
        icon="trash",
        contexts={VIDEO_EDITOR},
    )
    add(
        "add_clip",
        QCoreApplication.translate("MainWindow", "Добавить клип…"),
        "",
        ve(lambda e: e.add_clip()),
        icon="add_clip",
        contexts={VIDEO_EDITOR},
    )
    add(
        "cut_marks",
        QCoreApplication.translate("MainWindow", "Вырезать выделение"),
        "Ctrl+X",
        ve(lambda e: e.cut_marks()),
        icon="trim",
        contexts={VIDEO_EDITOR},
    )
    add(
        "reset_trim",
        QCoreApplication.translate("MainWindow", "Вернуть блок целиком"),
        "",
        ve(lambda e: e.reset_trim()),
        icon="reset_trim",
        contexts={VIDEO_EDITOR},
    )
    add(
        "trim_zoom_in",
        QCoreApplication.translate("MainWindow", "Увеличить полосу"),
        "",
        ve(lambda e: e.timeline.zoom_in()),
        icon="zoom_in",
        contexts={VIDEO_EDITOR},
    )
    add(
        "trim_zoom_out",
        QCoreApplication.translate("MainWindow", "Уменьшить полосу"),
        "",
        ve(lambda e: e.timeline.zoom_out()),
        icon="zoom_out",
        contexts={VIDEO_EDITOR},
    )
    add(
        "trim_fit",
        QCoreApplication.translate("MainWindow", "Вписать полосу целиком"),
        "",
        ve(lambda e: e.timeline.fit()),
        icon="fit",
        contexts={VIDEO_EDITOR},
    )
    # --- файл: то, что есть у открытого фото и видео
    files = w.files
    add(
        "copy_image",
        QCoreApplication.translate("MainWindow", "Копировать изображение"),
        "Ctrl+C",
        files.copy_image,
        icon="copy",
        contexts={PHOTO},
    )
    add(
        "copy_file",
        QCoreApplication.translate("MainWindow", "Копировать как файл"),
        "",
        files.copy_file,
        icon="copy",
        contexts={PHOTO},
    )
    add(
        "clean_copy",
        QCoreApplication.translate("MainWindow", "Сохранить копию без метаданных"),
        "",
        files.clean_copy,
        icon="save_as",
        contexts={PHOTO},
    )
    add(
        "reveal",
        QCoreApplication.translate("MainWindow", "Показать в папке"),
        "",
        files.reveal,
        icon="folder",
        contexts=VIEWING,
    )
    add(
        "copy_path",
        QCoreApplication.translate("MainWindow", "Копировать путь"),
        "",
        files.copy_path,
        icon="copy",
        contexts=VIEWING,
    )
    add(
        "rename",
        QCoreApplication.translate("MainWindow", "Переименовать…"),
        "F2",
        files.rename,
        icon="edit",
        contexts=VIEWING,
    )
    add(
        "delete_file",
        QCoreApplication.translate("MainWindow", "Удалить"),
        Qt.Key.Key_Delete,
        files.delete,
        icon="trash",
        contexts=VIEWING,
    )
    add(
        "properties",
        QCoreApplication.translate("MainWindow", "Свойства"),
        "Alt+Return",
        files.properties,
        icon="info",
        contexts=VIEWING,
    )
    add(
        "screenshot_copy",
        QCoreApplication.translate("MainWindow", "Копировать кадр"),
        "",
        files.screenshot_copy,
        icon="copy",
        contexts={VIDEO},
    )
    add(
        "screenshot_save",
        QCoreApplication.translate("MainWindow", "Сохранить кадр в файл"),
        "",
        files.screenshot_save,
        icon="save",
        contexts={VIDEO},
    )
    return reg
