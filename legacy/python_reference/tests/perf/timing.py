from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class Timing:
    name: str
    ms: float


def timed(name: str, fn: Callable[[], T]) -> tuple[Timing, T]:
    start = time.perf_counter()
    result = fn()
    ms = (time.perf_counter() - start) * 1000.0
    return Timing(name=name, ms=ms), result


def format_stress_line(scenario: str, *, n: int, ms: float) -> str:
    return f"[datapage-stress] {scenario} n={n} elapsed_ms={ms:.1f}"


def print_stress(scenario: str, *, n: int, ms: float) -> None:
    print(format_stress_line(scenario, n=n, ms=ms), flush=True)
