from chopchop.core.tracks import Track, next_track_id, of_kind, parse_tracks

RAW = [
    {"id": 1, "type": "video"},
    {"id": 1, "type": "audio", "lang": "eng", "title": "Stereo", "selected": True},
    {"id": 2, "type": "audio", "lang": "rus"},
    {"id": 1, "type": "sub", "lang": "eng", "external": False},
    {"id": 2, "type": "sub", "title": "movie.srt", "external": True},
]


def test_parse_skips_video_and_reads_fields() -> None:
    tracks = parse_tracks(RAW)
    assert [(t.kind, t.id) for t in tracks] == [("audio", 1), ("audio", 2), ("sub", 1), ("sub", 2)]
    first = tracks[0]
    assert first.lang == "eng"
    assert first.title == "Stereo"
    assert first.selected
    assert tracks[3].external


def test_of_kind() -> None:
    assert [t.id for t in of_kind(parse_tracks(RAW), "sub")] == [1, 2]


def test_label() -> None:
    assert Track(2, "sub", "rus", "Full", external=True).label == "2 · rus · Full · (внешняя)"
    assert Track(3, "audio").label == "3"


def test_next_track_cycles_through_off() -> None:
    subs = of_kind(parse_tracks(RAW), "sub")
    assert next_track_id(subs, None, allow_off=True) == 1
    assert next_track_id(subs, 1, allow_off=True) == 2
    assert next_track_id(subs, 2, allow_off=True) is None


def test_next_track_without_off_wraps() -> None:
    audio = of_kind(parse_tracks(RAW), "audio")
    assert next_track_id(audio, 2, allow_off=False) == 1


def test_next_track_with_no_tracks() -> None:
    assert next_track_id([], None, allow_off=False) is None
    assert next_track_id([], None, allow_off=True) is None
