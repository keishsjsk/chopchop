"""Как программа рисует: режим рендера и видеокарта (настройки «Графика»).

Всё решается до создания `QApplication`, потому что режим OpenGL и видеокарту нельзя сменить на
лету: `plan()` читает настройки, `apply()` выставляет переменные среды и (на Windows) настройку
видеокарты для самой программы. Подробности и цифры: `docs/performance.md`.

Три режима рендера:
  - «аппаратный»: плеер рисует через OpenGL (`QOpenGLWidget`), как обычно;
  - «программный»: без OpenGL вообще: mpv рисует кадр в память (render API `sw`), окно обычное
    растровое. Нужен там, где нет аппаратного OpenGL или он тормозит;
  - «авто»: аппаратный, а если в первые секунды воспроизведения интерфейс зависал слишком часто
    (`HangGuard`), следующий запуск идёт в программном режиме.

Гибридные ноутбуки (Intel + NVIDIA, Intel + AMD): по умолчанию Windows даёт OpenGL дискретной
видеокарте, а окном управляет встроенная, и каждый кадр копируется между ними. Программа просит
у Windows для себя встроенную видеокарту (`HKCU\\Software\\Microsoft\\DirectX\\UserGpuPreferences`,
то же, что «Параметры → Дисплей → Графика»), на Linux ставит `DRI_PRIME`.
"""

import contextlib
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

RENDER_MODES = ("auto", "hardware", "software")
GPU_CHOICES = ("auto", "integrated", "discrete", "system")
# значения `GpuPreference` в реестре Windows: 0 решает система, 1 энергосбережение (встроенная),
# 2 высокая производительность (дискретная)
WINDOWS_PREFERENCE = {"integrated": 1, "discrete": 2, "system": 0}
PREFERENCES_KEY = r"Software\Microsoft\DirectX\UserGpuPreferences"
DISPLAY_CLASS_KEY = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
DISCRETE_WORDS = ("nvidia", "geforce", "quadro", "radeon rx", "radeon pro", "arc a", "arc(tm) a")
INTEGRATED_WORDS = (
    "intel(r) uhd",
    "intel(r) iris",
    "intel(r) hd",
    "radeon(tm) graphics",
    "radeon graphics",
)


@dataclass(frozen=True)
class Plan:
    render: str  # "hardware" или "software"
    gpu: str  # "integrated", "discrete" или "system"
    hybrid: bool
    reason: str


_current = Plan("hardware", "system", False, "")
_applied = False


def current() -> Plan:
    return _current


def software() -> bool:
    return _current.render == "software"


def adapters() -> list[str]:
    """Названия видеоадаптеров системы (Windows: из реестра; Linux: из `/sys/class/drm`)."""
    names: list[str] = []
    if sys.platform == "win32":
        import winreg

        with (
            contextlib.suppress(OSError),
            winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, DISPLAY_CLASS_KEY) as root,
        ):
            index = 0
            while True:
                try:
                    sub = winreg.EnumKey(root, index)
                except OSError:
                    break
                index += 1
                if sub.isdigit():
                    with contextlib.suppress(OSError), winreg.OpenKey(root, sub) as key:
                        names.append(str(winreg.QueryValueEx(key, "DriverDesc")[0]))
    else:
        vendors = {"0x8086": "Intel", "0x10de": "NVIDIA", "0x1002": "AMD"}
        for card in sorted(Path("/sys/class/drm").glob("card[0-9]")):
            with contextlib.suppress(OSError):
                vendor = (card / "device" / "vendor").read_text().strip()
                names.append(vendors.get(vendor, vendor))
    return names


def is_hybrid(names: list[str] | None = None) -> bool:
    """Есть и встроенная, и дискретная видеокарта (типичный ноутбук Intel + NVIDIA)."""
    names = adapters() if names is None else names
    lowered = [name.lower() for name in names]
    if sys.platform != "win32":
        return len(set(lowered)) > 1 and any(n in ("nvidia", "amd") for n in lowered)
    discrete = any(any(word in n for word in DISCRETE_WORDS) for n in lowered)
    integrated = any(any(word in n for word in INTEGRATED_WORDS) for n in lowered)
    return discrete and integrated


def plan(render: str, gpu: str, fallback: bool, hybrid: bool | None = None) -> Plan:
    """Что делать при запуске по настройкам (чистая функция: проверяется тестами)."""
    hybrid = is_hybrid() if hybrid is None else hybrid
    if render == "software":
        mode, why = "software", "режим выбран в настройках"
    elif render == "hardware":
        mode, why = "hardware", "режим выбран в настройках"
    elif fallback:
        mode, why = "software", "авто: прошлый запуск зависал, включён программный режим"
    else:
        mode, why = "hardware", "авто"
    if gpu == "auto":
        # на гибридном ноутбуке OpenGL и окно должны быть на одной видеокарте: встроенной
        chosen = "integrated" if hybrid else "system"
    else:
        chosen = gpu if gpu in WINDOWS_PREFERENCE else "system"
    return Plan(mode, chosen, hybrid, why)


