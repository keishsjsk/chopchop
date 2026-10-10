"""Предпросмотр монтажа: ролик из блоков в виде EDL для mpv (`edl://`).

Время плеера при этом равно времени итога, поэтому позиция, полоса блоков и время показа эффектов
считаются в одной шкале. Соседние блоки одного файла, идущие впритык, склеиваются в одну строку
EDL: разрез сам по себе предпросмотр не меняет, и плеер не перезагружается.
"""

from pathlib import Path

from chopchop.core.video import EPS, VideoProject

Entry = tuple[Path, float, float]  # файл, начало и конец в исходном времени


def edl_entries(project: VideoProject) -> list[Entry]:
    """Куски файлов подряд; впритык идущие куски одного файла объединены."""
    entries: list[Entry] = []
    for clip in project.clips:
        if entries:
            path, start, stop = entries[-1]
            if path == clip.path and abs(stop - clip.start) <= EPS:
                entries[-1] = (path, start, clip.stop)
                continue
        entries.append((clip.path, clip.start, clip.stop))
    return entries


def edl_source(project: VideoProject) -> str:
    """Что загрузить в mpv: сам файл, если показывается он весь, иначе `edl://`."""
    entries = edl_entries(project)
    duration = project.clips[0].info.duration
    if len(entries) == 1 and entries[0][1] <= EPS and entries[0][2] >= duration - EPS:
        return str(entries[0][0])  # весь файл целиком, как есть
    parts = []
    for path, start, stop in entries:
        text = str(path)
        # перед именем длина в байтах: так в нём можно держать запятые и точки с запятой
        parts.append(f"%{len(text.encode('utf-8'))}%{text},{start:.6f},{stop - start:.6f}")
    return "edl://" + ";".join(parts)
