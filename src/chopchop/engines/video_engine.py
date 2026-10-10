"""Превращает проект монтажа в команды ffmpeg. Чистые функции: проверяются сравнением аргументов.

Правило: если видео только обрезано, склеено или лишено звука, оно копируется без перекодирования.
Звук перекодируется (в AAC) только при смене громкости или замене дорожки.
Перекодирование (libx264) включается для эффектов, точной обрезки и склейки разных роликов.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePath

from chopchop.core.keyframes import snap_back
from chopchop.core.operations import Text
from chopchop.core.video import EPS, AudioSettings, Clip, FlatRange, VideoProject
from chopchop.engines.ffmpeg import FfmpegStep
from chopchop.engines.video_filters import build_effects_graph
from chopchop.services.output import render_name, unique_path

AUDIO_BITRATE = "192k"
HW_ENCODERS = {"nvenc": "h264_nvenc", "qsv": "h264_qsv", "amf": "h264_amf"}


@dataclass(frozen=True)
class EncodeOptions:
    """Как перекодировать видео: качество (crf), скорость, кодер и число потоков."""

    crf: int = 20
    preset: str = "veryfast"
    encoder: str = "cpu"  # cpu (libx264), nvenc, qsv или amf
    threads: int = 0  # 0 — решает ffmpeg

    @property
    def is_hardware(self) -> bool:
        return self.encoder in HW_ENCODERS

    def video_args(self) -> list[str]:
        """Аргументы видеокодера; качество видеокарт задаётся той же шкалой, что и crf."""
        crf = str(self.crf)
        match self.encoder:
            case "nvenc":
                args = ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", crf]
                args += ["-b:v", "0"]
            case "qsv":
                args = ["-c:v", "h264_qsv", "-preset", self.preset, "-global_quality", crf]
            case "amf":
                args = ["-c:v", "h264_amf", "-quality", "balanced", "-rc", "cqp"]
                args += ["-qp_i", crf, "-qp_p", crf, "-qp_b", crf]
            case _:
                args = ["-c:v", "libx264", "-preset", self.preset, "-crf", crf]
                if self.threads > 0:
                    args += ["-threads", str(self.threads)]
        return [*args, "-pix_fmt", "yuv420p"]

    def on_cpu(self) -> "EncodeOptions":
        return EncodeOptions(self.crf, self.preset, "cpu", self.threads)


def pick_encoder(wanted: str, available: Sequence[str]) -> str:
    """Кодер из настройки: «auto» берёт первый доступный аппаратный, неизвестный — процессор."""
    if wanted == "auto":
        return next((key for key, name in HW_ENCODERS.items() if name in available), "cpu")
    if wanted in HW_ENCODERS and HW_ENCODERS[wanted] in available:
        return wanted
    return "cpu"


def parse_encoder_names(output: str) -> list[str]:
    """Имена аппаратных кодеров из вывода `ffmpeg -encoders`."""
    names = set(HW_ENCODERS.values())
    found = [line.split()[1] for line in output.splitlines() if len(line.split()) > 1]
    return [name for name in found if name in names]


DEFAULT_ENCODE = EncodeOptions()
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
    encode: EncodeOptions = DEFAULT_ENCODE,
    keyframes: Mapping[Path, Sequence[float]] | None = None,
) -> ExportPlan:
    """Шаги экспорта. workdir — папка для списка склейки и текстов эффектов.

    precise=True включает точную обрезку: видео перекодируется, зато границы — с точностью до кадра.
    keyframes — ключевые кадры файлов: при быстрой резке начала диапазонов привязываются к ним.
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
        return _build_copy_plan(project, dest, ffmpeg, workdir, keyframes or {})
    return _build_reencode_plan(project, dest, ffmpeg, workdir, font, encode)


def write_text_files(texts: tuple[Text, ...], workdir: Path) -> dict[int, Path]:
    """Текст для drawtext хранится в файлах: так не нужно экранировать кавычки и двоеточия."""
    files: dict[int, Path] = {}
    for index, text in enumerate(texts):
        if text.text.strip():
            path = workdir / f"text{index:02d}.txt"
            path.write_text(text.text, encoding="utf-8")
            files[index] = path
    return files


def _normalize_video(source: str, out: str, width: int, height: int, fps: float) -> str:
    """Привести кусок к размеру и fps первого клипа; при другом формате — чёрные поля."""
    return (
        f"[{source}]scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps:.3f},"
        f"format=yuv420p[{out}]"
    )


def _normalize_audio(source: str, out: str) -> str:
    return (
        f"[{source}]aresample={SAMPLE_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo[{out}]"
    )


