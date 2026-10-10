"""Режим рендера, выбор видеокарты и сторож зависаний (`services/graphics.py`)."""

import sys

import pytest

from chopchop.core.settings_schema import BY_KEY
from chopchop.services import graphics

HYBRID = ["Intel(R) Iris(R) Xe Graphics", "NVIDIA GeForce RTX 3060 Laptop GPU"]


def test_hybrid_laptop_is_detected_from_adapter_names() -> None:
    assert graphics.is_hybrid(HYBRID)
    assert not graphics.is_hybrid(["NVIDIA GeForce RTX 3060"])
    assert not graphics.is_hybrid(["Intel(R) UHD Graphics 620"])
    assert not graphics.is_hybrid([])


def test_auto_takes_the_integrated_gpu_only_on_hybrid_laptops() -> None:
    assert graphics.plan("auto", "auto", False, hybrid=True).gpu == "integrated"
    assert graphics.plan("auto", "auto", False, hybrid=False).gpu == "system"
    assert graphics.plan("auto", "discrete", False, hybrid=True).gpu == "discrete"
    assert graphics.plan("auto", "system", False, hybrid=True).gpu == "system"


def test_render_mode_follows_settings_and_fallback() -> None:
    assert graphics.plan("auto", "auto", False, hybrid=False).render == "hardware"
    assert graphics.plan("auto", "auto", True, hybrid=False).render == "software"
    assert graphics.plan("hardware", "auto", True, hybrid=False).render == "hardware"
    assert graphics.plan("software", "auto", False, hybrid=False).render == "software"


def test_settings_defaults() -> None:
    assert BY_KEY["graphics.render"].default == "auto"
    assert BY_KEY["graphics.gpu"].default == "auto"
    assert BY_KEY["graphics.render"].apply == "restart"
    assert BY_KEY["state.graphics_fallback"].default is False
    assert BY_KEY["graphics.hang_grace"].default == 6


def test_guard_ignores_stalls_inside_the_grace_period() -> None:
    tripped: list[int] = []
    guard = graphics.HangGuard(lambda: tripped.append(1), grace_s=5.0, limit=3)
    guard.start(0.0)
    now = 0.0
    for _ in range(10):  # 10 пауз по 0,2 с в первые 2 секунды: открытие файла
        now += 0.2
        guard.tick(now)
    assert not tripped and guard.stalls == 0


def test_guard_trips_after_the_grace_period_on_repeated_stalls() -> None:
    tripped: list[int] = []
    guard = graphics.HangGuard(lambda: tripped.append(1), grace_s=1.0, limit=3)
    guard.start(0.0)
    now = 0.0
    for _ in range(80):
        now += 0.016
        guard.tick(now)
    assert not tripped
    for _ in range(3):
        now += 0.25
        guard.tick(now)
    assert tripped == [1] and guard.tripped


def test_guard_needs_repeated_stalls_not_a_single_long_one() -> None:
    tripped: list[int] = []
    guard = graphics.HangGuard(lambda: tripped.append(1), grace_s=0.0, limit=3)
    guard.start(0.0)
    guard.tick(5.0)  # одна долгая пауза, например диск
    assert not tripped and guard.stalls == 1


def test_guard_does_not_count_time_while_inactive() -> None:
    tripped: list[int] = []
    guard = graphics.HangGuard(lambda: tripped.append(1), grace_s=0.0, limit=2)
    guard.start(0.0)
    now = 0.0
    for _ in range(6):  # редактор открыт: паузы не считаются
        now += 0.3
        guard.tick(now, active=False)
    assert not tripped and guard.stalls == 0


def test_guard_stops_watching_after_the_window() -> None:
    tripped: list[int] = []
    guard = graphics.HangGuard(lambda: tripped.append(1), grace_s=0.0, window_s=1.0, limit=2)
    guard.start(0.0)
    guard.tick(2.0)  # окно наблюдения кончилось одной паузой: она засчитана
    for i in range(10):
        guard.tick(3.0 + i)
    assert guard.stalls <= 1 and not tripped


@pytest.mark.skipif(sys.platform != "win32", reason="реестр Windows")
def test_gpu_preference_round_trip_in_the_registry() -> None:
    image = r"C:\chopchop-test\fake-chopchop-test.exe"
    try:
        assert graphics.read_gpu_preference(image) is None
        graphics.write_gpu_preference(1, image)
        assert graphics.read_gpu_preference(image) == 1
        graphics.write_gpu_preference(2, image)
        assert graphics.read_gpu_preference(image) == 2
    finally:
        graphics.write_gpu_preference(None, image)
    assert graphics.read_gpu_preference(image) is None
