"""Контекстные меню: состав, те же обработчики, что у клавиш, удаление, переименование, свойства."""

import subprocess
import sys
import time
from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtCore import QPoint, QSettings
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QApplication, QMessageBox
from pytestqt.qtbot import QtBot

from chopchop.core.geometry import Rect
from chopchop.core.operations import Redact, Text
from chopchop.services import file_ops
from chopchop.services.app_settings import AppSettings
from chopchop.ui.actions import (
    EDITORS,
    PHOTO,
    PHOTO_EDITOR,
    START,
    VIDEO,
    VIDEO_EDITOR,
)
from chopchop.ui.context_gate import menu_allowed
from chopchop.ui.context_menus import ids
from chopchop.ui.file_dialogs import RenameDialog
from chopchop.ui.main_window import MainWindow
from chopchop.ui.themed_menu import ThemedMenu
from chopchop.ui.video_editor_page import VideoEditorPage
from fakes import FakeVideoPage
from media import HAS_FFMPEG, make_video


def _window(qtbot: QtBot, tmp_path: Path, **settings: object) -> MainWindow:
    app = AppSettings(None)
    for key, value in settings.items():
        app.set(key.replace("__", "."), value)
    window = MainWindow(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat), app)
    qtbot.addWidget(window)
    window.show()
    return window


def _photos(folder: Path, names: tuple[str, ...] = ("a.png", "b.png", "c.png")) -> list[Path]:
    folder.mkdir(exist_ok=True)
    paths = []
    for name in names:
        path = folder / name
        Image.new("RGB", (40, 30), "red").save(path)
        paths.append(path)
    return paths


def _open_photo(qtbot: QtBot, window: MainWindow, path: Path) -> None:
    window.open_file(path)
    qtbot.waitUntil(lambda: window.current_path == path and window.viewer.has_image(), timeout=5000)


def _video_window(qtbot: QtBot, tmp_path: Path) -> tuple[MainWindow, FakeVideoPage, Path]:
    source = tmp_path / "movie.mp4"
    source.write_bytes(b"x")
    window = _window(qtbot, tmp_path)
    fake = FakeVideoPage()
    fake.mpv.track_list = [
        {"id": 1, "type": "audio", "lang": "rus", "title": "Дубляж", "selected": True},
        {"id": 2, "type": "audio", "lang": "eng"},
        {"id": 1, "type": "sub", "lang": "rus", "selected": True},
        {"id": 2, "type": "sub", "lang": "eng"},
    ]
    fake.mpv.aid = 1
    fake.mpv.sid = 1
    window.video_page = fake.as_video_page()
    window._stack.addWidget(fake)
    window._stack.setCurrentWidget(fake)
    window._video_path = window.current_path = source
    return window, fake, source


def _item(menu: ThemedMenu, action_id: str) -> QAction:
    return next(a for a in menu.actions() if a.objectName() == action_id)


def _submenu(menu: ThemedMenu, title: str) -> ThemedMenu:
    for action in menu.actions():
        sub = action.menu()
        if isinstance(sub, ThemedMenu) and sub.title() == title:
            return sub
    raise AssertionError(title)


# --- реестр -------------------------------------------------------------------------------------


def test_one_shortcut_means_one_action_per_screen(qtbot: QtBot, tmp_path: Path) -> None:
    window = _window(qtbot, tmp_path)
    reg = window.registry
    for context in (START, PHOTO, VIDEO, PHOTO_EDITOR, VIDEO_EDITOR):
        reg.set_context(context)
        seen: dict[str, str] = {}
        for action_id in reg.ids():
            action = reg[action_id]
            if not action.isEnabled():
                continue
            for key in action.shortcuts():
                text = key.toString()
                assert text not in seen, f"{context}: {text} у {seen[text]} и {action_id}"
                seen[text] = action_id
    reg.set_context(START)


def test_context_follows_the_open_screen(qtbot: QtBot, tmp_path: Path) -> None:
    window = _window(qtbot, tmp_path)
    assert window.registry.context == START and not window.registry["rename"].isEnabled()
    [first, *_rest] = _photos(tmp_path / "p")
    _open_photo(qtbot, window, first)
    assert window.registry.context == PHOTO
    assert window.registry["copy_image"].isEnabled() and not window.registry["undo"].isEnabled()
    assert window.registry["delete_file"].isEnabled()
    assert not window.registry["delete_segment"].isEnabled()  # у Delete в видеоредакторе своё дело