def _silence(out: str, length: float) -> str:
    # у клипа нет звука: вместо него тишина той же длины, иначе склейка собьёт синхронизацию
    return (
        f"anullsrc=r={SAMPLE_RATE}:cl=stereo,atrim=duration={length:.3f},"
        f"asetpts=PTS-STARTPTS[{out}]"
    )


@dataclass(frozen=True)
class _Piece:
    """Один оставленный диапазон на входе фильтра склейки."""

    video: str  # метка видео до нормализации
    audio: str | None  # метка звука; None — у клипа звука нет, нужна тишина
    length: float


def _split_clip(index: int, clip: Clip, join_audio: bool) -> tuple[list[str], list[_Piece]]:
    """Фильтры, разделяющие вход клипа на диапазоны: split, trim/atrim и setpts от нуля.

    Вход уже обрезан по внешним границам клипа (-ss/-to), поэтому метки времени внутри него
    отсчитываются от `clip.start`. Каждый диапазон получает собственные метки от нуля,
    иначе concat склеит куски с дырами и рассинхроном.
    """
    ranges = clip.ranges
    has_audio = clip.info.has_audio
    if len(ranges) == 1:
        single_audio = f"{index}:a" if has_audio else None
        return [], [_Piece(f"{index}:v", single_audio, clip.length)]
    graph: list[str] = []
    count = len(ranges)
    v_out = "".join(f"[sv{index}_{j}]" for j in range(count))
    graph.append(f"[{index}:v]split={count}{v_out}")
    if join_audio and has_audio:
        a_out = "".join(f"[sa{index}_{j}]" for j in range(count))
        graph.append(f"[{index}:a]asplit={count}{a_out}")
    pieces: list[_Piece] = []
    for j, (a, b) in enumerate(ranges):
        rel_a, rel_b = a - clip.start, b - clip.start
        graph.append(
            f"[sv{index}_{j}]trim=start={rel_a:.3f}:end={rel_b:.3f},setpts=PTS-STARTPTS[tv{index}_{j}]"
        )
        label: str | None = None
        if join_audio and has_audio:
            graph.append(
                f"[sa{index}_{j}]atrim=start={rel_a:.3f}:end={rel_b:.3f},"
                f"asetpts=PTS-STARTPTS[ta{index}_{j}]"
            )
            label = f"ta{index}_{j}"
        pieces.append(_Piece(f"tv{index}_{j}", label, b - a))
    return graph, pieces


def _build_reencode_plan(
    project: VideoProject,
    dest: Path,
    ffmpeg: Path,
    workdir: Path,
    font: Path | None,
    encode: EncodeOptions,
) -> ExportPlan:
    """Один вызов ffmpeg: диапазоны вырезаются, нормализуются, склеиваются, затем идут эффекты."""
    clips = project.clips
    effects = project.effects
    audio = project.audio
    total_pieces = len(project.flat_ranges())
    many = total_pieces > 1
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
        pieces: list[_Piece] = []
        for index, clip in enumerate(clips):
            parts, clip_pieces = _split_clip(index, clip, join_audio)
            graph += parts
            pieces += clip_pieces
        labels = ""
        for number, piece in enumerate(pieces):
            graph.append(_normalize_video(piece.video, f"v{number}", width, height, fps))
            labels += f"[v{number}]"
            if join_audio:
                if piece.audio is not None:
                    graph.append(_normalize_audio(piece.audio, f"a{number}"))
                else:
                    graph.append(_silence(f"a{number}", piece.length))
                labels += f"[a{number}]"
        outputs = "[vcat][acat]" if join_audio else "[vcat]"
        graph.append(f"{labels}concat=n={len(pieces)}:v=1:a={1 if join_audio else 0}{outputs}")
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
        *encode.video_args(),
        *_output_options(dest),
    ]
    files = tuple(text_files.values())
    step = FfmpegStep(tuple(args), total, dest)
    return ExportPlan((step,), dest, not audio.mute and (any_audio or use_replacement), files, True)


def _aac() -> list[str]:
    return ["-c:a", "aac", "-b:a", AUDIO_BITRATE]


def ranges_concat_list(entries: Sequence[tuple[PurePath, float | None, float | None]]) -> str:
    """Список для concat demuxer: файл и, если нужно, inpoint и outpoint (секунды)."""
    lines = ["ffconcat version 1.0"]
    for path, inpoint, outpoint in entries:
        escaped = path.as_posix().replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
        if inpoint is not None:
            lines.append(f"inpoint {inpoint:.6f}")
        if outpoint is not None:
            lines.append(f"outpoint {outpoint:.6f}")
    return "\n".join(lines) + "\n"


