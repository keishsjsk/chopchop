import tomllib

import pytest

from chopchop.core import settings as core
from chopchop.core import settings_schema as schema
from chopchop.core.settings import SettingsFileError


def test_every_default_passes_its_own_validation() -> None:
    for spec in schema.SPECS:
        assert schema.coerce(spec, spec.default) == spec.default, spec.key


def test_keys_are_unique_and_sections_are_known() -> None:
    keys = [spec.key for spec in schema.SPECS]
    assert len(keys) == len(set(keys))
    known = {name for name, _ in schema.SECTIONS} | {"state"}
    assert {spec.section for spec in schema.SPECS} <= known


def test_ranges_and_choices_are_consistent() -> None:
    for spec in schema.SPECS:
        if spec.kind in ("int", "float"):
            assert spec.low is not None and spec.high is not None, spec.key
            assert spec.low <= float(str(spec.default)) <= spec.high, spec.key
        if spec.kind == "choice":
            assert spec.default in {value for value, _ in spec.choices}, spec.key


def test_numbers_are_clamped_and_wrong_types_rejected() -> None:
    volume = schema.BY_KEY["playback.volume_default"]
    assert schema.coerce(volume, 500) == 130
    assert schema.coerce(volume, -4) == 0
    for bad in ("loud", 1.5, True, None, [1]):
        with pytest.raises(ValueError):
            schema.coerce(volume, bad)
    with pytest.raises(ValueError):
        schema.coerce(schema.BY_KEY["general.language"], "de")
    with pytest.raises(ValueError):
        schema.coerce(schema.BY_KEY["editor.brush_color"], "red")
    assert schema.coerce(schema.BY_KEY["editor.brush_color"], "#FF00AA") == "#ff00aa"


def test_languages_are_cleaned_like_before() -> None:
    langs = schema.BY_KEY["playback.audio_langs"]
    assert schema.coerce(langs, " rus, eng;rm -rf ,,en-US") == "rus,engrm-rf,en-US"
    assert schema.coerce(langs, ["rus", "eng"]) == "rus,eng"


@pytest.mark.parametrize(
    "template",
    ["{name}_edited", "{name}-{date}", "copy of {name} {time}"],
)
def test_good_name_templates(template: str) -> None:
    assert schema.validate_template(template) == template


@pytest.mark.parametrize(
    "template",
    ["edited", "{name}{unknown}", "{name", "{name}/x", "..\\{name}", "{name.__class__}", "{0}"],
)
def test_bad_name_templates(template: str) -> None:
    with pytest.raises(ValueError):
        schema.validate_template(template)


def test_dumps_then_parse_round_trips_all_values() -> None:
    values = schema.defaults()
    values["playback.audio_langs"] = "rus,eng"
    values["editor.output_dir"] = 'C:\\Фото\\"тест"\n\tконец'
    values["photo.zoom_step"] = 1.4
    values["general.language"] = "en"
    text = core.dumps(values)
    tomllib.loads(text)  # это корректный TOML
    result = core.parse(text)
    assert result.warnings == []
    assert result.values == values


def test_parse_replaces_bad_values_with_defaults_and_reports_them() -> None:
    text = '[playback]\nvolume_default = "loud"\nseek_short = 9\n[photo]\nwheel_action = "fly"\n'
    result = core.parse(text)
    assert result.values["playback.volume_default"] == 100
    assert result.values["playback.seek_short"] == 9
    assert result.values["photo.wheel_action"] == "zoom"
    assert len(result.warnings) == 2


def test_unknown_keys_survive_a_rewrite() -> None:
    text = 'version = 1\n[playback]\nfuture_toggle = true\n[plugins]\nname = "x"\n'
    result = core.parse(text)
    assert result.extra == {"playback": {"future_toggle": True}, "plugins": {"name": "x"}}
    again = core.parse(core.dumps(result.values, result.extra))
    assert again.extra == result.extra


@pytest.mark.parametrize(
    "text",
    ["not = [valid", "version = 99\n", 'version = "one"\n', "version = 0\n", "\x00\x01"],
)
def test_broken_files_are_rejected(text: str) -> None:
    with pytest.raises(SettingsFileError):
        core.parse(text)


def test_migrations_run_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(schema, "SCHEMA_VERSION", 3)
    monkeypatch.setattr(
        core,
        "MIGRATIONS",
        {
            1: lambda data: {**data, "general": {"language": "en"}},
            2: lambda data: {**data, "playback": {"seek_short": 12}},
        },
    )
    result = core.parse("version = 1\n")
    assert result.values["general.language"] == "en"
    assert result.values["playback.seek_short"] == 12


def test_empty_file_gives_defaults() -> None:
    result = core.parse("")
    assert result.values == schema.defaults()
    assert result.warnings == []


def test_unknown_setting_key_is_an_error() -> None:
    with pytest.raises(KeyError):
        core.spec_of("nope.nothing")
