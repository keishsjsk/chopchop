"""Описание всех настроек: тип, диапазон, значение по умолчанию, применение на лету.

Чистый Python без Qt. Подписи на русском (исходный язык), в окне настроек они переводятся.
Это единственное место, где заданы настройки: окно, файл, импорт и docs/settings.md строятся
из него.
"""

import re
from dataclasses import dataclass
from typing import Literal

from chopchop.core.subtitle_style import CODEPAGES
from chopchop.core.tr_marks import QT_TRANSLATE_NOOP

Kind = Literal["bool", "int", "float", "choice", "str", "color", "path", "langs"]
Apply = Literal["live", "restart"]

SCHEMA_VERSION = 1
COLOR_PATTERN = re.compile(r"#[0-9a-fA-F]{6}")


@dataclass(frozen=True)
class Spec:
    key: str  # "раздел.имя"
    kind: Kind
    default: object
    label: str
    hint: str = ""
    low: float | None = None
    high: float | None = None
    step: float = 1.0
    choices: tuple[tuple[str, str], ...] = ()  # (значение в файле, подпись)
    apply: Apply = "live"
    advanced: bool = False
    shown: bool = True  # показывать в окне настроек (False, пока функция не подключена)

    @property
    def section(self) -> str:
        return self.key.split(".", 1)[0]

    @property
    def name(self) -> str:
        return self.key.split(".", 1)[1]


SECTIONS: tuple[tuple[str, str], ...] = (
    ("general", QT_TRANSLATE_NOOP("Settings", "Основные")),
    ("playback", QT_TRANSLATE_NOOP("Settings", "Воспроизведение")),
    ("photo", QT_TRANSLATE_NOOP("Settings", "Фото")),
    ("subtitles", QT_TRANSLATE_NOOP("Settings", "Субтитры")),
    ("appearance", QT_TRANSLATE_NOOP("Settings", "Внешний вид")),
    ("editor", QT_TRANSLATE_NOOP("Settings", "Редактор")),
    ("advanced", QT_TRANSLATE_NOOP("Settings", "Дополнительно")),
)

PRESETS = ("ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower")
RATIO_CHOICES = (
    ("free", QT_TRANSLATE_NOOP("Settings", "Свободно")),
    ("original", QT_TRANSLATE_NOOP("Settings", "Исходное")),
    ("1:1", "1:1"),
    ("4:3", "4:3"),
    ("3:2", "3:2"),
    ("16:9", "16:9"),
    ("21:9", "21:9"),
    ("3:4", "3:4"),
    ("2:3", "2:3"),
    ("9:16", "9:16"),
)

