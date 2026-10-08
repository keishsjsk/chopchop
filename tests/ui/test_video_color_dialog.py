import pytest
from pytestqt.qtbot import QtBot

from chopchop.core.operations import Adjust
from chopchop.ui.video_color_dialog import (
    VideoColorDialog,
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


def test_dialog_emits_live_preview_and_returns_values(qtbot: QtBot) -> None:
    dialog = VideoColorDialog(Adjust(), None)
    qtbot.addWidget(dialog)
    previews: list[tuple[Adjust, object]] = []
    dialog.previewChanged.connect(lambda adjust, name: previews.append((adjust, name)))
    dialog._sliders["contrast"].setValue(40)
    assert previews[-1][0].contrast == pytest.approx(1.4)
    dialog._filter.setCurrentIndex(dialog._filter.findData("sepia"))
    assert previews[-1][1] == "sepia"
    assert dialog.filter_name() == "sepia"
    assert dialog.adjust().contrast == pytest.approx(1.4)


def test_dialog_starts_from_current_values_and_resets(qtbot: QtBot) -> None:
    dialog = VideoColorDialog(Adjust(saturation=0.5), "blur")
    qtbot.addWidget(dialog)
    assert dialog._sliders["saturation"].value() == -50
    assert dialog.filter_name() == "blur"
    previews: list[object] = []
    dialog.previewChanged.connect(lambda adjust, name: previews.append((adjust, name)))
    dialog._reset()
    assert dialog.adjust().is_identity
    assert dialog.filter_name() is None
    assert len(previews) == 1  # один сигнал, а не по одному на каждый ползунок
