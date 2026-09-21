// CONV-34 — see header for provenance; every formula here mirrors
// paleo_workbench/runtime/resource_budget.py line-for-line.

#include "pwb/job_runtime/resource_budget.hpp"

#include <algorithm>
#include <charconv>
#include <cmath>
#include <cstdlib>
#include <fstream>
#include <mutex>
#include <string>
#include <thread>

namespace pwb::job {
namespace {

[[nodiscard]] double clamp01_up(double v, double lo, double hi) {
    return std::min(hi, std::max(lo, v));
}

// Python int(round(x)) under the default IEEE to-nearest-even mode.
[[nodiscard]] int py_round_to_int(double v) {
    return static_cast<int>(std::nearbyint(v));
}

[[nodiscard]] int env_int(const char* name, bool* present) {
    const char* raw = std::getenv(name);
    *present = false;
    if (raw == nullptr) return 0;
    std::string s(raw);
    const auto first = s.find_first_not_of(" \t\n\r\v\f");
    if (first == std::string::npos) return 0;
    const auto last = s.find_last_not_of(" \t\n\r\v\f");
    s = s.substr(first, last - first + 1);
    int value = 0;
    const char* digits = s.data();
    if (*digits == '+') ++digits;  // Python int() accepts a leading '+'
    const auto* end = s.data() + s.size();
    const auto res = std::from_chars(digits, end, value);
    if (res.ec != std::errc{} || res.ptr != end) return 0;  // ValueError -> None
    *present = true;
    return value;
}

// _apply_env_overrides: cores/io_slots gate on truthiness (0 keeps the
// detected column); nice gates on presence — PALEO_BACKGROUND_NICE=0 is a
// real override. Python `cores if cores else` / `nice if nice is not None`
// parity.
void apply_env_overrides(ResourceBudget& budget) {
    bool has_cores = false;
    bool has_io = false;
    bool has_nice = false;
    const int cores = env_int("PALEO_BUDGET_CORES", &has_cores);
    const int io_slots = env_int("PALEO_IO_SLOTS", &has_io);
    const int nice = env_int("PALEO_BACKGROUND_NICE", &has_nice);
    if (has_cores && cores) budget.logical_cores = cores;
    if (has_io && io_slots) budget.io_slots = static_cast<double>(io_slots);
    if (has_nice) budget.background_nice = nice;
}

}  // namespace

double ResourceBudget::page_cache_floor_gb() const {
    const double l1 = static_cast<double>(l1_slice_cache_bytes) / kGiB;
    const double stream = static_cast<double>(streaming_buffer_bytes) / kGiB;
    return std::max(0.0, total_ram_gb - os_reserve_gb - python_reserve_gb - l1 - stream);
}

int ResourceBudget::detected_logical_cores() const {
    if (logical_cores > 0) return logical_cores;
    const unsigned hw = std::thread::hardware_concurrency();
    return std::max(1, static_cast<int>(hw));
}

int ResourceBudget::background_cores() const {
    const int ceiling = background_core_ceiling > 0
                            ? background_core_ceiling
                            : detected_logical_cores() - interactive_reserve_cores;
    return std::max(1, std::min(ceiling, detected_logical_cores() - 1));
}

int ResourceBudget::heavy_task_core_allowance() const {
    return std::max(1, std::min(background_cores(), detected_logical_cores() - 1));
}

ResourceBudget ResourceBudget::for_total_ram_gb(double gb) {
    gb = std::max(8.0, gb);
    const double scale = std::min(1.0, gb / 32.0);  // caps never grow past spec
    ResourceBudget b;
    b.total_ram_gb = gb;
    b.os_reserve_gb = gb >= 24 ? 6.0 : 4.0;
    b.python_reserve_gb = 2.0;
    b.l1_slice_cache_bytes = static_cast<std::int64_t>(2 * kGiB * scale);
    b.streaming_buffer_bytes = static_cast<std::int64_t>(5 * kGiB * scale);
    b.vram_budget_mb = gb >= 16 ? 1024 : 512;
    b.interactive_reserve_cores = gb >= 16 ? 2 : 1;
    return b;
}

ResourceBudget ResourceBudget::with_pressure_scale(double factor) const {
    factor = clamp01_up(factor, 0.1, 1.0);
    ResourceBudget b = *this;
    b.background_core_ceiling = std::max(1, py_round_to_int(background_cores() * factor));
    b.io_slots = std::max(1.0, io_slots * factor);
    return b;
}

double detect_ram_gb() {
    std::ifstream in("/proc/meminfo");
    std::string line;
    while (std::getline(in, line)) {
        if (line.rfind("MemTotal:", 0) == 0) {
            std::size_t i = 9;
            while (i < line.size() && (line[i] == ' ' || line[i] == '\t')) ++i;
            std::int64_t kb = 0;
            const auto* end = line.data() + line.size();
            if (std::from_chars(line.data() + i, end, kb).ec == std::errc{}) {
                return static_cast<double>(kb) / (1024.0 * 1024.0);
            }
            break;
        }
    }
    return 32.0;
}

namespace {
std::mutex g_budget_mutex;
ResourceBudget g_active;
bool g_active_set = false;
}  // namespace

ResourceBudget active_budget() {
    std::lock_guard<std::mutex> lock(g_budget_mutex);
    if (g_active_set) return g_active;
    const char* env = std::getenv("PALEO_BUDGET_RAM_GB");
    ResourceBudget b;
    if (env != nullptr && *env != '\0') {
        // Python float(env): full-string parse incl. surrounding space;
        // ValueError (garbage, trailing junk) -> plain ResourceBudget().
        // float("nan") does NOT raise: it flows into for_total_ram_gb
        // where max(8.0, nan) = 8.0 — std::max mirrors that ordering.
        char* end = nullptr;
        const double gb = std::strtod(env, &end);
        while (end != nullptr && (*end == ' ' || *end == '\t')) ++end;
        if (end != nullptr && *end == '\0' && end != env) {
            b = ResourceBudget::for_total_ram_gb(gb);
        } else {
            b = ResourceBudget{};
        }
    } else {
        b = ResourceBudget::for_total_ram_gb(detect_ram_gb());
    }
    apply_env_overrides(b);
    g_active = b;
    g_active_set = true;
    return g_active;
}

void set_budget(const ResourceBudget& budget) {
    std::lock_guard<std::mutex> lock(g_budget_mutex);
    g_active = budget;
    g_active_set = true;
}

void reset_active_budget() {
    std::lock_guard<std::mutex> lock(g_budget_mutex);
    g_active = ResourceBudget{};
    g_active_set = false;
}

}  // namespace pwb::job