SPECS: tuple[Spec, ...] = (
    # --- Основные
    Spec(
        "general.language",
        "choice",
        "ru",
        QT_TRANSLATE_NOOP("Settings", "Язык интерфейса"),
        choices=(("ru", "Русский"), ("en", "English")),
        apply="restart",
    ),
    Spec(
        "general.open_mode",
        "choice",
        "view",
        QT_TRANSLATE_NOOP("Settings", "Открывать фото"),
        QT_TRANSLATE_NOOP("Settings", "В просмотре или сразу в редакторе"),
        choices=(
            ("view", QT_TRANSLATE_NOOP("Settings", "в просмотре")),
            ("edit", QT_TRANSLATE_NOOP("Settings", "сразу в редакторе")),
        ),
    ),
    Spec(
        "general.remember_window",
        "bool",
        True,
        QT_TRANSLATE_NOOP("Settings", "Запоминать размер и положение окна"),
    ),
    Spec(
        "general.open_in",
        "choice",
        "same",
        QT_TRANSLATE_NOOP("Settings", "Открывать другой файл"),
        QT_TRANSLATE_NOOP("Settings", "Если в окне уже что-то открыто: в нём же или в новом окне"),
        choices=(
            ("same", QT_TRANSLATE_NOOP("Settings", "в том же окне")),
            ("new", QT_TRANSLATE_NOOP("Settings", "в новом окне")),
        ),
    ),
    Spec(
        "general.confirm_delete",
        "bool",
        True,
        QT_TRANSLATE_NOOP("Settings", "Подтверждать удаление"),
        QT_TRANSLATE_NOOP("Settings", "Файл всегда уходит в корзину, а не удаляется навсегда"),
    ),
    Spec(
        "general.screenshot_subtitles",
        "bool",
        False,
        QT_TRANSLATE_NOOP("Settings", "Снимок кадра с субтитрами"),
        QT_TRANSLATE_NOOP("Settings", "По умолчанию субтитры в снимок кадра не попадают"),
    ),
    # --- Воспроизведение
    Spec(
        "playback.volume_default",
        "int",
        100,
        QT_TRANSLATE_NOOP("Settings", "Громкость по умолчанию, %"),
        QT_TRANSLATE_NOOP("Settings", "Для файлов, у которых своя громкость не запомнена"),
        low=0,
        high=130,
    ),
    Spec(
        "playback.volume_step",
        "int",
        5,
        QT_TRANSLATE_NOOP("Settings", "Шаг громкости, %"),
        low=1,
        high=20,
    ),
    Spec(
        "playback.seek_short",
        "int",
        5,
        QT_TRANSLATE_NOOP("Settings", "Короткая перемотка, с"),
        QT_TRANSLATE_NOOP("Settings", "Стрелки влево и вправо"),
        low=1,
        high=60,
    ),
    Spec(
        "playback.seek_long",
        "int",
        30,
        QT_TRANSLATE_NOOP("Settings", "Длинная перемотка, с"),
        QT_TRANSLATE_NOOP("Settings", "Shift и стрелки влево и вправо"),
        low=5,
        high=600,
    ),
    Spec(
        "playback.remember_position",
        "bool",
        True,
        QT_TRANSLATE_NOOP("Settings", "Запоминать позицию в каждом файле"),
    ),
    Spec(
        "playback.autoplay_next",
        "bool",
        False,
        QT_TRANSLATE_NOOP("Settings", "Переходить к следующему видео в папке"),
        QT_TRANSLATE_NOOP("Settings", "По окончании файла включается следующий"),
    ),
    Spec(
        "playback.audio_langs",
        "langs",
        "",
        QT_TRANSLATE_NOOP("Settings", "Языки аудио по порядку предпочтения"),
        QT_TRANSLATE_NOOP("Settings", "Коды языков через запятую, например rus,eng"),
    ),
    Spec(
        "playback.sub_langs",
        "langs",
        "",
        QT_TRANSLATE_NOOP("Settings", "Языки субтитров по порядку предпочтения"),
        QT_TRANSLATE_NOOP("Settings", "Коды языков через запятую, например rus,eng"),
    ),
    Spec(
        "playback.hwdec",
        "choice",
        "auto",
        QT_TRANSLATE_NOOP("Settings", "Аппаратное декодирование видео"),
        QT_TRANSLATE_NOOP("Settings", "Если в картинке мусор или полосы, выберите «Выключено»"),
        choices=(
            ("auto", QT_TRANSLATE_NOOP("Settings", "авто")),
            ("off", QT_TRANSLATE_NOOP("Settings", "выключено (процессор)")),
        ),
    ),
    Spec(
        "playback.end_action",
        "choice",
        "stop",
        QT_TRANSLATE_NOOP("Settings", "В конце файла"),
        choices=(
            ("stop", QT_TRANSLATE_NOOP("Settings", "остановиться на последнем кадре")),
            ("loop", QT_TRANSLATE_NOOP("Settings", "повторять")),
            ("close", QT_TRANSLATE_NOOP("Settings", "вернуться на стартовый экран")),
        ),
    ),
    Spec(
        "playback.hide_delay",
        "float",
        2.5,
        QT_TRANSLATE_NOOP("Settings", "Прятать панели через, с"),
        QT_TRANSLATE_NOOP("Settings", "Панели и курсор над видео исчезают, если мышь неподвижна"),
        low=1.0,
        high=10.0,
        step=0.5,
    ),
    Spec(
        "playback.fs_panel",
        "choice",
        "compact",
        QT_TRANSLATE_NOOP("Settings", "Панель в полном экране"),
        choices=(
            ("compact", QT_TRANSLATE_NOOP("Settings", "компактная")),
            ("normal", QT_TRANSLATE_NOOP("Settings", "обычная")),
        ),
    ),
    Spec(
        "playback.fs_progress_line",
        "bool",
        True,
        QT_TRANSLATE_NOOP("Settings", "Линия прогресса при спрятанной панели (полный экран)"),
    ),
    Spec(
        "playback.speed_step",
        "float",
        0.25,
        QT_TRANSLATE_NOOP("Settings", "Шаг скорости"),
        low=0.05,
        high=1.0,
        step=0.05,
    ),
    # --- Субтитры: раздел в окне настроек рисует свой виджет (`ui/subtitle_style_editor.py`),
    # поэтому отдельные строки скрыты; значения лежат в файле и применяются к mpv на лету
    Spec(
        "subtitles.font",
        "str",
        "",
        QT_TRANSLATE_NOOP("Settings", "Шрифт субтитров"),
        hint=QT_TRANSLATE_NOOP("Settings", "Пусто — шрифт по умолчанию"),
        shown=False,
    ),
    Spec(
        "subtitles.font_size",
        "int",
        55,
        QT_TRANSLATE_NOOP("Settings", "Размер шрифта субтитров"),
        hint=QT_TRANSLATE_NOOP("Settings", "Относительно высоты видео: 55 = 7,6 % высоты кадра"),
        low=10,
        high=150,
        shown=False,
    ),
    Spec("subtitles.bold", "bool", False, QT_TRANSLATE_NOOP("Settings", "Жирный"), shown=False),
    Spec("subtitles.italic", "bool", False, QT_TRANSLATE_NOOP("Settings", "Курсив"), shown=False),
    Spec(
        "subtitles.color",
        "color",
        "#ffffff",
        QT_TRANSLATE_NOOP("Settings", "Цвет текста субтитров"),
        shown=False,
    ),
    Spec(
        "subtitles.outline_color",
        "color",
        "#000000",
        QT_TRANSLATE_NOOP("Settings", "Цвет контура"),
        shown=False,
    ),
    Spec(
        "subtitles.outline_size",
        "float",
        3.0,
        QT_TRANSLATE_NOOP("Settings", "Толщина контура"),
        low=0.0,
        high=10.0,
        step=0.5,
        shown=False,
    ),
    Spec(
        "subtitles.shadow_color",
        "color",
        "#000000",
        QT_TRANSLATE_NOOP("Settings", "Цвет тени"),
        shown=False,
    ),
    Spec(
        "subtitles.shadow_offset",
        "float",
        0.0,
        QT_TRANSLATE_NOOP("Settings", "Смещение тени"),
        low=0.0,
        high=10.0,
        step=0.5,
        shown=False,
    ),
    Spec(
        "subtitles.back_enabled",
        "bool",
        False,
        QT_TRANSLATE_NOOP("Settings", "Подложка под текстом"),
        shown=False,
    ),
    Spec(
        "subtitles.back_color",
        "color",
        "#000000",
        QT_TRANSLATE_NOOP("Settings", "Цвет подложки"),
        shown=False,
    ),
    Spec(
        "subtitles.back_opacity",
        "int",
        70,
        QT_TRANSLATE_NOOP("Settings", "Непрозрачность подложки, %"),
        low=0,
        high=100,
        shown=False,
    ),
    Spec(
        "subtitles.line_spacing",
        "int",
        0,
        QT_TRANSLATE_NOOP("Settings", "Межстрочный интервал"),
        low=0,
        high=60,
        shown=False,
    ),
    Spec(
        "subtitles.margin",
        "int",
        22,
        QT_TRANSLATE_NOOP("Settings", "Вертикальный отступ субтитров"),
        low=0,
        high=300,
        shown=False,
    ),
    Spec(
        "subtitles.margin_x",
        "int",
        19,
        QT_TRANSLATE_NOOP("Settings", "Горизонтальный отступ субтитров"),
        low=0,
        high=300,
        shown=False,
    ),
    Spec(
        "subtitles.align_x",
        "choice",
        "center",
        QT_TRANSLATE_NOOP("Settings", "Выравнивание по горизонтали"),
        choices=(
            ("left", QT_TRANSLATE_NOOP("Settings", "слева")),
            ("center", QT_TRANSLATE_NOOP("Settings", "по центру")),
            ("right", QT_TRANSLATE_NOOP("Settings", "справа")),
        ),
        shown=False,
    ),
    Spec(
        "subtitles.align_y",
        "choice",
        "bottom",
        QT_TRANSLATE_NOOP("Settings", "Выравнивание по вертикали"),
        choices=(
            ("top", QT_TRANSLATE_NOOP("Settings", "сверху")),
            ("center", QT_TRANSLATE_NOOP("Settings", "по центру")),
            ("bottom", QT_TRANSLATE_NOOP("Settings", "снизу")),
        ),
        shown=False,
    ),
    Spec(
        "subtitles.pos",
        "int",
        100,
        QT_TRANSLATE_NOOP("Settings", "Положение по высоте, %"),
        hint=QT_TRANSLATE_NOOP(
            "Settings", "0 — вверху кадра, 100 — внизу; действует и на картинки"
        ),
        low=0,
        high=100,
        shown=False,
    ),
    Spec(
        "subtitles.pos2",
        "int",
        0,
        QT_TRANSLATE_NOOP("Settings", "Положение второй строки, %"),
        low=0,
        high=100,
        shown=False,
    ),
    Spec(
        "subtitles.scale",
        "float",
        1.0,
        QT_TRANSLATE_NOOP("Settings", "Масштаб субтитров"),
        low=0.5,
        high=3.0,
        step=0.05,
        shown=False,
    ),
    Spec(
        "subtitles.ass_mode",
        "choice",
        "scale",
        QT_TRANSLATE_NOOP("Settings", "Оформление из файла или моё"),
        choices=(
            ("file", QT_TRANSLATE_NOOP("Settings", "как в файле")),
            ("scale", QT_TRANSLATE_NOOP("Settings", "как в файле, мой масштаб")),
            ("mine", QT_TRANSLATE_NOOP("Settings", "моё оформление")),
        ),
        shown=False,
    ),
    Spec(
        "subtitles.codepage",
        "choice",
        "auto",
        QT_TRANSLATE_NOOP("Settings", "Кодировка текстовых субтитров"),
        choices=CODEPAGES,
        shown=False,
    ),
    Spec(
        "subtitles.preset",
        "str",
        "",
        QT_TRANSLATE_NOOP("Settings", "Последний выбранный пресет"),
        shown=False,
    ),
    # --- Фото
    Spec(
        "photo.fit_mode",
        "choice",
        "fit",
        QT_TRANSLATE_NOOP("Settings", "Масштаб при открытии"),
        choices=(
            ("fit", QT_TRANSLATE_NOOP("Settings", "вписать (маленькие не растягивать)")),
            ("fit_all", QT_TRANSLATE_NOOP("Settings", "вписать всегда")),
            ("actual", QT_TRANSLATE_NOOP("Settings", "100%")),
        ),
    ),
    Spec(
        "photo.zoom_step",
        "float",
        1.25,
        QT_TRANSLATE_NOOP("Settings", "Шаг масштаба"),
        QT_TRANSLATE_NOOP("Settings", "Во сколько раз меняется масштаб за один щелчок колеса"),
        low=1.05,
        high=2.0,
        step=0.05,
    ),
    Spec(
        "photo.wheel_action",
        "choice",
        "zoom",
        QT_TRANSLATE_NOOP("Settings", "Колесо мыши"),
        choices=(
            ("zoom", QT_TRANSLATE_NOOP("Settings", "масштаб")),
            ("navigate", QT_TRANSLATE_NOOP("Settings", "переключение фото")),
        ),
    ),
    Spec("photo.background", "color", "#202020", QT_TRANSLATE_NOOP("Settings", "Цвет фона")),
    Spec(
        "photo.preload",
        "int",
        2,
        QT_TRANSLATE_NOOP("Settings", "Предзагружать соседних фото"),
        QT_TRANSLATE_NOOP("Settings", "Сколько следующих фото готовить заранее (0 — не готовить)"),
        low=0,
        high=6,
    ),
    Spec(
        "photo.smoothing",
        "choice",
        "smooth",
        QT_TRANSLATE_NOOP("Settings", "Сглаживание при увеличении"),
        choices=(
            ("smooth", QT_TRANSLATE_NOOP("Settings", "плавное")),
            ("pixel", QT_TRANSLATE_NOOP("Settings", "пиксельное")),
        ),
    ),
    # --- Внешний вид (подключаются в фазах 3 и 4)
    Spec(
        "appearance.theme",
        "choice",
        "system",
        QT_TRANSLATE_NOOP("Settings", "Тема"),
        choices=(
            ("system", QT_TRANSLATE_NOOP("Settings", "как в системе")),
            ("light", QT_TRANSLATE_NOOP("Settings", "светлая")),
            ("dark", QT_TRANSLATE_NOOP("Settings", "тёмная")),
        ),
    ),
    Spec(
        "appearance.accent",
        "choice",
        "ember",
        QT_TRANSLATE_NOOP("Settings", "Акцентный цвет"),
        QT_TRANSLATE_NOOP("Settings", "Палитра акцента: терракота, шалфей, закат или роза"),
        choices=(
            ("ember", QT_TRANSLATE_NOOP("Settings", "терракота")),
            ("meadow", QT_TRANSLATE_NOOP("Settings", "шалфей")),
            ("sunset", QT_TRANSLATE_NOOP("Settings", "закат")),
            ("rose", QT_TRANSLATE_NOOP("Settings", "роза")),
        ),
    ),
    Spec(
        "appearance.ui_scale",
        "int",
        100,
        QT_TRANSLATE_NOOP("Settings", "Масштаб интерфейса, %"),
        low=90,
        high=150,
        step=5,
        apply="restart",
    ),
    Spec(
        "appearance.font",
        "choice",
        "monocraft",
        QT_TRANSLATE_NOOP("Settings", "Шрифт интерфейса"),
        QT_TRANSLATE_NOOP("Settings", "Monocraft (пиксельный, размеры кратны 9) или шрифт системы"),
        choices=(
            ("monocraft", "Monocraft"),
            ("system", QT_TRANSLATE_NOOP("Settings", "системный")),
        ),
    ),
    Spec(
        "appearance.animations",
        "bool",
        True,
        QT_TRANSLATE_NOOP("Settings", "Анимации"),
    ),
    Spec(
        "appearance.compact",
        "bool",
        False,
        QT_TRANSLATE_NOOP("Settings", "Компактный режим"),
    ),
    # --- Редактор
    Spec(
        "editor.jpeg_quality",
        "int",
        92,
        QT_TRANSLATE_NOOP("Settings", "Качество JPEG по умолчанию"),
        low=1,
        high=100,
    ),
    Spec(
        "editor.webp_quality",
        "int",
        90,
        QT_TRANSLATE_NOOP("Settings", "Качество WebP по умолчанию"),
        low=1,
        high=100,
    ),
    Spec(
        "editor.strip_metadata",
        "bool",
        True,
        QT_TRANSLATE_NOOP("Settings", "Удалять метаданные при сохранении"),
        QT_TRANSLATE_NOOP("Settings", "EXIF, место съёмки, устройство"),
    ),
    Spec(
        "editor.output_dir",
        "path",
        "",
        QT_TRANSLATE_NOOP("Settings", "Папка для результатов"),
        QT_TRANSLATE_NOOP("Settings", "Пусто — рядом с исходным файлом"),
    ),
    Spec(
        "editor.output_template",
        "str",
        "{name}_edited",
        QT_TRANSLATE_NOOP("Settings", "Шаблон имени результата"),
        QT_TRANSLATE_NOOP(
            "Settings", "Можно использовать {name}, {date}, {time}; расширение добавляется само"
        ),
    ),
    Spec(
        "editor.x264_crf",
        "int",
        20,
        QT_TRANSLATE_NOOP("Settings", "Качество видео (CRF x264)"),
        QT_TRANSLATE_NOOP("Settings", "Меньше — лучше качество и больше файл"),
        low=0,
        high=51,
    ),
    Spec(
        "editor.x264_preset",
        "choice",
        "veryfast",
        QT_TRANSLATE_NOOP("Settings", "Скорость кодирования x264"),
        QT_TRANSLATE_NOOP("Settings", "Медленнее — меньше файл при том же качестве"),
        choices=tuple((p, p) for p in PRESETS),
    ),
    Spec(
        "editor.hw_encoder",
        "choice",
        "cpu",
        QT_TRANSLATE_NOOP("Settings", "Кодер видео"),
        QT_TRANSLATE_NOOP(
            "Settings", "Видеокарта кодирует быстрее, но качество при том же размере ниже"
        ),
        choices=(
            ("cpu", QT_TRANSLATE_NOOP("Settings", "процессор (x264)")),
            ("auto", QT_TRANSLATE_NOOP("Settings", "видеокарта, если есть")),
            ("nvenc", "NVIDIA NVENC"),
            ("qsv", "Intel Quick Sync"),
            ("amf", "AMD AMF"),
        ),
    ),
    Spec(
        "editor.brush_color",
        "color",
        "#ff0000",
        QT_TRANSLATE_NOOP("Settings", "Цвет кисти по умолчанию"),
    ),
    Spec(
        "editor.brush_width",
        "int",
        4,
        QT_TRANSLATE_NOOP("Settings", "Толщина кисти по умолчанию"),
        low=1,
        high=20,
    ),
    Spec(
        "editor.crop_ratio",
        "choice",
        "free",
        QT_TRANSLATE_NOOP("Settings", "Пропорции кадрирования по умолчанию"),
        choices=RATIO_CHOICES,
    ),
    Spec(
        "editor.cut_mode",
        "choice",
        "ask",
        QT_TRANSLATE_NOOP("Settings", "Резка видео"),
        QT_TRANSLATE_NOOP(
            "Settings",
            "Быстрая — без перекодирования, по ключевым кадрам; точная — с перекодированием",
        ),
        choices=(
            ("fast", QT_TRANSLATE_NOOP("Settings", "быстрая")),
            ("precise", QT_TRANSLATE_NOOP("Settings", "точная")),
            ("ask", QT_TRANSLATE_NOOP("Settings", "спрашивать при экспорте")),
        ),
    ),
    # --- Дополнительно
    Spec(
        "advanced.temp_dir",
        "path",
        "",
        QT_TRANSLATE_NOOP("Settings", "Папка временных файлов"),
        QT_TRANSLATE_NOOP("Settings", "Пусто — системная"),
        advanced=True,
    ),
    Spec(
        "advanced.thumb_cache_mb",
        "int",
        200,
        QT_TRANSLATE_NOOP("Settings", "Лимит кэша миниатюр, МБ"),
        low=0,
        high=5000,
        step=50,
        advanced=True,
    ),
    Spec(
        "advanced.threads",
        "int",
        0,
        QT_TRANSLATE_NOOP("Settings", "Число потоков кодирования"),
        QT_TRANSLATE_NOOP("Settings", "0 — решает программа"),
        low=0,
        high=64,
        advanced=True,
    ),
    Spec(
        "advanced.log_level",
        "choice",
        "warning",
        QT_TRANSLATE_NOOP("Settings", "Уровень журнала"),
        choices=(
            ("error", QT_TRANSLATE_NOOP("Settings", "только ошибки")),
            ("warning", QT_TRANSLATE_NOOP("Settings", "предупреждения")),
            ("info", QT_TRANSLATE_NOOP("Settings", "подробно")),
            ("debug", QT_TRANSLATE_NOOP("Settings", "отладка")),
        ),
        advanced=True,
    ),
    # --- Служебное: не показывается в окне, но хранится в файле
    Spec("state.window", "str", "", QT_TRANSLATE_NOOP("Settings", "Положение окна"), shown=False),
    Spec(
        "state.settings_size",
        "str",
        "860x600",
        QT_TRANSLATE_NOOP("Settings", "Размер окна настроек"),
        shown=False,
    ),
    Spec(
        "state.trim_height",
        "int",
        112,
        QT_TRANSLATE_NOOP("Settings", "Высота полосы блоков"),
        low=88,
        high=200,
        shown=False,
    ),
)

