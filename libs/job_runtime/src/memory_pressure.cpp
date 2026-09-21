// CONV-34 — see header for provenance; mirrors
// paleo_workbench/runtime/memory_pressure.py line-for-line.

#include "pwb/job_runtime/memory_pressure.hpp"

#include <chrono>
#include <charconv>
#include <fstream>

namespace pwb::job {
namespace {

[[nodiscard]] double default_clock() {
    return std::chrono::duration<double>(
               std::chrono::steady_clock::now().time_since_epoch())
        .count();
}

[[nodiscard]] std::int64_t parse_kb_field(const std::string& line,
                                          std::size_t value_begin) {
    while (value_begin < line.size() &&
           (line[value_begin] == ' ' || line[value_begin] == '\t')) {
        ++value_begin;
    }
    std::int64_t kb = 0;
    const auto* end = line.data() + line.size();
    if (std::from_chars(line.data() + value_begin, end, kb).ec != std::errc{}) {
        return 0;
    }
    return kb * 1024;
}

}  // namespace

const char* pressure_state_id(PressureState state) noexcept {
    switch (state) {
        case PressureState::normal: return "normal";
        case PressureState::pressure: return "pressure";
        case PressureState::critical: return "critical";
    }
    return "normal";
}

PressureState classify_pressure(double used_frac, double pressure_frac,
                                double critical_frac) noexcept {
    if (used_frac >= critical_frac) return PressureState::critical;
    if (used_frac >= pressure_frac) return PressureState::pressure;
    return PressureState::normal;
}

ProcMemory read_proc_memory() {
    ProcMemory out;
    {
        std::ifstream in("/proc/meminfo");
        std::string line;
        while (std::getline(in, line)) {
            if (line.rfind("MemTotal:", 0) == 0) {
                out.total_bytes = parse_kb_field(line, 9);
            } else if (line.rfind("MemAvailable:", 0) == 0) {
                out.avail_bytes = parse_kb_field(line, 13);
            }
        }
    }
    {
        std::ifstream in("/proc/self/status");
        std::string line;
        while (std::getline(in, line)) {
            if (line.rfind("VmRSS:", 0) == 0) {
                out.rss_bytes = parse_kb_field(line, 6);
                break;
            }
        }
    }
    return out;
}

MemorySample read_system_memory(const ResourceBudget& budget) {
    const ProcMemory raw = read_proc_memory();
    std::int64_t avail = raw.avail_bytes;
    std::int64_t total = raw.total_bytes;
    if (total <= 0) {
        total = static_cast<std::int64_t>(budget.total_ram_gb * kGiB);
        avail = total;
    }
    const std::int64_t used = std::max<std::int64_t>(0, total - avail);
    return {total > 0 ? static_cast<double>(used) / total : 0.0,
            raw.rss_bytes, total};
}

MemoryPressureMonitor::MemoryPressureMonitor(ResourceBudget budget,
                                             double sample_interval_s,
                                             Clock clock,
                                             MemorySampler sampler)
    : budget_(budget),
      interval_(std::max(0.0, sample_interval_s)),
      clock_(clock ? std::move(clock) : Clock(default_clock)),
      sampler_(sampler ? std::move(sampler) : MemorySampler(read_system_memory)),
      total_bytes_(static_cast<std::int64_t>(budget.total_ram_gb * kGiB)) {}

void MemoryPressureMonitor::register_evictable(const std::string& name,
                                               Evictable evict) {
    std::lock_guard<std::mutex> lock(lock_);
    evictables_[name] = std::move(evict);
}

void MemoryPressureMonitor::unregister_evictable(const std::string& name) {
    std::lock_guard<std::mutex> lock(lock_);
    evictables_.erase(name);
}

void MemoryPressureMonitor::rebind_budget(const ResourceBudget& budget) {
    std::lock_guard<std::mutex> lock(lock_);
    budget_ = budget;
}

PressureState MemoryPressureMonitor::state(bool refresh) {
    {
        std::lock_guard<std::mutex> lock(lock_);
        const bool stale =
            refresh || (clock_() - sampled_at_) >= interval_;
        if (!stale) return state_;
    }
    if (!sample_gate_.try_lock()) {
        // Someone else is sampling; the cached state is fresh enough.
        std::lock_guard<std::mutex> lock(lock_);
        return state_;
    }
    try {
        sample_once();
    } catch (...) {
        sample_gate_.unlock();
        throw;
    }
    sample_gate_.unlock();
    std::lock_guard<std::mutex> lock(lock_);
    return state_;
}

void MemoryPressureMonitor::sample_once() {
    // Read memory (unlocked), then commit state and run relief outside the
    // state lock so readers stay fast — Python _sample() parity. The
    // budget is copied once under the lock so rebind_budget() cannot tear
    // the read (the GIL hid this race in Python).
    ResourceBudget budget;
    {
        std::lock_guard<std::mutex> lock(lock_);
        budget = budget_;
    }
    const MemorySample sample = sampler_(budget);
    bool needs_relief = false;
    {
        std::lock_guard<std::mutex> lock(lock_);
        sampled_at_ = clock_();
        system_used_frac_ = sample.system_used_frac;
        rss_bytes_ = sample.rss_bytes;
        total_bytes_ = sample.total_bytes;
        state_ = classify_pressure(sample.system_used_frac,
                                   budget.ram_pressure_frac,
                                   budget.ram_critical_frac);
        needs_relief = state_ != PressureState::normal;
    }
    // State transitions AND re-entries into PRESSURE both trigger relief;
    // NORMAL is the only no-op state.
    if (needs_relief) run_relief();
}

void MemoryPressureMonitor::run_relief() {
    std::int64_t freed_total = 0;
    std::vector<Evictable> evicts;
    {
        std::lock_guard<std::mutex> lock(lock_);
        evicts.reserve(evictables_.size());
        for (const auto& [name, evict] : evictables_) evicts.push_back(evict);
    }
    for (const auto& evict : evicts) {
        try {
            freed_total += evict();  // relief must never take the app down
        } catch (...) {
        }
    }
    std::lock_guard<std::mutex> lock(lock_);
    relief_bytes_total_ += freed_total;
    relief_runs_ += 1;
}

MemoryPressureSnapshot MemoryPressureMonitor::snapshot() const {
    std::lock_guard<std::mutex> lock(lock_);
    MemoryPressureSnapshot out;
    out.state = state_;
    out.system_used_frac = system_used_frac_;
    out.rss_bytes = rss_bytes_;
    out.total_bytes = total_bytes_;
    out.pressure_frac = budget_.ram_pressure_frac;
    out.critical_frac = budget_.ram_critical_frac;
    out.relief_runs = relief_runs_;
    out.relief_freed_bytes = relief_bytes_total_;
    out.evictables.reserve(evictables_.size());
    for (const auto& [name, _] : evictables_) out.evictables.push_back(name);
    return out;
}

namespace {
std::mutex g_monitor_mutex;
std::unique_ptr<MemoryPressureMonitor> g_monitor;
}  // namespace

MemoryPressureMonitor& pressure_monitor() {
    std::lock_guard<std::mutex> lock(g_monitor_mutex);
    if (!g_monitor) {
        g_monitor = std::make_unique<MemoryPressureMonitor>(active_budget());
    }
    return *g_monitor;
}

void set_pressure_monitor(std::unique_ptr<MemoryPressureMonitor> monitor) {
    std::lock_guard<std::mutex> lock(g_monitor_mutex);
    g_monitor = std::move(monitor);
}

}  // namespace pwb::job
