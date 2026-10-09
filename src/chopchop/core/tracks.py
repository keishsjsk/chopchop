"""Описание аудио- и субтитровых дорожек. Чистый Python, без Qt и mpv."""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

TrackKind = Literal["audio", "sub"]


@dataclass(frozen=True)
class Track:
    id: int
    kind: TrackKind
    lang: str | None = None
    title: str | None = None
    external: bool = False
    selected: bool = False
    codec: str | None = None

    @property
    def label(self) -> str:
        parts = [str(self.id)]
        if self.lang:
            parts.append(self.lang)
        if self.title:
            parts.append(self.title)
        if self.external:
            parts.append("(внешняя)")
        return " · ".join(parts)


def parse_tracks(track_list: Iterable[Mapping[str, Any]]) -> list[Track]:
    """Превращает свойство mpv ``track-list`` в дорожки; видео и обложки пропускаются."""
    tracks: list[Track] = []
    for raw in track_list:
        kind = raw.get("type")
        if kind not in ("audio", "sub"):
            continue
        tracks.append(
            Track(
                id=int(raw["id"]),
                kind=kind,
                lang=raw.get("lang") or None,
                title=raw.get("title") or None,
                external=bool(raw.get("external")),
                selected=bool(raw.get("selected")),
                codec=raw.get("codec") or None,
            )
        )
    return tracks


def of_kind(tracks: Iterable[Track], kind: TrackKind) -> list[Track]:
    return [t for t in tracks if t.kind == kind]


def next_track_id(tracks: Sequence[Track], current: int | None, allow_off: bool) -> int | None:
    """Следующая дорожка по кругу. None означает «выключено» (если оно разрешено)."""
    ids: list[int | None] = [t.id for t in tracks]
    if allow_off:
        ids.append(None)
    if not ids:
        return None
    if current not in ids:
        return ids[0]
    return ids[(ids.index(current) + 1) % len(ids)]