BY_KEY: dict[str, Spec] = {spec.key: spec for spec in SPECS}


def specs_of(section: str) -> list[Spec]:
    return [spec for spec in SPECS if spec.section == section]


def defaults() -> dict[str, object]:
    return {spec.key: spec.default for spec in SPECS}


# значения, которые в старых файлах назывались иначе (акценты 0.1 до смены палитры)
LEGACY_CHOICES: dict[str, dict[str, str]] = {
    "appearance.accent": {
        "orange": "ember",
        "violet": "meadow",
        "coral": "rose",
        "burgundy": "sunset",
    }
}


def coerce(spec: Spec, raw: object) -> object:
    """Приводит значение из файла к типу настройки; ValueError, если оно не подходит.

    Числа вне диапазона не отбрасываются, а ограничиваются: файл могли править вручную.
    """
    match spec.kind:
        case "bool":
            if isinstance(raw, bool):
                return raw
        case "int":
            if isinstance(raw, int) and not isinstance(raw, bool):
                return _clamp(spec, raw)
        case "float":
            if isinstance(raw, int | float) and not isinstance(raw, bool):
                return _clamp(spec, float(raw))
        case "choice":
            raw = LEGACY_CHOICES.get(spec.key, {}).get(str(raw), raw)  # прежние названия
            if isinstance(raw, str) and raw in {value for value, _ in spec.choices}:
                return raw
        case "color":
            if isinstance(raw, str) and COLOR_PATTERN.fullmatch(raw):
                return raw.lower()
        case "langs":
            if isinstance(raw, str):
                return clean_langs(raw)
            if isinstance(raw, list) and all(isinstance(item, str) for item in raw):
                return clean_langs(",".join(raw))
        case "path" | "str":
            if isinstance(raw, str) and len(raw) <= 4096 and "\0" not in raw:
                if spec.key == "editor.output_template":
                    return validate_template(raw)
                return raw
    raise ValueError(f"{spec.key}: недопустимое значение {raw!r}")


def _clamp(spec: Spec, value: float) -> float:
    if spec.low is not None:
        value = max(value, spec.low)
    if spec.high is not None:
        value = min(value, spec.high)
    return value


def clean_langs(text: str) -> str:
    """Оставляет только коды языков через запятую (они уходят в параметры mpv)."""
    codes = (re.sub(r"[^A-Za-z-]", "", part) for part in text.split(","))
    return ",".join(code for code in codes if code)


TEMPLATE_FIELD = re.compile(r"\{(name|date|time)\}")


def validate_template(template: str) -> str:
    """Шаблон имени файла: только {name}, {date}, {time}, обязательно {name}; иначе ValueError."""
    rest = TEMPLATE_FIELD.sub("", template)
    if "{name}" not in template or "{" in rest or "}" in rest:
        raise ValueError(
            f"шаблон имени должен содержать {{name}} и только известные поля: {template!r}"
        )
    if any(char in template for char in '/\\:*?"<>|'):
        raise ValueError("шаблон имени содержит недопустимые символы")
    return template