def process_image() -> str:
    """Путь к exe текущего процесса: по нему Windows хранит выбор видеокарты."""
    if sys.platform != "win32":
        return sys.executable
    import ctypes

    buffer = ctypes.create_unicode_buffer(1024)
    ctypes.windll.kernel32.GetModuleFileNameW(None, buffer, 1024)
    return buffer.value


def read_gpu_preference(image: str | None = None) -> int | None:
    if sys.platform != "win32":
        return None
    import winreg

    with (
        contextlib.suppress(OSError),
        winreg.OpenKey(winreg.HKEY_CURRENT_USER, PREFERENCES_KEY) as key,
    ):
        text = str(winreg.QueryValueEx(key, image or process_image())[0])
        for part in text.split(";"):
            if part.startswith("GpuPreference="):
                return int(part.split("=", 1)[1])
    return None


def write_gpu_preference(value: int | None, image: str | None = None) -> None:
    """Запоминает для программы видеокарту (0, 1, 2); None удаляет запись.

    Действует сразу, если записать до первого обращения процесса к OpenGL, то есть до показа окна.
    """
    if sys.platform != "win32":
        return
    import winreg

    image = image or process_image()
    with (
        contextlib.suppress(OSError),
        winreg.CreateKey(winreg.HKEY_CURRENT_USER, PREFERENCES_KEY) as key,
    ):
        if value is None:
            with contextlib.suppress(OSError):
                winreg.DeleteValue(key, image)
        else:
            winreg.SetValueEx(key, image, 0, winreg.REG_SZ, f"GpuPreference={value};")


def apply(chosen: Plan) -> None:
    """Выставляет среду для выбранного плана. Вызывать до создания `QApplication`."""
    global _current, _applied
    _current = chosen
    _applied = True
    if sys.platform == "win32":
        wanted = WINDOWS_PREFERENCE.get(chosen.gpu, 0)
        if chosen.gpu == "system":
            # свою запись не оставляем: пусть решает система (или пользователь в «Параметрах»)
            if read_gpu_preference() in (1, 2):
                write_gpu_preference(None)
        elif read_gpu_preference() != wanted:
            write_gpu_preference(wanted)
    elif chosen.gpu == "integrated":
        os.environ.setdefault("DRI_PRIME", "0")
    elif chosen.gpu == "discrete":
        os.environ.setdefault("DRI_PRIME", "1")
        os.environ.setdefault("__NV_PRIME_RENDER_OFFLOAD", "1")
        os.environ.setdefault("__GLX_VENDOR_LIBRARY_NAME", "nvidia")


class HangGuard:
    """Считает зависания цикла событий в первые секунды воспроизведения.

    Первые `grace_s` секунд после начала не считаются: в это время открывается файл, строятся
    панели и миниатюры, и паузы там нормальны. Дальше в течение `window_s` секунд ведётся счёт:
    если пауз дольше `stall_ms` набралось `limit`, вызывается `on_trip` (программа запоминает:
    в следующий раз идти в программном режиме). Пока `active` ложно (открыт редактор, окно
    скрыто), время не считается и паузы не копятся.
    """

    def __init__(
        self,
        on_trip: Callable[[], None] | None,
        grace_s: float = 6.0,
        window_s: float = 12.0,
        stall_ms: float = 100.0,
        limit: int = 12,
    ) -> None:
        self.on_trip = on_trip
        self.grace_s = grace_s
        self.window_s = window_s
        self.stall_ms = stall_ms
        self.limit = limit
        self.stalls = 0
        self.tripped = False
        self._started: float | None = None
        self._last = 0.0
        self._counted = 0.0  # сколько активного времени прошло с начала

    def start(self, now: float | None = None) -> None:
        self._started = time.perf_counter() if now is None else now
        self._last = self._started
        self._counted = 0.0
        self.stalls = 0

    def tick(self, now: float | None = None, active: bool = True) -> None:
        """Вызывается таймером интерфейса примерно раз в 16 мс."""
        if self._started is None or self.tripped:
            return
        now = time.perf_counter() if now is None else now
        gap = now - self._last
        self._last = now
        if not active:
            return  # время простоя редактора и скрытого окна не считается
        self._counted += gap
        if self._counted > self.grace_s + self.window_s:
            self._started = None
            return
        if self._counted > self.grace_s and gap * 1000 > self.stall_ms:
            self.stalls += 1
            if self.stalls >= self.limit:
                self.tripped = True
                if self.on_trip is not None:
                    self.on_trip()
