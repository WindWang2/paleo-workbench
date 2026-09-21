#pragma once

// CONV-34 — RAM pressure monitoring, ported 1:1 from
// paleo_workbench/runtime/memory_pressure.py (frozen in
// governor_oracle.json; replayed in job_runtime.governor_oracle).
//
// The budget decides what the process *may* use; this monitor observes
// what the machine *has left* and classifies it NORMAL / PRESSURE /
// CRITICAL. Sampling is lazy and rate-limited (no background thread):
// the governor samples on admission and anyone may call refresh().

#include <cstdint>
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

#include "pwb/job_runtime/resource_budget.hpp"

namespace pwb::job {

enum class PressureState : std::uint8_t { normal, pressure, critical };

[[nodiscard]] const char* pressure_state_id(PressureState state) noexcept;

// (system_used_fraction, process_rss_bytes, system_total_bytes)
struct MemorySample {
    double system_used_frac = 0.0;
    std::int64_t rss_bytes = 0;
    std::int64_t total_bytes = 0;
};

// Eviction callback registered by cache owners: returns bytes actually
// freed (best effort, must never throw).
using Evictable = std::function<std::int64_t()>;
using Clock = std::function<double()>;  // monotonic seconds
using MemorySampler = std::function<MemorySample(const ResourceBudget&)>;

[[nodiscard]] PressureState classify_pressure(double used_frac,
                                              double pressure_frac,
                                              double critical_frac) noexcept;

// (MemTotal, MemAvailable, VmRSS) bytes from /proc; zeros when
// unavailable — Python _read_proc_meminfo parity.
struct ProcMemory {
    std::int64_t total_bytes = 0;
    std::int64_t avail_bytes = 0;
    std::int64_t rss_bytes = 0;
};
[[nodiscard]] ProcMemory read_proc_memory();
// psutil-first equivalent: /proc everywhere (no psutil dependency); final
// fallback trusts the budget so the governor still functions on platforms
// without /proc.
[[nodiscard]] MemorySample read_system_memory(const ResourceBudget& budget);

struct MemoryPressureSnapshot {
    PressureState state = PressureState::normal;
    double system_used_frac = 0.0;
    std::int64_t rss_bytes = 0;
    std::int64_t total_bytes = 0;
    double pressure_frac = 0.0;
    double critical_frac = 0.0;
    std::int64_t relief_runs = 0;
    std::int64_t relief_freed_bytes = 0;
    std::vector<std::string> evictables;  // sorted names
};

class MemoryPressureMonitor {
public:
    explicit MemoryPressureMonitor(
        ResourceBudget budget,
        double sample_interval_s = 1.0,
        Clock clock = {},
        MemorySampler sampler = {});

    // Best-effort cache-eviction callback (idempotent by name).
    void register_evictable(const std::string& name, Evictable evict);
    void unregister_evictable(const std::string& name);
    // Follow a new budget's thresholds (state survives).
    void rebind_budget(const ResourceBudget& budget);

    // Current state; re-samples when the cached sample is stale. Never
    // blocks on sampling: one caller becomes the sampler (gated), everyone
    // else reads the cached state — a slow /proc read must not serialize
    // every admission.
    [[nodiscard]] PressureState state(bool refresh = false);
    [[nodiscard]] PressureState refresh() { return state(true); }

    [[nodiscard]] MemoryPressureSnapshot snapshot() const;

private:
    void sample_once();
    void run_relief();

    ResourceBudget budget_;
    double interval_;
    Clock clock_;
    MemorySampler sampler_;
    mutable std::mutex lock_;
    std::mutex sample_gate_;  // try-lock: one sampler at a time
    std::map<std::string, Evictable> evictables_;
    PressureState state_ = PressureState::normal;
    double sampled_at_ = -1e300;  // -inf parity: first state() always samples
    double system_used_frac_ = 0.0;
    std::int64_t rss_bytes_ = 0;
    std::int64_t total_bytes_;
    std::int64_t relief_bytes_total_ = 0;
    std::int64_t relief_runs_ = 0;
};

// Process-wide monitor bound to the active budget (lazily created).
// Default evictables are engine wiring, installed by the app — the kernel
// carries no cache knowledge (Python `_install_default_evictables` pushed
// Python-side caches that have no counterpart in this kernel).
[[nodiscard]] MemoryPressureMonitor& pressure_monitor();
// Test/teardown helper; nullptr resets to lazy default.
void set_pressure_monitor(std::unique_ptr<MemoryPressureMonitor> monitor);

}  // namespace pwb::job
