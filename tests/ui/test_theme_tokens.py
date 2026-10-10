import pytest

from chopchop.ui.theme import tokens
from chopchop.ui.theme.tokens import ACCENTS, Palette, contrast, make_palette

THEMES = ("light", "dark")
TEXT = 4.5  # текст
CONTROL = 3.0  # элементы управления и рамки

PAIRS_TEXT = [
    ("text", "bg"),
    ("text", "surface"),
    ("text", "surface_raised"),
    ("text_muted", "bg"),
    ("text_muted", "surface"),
    ("text_muted", "surface_raised"),
    ("secondary", "bg"),
    ("secondary", "surface"),
    ("danger", "bg"),
    ("danger", "surface"),
    ("success", "bg"),
    ("success", "surface"),
    ("text", "accent_tint"),
    ("on_accent", "accent"),
    ("on_accent", "accent_hover"),
    ("on_accent", "accent_pressed"),
    ("on_secondary", "secondary"),
    ("on_danger", "danger"),
]
PAIRS_CONTROL = [
    ("accent", "bg"),
    ("accent", "surface"),
    ("border_strong", "bg"),
    ("border_strong", "surface"),
    ("border_strong", "surface_raised"),
    ("focus_ring", "bg"),
    ("focus_ring", "surface"),
    ("focus_ring", "surface_raised"),
]


def _all_palettes() -> list[tuple[str, str, Palette]]:
    return [(t, a, make_palette(t, a)) for t in THEMES for a in ACCENTS]


@pytest.mark.parametrize(("theme", "accent", "palette"), _all_palettes())
def test_text_pairs_meet_4_5_to_1(theme: str, accent: str, palette: Palette) -> None:
    for foreground, background in PAIRS_TEXT:
        ratio = contrast(getattr(palette, foreground), getattr(palette, background))
        assert ratio >= TEXT, f"{theme}/{accent}: {foreground} on {background} = {ratio:.2f}"


@pytest.mark.parametrize(("theme", "accent", "palette"), _all_palettes())
def test_control_pairs_meet_3_to_1(theme: str, accent: str, palette: Palette) -> None:
    for foreground, background in PAIRS_CONTROL:
        ratio = contrast(getattr(palette, foreground), getattr(palette, background))
        assert ratio >= CONTROL, f"{theme}/{accent}: {foreground} on {background} = {ratio:.2f}"


def test_contrast_helper_matches_known_values() -> None:
    assert contrast("#000000", "#FFFFFF") == pytest.approx(21.0)
    assert contrast("#777777", "#777777") == pytest.approx(1.0)
    assert contrast("#767676", "#FFFFFF") == pytest.approx(4.54, abs=0.01)


def test_blend() -> None:
    assert tokens.blend("#ffffff", "#000000", 0.5) == "#808080"
    assert tokens.blend("#123456", "#abcdef", 1.0) == "#123456"


def test_spacing_grid_and_minimum_sizes() -> None:
    assert (tokens.SPACE_1, tokens.SPACE_2, tokens.SPACE_3, tokens.SPACE_4, tokens.SPACE_6) == (
        4,
        8,
        12,
        16,
        24,
    )
    assert tokens.MIN_HIT >= 32 and tokens.BUTTON_HEIGHT >= 40 and tokens.RAIL_BUTTON >= 40


def test_all_colors_are_well_formed() -> None:
    for _theme, _accent, palette in _all_palettes():
        for field, value in vars(palette).items():
            if field == "scrim":
                assert len(value) == 4 and all(0 <= part <= 255 for part in value)
            elif field != "name":
                assert len(value) == 7 and value[0] == "#" and int(value[1:], 16) >= 0, field


def test_unknown_accent_falls_back_to_default() -> None:
    assert make_palette("light", "nonsense") == make_palette("light", tokens.DEFAULT_ACCENT)


def test_accent_changes_only_accent_colors() -> None:
    orange, violet = make_palette("dark", "orange"), make_palette("dark", "violet")
    assert orange.accent != violet.accent
    assert (orange.bg, orange.text, orange.surface) == (violet.bg, violet.text, violet.surface)