def _entries(
    project: VideoProject,
    flat: Sequence[FlatRange],
    keyframes: Mapping[Path, Sequence[float]],
) -> list[tuple[PurePath, float | None, float | None]]:
    """Строки списка склейки: начало привязано к ключевому кадру не позже него."""
    entries: list[tuple[PurePath, float | None, float | None]] = []
    for item in flat:
        clip = project.clips[item.clip_index]
        frames = keyframes.get(clip.path, ())
        start = snap_back(frames, item.start) if frames else item.start
        inpoint = start if start > EPS else None
        outpoint = item.stop if item.stop < clip.info.duration - EPS else None
        entries.append((clip.path, inpoint, outpoint))
    return entries


def _build_piece_plan(
    project: VideoProject,
    dest: Path,
    ffmpeg: Path,
    workdir: Path,
    keyframes: Mapping[Path, Sequence[float]],
    audio: "_AudioArgs",
) -> ExportPlan:
    """Быстрый экспорт из нескольких разных файлов: каждый файл сначала в общий контейнер.

    Склеивать разные файлы напрямую concat demuxer нельзя: у контейнеров разные единицы
    времени (mp4 и mkv), метки времени ломаются, а звук растягивается в разы. Поэтому подряд
    идущие блоки одного файла копируются в mkv одним списком inpoint и outpoint, а затем куски
    склеиваются.
    """
    steps: list[FfmpegStep] = []
    temp_files: list[Path] = []
    pieces: list[Path] = []
    runs: list[list[Clip]] = []
    for clip in project.clips:
        if runs and runs[-1][0].path == clip.path:
            runs[-1].append(clip)
        else:
            runs.append([clip])
    for number, run in enumerate(runs):
        piece = workdir / f"clip{number:03d}.mkv"
        clip = run[0]
        if len(run) == 1:
            source = _trim_input(clip)
        else:
            listing = workdir / f"clip{number:03d}.txt"
            single = VideoProject(tuple(run))
            flat = single.flat_ranges()
            listing.write_text(
                ranges_concat_list(_entries(single, flat, keyframes)), encoding="utf-8"
            )
            temp_files.append(listing)
            source = ["-f", "concat", "-safe", "0", "-i", str(listing)]
        trim_args = [
            *_base(ffmpeg),
            *source,
            *["-map", "0:v", "-map", "0:a?", "-c", "copy", "-avoid_negative_ts", "make_zero"],
            str(piece),
        ]
        steps.append(FfmpegStep(tuple(trim_args), sum(c.length for c in run), piece))
        pieces.append(piece)
        temp_files.append(piece)
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


def _build_copy_plan(
    project: VideoProject,
    dest: Path,
    ffmpeg: Path,
    workdir: Path,
    keyframes: Mapping[Path, Sequence[float]],
) -> ExportPlan:
    """Быстрый экспорт: видео копируется без перекодирования.

    Один клип одним куском — обычная обрезка (-ss и -to). Вырезы из середины одного файла — один
    вызов ffmpeg с concat demuxer: диапазоны перечислены директивами inpoint и outpoint,
    промежуточных медиафайлов нет. Начало каждого диапазона привязывается к ключевому кадру не
    позже него: иначе демультиплексор отдал бы лишние кадры до начала. Склейка разных файлов
    идёт через общий контейнер (см. `_build_piece_plan`).
    """
    clips = project.clips
    has_audio = clips[0].info.has_audio
    audio = _audio_args(project.audio, has_audio, project.duration)
    flat = project.flat_ranges()

    if len(clips) == 1 and len(flat) == 1:
        args = [
            *_base(ffmpeg),
            *_trim_input(clips[0]),
            *audio.extra_input,
            *audio.maps,
            *audio.codec,
            *_output_options(dest),
        ]
        return ExportPlan(
            (FfmpegStep(tuple(args), project.duration, dest),), dest, audio.reencodes, ()
        )

    if len({clip.path for clip in clips}) > 1:
        return _build_piece_plan(project, dest, ffmpeg, workdir, keyframes, audio)
    list_file = workdir / "list.txt"
    list_file.write_text(ranges_concat_list(_entries(project, flat, keyframes)), encoding="utf-8")
    final_args = [
        *_base(ffmpeg),
        *["-f", "concat", "-safe", "0", "-i", str(list_file)],
        *audio.extra_input,
        *audio.maps,
        *audio.codec,
        *_output_options(dest),
    ]
    step = FfmpegStep(tuple(final_args), project.duration, dest)
    return ExportPlan((step,), dest, audio.reencodes, (list_file,))


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


def default_video_output(
    source: Path,
    extension: str | None = None,
    folder: Path | None = None,
    template: str = "{name}_edited",
) -> Path:
    """Путь вида movie_edited.mp4 рядом с исходником; существующие файлы не перезаписываются."""
    suffix = extension or (source.suffix.lower() if source.suffix.lower() in CONTAINERS else ".mkv")
    return unique_path(folder or source.parent, render_name(template, source.stem), suffix)