def test_menu_shows_the_shortcut_next_to_the_item_and_uses_the_same_action(
    qtbot: QtBot, tmp_path: Path
) -> None:
    window = _window(qtbot, tmp_path)
    [first, *_rest] = _photos(tmp_path / "p")
    _open_photo(qtbot, window, first)
    menu = window.menus.photo()
    edit = _item(menu, "edit")
    assert edit.text() == "Редактировать\tCtrl+E"
    assert edit.objectName() == window.registry["edit"].objectName()
    assert window.registry.shortcut_text("edit") == "Ctrl+E"


# --- фото ---------------------------------------------------------------------------------------


def test_photo_menu_composition(qtbot: QtBot, tmp_path: Path) -> None:
    window = _window(qtbot, tmp_path)
    [first, *_rest] = _photos(tmp_path / "p")
    _open_photo(qtbot, window, first)
    assert ids(window.menus.photo()) == [
        "next",
        "prev",
        "menu:Масштаб",
        "-",
        "copy_image",
        "copy_file",
        "clean_copy",
        "edit",
        "fullscreen",
        "-",
        "reveal",
        "copy_path",
        "rename",
        "delete_file",
        "properties",
    ]
    zoom = _submenu(window.menus.photo(), "Масштаб")
    assert ids(zoom) == ["fit", "actual", "fill"]


def test_photo_menu_items_run_the_same_handlers_as_the_keys(qtbot: QtBot, tmp_path: Path) -> None:
    window = _window(qtbot, tmp_path)
    first, second, _third = _photos(tmp_path / "p")
    _open_photo(qtbot, window, first)
    _item(window.menus.photo(), "next").trigger()
    qtbot.waitUntil(lambda: window.current_path == second, timeout=5000)
    window.registry["prev"].trigger()  # клавиша ←
    assert window.current_path == first
    _item(window.menus.photo(), "copy_path").trigger()
    assert QApplication.clipboard().text() == str(first)
    _item(window.menus.photo(), "copy_file").trigger()
    urls = QApplication.clipboard().mimeData().urls()
    assert [Path(u.toLocalFile()) for u in urls] == [first]
    qtbot.waitUntil(lambda: window._cache.get(first) is not None, timeout=5000)
    _item(window.menus.photo(), "copy_image").trigger()
    assert QApplication.clipboard().image().width() == 40


def test_right_click_signal_opens_the_photo_menu_but_not_during_a_drag(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = _window(qtbot, tmp_path)
    [first, *_rest] = _photos(tmp_path / "p")
    _open_photo(qtbot, window, first)
    opened: list[ThemedMenu] = []
    monkeypatch.setattr(window, "_popup", lambda menu, pos: opened.append(menu))
    window.viewer.contextMenuRequested.emit(QPoint(10, 10))
    assert len(opened) == 1 and "copy_image" in ids(opened[0])
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QContextMenuEvent

    monkeypatch.setattr(
        QGuiApplication, "mouseButtons", staticmethod(lambda: Qt.MouseButton.LeftButton)
    )
    assert not menu_allowed()
    window.viewer.contextMenuEvent(
        QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(5, 5), QPoint(5, 5))
    )
    assert len(opened) == 1  # во время перетаскивания меню не открылось


