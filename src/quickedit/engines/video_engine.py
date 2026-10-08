"""Превращает проект монтажа в команды ffmpeg. Чистые функции: проверяются сравнением аргументов.

Правило: если видео только обрезано, склеено или лишено звука, оно копируется без перекодирования.
Звук перекодируется (в AAC) только при смене громкости или замене дорожки.
"""

from dataclasses import dataclass
from pathlib import Path

from quickedit.core.video import AudioSettings, Clip, VideoProject, incompatibility
from quickedit.engines.ffmpeg import FfmpegStep
from quickedit.services.output import unique_path

AUDIO_BITRATE = "192k"
THUMB_WIDTH = 160
CONTAINERS = (".mp4", ".mkv", ".mov")


class ExportPlanError(ValueError):
    """Проект нельзя экспортировать (разные параметры клипов, выход совпадает с исходником)."""


@dataclass(frozen=True)
class ExportPlan:
    steps: tuple[FfmpegStep, ...]
    dest: Path
    reencodes_audio: bool
    workdir_files: tuple[Path, ...]  # временные файлы, которые нужно удалить после экспорта


def seconds(value: float) -> str:
    return f"{value:.3f}"


def _base(ffmpeg: Path) -> list[str]:
    return [
        str(ffmpeg),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-loglevel",
        "error",
        "-progress",
        "pipe:1",
        "-nostats",
    ]


def _output_options(dest: Path) -> list[str]:
    options = ["-map_metadata", "-1", "-map_chapters", "-1"]
    if dest.suffix.lower() in (".mp4", ".mov"):
        options += ["-movflags", "+faststart"]
    return [*options, str(dest)]


def _trim_input(clip: Clip) -> list[str]:
    """Входной файл с обрезкой: -ss и -to до -i, чтобы ffmpeg перематывал быстро."""
    args: list[str] = []
    if clip.start > 0.0005:
        args += ["-ss", seconds(clip.start)]
    if clip.stop < clip.info.duration - 0.0005:
        args += ["-to", seconds(clip.stop)]
    return [*args, "-i", str(clip.path)]


@dataclass(frozen=True)
class _AudioArgs:
    extra_input: list[str]
    maps: list[str]
    codec: list[str]
    reencodes: bool


def _audio_args(audio: AudioSettings, has_source_audio: bool, total: float) -> _AudioArgs:
    """Аргументы звука; дополнительный вход (замена звука) — это следующий по номеру вход."""
    if audio.mute or (not has_source_audio and audio.replacement is None):
        return _AudioArgs([], ["-map", "0:v"], ["-c:v", "copy", "-an"], False)
    if audio.replacement is not None:
        filters = f"volume={audio.volume:.3f},apad" if audio.volume != 1.0 else "apad"
        return _AudioArgs(
            ["-i", str(audio.replacement)],
            ["-map", "0:v", "-map", "1:a:0"],
            ["-c:v", "copy", "-c:a", "aac", "-b:a", AUDIO_BITRATE, "-af", filters]
            + ["-t", seconds(total)],  # apad бесконечен, длину задаёт видео
            True,
        )
    if audio.volume != 1.0:
        return _AudioArgs(
            [],
            ["-map", "0:v", "-map", "0:a?"],
            ["-c:v", "copy", "-c:a", "aac", "-b:a", AUDIO_BITRATE]
            + ["-af", f"volume={audio.volume:.3f}"],
            True,
        )
    return _AudioArgs([], ["-map", "0:v", "-map", "0:a?"], ["-c", "copy"], False)


def concat_list(paths: list[Path]) -> str:
    """Текст файла для concat demuxer: слеши прямые, одинарные кавычки экранированы."""
    lines = []
    for path in paths:
        escaped = path.as_posix().replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    return "\n".join(lines) + "\n"


def build_plan(project: VideoProject, dest: Path, ffmpeg: Path, workdir: Path) -> ExportPlan:
    """Шаги экспорта. workdir — пустая временная папка для промежуточных файлов."""
    clips = project.clips
    if not clips:
        raise ExportPlanError("empty project")
    sources = {clip.path.resolve() for clip in clips}
    if project.audio.replacement is not None:
        sources.add(project.audio.replacement.resolve())
    if dest.resolve() in sources:
        raise ExportPlanError("output would overwrite a source file")
    for other in clips[1:]:
        reason = incompatibility(clips[0].info, other.info)
        if reason is not None:
            raise ExportPlanError(f"clips are not compatible: {reason}")

    has_audio = clips[0].info.has_audio
    audio = _audio_args(project.audio, has_audio, project.duration)
    steps: list[FfmpegStep] = []
    temp_files: list[Path] = []

    if len(clips) == 1:
        args = [
            *_base(ffmpeg),
            *_trim_input(clips[0]),
            *audio.extra_input,
            *audio.maps,
            *audio.codec,
            *_output_options(dest),
        ]
        steps.append(FfmpegStep(tuple(args), project.duration, dest))
        return ExportPlan(tuple(steps), dest, audio.reencodes, ())

    # шаг 1: каждый клип (обрезанный или нет) копируется в одинаковый временный контейнер.
    # Склеивать оригиналы напрямую нельзя: смесь контейнеров (mp4 и mkv) ломает метки времени,
    # и звук получается в десятки раз длиннее видео.
    pieces: list[Path] = []
    for number, clip in enumerate(clips):
        piece = workdir / f"clip{number:03d}.mkv"
        trim_args = [
            *_base(ffmpeg),
            *_trim_input(clip),
            *["-map", "0:v", "-map", "0:a?", "-c", "copy", "-avoid_negative_ts", "make_zero"],
            str(piece),
        ]
        steps.append(FfmpegStep(tuple(trim_args), clip.length, piece))
        pieces.append(piece)
        temp_files.append(piece)

    # шаг 2: склейка (вместе с настройками звука) в итоговый файл
    list_file = workdir / "list.txt"
    list_file.write_text(concat_list(pieces), encoding="utf-8")
    temp_files.append(list_file)
    final_args = [
        *_base(ffmpeg),
        *["-f", "concat", "-safe", "0", "-i", str(list_file)],
        *audio.extra_input,
        *audio.maps,
        *audio.codec,
        *_output_options(dest),
    ]
    steps.append(FfmpegStep(tuple(final_args), project.duration, dest))
    return ExportPlan(tuple(steps), dest, audio.reencodes, tuple(temp_files))


def thumbnail_args(ffmpeg: Path, path: Path, at: float, width: int = THUMB_WIDTH) -> list[str]:
    """Один кадр в виде PNG на стандартный вывод."""
    return [
        str(ffmpeg),
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-ss",
        seconds(at),
        "-i",
        str(path),
        "-frames:v",
        "1",
        "-vf",
        f"scale={width}:-2",
        "-f",
        "image2pipe",
        "-c:v",
        "png",
        "-",
    ]


def default_video_output(source: Path, extension: str | None = None) -> Path:
    """Путь вида movie_edited.mp4 рядом с исходником; существующие файлы не перезаписываются."""
    suffix = extension or (source.suffix.lower() if source.suffix.lower() in CONTAINERS else ".mkv")
    return unique_path(source.parent, f"{source.stem}_edited", suffix)
