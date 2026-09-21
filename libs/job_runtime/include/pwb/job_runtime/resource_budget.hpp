#pragma once

// CONV-34 — process-wide resource budget, ported 1:1 from
// paleo_workbench/runtime/resource_budget.py (frozen against
// governor_oracle.json; replayed in job_runtime.governor_oracle).
//
// One place that answers "how much RAM/VRAM/CPU/IO may background tasks
// use" so transcode buffers, attribute banding and inference batching stop
// guessing. Nothing is pre-allocated: the budget is advisory caps that
// streaming code divides window/batch sizes by; the ResourceGovernor turns
// the caps into admission decisions — this stays a pure policy object.

#include <cstdint>
#include <string>

namespace pwb::job {

inline constexpr std::int64_t kGiB = 1024LL * 1024 * 1024;

struct ResourceBudget {
    double total_ram_gb = 32.0;
    double os_reserve_gb = 6.0;
    double python_reserve_gb = 2.0;
    std::int64_t l1_slice_cache_bytes = 2 * kGiB;
    std::int64_t streaming_buffer_bytes = 5 * kGiB;
    int vram_budget_mb = 1024;
    // --- CPU column ------------------------------------------------------
    int logical_cores = 0;  // 0 -> auto-detect
    int interactive_reserve_cores = 2;
    int background_core_ceiling = 0;  // 0 -> logical_cores - reserve
    // --- IO column --------------------------------------------------------
    double io_slots = 4.0;
    // OS niceness applied to background scheduler threads (Linux-only in
    // the Python source; kept as a policy field so env pinning round-trips).
    int background_nice = 5;
    // --- RAM pressure thresholds (fractions of total RAM) -----------------
    double ram_pressure_frac = 0.85;
    double ram_critical_frac = 0.95;

    // RAM left for the OS page cache — heavy tasks must not eat into it.
    [[nodiscard]] double page_cache_floor_gb() const;

    // logical_cores > 0 wins; else std::thread::hardware_concurrency (the
    // C++ counterpart of psutil.cpu_count -> os.cpu_count); floor 1.
    [[nodiscard]] int detected_logical_cores() const;

    // Cores background work may occupy in aggregate. Degrades gracefully:
    // at least 1 core for background, at least 1 for the GUI/OS.
    [[nodiscard]] int background_cores() const;

    // Cores a single large task may use: budget minus the GUI reserve.
    [[nodiscard]] int heavy_task_core_allowance() const;

    // Scale the split for smaller/larger machines (32 GB = spec defaults).
    [[nodiscard]] static ResourceBudget for_total_ram_gb(double gb);

    // Shrink CPU/IO columns under memory pressure (RAM caps unchanged —
    // relief comes from eviction, not from re-planning the split).
    // Python parity: int(round(x)) is banker's rounding — implemented via
    // std::nearbyint (to-nearest-even), NOT std::round (half-away).
    [[nodiscard]] ResourceBudget with_pressure_scale(double factor) const;
};

// The process budget. Stable configuration path: RAM via
// PALEO_BUDGET_RAM_GB; CPU/IO via PALEO_BUDGET_CORES / PALEO_IO_SLOTS /
// PALEO_BACKGROUND_NICE on top of the detected budget.
[[nodiscard]] ResourceBudget active_budget();
void set_budget(const ResourceBudget& budget);  // test/reconfigure seam
// Test/teardown seam: clears the cached budget so the next active_budget()
// re-reads env (Python parity: assigning ``resource_budget._ACTIVE = None``).
void reset_active_budget();

// Reads /proc/meminfo MemTotal (Linux); falls back to the 32 GB spec
// default on platforms without it (Python parity: same fallback).
[[nodiscard]] double detect_ram_gb();

}  // namespace pwb::job