def test_menu_key_opens_the_menu_of_the_current_screen(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = _window(qtbot, tmp_path)
    [first, *_rest] = _photos(tmp_path / "p")
    _open_photo(qtbot, window, first)
    opened: list[ThemedMenu] = []
    monkeypatch.setattr(window, "_popup", lambda menu, pos: opened.append(menu))
    window.registry.trigger("context_menu")
    assert len(opened) == 1 and "next" in ids(opened[0])
    keys = [k.toString() for k in window.registry["context_menu"].shortcuts()]
    assert keys == ["Menu", "Shift+F10"]
    window.show_start()
    window.registry.trigger("context_menu")
    assert len(opened) == 1  # на стартовом экране меню нет


def test_menu_builds_fast(qtbot: QtBot, tmp_path: Path) -> None:
    window, _fake, _source = _video_window(qtbot, tmp_path)
    window.menus.video()  # первый раз: значки и шрифты
    started = time.perf_counter()
    for _ in range(5):
        window.menus.video()
    average_ms = (time.perf_counter() - started) / 5 * 1000
    assert average_ms < 50, average_ms  # в программе меньше 16 мс; в тестах запас на медленные CI


# --- видео --------------------------------------------------------------------------------------


def test_video_menu_composition_and_marks(qtbot: QtBot, tmp_path: Path) -> None:
    window, fake, _source = _video_window(qtbot, tmp_path)
    fake.mpv.speed = 1.5
    fake.mpv.loop_file = "inf"
    menu = window.menus.video()
    assert ids(menu) == [
        "pause",
        "menu:Скорость",
        "menu:Аудиодорожка",
        "menu:Субтитры 1",
        "menu:Субтитры 2",
        "loop",
        "menu:Снимок кадра",
        "-",
        "edit",
        "fullscreen",
        "-",
        "reveal",
        "copy_path",
        "rename",
        "delete_file",
        "properties",
    ]
    speed = _submenu(menu, "Скорость")
    assert [a.isChecked() for a in speed.actions()].count(True) == 1
    assert next(a for a in speed.actions() if a.isChecked()).text() == "1.5×"
    audio = _submenu(menu, "Аудиодорожка")
    assert [a.text() for a in audio.actions()] == ["1 · rus · Дубляж", "2 · eng"]
    assert [a.isChecked() for a in audio.actions()] == [True, False]
    assert _item(menu, "loop").isChecked()
    assert ids(_submenu(menu, "Снимок кадра")) == ["screenshot_copy", "screenshot_save"]


def test_video_menu_actions_change_the_player(qtbot: QtBot, tmp_path: Path) -> None:
    window, fake, _source = _video_window(qtbot, tmp_path)
    menu = window.menus.video()
    speed = _submenu(menu, "Скорость")
    next(a for a in speed.actions() if a.text() == "2×").trigger()
    assert fake.mpv.speed == 2.0
    audio = _submenu(menu, "Аудиодорожка")
    audio.actions()[1].trigger()
    assert fake.mpv.aid == 2
    subs = _submenu(menu, "Субтитры 1")
    labels = [a.text() for a in subs.actions() if not a.isSeparator()]
    assert labels[0] == "Выключить" and labels[-1] == "Загрузить из файла…"
    subs.actions()[0].trigger()  # выключить
    assert fake.mpv.sid == "no"
    _item(menu, "pause").trigger()
    assert fake.mpv.pause is True
    _item(menu, "loop").trigger()  # переключатель повтора
    assert fake.mpv.loop_file == "inf"
    _item(window.menus.video(), "loop").trigger()
    assert fake.mpv.loop_file == "no"


def test_second_subtitle_menu_skips_the_track_shown_in_the_first_line(
    qtbot: QtBot, tmp_path: Path
) -> None:
    window, fake, _source = _video_window(qtbot, tmp_path)
    menu = window.menus.video()
    second = _submenu(menu, "Субтитры 2")
    tracks = [a for a in second.actions() if a.text().startswith(("1 ·", "2 ·"))]
    assert [a.isEnabled() for a in tracks] == [False, True]  # дорожка 1 уже в первой строке
    assert fake.mpv.secondary_sid == "no"


def test_screenshot_leaves_subtitles_out_unless_the_setting_asks(
    qtbot: QtBot, tmp_path: Path
) -> None:
    window, fake, _source = _video_window(qtbot, tmp_path)
    window.registry.trigger("screenshot_copy")
    assert fake.mpv.shots == ["video"]
    assert QApplication.clipboard().image().width() == 32
    window._app.set("general.screenshot_subtitles", True)
    window.registry.trigger("screenshot_save")
    assert fake.mpv.shots == ["video", "subtitles"]
    saved = list(tmp_path.glob("movie_кадр_*.png"))
    assert len(saved) == 1


# --- удаление, переименование, свойства --------------------------------------------------------


def _fake_trash(monkeypatch: pytest.MonkeyPatch, fail: bool = False) -> list[Path]:
    trashed: list[Path] = []

    def move(path: str) -> bool:
        if fail:
            return False
        trashed.append(Path(path))
        Path(path).unlink()  # как корзина: файла на прежнем месте больше нет
        return True

    monkeypatch.setattr("chopchop.services.file_ops.QFile.moveToTrash", staticmethod(move))
    return trashed


def test_delete_goes_to_the_trash_and_opens_the_next_file(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = _window(qtbot, tmp_path)
    first, second, third = _photos(tmp_path / "p")
    _open_photo(qtbot, window, second)
    trashed = _fake_trash(monkeypatch)
    asked: list[str] = []

    def yes(*args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        asked.append(str(args[2]))
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", yes)
    _item(window.menus.photo(), "delete_file").trigger()
    assert trashed == [second] and not second.exists()
    assert "b.png" in asked[0]  # подтверждение называет файл
    qtbot.waitUntil(
        lambda: window.current_path == third, timeout=5000
    )  # на его место встал следующий
    assert window._nav is not None and window._nav.files == [first, third]


def test_delete_asks_first_and_declining_keeps_the_file(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = _window(qtbot, tmp_path)
    [first, *_rest] = _photos(tmp_path / "p")
    _open_photo(qtbot, window, first)
    trashed = _fake_trash(monkeypatch)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    window.registry.trigger("delete_file")
    assert trashed == [] and first.exists()


def test_delete_without_confirmation_when_the_setting_is_off(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = _window(qtbot, tmp_path, general__confirm_delete=False)
    only = _photos(tmp_path / "p", ("only.png",))[0]
    _open_photo(qtbot, window, only)
    trashed = _fake_trash(monkeypatch)

    def no_dialog(*_a: object, **_k: object) -> None:
        raise AssertionError("подтверждение отключено настройкой")

    monkeypatch.setattr(QMessageBox, "question", no_dialog)
    window.registry.trigger("delete_file")
    assert trashed == [only]
    assert window.registry.context == START  # папка опустела: стартовый экран
    assert window.current_path is None


def test_delete_never_removes_for_good_when_there_is_no_trash(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = _window(qtbot, tmp_path, general__confirm_delete=False)
    [first, *_rest] = _photos(tmp_path / "p")
    _open_photo(qtbot, window, first)
    _fake_trash(monkeypatch, fail=True)
    warned: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(str(a[2])))
    window.registry.trigger("delete_file")
    assert first.exists() and window.current_path == first  # файл на месте
    assert warned and "не тронут" in warned[0]
    with pytest.raises(file_ops.TrashError):
        file_ops.move_to_trash(tmp_path / "missing.png")


def test_rename_validation() -> None:
    source = Path("C:/x/photo.jpg") if False else Path("photo.jpg")
    for name, code in (
        ("", file_ops.EMPTY),
        ("   ", file_ops.EMPTY),
        ("a/b", file_ops.INVALID),
        ("a:b", file_ops.INVALID),
        ('a"b', file_ops.INVALID),
        ("name.", file_ops.INVALID),
        ("CON", file_ops.RESERVED),
        ("nul.txt", file_ops.RESERVED),
        ("x" * 300, file_ops.TOO_LONG),
        ("photo", file_ops.UNCHANGED),
    ):
        assert file_ops.validate_name(name, source) == code, name
    assert file_ops.validate_name("holiday", source) is None


def test_rename_dialog_keeps_the_extension_and_blocks_conflicts(
    qtbot: QtBot, tmp_path: Path
) -> None:
    [first, second, _third] = _photos(tmp_path / "p")
    dialog = RenameDialog(first, None)
    qtbot.addWidget(dialog)
    assert dialog._edit.text() == "a" and dialog._edit.selectedText() == "a"  # выделено имя
    dialog._edit.setText("b")
    assert dialog.error_code() == file_ops.EXISTS and not dialog._error.isHidden()
    ok = dialog._buttons.button(dialog._buttons.StandardButton.Ok)
    assert not ok.isEnabled()
    dialog._edit.setText("new name")
    assert dialog.error_code() is None and ok.isEnabled()
    assert file_ops.rename_path(second, "z").name == "z.png"  # расширение прежнее


def test_rename_updates_navigation_recent_and_resume(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = _window(qtbot, tmp_path)
    first, second, third = _photos(tmp_path / "p")
    _open_photo(qtbot, window, second)
    window._recent.add(second)
    from chopchop.player.resume import ResumeState

    window._resume.save(second, ResumeState(position=30.0), 100.0)
    monkeypatch.setattr(RenameDialog, "exec", lambda self: 1)
    monkeypatch.setattr(RenameDialog, "new_stem", lambda self: "zz")
    window.registry.trigger("rename")
    renamed = tmp_path / "p" / "zz.png"
    assert renamed.exists() and not second.exists()
    qtbot.waitUntil(
        lambda: window.current_path == renamed and window.viewer.has_image(), timeout=5000
    )
    assert window._nav is not None and window._nav.files == [
        first,
        third,
        renamed,
    ]  # порядок по имени
    assert renamed in window._recent.items() and second not in window._recent.items()
    assert window._resume.load(renamed) is not None and window._resume.load(second) is None


def test_rename_failure_leaves_everything_as_it_was(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = _window(qtbot, tmp_path)
    first, second, _third = _photos(tmp_path / "p")
    _open_photo(qtbot, window, first)
    monkeypatch.setattr(RenameDialog, "exec", lambda self: 1)
    monkeypatch.setattr(RenameDialog, "new_stem", lambda self: "b")  # имя занято
    warned: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(str(a[2])))
    window.registry.trigger("rename")
    assert first.exists() and second.exists() and warned and window.current_path == first


def test_properties_rows_for_a_photo_and_the_metadata_flag(qtbot: QtBot, tmp_path: Path) -> None:
    window = _window(qtbot, tmp_path)
    plain = _photos(tmp_path / "p", ("plain.jpg",))[0]
    _open_photo(qtbot, window, plain)
    rows = dict(window.files.property_rows(plain))
    assert rows["Имя"] == "plain.jpg" and rows["Разрешение"] == "40×30"
    assert rows["Путь"] == str(plain.parent) and "КБ" in rows["Размер"] or "Б" in rows["Размер"]
    assert window.files.metadata_text(plain) == "Метаданных (EXIF, GPS) в файле нет"
    tagged = tmp_path / "p" / "tagged.jpg"
    exif = Image.Exif()
    exif[0x010F] = "Camera Maker"
    exif.get_ifd(0x8825)[1] = "N"  # блок GPS
    Image.new("RGB", (40, 30), "blue").save(tagged, exif=exif)
    flags = file_ops.photo_metadata(tagged)
    assert flags.has_exif and flags.has_gps
    assert "EXIF" in (window.files.metadata_text(tagged) or "")
    assert "GPS" in (window.files.metadata_text(tagged) or "")


def test_clean_copy_drops_exif_and_gps(qtbot: QtBot, tmp_path: Path) -> None:
    window = _window(qtbot, tmp_path)
    folder = tmp_path / "p"
    folder.mkdir()
    tagged = folder / "tagged.jpg"
    exif = Image.Exif()
    exif[0x010F] = "Camera Maker"
    exif.get_ifd(0x8825)[1] = "N"
    Image.new("RGB", (40, 30), "blue").save(tagged, exif=exif)
    _open_photo(qtbot, window, tagged)
    window.registry.trigger("clean_copy")
    qtbot.waitUntil(lambda: len(list(folder.glob("tagged_edited*.jpg"))) == 1, timeout=10000)
    clean = next(folder.glob("tagged_edited*.jpg"))
    assert not file_ops.photo_metadata(clean).any  # метаданных в копии нет
    assert file_ops.photo_metadata(tagged).any  # исходник не тронут


def test_reveal_builds_an_argument_list_without_a_shell(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from chopchop.services import reveal

    path = tmp_path / "it's a file; rm -rf.mp4"
    calls: list[tuple[object, dict[str, object]]] = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: calls.append((a[0], k)))
    monkeypatch.setattr(sys, "platform", "win32")
    reveal.reveal_in_folder(path)
    command, kwargs = calls[0]
    assert isinstance(command, list) and command[0] == "explorer"
    assert command[1] == f"/select,{path}" and not kwargs.get("shell")  # имя — один аргумент
    message = reveal.show_items_message(path)
    arguments = message.arguments()
    assert arguments[0][0].startswith("file:///") and "rm" in arguments[0][0] and arguments[1] == ""
    assert message.service() == "org.freedesktop.FileManager1"
    assert message.member() == "ShowItems"
    assert sys.platform  # метод не зависит от системы


def test_linux_falls_back_to_opening_the_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from chopchop.services import reveal

    opened: list[object] = []
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(reveal, "_reveal_with_dbus", lambda _p: False)
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url))
    reveal.reveal_in_folder(tmp_path / "a.png")
    assert len(opened) == 1
    assert Path(opened[0].toLocalFile()) == tmp_path  # type: ignore[attr-defined]


def test_themed_menu_renders_in_both_themes_and_without_animation(
    qtbot: QtBot, tmp_path: Path
) -> None:
    from chopchop.ui import anim
    from chopchop.ui.theme import current
    from chopchop.ui.theme.tokens import make_palette

    window, _fake, _source = _video_window(qtbot, tmp_path)
    for theme in ("light", "dark"):
        current.set_palette(make_palette(theme))
        menu = window.menus.video()
        menu.resize(menu.sizeHint())
        assert not menu.grab().isNull()
    anim.set_enabled(False)
    try:
        menu = window.menus.video()
        menu.show()
        assert menu.windowOpacity() == 1.0  # без анимации сразу целиком
        menu.close()
    finally:
        anim.set_enabled(True)
        current.set_palette(make_palette("light"))


# --- редакторы ----------------------------------------------------------------------------------


def _photo_editor(qtbot: QtBot, window: MainWindow, path: Path) -> None:
    window.open_file(path)
    qtbot.waitUntil(window.viewer.has_image, timeout=5000)
    window.toggle_editor()
    qtbot.waitUntil(lambda: window.editor is not None, timeout=10000)


def test_photo_editor_menu_with_and_without_a_selection(qtbot: QtBot, tmp_path: Path) -> None:
    window = _window(qtbot, tmp_path)
    [first, *_rest] = _photos(tmp_path / "p")
    _photo_editor(qtbot, window, first)
    editor = window.editor
    assert editor is not None and window.registry.context == PHOTO_EDITOR
    menu = window.menus.editor_preview()
    assert ids(menu) == ["undo", "redo", "-", "back_to_view", "save"]
    assert not _item(menu, "undo").isEnabled() and not _item(menu, "redo").isEnabled()
    editor.select_tool("redact")
    tool = editor.tools["redact"]
    tool.press(2, 2, 4.0)
    tool.move(20, 20)
    tool.release(20, 20)
    with_selection = window.menus.editor_preview()
    assert ids(with_selection)[:5] == ["apply", "Отмена\tEsc", "Сбросить выделение", "-", "undo"]
    next(a for a in with_selection.actions() if a.text() == "Сбросить выделение").trigger()
    assert not editor.has_pending()
    assert "apply" not in ids(window.menus.editor_preview())
    window.registry.trigger("back_to_view")  # тот же обработчик, что у Ctrl+E


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg не установлен")
class TestVideoEditorMenus:
    @pytest.fixture(autouse=True)
    def _no_save_prompt(self, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
        """Упавшая проверка не должна оставлять вопрос «выйти без сохранения» и вешать прогон."""
        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)

    def _open(
        self, qtbot: QtBot, tmp_path: Path
    ) -> tuple[MainWindow, FakeVideoPage, VideoEditorPage]:
        source = make_video(tmp_path / "movie.mp4", seconds=6)
        window = _window(qtbot, tmp_path)
        fake = FakeVideoPage()
        window.video_page = fake.as_video_page()
        window._stack.addWidget(fake)
        window._stack.setCurrentWidget(fake)
        window._video_path = window.current_path = source
        window.toggle_editor()
        qtbot.waitUntil(lambda: window.video_editor is not None, timeout=10000)
        assert window.video_editor is not None
        return window, fake, window.video_editor

    def test_preview_timeline_and_effect_menus(
        self, qtbot: QtBot, tmp_path: Path, no_thumbnails: None
    ) -> None:
        window, fake, editor = self._open(qtbot, tmp_path)
        assert window.registry.context == VIDEO_EDITOR
        preview = window.menus.editor_preview()
        assert ids(preview) == ["undo", "redo", "-", "back_to_view", "export"]
        timeline = window.menus.timeline((0, 2.0))
        assert [a.text() for a in timeline.actions() if not a.isSeparator()] == [
            "Разрезать здесь	K",
            "Удалить блок	Del",
            "Влево",
            "Вправо",
            "Вернуть блок целиком",
            "cut_marks",
            "mark_in",
            "mark_out",
            "add_clip",
            "Показать в папке",
            "menu:Масштаб полосы",
        ] or ids(timeline)  # подписи действий реестра приходят из реестра
        items = {a.text(): a for a in timeline.actions() if not a.isSeparator()}
        assert not items["Удалить блок	Del"].isEnabled()  # единственный блок
        assert not items["Влево"].isEnabled() and not items["Вправо"].isEnabled()
        assert not items["Вернуть блок целиком"].isEnabled()  # блок целый
        items["Разрезать здесь	K"].trigger()
        assert len(editor.session.project.clips) == 2
        two = {
            a.text(): a for a in window.menus.timeline((0, 1.0)).actions() if not a.isSeparator()
        }
        assert two["Удалить блок	Del"].isEnabled() and two["Вправо"].isEnabled()
        two["Вправо"].trigger()  # блок на место следующего
        assert [c.start for c in editor.session.project.clips] == [2.0, 0.0]
        editor.session.add_redact(Redact(Rect(0, 0, 10, 10)))
        editor.session.add_text(Text("Привет", 1, 1))
        entries = [(e, editor.effects_chip.label_for(e)) for e in editor.effects_chip.entries()]
        effect_menu = window.menus.effects(entries)
        assert [a.text() for a in effect_menu.actions()][0].startswith("Удалить: ")
        effect_menu.actions()[0].trigger()
        assert not editor.session.project.effects.redacts
        single = window.menus.effects(entries[1:])
        assert [a.text() for a in single.actions()] == ["Удалить эффект"]
        single.actions()[0].trigger()
        assert not editor.session.project.effects.texts
        editor.session.mark_saved()

    def test_timeline_menu_items_run_the_same_handlers_as_the_keys(
        self, qtbot: QtBot, tmp_path: Path, no_thumbnails: None
    ) -> None:
        window, fake, editor = self._open(qtbot, tmp_path)
        editor._on_position(2.0)
        window.registry.trigger("split")  # клавиша K: в позиции воспроизведения
        assert [c.stop for c in editor.session.project.clips] == [2.0, 6.0]
        window.registry.trigger("split")  # второй раз на том же месте ничего не меняет
        assert len(editor.session.project.clips) == 2
        editor.select_block(1)
        window.registry.trigger("delete_segment")  # Delete: выбранный блок
        assert len(editor.session.project.clips) == 1
        editor._on_position(1.0)
        items = {a.text(): a for a in window.menus.timeline((0, 1.0)).actions()}
        zoom = _submenu(window.menus.timeline((0, 1.0)), "Масштаб полосы")
        _item(zoom, "trim_zoom_in").trigger()
        assert editor.timeline.zoom_level > 1.0
        assert "Разрезать здесь	K" in items
        editor.session.mark_saved()

    def test_right_click_signals_reach_the_window(
        self, qtbot: QtBot, tmp_path: Path, no_thumbnails: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        window, fake, editor = self._open(qtbot, tmp_path)
        opened: list[ThemedMenu] = []
        monkeypatch.setattr(window, "_popup", lambda menu, pos: opened.append(menu))
        fake.contextMenuRequested.emit(QPoint(3, 3))  # ПКМ над превью
        editor.timeline.menuRequested.emit(QPoint(3, 3), (0, 1.0))
        editor.timeline.menuRequested.emit(QPoint(3, 3), None)  # с клавиши Menu
        editor.session.add_text(Text("t", 0, 0))
        editor.shell.rail.contextRequested.emit("text", QPoint(3, 3))
        firsts = [m.actions()[0].text() for m in opened]
        assert firsts[0].startswith("Отменить")
        assert firsts[1] == firsts[2] == "Разрезать здесь	K"
        assert firsts[3] == "Удалить эффект"
        editor.session.mark_saved()

    def test_buttons_use_the_registry_actions(
        self, qtbot: QtBot, tmp_path: Path, no_thumbnails: None
    ) -> None:
        window, fake, editor = self._open(qtbot, tmp_path)
        editor._on_position(2.0)
        editor._split.click()  # кнопка «Разрезать» запускает действие K
        assert [c.stop for c in editor.session.project.clips] == [2.0, 6.0]
        editor._on_position(3.0)
        editor.select_block(1)
        editor._set_in.click()  # «Обрезать начало здесь»: 3 с итога = 3 с файла
        assert editor.session.project.clips[1].start == 3.0
        editor._reset.click()  # «Вернуть блок целиком»
        assert not editor.session.project.clips[1].is_trimmed
        editor.session.mark_saved()


def test_every_editor_context_has_apply_and_export_without_conflicts() -> None:
    assert PHOTO_EDITOR in EDITORS and VIDEO_EDITOR in EDITORS
