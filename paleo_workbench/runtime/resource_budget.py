"""Process-wide resource budget for heavy workflows (#1081, extended P2-A).

One place that answers "how much RAM/VRAM/CPU/IO may background tasks use" so
transcode buffers, attribute banding and inference batching stop guessing.
Defaults follow the 100G spec §7 (32 GB machine):

    OS + Qt                  ~6 GB   (reserved, not ours)
    Python/business          ~2 GB   (reserved)
    L1 slice cache            2 GB   (RamSliceCache global ledger)
    Streaming buffer          5 GB   (heavy-task working set cap)
    OS page cache          remaining (never pre-allocated)
    VRAM (L2)               1 GiB    (VramTextureCache budget)

P2-A adds the CPU and IO columns on the same authority:

    logical cores              all   (detected, override ``logical_cores``)
    interactive reserve      2 cores (GUI/OS + interactive rendering)
    background ceiling  cores − reserve (what heavy tasks may use)
    IO slots                    4    (process-wide weighted IO concurrency)

Nothing is pre-allocated: the budget is advisory caps that streaming code
divides its window/batch sizes by. The :class:`ResourceGovernor` turns the
caps into admission decisions; this module stays a pure policy object.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, replace

_GIB = 1024**3


@dataclass(frozen=True)
class ResourceBudget:
    total_ram_gb: float = 32.0
    os_reserve_gb: float = 6.0
    python_reserve_gb: float = 2.0
    l1_slice_cache_bytes: int = 2 * _GIB
    streaming_buffer_bytes: int = 5 * _GIB
    vram_budget_mb: int = 1024
    # --- CPU column (P2-A) ------------------------------------------------
    logical_cores: int = 0  # 0 -> auto-detect
    interactive_reserve_cores: int = 2
    background_core_ceiling: int = 0  # 0 -> logical_cores - interactive_reserve
    # --- IO column (P2-A) -------------------------------------------------
    io_slots: float = 4.0
    # --- RAM pressure thresholds (P2-A), fractions of total RAM -----------
    ram_pressure_frac: float = 0.85
    ram_critical_frac: float = 0.95

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

    @property
    def detected_logical_cores(self) -> int:
        if self.logical_cores > 0:
            return self.logical_cores
        try:
            import psutil

            n = psutil.cpu_count(logical=True)
        except Exception:
            n = os.cpu_count()
        return max(1, n or 1)

    @property
    def background_cores(self) -> int:
        """Cores background (non-interactive) work may occupy in aggregate.

        Degrades gracefully on small machines: at least 1 core stays
        available for background work, at least 1 for the GUI/OS.
        """
        ceiling = (
            self.background_core_ceiling
            if self.background_core_ceiling > 0
            else self.detected_logical_cores - self.interactive_reserve_cores
        )
        return max(1, min(ceiling, self.detected_logical_cores - 1))

    @property
    def heavy_task_core_allowance(self) -> int:
        """Cores a single large task may use: budget, minus the GUI reserve."""
        return max(1, min(self.background_cores, self.detected_logical_cores - 1))

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
            interactive_reserve_cores=2 if gb >= 16 else 1,
        )

    def with_pressure_scale(self, factor: float) -> "ResourceBudget":
        """Shrink the CPU/IO columns under memory pressure (RAM caps unchanged:
        pressure relief comes from eviction, not from re-planning the split)."""
        factor = min(1.0, max(0.1, float(factor)))
        return replace(
            self,
            background_core_ceiling=max(1, int(round(self.background_cores * factor))),
            io_slots=max(1.0, self.io_slots * factor),
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


def apply_l1_budget(budget: ResourceBudget) -> bool:
    """Push the L1 slice-cache cap into the engine's shared RAM ledger."""
    try:
        from geoviz_seismic.cache import set_global_budget  # type: ignore

        set_global_budget(budget.l1_slice_cache_bytes)
        return True
    except Exception:
        return False


def apply_compute_budget(budget: ResourceBudget) -> bool:
    """Constrain the vendored interpolation engine's CPU dial to the budget.

    The vendored ``ComputeSettings`` maps a 0–100 percent slider to worker
    counts; we express "background ceiling of N cores out of M logical" as a
    percentage so its own clamping logic (always leaving UI headroom) keeps
    working. Explicit ``PALEO_HAIYOU_CPU_PERCENT`` env wins — vendored code
    stays env-driven.
    """
    if os.environ.get("PALEO_HAIYOU_CPU_PERCENT"):
        return False
    try:
        from paleo_workbench._vendored.haiyou_constrained_idw.drawing.compute.performance import (
            get_compute_settings,
        )

        settings = get_compute_settings()
        logical = budget.detected_logical_cores
        percent = int(round(100.0 * budget.background_cores / max(1, logical)))
        settings.set_cpu_percent(min(100, max(1, percent)))
        return True
    except Exception:
        return False


def apply_all_budgets(budget: ResourceBudget) -> dict[str, bool]:
    """Push every budget column into its engine; missing engines report False."""
    return {
        "vram": apply_vram_budget(budget),
        "l1_slice_cache": apply_l1_budget(budget),
        "compute": apply_compute_budget(budget),
    }


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
