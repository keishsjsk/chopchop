from pathlib import Path

import pytest
from PySide6.QtWidgets import QPushButton, QWidget
from pytestqt.qtbot import QtBot

from quickedit.core.document import AudioInfo, MediaInfo
from quickedit.core.geometry import Rect
from quickedit.core.operations import Redact, Text
from quickedit.core.video import Clip, VideoProject
from quickedit.editor.video_session import VideoSession
from quickedit.ui.tools.crop_tool import CropTool
from quickedit.ui.tools.redact_tool import RedactTool
from quickedit.ui.tools.text_tool import TextTool
from quickedit.ui.video_effects_panel import VideoEffectsPanel
from quickedit.ui.video_overlay import VideoOverlay

INFO = MediaInfo(640, 360, 30.0, 25.0, "h264", "yuv420p", 0, AudioInfo("aac", 44100, 2))


def _panel(qtbot: QtBot) -> tuple[VideoEffectsPanel, VideoSession]:
    session = VideoSession(VideoProject((Clip(Path("a.mp4"), INFO),)))
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(800, 500)
    overlay = VideoOverlay(host, session.project.frame_size)
    panel = VideoEffectsPanel(session, overlay)
    qtbot.addWidget(panel)
    panel.show()
    session.changed.connect(panel.refresh)
    return panel, session


def _drag(tool: object, a: tuple[float, float], b: tuple[float, float]) -> None:
    assert isinstance(tool, CropTool | RedactTool)
    tool.press(*a, 4.0)
    tool.move(*b)
    tool.release(*b)


def test_tools_know_the_frame_size(qtbot: QtBot) -> None:
    panel, _session = _panel(qtbot)
    assert all(tool.bounds == (640.0, 360.0) for tool in panel.tools.values())


def test_crop_applies_on_enter_and_can_be_adjusted(qtbot: QtBot) -> None:
    panel, session = _panel(qtbot)
    panel.select_tool("crop")
    tool = panel.tools["crop"]
    assert isinstance(tool, CropTool)
    assert tool.selection.rect == Rect(0, 0, 640, 360)  # сразу весь кадр
    assert not panel.has_pending()
    _drag(tool, (0, 0), (100, 50))  # левый верхний угол
    _drag(tool, (640, 360), (500, 300))  # правый нижний угол
    assert panel.has_pending()
    panel.apply_pending()
    assert session.project.effects.crop == Rect(100, 50, 400, 250)
    assert not panel.has_pending()
    assert "кадр" in panel._summary.text()
    # при повторном выборе инструмент показывает прежний кадр для правки
    panel.select_tool("crop")  # снять
    panel.select_tool("crop")  # выбрать снова
    tool = panel.tools["crop"]
    assert isinstance(tool, CropTool)
    assert tool.selection.rect == Rect(100, 50, 400, 250)


def test_redact_defaults_to_fill_and_hints_about_blur(qtbot: QtBot) -> None:
    panel, session = _panel(qtbot)
    panel.select_tool("redact")
    _drag(panel.tools["redact"], (10, 10), (120, 90))
    panel.apply_pending()
    (redact,) = session.project.effects.redacts
    assert isinstance(redact, Redact)
    assert redact.mode == "fill"
    assert not panel._redact_hint.isVisibleTo(panel)
    panel._redact_mode.setCurrentIndex(panel._redact_mode.findData("blur"))
    assert panel._redact_hint.isVisibleTo(panel)
    _drag(panel.tools["redact"], (200, 100), (320, 200))
    panel.apply_pending()
    assert session.project.effects.redacts[1].mode == "blur"


def test_text_is_placed_where_clicked(qtbot: QtBot) -> None:
    panel, session = _panel(qtbot)
    panel.select_tool("text")
    tool = panel.tools["text"]
    assert isinstance(tool, TextTool)
    assert tool.draw_preview
    assert not panel.has_pending()  # пустой текст
    panel._text.setText("Привет")
    tool.press(50, 60, 4.0)
    panel.apply_pending()
    (text,) = session.project.effects.texts
    assert isinstance(text, Text)
    assert (text.text, text.x, text.y) == ("Привет", 50, 60)
    assert text.size == pytest.approx(0.06 * 360)


def test_apply_without_pending_explains(qtbot: QtBot) -> None:
    panel, session = _panel(qtbot)
    messages: list[str] = []
    panel.message.connect(messages.append)
    panel.select_tool("crop")
    panel.apply_pending()
    assert messages
    assert session.project.effects.is_default


def test_escape_cancels_pending_then_deselects_then_gives_up(qtbot: QtBot) -> None:
    panel, _session = _panel(qtbot)
    assert not panel.escape()  # инструмента нет — Esc должен выйти из редактора
    panel.select_tool("redact")
    _drag(panel.tools["redact"], (10, 10), (100, 100))
    assert panel.escape()
    assert not panel.has_pending()
    assert panel.active == "redact"
    assert panel.escape()
    assert panel.active is None
    assert not panel.escape()


def test_selecting_same_tool_twice_deselects_and_unknown_is_ignored(qtbot: QtBot) -> None:
    panel, _session = _panel(qtbot)
    panel.select_tool("text")
    assert panel.active == "text"
    panel.select_tool("text")
    assert panel.active is None
    panel.select_tool("rotate")  # клавиши фото-редактора здесь не работают
    assert panel.active is None


def test_reset_button_and_rotation_note(qtbot: QtBot) -> None:
    panel, session = _panel(qtbot)
    reset = next(b for b in panel.findChildren(QPushButton) if b.text() == "Сбросить эффекты")
    assert not reset.isEnabled()
    session.rotate(90)
    assert reset.isEnabled()
    assert "поворот 90°" in panel._summary.text()
    assert panel.overlay._rotation_note
    reset.click()
    assert session.project.effects.is_default
    assert panel._summary.text() == "без эффектов"
    assert not panel.overlay._rotation_note


def test_crop_ratio_for_video(qtbot: QtBot) -> None:
    panel, session = _panel(qtbot)
    panel.select_tool("crop")
    tool = panel.tools["crop"]
    assert isinstance(tool, CropTool)
    panel._ratio_bar.set_value(1.0)
    assert tool.selection.rect == Rect(140, 0, 360, 360)  # квадрат по центру кадра 640x360
    panel.apply_pending()
    assert session.project.effects.crop == Rect(140, 0, 360, 360)
    # рамка остаётся на прежнем кадре, её можно подправить
    assert tool.selection.rect == Rect(140, 0, 360, 360)


def test_full_frame_crop_changes_nothing_for_video(qtbot: QtBot) -> None:
    panel, session = _panel(qtbot)
    messages: list[str] = []
    panel.message.connect(messages.append)
    panel.select_tool("crop")
    panel.apply_pending()
    assert messages
    assert session.project.effects.crop is None


def test_existing_crop_is_shown_for_adjusting_and_can_be_removed(qtbot: QtBot) -> None:
    panel, session = _panel(qtbot)
    session.set_crop(Rect(10, 10, 200, 100))
    panel.select_tool("crop")
    tool = panel.tools["crop"]
    assert isinstance(tool, CropTool)
    assert tool.selection.rect == Rect(10, 10, 200, 100)  # показан прежний кадр
    panel.remove_crop()
    assert session.project.effects.crop is None
    assert tool.selection.rect == Rect(0, 0, 640, 360)  # рамка снова по всему кадру
