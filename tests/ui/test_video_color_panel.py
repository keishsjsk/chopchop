import pytest
from pytestqt.qtbot import QtBot

from chopchop.core.operations import Adjust
from chopchop.ui.video_color_panel import (
    ColorPanel,
    adjust_to_slider,
    slider_to_adjust,
)


def test_slider_mapping_roundtrip() -> None:
    adjust = Adjust(brightness=1.3, contrast=0.8, saturation=1.5, gamma=2.0)
    values = adjust_to_slider(adjust)
    assert values == {"brightness": 30, "contrast": -20, "saturation": 50, "gamma": 50}
    again = slider_to_adjust(values)
    assert again.brightness == pytest.approx(1.3)
    assert again.gamma == pytest.approx(2.0)
    assert slider_to_adjust(adjust_to_slider(Adjust())).is_identity


def test_panel_emits_live_preview_and_commits_once(qtbot: QtBot) -> None:
    panel = ColorPanel()
    qtbot.addWidget(panel)
    previews: list[tuple[Adjust, object]] = []
    commits: list[tuple[Adjust, object]] = []
    panel.previewChanged.connect(lambda adjust, name: previews.append((adjust, name)))
    panel.committed.connect(lambda adjust, name: commits.append((adjust, name)))
    for value in (10, 25, 40):
        panel._sliders["contrast"].setValue(value)
    assert previews[-1][0].contrast == pytest.approx(1.4)  # превью на каждое движение
    assert commits == []
    qtbot.waitUntil(lambda: len(commits) == 1, timeout=2000)
    panel._filter.setCurrentIndex(panel._filter.findData("sepia"))
    assert previews[-1][1] == "sepia"
    assert panel.filter_name() == "sepia"
    qtbot.waitUntil(lambda: len(commits) == 2, timeout=2000)
    assert commits[-1][0].contrast == pytest.approx(1.4)


def test_panel_starts_from_current_values_and_resets(qtbot: QtBot) -> None:
    panel = ColorPanel(Adjust(saturation=0.5), "blur")
    qtbot.addWidget(panel)
    assert panel._sliders["saturation"].value() == -50
    assert panel.filter_name() == "blur"
    previews: list[object] = []
    panel.previewChanged.connect(lambda adjust, name: previews.append((adjust, name)))
    panel._reset()
    assert panel.adjust().is_identity
    assert panel.filter_name() is None
    assert len(previews) == 1  # один сигнал, а не по одному на каждый ползунок


def test_panel_follows_project_but_not_while_a_commit_is_pending(qtbot: QtBot) -> None:
    panel = ColorPanel()
    qtbot.addWidget(panel)
    panel._sliders["brightness"].setValue(20)
    panel.set_values(Adjust(), None)  # проект ещё старый: ползунок не должен прыгать назад
    assert panel._sliders["brightness"].value() == 20
    qtbot.waitUntil(lambda: not panel._timer.isActive(), timeout=2000)
    panel.set_values(Adjust(brightness=1.1), None)
    assert panel._sliders["brightness"].value() == 10
