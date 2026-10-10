"""Единый реестр действий: меню, горячие клавиши, кнопки панелей и контекстные меню.

Каждое действие создаётся один раз как `QAction` со своим идентификатором, текстом, значком и
горячей клавишей. Дальше им пользуются все: строка меню, контекстное меню, кнопки панелей
(`bind`) и сами клавиши. Одинаковые сочетания у разных действий (Ctrl+C, Delete) не конфликтуют,
потому что у действия есть контексты: включено оно только на «своих» экранах (`set_context`).
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QAbstractButton, QWidget

from chopchop.ui.theme import current, icons

Shortcut = QKeySequence.StandardKey | Qt.Key | str

# экраны, на которых работают действия
PHOTO = "photo"
VIDEO = "video"
PHOTO_EDITOR = "photo_editor"
VIDEO_EDITOR = "video_editor"
START = "start"
ALL = frozenset({PHOTO, VIDEO, PHOTO_EDITOR, VIDEO_EDITOR, START})
EDITORS = frozenset({PHOTO_EDITOR, VIDEO_EDITOR})
VIEWING = frozenset({PHOTO, VIDEO})


@dataclass
class ActionInfo:
    """Описание действия: нужно меню, чтобы показывать значок и скрывать неприменимое."""

    contexts: frozenset[str]
    icon: str | None = None


class ActionRegistry(QObject):
    """Действия окна по идентификаторам."""

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self._window = window
        self._actions: dict[str, QAction] = {}
        self._info: dict[str, ActionInfo] = {}
        self._context = START

    # --- создание ----------------------------------------------------------------------------

    def add(
        self,
        action_id: str,
        text: str,
        shortcut: Shortcut | Iterable[Shortcut] | None = None,
        slot: Callable[[], object] | None = None,
        *,
        icon: str | None = None,
        contexts: Iterable[str] = ALL,
        checkable: bool = False,
        in_window: bool = True,
    ) -> QAction:
        """Новое действие. Горячие клавиши работают во всём окне (`in_window`)."""
        if action_id in self._actions:
            raise ValueError(f"действие {action_id} уже есть")
        action = QAction(text, self._window)
        action.setObjectName(action_id)
        action.setCheckable(checkable)
        action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        keys = self._keys(shortcut)
        if keys:
            action.setShortcuts(keys)
        if slot is not None:
            action.triggered.connect(lambda _checked=False: slot())
        if in_window:
            self._window.addAction(action)
        self._actions[action_id] = action
        self._info[action_id] = ActionInfo(frozenset(contexts), icon)
        if icon:
            action.setIcon(icons.qicon(icon, current.palette(), logical=32))
        return action

    @staticmethod
    def _keys(shortcut: Shortcut | Iterable[Shortcut] | None) -> list[QKeySequence]:
        if shortcut is None or shortcut == "":
            return []
        if isinstance(shortcut, str | Qt.Key | QKeySequence.StandardKey):
            return [QKeySequence(shortcut)]
        return [QKeySequence(item) for item in shortcut]

    # --- доступ ------------------------------------------------------------------------------

    def __contains__(self, action_id: str) -> bool:
        return action_id in self._actions

    def __getitem__(self, action_id: str) -> QAction:
        return self._actions[action_id]

    def ids(self) -> list[str]:
        return list(self._actions)

    def info(self, action_id: str) -> ActionInfo:
        return self._info[action_id]

    def shortcut_text(self, action_id: str) -> str:
        return self._actions[action_id].shortcut().toString(QKeySequence.SequenceFormat.NativeText)

    def trigger(self, action_id: str) -> None:
        self._actions[action_id].trigger()

    # --- контексты ---------------------------------------------------------------------------

    @property
    def context(self) -> str:
        return self._context

    def set_context(self, context: str) -> None:
        """Включает действия текущего экрана и выключает чужие (в том числе их клавиши)."""
        self._context = context
        for action_id, action in self._actions.items():
            action.setEnabled(context in self._info[action_id].contexts)

    def applies(self, action_id: str, context: str | None = None) -> bool:
        return (context or self._context) in self._info[action_id].contexts

    def refresh_icons(self) -> None:
        """Тема сменилась: значки действий перекрашиваются."""
        for action_id, action in self._actions.items():
            name = self._info[action_id].icon
            if name:
                action.setIcon(icons.qicon(name, current.palette(), logical=32))

    # --- кнопки ------------------------------------------------------------------------------

    def bind(self, button: QAbstractButton, action_id: str) -> None:
        """Кнопка панели запускает то же действие. Доступность кнопки решает сама панель:
        «Отменить» серая, пока нечего отменять, а действие в реестре от этого не выключается."""
        action = self._actions[action_id]
        button.clicked.connect(lambda _checked=False: action.trigger())
