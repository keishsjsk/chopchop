from pathlib import Path

import pytest
from PySide6.QtWidgets import QWidget
from pytestqt.qtbot import QtBot

from chopchop.core.document import AudioInfo, MediaInfo
from chopchop.core.geometry import Rect
from chopchop.core.operations import Redact, Text
from chopchop.core.video import Clip, VideoProject, effect_entries
from chopchop.editor.video_session import VideoSession
from chopchop.ui.tools.crop_tool import CropTool
from chopchop.ui.tools.redact_tool import RedactTool
from chopchop.ui.tools.text_tool import TextTool
from chopchop.ui.video_effects_panel import VideoEffectsPanel
from chopchop.ui.video_overlay import VideoOverlay

INFO = MediaInfo(640, 360, 30.0, 25.0, "h264", "yuv420p", 0, AudioInfo("aac", 44100, 2))


def _panel(qtbot: QtBot) -> tuple[VideoEffectsPanel, VideoSession]:
    session = VideoSession(VideoProject((Clip(Path("a.mp4"), INFO),)))
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(800, 500)
    overlay = VideoOverlay(host, session.project.frame_size)
    panel = VideoEffectsPanel(session, overlay)
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
    assert [e.kind for e in effect_entries(session.project.effects)] == ["crop"]
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
    assert "паролей" in panel._redact_hint.text()  # заливка надёжна для паролей и текста
    panel._modes.set_value("blur", emit=True)
    assert "восстановить" in panel._redact_hint.text()  # а размытие — нет
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
    panel.select_tool("draw")  # кисти в видеоредакторе нет
    assert panel.active is None
    panel.select_tool("rotate")  # поворот, цвет и звук — пункты рейки без инструмента на кадре
    assert panel.active == "rotate"
    assert panel.overlay.tool is None


def test_rotate_segments_and_rotation_note(qtbot: QtBot) -> None:
    panel, session = _panel(qtbot)
    buttons = {b.text(): b for b in panel.rotate_segments.buttons()}
    buttons["90° вправо"].click()
    assert session.project.effects.rotation == 90
    assert panel.overlay._rotation_note
    buttons["90° влево"].click()
    assert session.project.effects.rotation == 0
    buttons["Отразить по горизонтали"].click()
    buttons["Отразить по вертикали"].click()
    assert session.project.effects.flip_h and session.project.effects.flip_v
    session.clear_effects()
    assert not panel.overlay._rotation_note


def test_selection_and_hint_signals(qtbot: QtBot) -> None:
    panel, _session = _panel(qtbot)
    chosen: list[object] = []
    hints: list[str] = []
    panel.selectionChanged.connect(chosen.append)
    panel.hintChanged.connect(hints.append)
    panel.select_tool("crop")
    assert chosen == ["crop"] and "Enter" in hints[-1] and "Esc" in hints[-1]
    panel.select_tool("crop")
    assert chosen == ["crop", None]
    assert "Выберите инструмент" in hints[-1]


def test_color_panel_commits_adjust_once(qtbot: QtBot) -> None:
    panel, session = _panel(qtbot)
    ended: list[bool] = []
    panel.colorPreviewEnded.connect(lambda: ended.append(True))
    panel.color._sliders["contrast"].setValue(30)
    qtbot.waitUntil(lambda: bool(ended), timeout=3000)
    assert session.project.effects.adjust.contrast == pytest.approx(1.3)
    session.undo()
    assert session.project.effects.adjust.is_identity


def test_crop_ratio_for_video(qtbot: QtBot) -> None:
    panel, session = _panel(qtbot)
    panel.select_tool("crop")
    tool = panel.tools["crop"]
    assert isinstance(tool, CropTool)
    panel._ratio.set_value(1.0)
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
