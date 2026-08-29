"""Process-wide resource budget for heavy workflows (#1081).

One place that answers "how much RAM/VRAM may background tasks use" so
transcode buffers, attribute banding and inference batching stop guessing.
Defaults follow the 100G spec §7 (32 GB machine):

    OS + Qt                  ~6 GB   (reserved, not ours)
    Python/business          ~2 GB   (reserved)
    L1 slice cache            2 GB   (RamSliceCache global ledger)
    Streaming buffer          5 GB   (heavy-task working set cap)
    OS page cache          remaining (never pre-allocated)
    VRAM (L2)               1 GiB    (VramTextureCache budget)

Nothing is pre-allocated: the budget is advisory caps that streaming code
divides its window/batch sizes by.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

_GIB = 1024**3


@dataclass(frozen=True)
class ResourceBudget:
    total_ram_gb: float = 32.0
    os_reserve_gb: float = 6.0
    python_reserve_gb: float = 2.0
    l1_slice_cache_bytes: int = 2 * _GIB
    streaming_buffer_bytes: int = 5 * _GIB
    vram_budget_mb: int = 1024

    @property
    def page_cache_floor_gb(self) -> float:
        """RAM left for the OS page cache — heavy tasks must not eat into it."""
        return max(
            0.0,
            self.total_ram_gb
            - self.os_reserve_gb
            - self.python_reserve_gb
            - self.l1_slice_cache_bytes / _GIB
            - self.streaming_buffer_bytes / _GIB,
        )

    @classmethod
    def for_total_ram_gb(cls, gb: float) -> "ResourceBudget":
        """Scale the split for smaller/larger machines (32 GB = spec defaults)."""
        gb = max(8.0, float(gb))
        scale = min(1.0, gb / 32.0)  # caps never grow beyond spec defaults
        return cls(
            total_ram_gb=gb,
            os_reserve_gb=6.0 if gb >= 24 else 4.0,
            python_reserve_gb=2.0,
            l1_slice_cache_bytes=int(2 * _GIB * scale),
            streaming_buffer_bytes=int(5 * _GIB * scale),
            vram_budget_mb=1024 if gb >= 16 else 512,
        )


_ACTIVE: ResourceBudget | None = None


def active_budget() -> ResourceBudget:
    """The process budget (env override: PALEO_BUDGET_RAM_GB)."""
    global _ACTIVE
    if _ACTIVE is None:
        env = os.environ.get("PALEO_BUDGET_RAM_GB")
        if env:
            try:
                _ACTIVE = ResourceBudget.for_total_ram_gb(float(env))
            except ValueError:
                _ACTIVE = ResourceBudget()
        else:
            _ACTIVE = ResourceBudget.for_total_ram_gb(_detect_ram_gb())
    return _ACTIVE


def set_budget(budget: ResourceBudget) -> None:
    global _ACTIVE
    _ACTIVE = budget


def apply_vram_budget(budget: ResourceBudget) -> bool:
    """Push the VRAM cap into the engine's L2 cache (all-type ledger)."""
    try:
        from geoviz_seismic.vram_cache import VRAM  # type: ignore

        VRAM.set_budget(budget.vram_budget_mb * 1024 * 1024)
        return True
    except Exception:
        return False


def _detect_ram_gb() -> float:
    try:
        with open("/proc/meminfo", encoding="ascii") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return kb / (1024**2)
    except (OSError, ValueError, IndexError):
        pass
    return 32.0
