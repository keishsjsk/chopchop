"""Превращает проект монтажа в команды ffmpeg. Чистые функции: проверяются сравнением аргументов.

Правило: если видео только обрезано, склеено или лишено звука, оно копируется без перекодирования.
Звук перекодируется (в AAC) только при смене громкости или замене дорожки.
Перекодирование (libx264) включается для эффектов, точной обрезки и склейки разных роликов.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePath

from chopchop.core.operations import Text
from chopchop.core.video import AudioSettings, Clip, VideoProject
from chopchop.engines.ffmpeg import FfmpegStep
from chopchop.engines.video_filters import build_effects_graph
from chopchop.services.output import unique_path

AUDIO_BITRATE = "192k"
VIDEO_ARGS = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]
SAMPLE_RATE = 48000
MAX_FPS = 60.0
DEFAULT_FPS = 30.0
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
    reencodes_video: bool = False


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


def concat_list(paths: Sequence[PurePath]) -> str:
    """Текст файла для concat demuxer: слеши прямые, одинарные кавычки экранированы."""
    lines = []
    for path in paths:
        escaped = path.as_posix().replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    return "\n".join(lines) + "\n"


def build_plan(
    project: VideoProject,
    dest: Path,
    ffmpeg: Path,
    workdir: Path,
    *,
    precise: bool = False,
    font: Path | None = None,
) -> ExportPlan:
    """Шаги экспорта. workdir — пустая временная папка для промежуточных файлов.

    precise=True включает точную обрезку: видео перекодируется, зато границы — с точностью до кадра.
    """
    clips = project.clips
    if not clips:
        raise ExportPlanError("empty project")
    sources = {clip.path.resolve() for clip in clips}
    if project.audio.replacement is not None:
        sources.add(project.audio.replacement.resolve())
    if dest.resolve() in sources:
        raise ExportPlanError("output would overwrite a source file")
    if project.reencode_reason(precise) is None:
        return _build_copy_plan(project, dest, ffmpeg, workdir)
    return _build_reencode_plan(project, dest, ffmpeg, workdir, font)


def write_text_files(texts: tuple[Text, ...], workdir: Path) -> dict[int, Path]:
    """Текст для drawtext хранится в файлах: так не нужно экранировать кавычки и двоеточия."""
    files: dict[int, Path] = {}
    for index, text in enumerate(texts):
        if text.text.strip():
            path = workdir / f"text{index:02d}.txt"
            path.write_text(text.text, encoding="utf-8")
            files[index] = path
    return files


def _normalize_video(index: int, width: int, height: int, fps: float) -> str:
    """Привести клип к размеру и fps первого клипа; при другом формате — чёрные поля."""
    return (
        f"[{index}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps:.3f},"
        f"format=yuv420p[v{index}]"
    )


def _normalize_audio(index: int, clip: Clip) -> str:
    if clip.info.has_audio:
        return (
            f"[{index}:a]aresample={SAMPLE_RATE},"
            f"aformat=sample_fmts=fltp:channel_layouts=stereo[a{index}]"
        )
    # у клипа нет звука: вместо него тишина той же длины, иначе склейка собьёт синхронизацию
    return (
        f"anullsrc=r={SAMPLE_RATE}:cl=stereo,atrim=duration={clip.length:.3f},"
        f"asetpts=PTS-STARTPTS[a{index}]"
    )


def _build_reencode_plan(
    project: VideoProject, dest: Path, ffmpeg: Path, workdir: Path, font: Path | None
) -> ExportPlan:
    """Один вызов ffmpeg: клипы нормализуются, склеиваются, затем идут эффекты."""
    clips = project.clips
    effects = project.effects
    audio = project.audio
    many = len(clips) > 1
    width, height = project.frame_size
    first_fps = clips[0].info.fps
    fps = min(first_fps, MAX_FPS) if first_fps > 0 else DEFAULT_FPS
    any_audio = any(clip.info.has_audio for clip in clips)
    use_replacement = audio.replacement is not None and not audio.mute
    # звук исходных клипов нужен только если его не убрали и не заменили своим
    join_audio = many and any_audio and not audio.mute and not use_replacement
    total = project.duration

    inputs: list[str] = []
    for clip in clips:
        inputs += _trim_input(clip)
    if use_replacement:
        assert audio.replacement is not None
        inputs += ["-i", str(audio.replacement)]

    graph: list[str] = []
    if many:
        for index, clip in enumerate(clips):
            graph.append(_normalize_video(index, width, height, fps))
            if join_audio:
                graph.append(_normalize_audio(index, clip))
        pairs = "".join(f"[v{i}][a{i}]" if join_audio else f"[v{i}]" for i in range(len(clips)))
        outputs = "[vcat][acat]" if join_audio else "[vcat]"
        graph.append(f"{pairs}concat=n={len(clips)}:v=1:a={1 if join_audio else 0}{outputs}")
        video_in = "vcat"
    else:
        video_in = "0:v"

    text_files = write_text_files(effects.texts, workdir)
    graph.append(
        build_effects_graph(
            effects, (width, height), text_files, font, in_label=video_in, out_label="vout"
        )
    )

    volume = f"volume={audio.volume:.3f}" if audio.volume != 1.0 else ""
    audio_args: list[str]
    if audio.mute or (not any_audio and not use_replacement):
        audio_args = ["-an"]
    elif use_replacement:
        index = len(clips)
        chain = f"{volume},apad" if volume else "apad"
        audio_args = ["-map", f"{index}:a:0", *_aac(), "-af", chain, "-t", seconds(total)]
    elif join_audio:
        if volume:
            graph.append(f"[acat]{volume}[aout]")
            audio_args = ["-map", "[aout]", *_aac()]
        else:
            audio_args = ["-map", "[acat]", *_aac()]
    else:
        audio_args = ["-map", "0:a?", *_aac()]
        if volume:
            audio_args += ["-af", volume]

    args = [
        *_base(ffmpeg),
        *inputs,
        *["-filter_complex", ";".join(graph), "-map", "[vout]"],
        *audio_args,
        *VIDEO_ARGS,
        *_output_options(dest),
    ]
    files = tuple(text_files.values())
    step = FfmpegStep(tuple(args), total, dest)
    return ExportPlan((step,), dest, not audio.mute and (any_audio or use_replacement), files, True)


def _aac() -> list[str]:
    return ["-c:a", "aac", "-b:a", AUDIO_BITRATE]


def _build_copy_plan(project: VideoProject, dest: Path, ffmpeg: Path, workdir: Path) -> ExportPlan:
    """Быстрый экспорт: видео копируется без перекодирования."""
    clips = project.clips
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
    return thumbnail_batch_args(ffmpeg, path, [(at, Path("-"))], width, to_stdout=True)


def thumbnail_batch_args(
    ffmpeg: Path,
    path: Path,
    frames: Sequence[tuple[float, Path]],
    width: int = THUMB_WIDTH,
    to_stdout: bool = False,
) -> list[str]:
    """Несколько кадров одним запуском ffmpeg: запуск процесса дороже самого кадра.

    Файл открывается по одному разу на кадр (быстрый переход -ss до входа), каждый кадр
    пишется в свой JPEG. Для одного кадра в stdout (to_stdout) формат PNG.
    """
    args = [str(ffmpeg), "-hide_banner", "-nostdin", "-loglevel", "error", "-y"]
    for at, _ in frames:
        args += ["-ss", seconds(at), "-an", "-sn", "-i", str(path)]
    for index, (_, dest) in enumerate(frames):
        args += ["-map", f"{index}:v:0", "-frames:v", "1", "-vf", f"scale={width}:-2"]
        if to_stdout:
            args += ["-f", "image2pipe", "-c:v", "png", "-"]
        else:
            args += ["-q:v", "4", "-c:v", "mjpeg", "-f", "image2", "-update", "1", str(dest)]
    return args


def default_video_output(source: Path, extension: str | None = None) -> Path:
    """Путь вида movie_edited.mp4 рядом с исходником; существующие файлы не перезаписываются."""
    suffix = extension or (source.suffix.lower() if source.suffix.lower() in CONTAINERS else ".mkv")
    return unique_path(source.parent, f"{source.stem}_edited", suffix)
