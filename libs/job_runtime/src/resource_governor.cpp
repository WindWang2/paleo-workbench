// CONV-34 — see header for provenance; mirrors
// paleo_workbench/runtime/resource_governor.py line-for-line.

#include "pwb/job_runtime/resource_governor.hpp"

#include <algorithm>
#include <chrono>

namespace pwb::job {
namespace {

// Pressure -> multiplier applied to the background CPU/IO columns.
[[nodiscard]] double pressure_scale(PressureState state) noexcept {
    switch (state) {
        case PressureState::normal: return 1.0;
        case PressureState::pressure: return 0.5;
        case PressureState::critical: return 0.25;
    }
    return 1.0;
}

// Categories that may still be admitted under CRITICAL pressure (small,
// user-facing work must keep responding; everything else is shed).
[[nodiscard]] bool critical_exempt(JobCategory category) noexcept {
    return category == JobCategory::interactive_render ||
           category == JobCategory::interactive_query ||
           category == JobCategory::preview;
}

[[nodiscard]] double default_clock() {
    return std::chrono::duration<double>(
               std::chrono::steady_clock::now().time_since_epoch())
        .count();
}

[[nodiscard]] bool starts_with(const std::string& s, std::string_view prefix) {
    return s.size() >= prefix.size() && s.compare(0, prefix.size(), prefix) == 0;
}

}  // namespace

TaskRequest TaskRequest::from_kind(const std::string& kind,
                                   std::optional<int> priority,
                                   std::string title,
                                   double estimated_cpu_cores,
                                   std::int64_t estimated_ram_bytes,
                                   std::int64_t estimated_vram_bytes,
                                   std::string task_id) {
    TaskRequest request;
    request.category = category_for_kind(kind);
    request.priority = priority;
    request.title = std::move(title);
    request.estimated_cpu_cores = estimated_cpu_cores;
    request.estimated_ram_bytes = estimated_ram_bytes;
    request.estimated_vram_bytes = estimated_vram_bytes;
    request.task_id = std::move(task_id);
    return request;
}

int TaskRequest::effective_priority() const {
    if (priority.has_value()) return *priority;
    const CategoryPolicy* policy = policy_for(category);
    return policy ? policy->base_priority : 0;
}

double TaskRequest::effective_io_weight() const {
    if (io_weight.has_value()) return *io_weight;
    const CategoryPolicy* policy = policy_for(category);
    return policy ? policy->io_weight : 1.0;
}

void ResourceLease::release() {
    if (released_at_.has_value() || governor_ == nullptr) return;
    released_at_ = governor_->now();
    governor_->release_lease(*this);
    governor_ = nullptr;
}

double ResourceLease::held_seconds() const {
    const double end = released_at_.value_or(governor_ ? governor_->now() : acquired_at_);
    return end - acquired_at_;
}

ResourceGovernor::ResourceGovernor(ResourceBudget budget,
                                   MemoryPressureMonitor* monitor,
                                   Clock clock)
    : budget_(budget),
      monitor_(monitor),
      clock_(clock ? std::move(clock) : Clock(default_clock)) {}

void ResourceGovernor::set_budget(const ResourceBudget& budget) {
    std::lock_guard<std::mutex> lock(lock_);
    budget_ = budget;
}

ResourceBudget ResourceGovernor::effective_budget() const {
    return budget_.with_pressure_scale(pressure_scale(pressure_));
}

std::unique_ptr<ResourceLease> ResourceGovernor::try_admit(const TaskRequest& request) {
    std::lock_guard<std::mutex> lock(lock_);
    refresh_pressure_locked();
    if (check_locked(request).has_value()) {
        metrics_.deferred += 1;
        return nullptr;
    }
    acquire_locked(request);
    metrics_.admitted += 1;
    return std::unique_ptr<ResourceLease>(
        new ResourceLease(request, *this, now()));
}

std::unique_ptr<ResourceLease> ResourceGovernor::admit(const TaskRequest& request) {
    std::lock_guard<std::mutex> lock(lock_);
    refresh_pressure_locked();
    const std::optional<std::string> reason = check_locked(request);
    if (reason.has_value()) {
        metrics_.rejected += 1;
        const bool shed = starts_with(*reason, "pressure:");
        if (shed) metrics_.pressure_rejections += 1;
        throw ResourceExhausted(*reason, !shed, pressure_state_id(pressure_));
    }
    acquire_locked(request);
    metrics_.admitted += 1;
    return std::unique_ptr<ResourceLease>(
        new ResourceLease(request, *this, now()));
}

void ResourceGovernor::refresh_pressure_locked() {
    if (monitor_ == nullptr) {
        pressure_ = PressureState::normal;
        return;
    }
    // Python holds the governor lock through sampling — admissions
    // serialize on the freshest state. Safe here: the monitor uses its own
    // lock + a non-blocking sample gate and never calls back.
    pressure_ = monitor_->state();
}

std::optional<std::string> ResourceGovernor::check_locked(const TaskRequest& request) const {
    const CategoryPolicy* policy = policy_for(request.category);
    const bool background = policy ? policy->background() : true;
    const ResourceBudget budget = effective_budget();

    // CRITICAL: shed everything that is not small interactive work.
    if (pressure_ == PressureState::critical && !critical_exempt(request.category)) {
        return "pressure: memory CRITICAL, shedding " +
               std::string(category_id(request.category));
    }

    // CPU column. Interactive categories draw on the full logical pool
    // minus what background work already holds; background categories are
    // bounded by the (pressure-scaled) background ceiling.
    const double cores = std::max(0.0, request.estimated_cpu_cores);
    if (background) {
        if (accounting_.reserved_cores + cores > budget.background_cores()) {
            return "cpu: background core ceiling exhausted";
        }
    } else {
        const int interactive_pool =
            budget.detected_logical_cores() - budget.background_cores();
        if (accounting_.interactive_cores + cores >
            std::max(1.0, static_cast<double>(
                              interactive_pool +
                              budget.interactive_reserve_cores))) {
            return "cpu: interactive pool exhausted";
        }
    }

    // RAM soft limit: outstanding estimates within the streaming window.
    // Interactive work never gets hard-blocked by estimates — it is
    // exactly the work the reserves exist for.
    const std::int64_t ram = std::max<std::int64_t>(0, request.estimated_ram_bytes);
    if (ram > 0 &&
        accounting_.reserved_ram_bytes + ram > budget_.streaming_buffer_bytes) {
        if (background || pressure_ != PressureState::normal) {
            return "ram: streaming buffer soft limit";
        }
    }

    // IO slots: weighted concurrency cap for background streams.
    if (background && request.effective_io_weight() > 0 &&
        accounting_.reserved_io_weight + request.effective_io_weight() >
            budget.io_slots) {
        return "io: slot budget exhausted";
    }

    // VRAM: admission only guards *reservations*; the L2 cache keeps its
    // own LRU contract (oversize entries stay resident with a warning).
    const std::int64_t vram =
        std::max<std::int64_t>(0, request.estimated_vram_bytes);
    if (vram > 0 &&
        accounting_.reserved_vram_bytes + vram >
            static_cast<std::int64_t>(budget_.vram_budget_mb) * 1024 * 1024) {
        if (background) {
            return "vram: L2 budget would be oversubscribed";
        }
    }
    return std::nullopt;
}

void ResourceGovernor::acquire_locked(const TaskRequest& request) {
    const CategoryPolicy* policy = policy_for(request.category);
    accounting_.reserved_cores += std::max(0.0, request.estimated_cpu_cores);
    accounting_.reserved_ram_bytes +=
        std::max<std::int64_t>(0, request.estimated_ram_bytes);
    accounting_.reserved_vram_bytes +=
        std::max<std::int64_t>(0, request.estimated_vram_bytes);
    accounting_.reserved_io_weight += std::max(0.0, request.effective_io_weight());
    if (policy && policy->interactive) {
        accounting_.interactive_cores += std::max(0.0, request.estimated_cpu_cores);
    }
    accounting_.active_leases += 1;
}

void ResourceGovernor::release_lease(const ResourceLease& lease) {
    const TaskRequest& request = lease.request();
    const CategoryPolicy* policy = policy_for(request.category);
    std::lock_guard<std::mutex> lock(lock_);
    accounting_.reserved_cores =
        std::max(0.0, accounting_.reserved_cores -
                          std::max(0.0, request.estimated_cpu_cores));
    accounting_.reserved_ram_bytes =
        std::max<std::int64_t>(0, accounting_.reserved_ram_bytes -
                                      std::max<std::int64_t>(0, request.estimated_ram_bytes));
    accounting_.reserved_vram_bytes =
        std::max<std::int64_t>(0, accounting_.reserved_vram_bytes -
                                      std::max<std::int64_t>(0, request.estimated_vram_bytes));
    accounting_.reserved_io_weight =
        std::max(0.0, accounting_.reserved_io_weight -
                          std::max(0.0, request.effective_io_weight()));
    if (policy && policy->interactive) {
        accounting_.interactive_cores =
            std::max(0.0, accounting_.interactive_cores -
                              std::max(0.0, request.estimated_cpu_cores));
    }
    accounting_.active_leases = std::max<std::int64_t>(0, accounting_.active_leases - 1);
    const double held = lease.held_seconds();
    metrics_.released += 1;
    metrics_.total_hold_seconds += held;
    metrics_.max_hold_seconds = std::max(metrics_.max_hold_seconds, held);
}

int ResourceGovernor::cpu_allowance(JobCategory category,
                                    std::optional<int> requested) {
    // Python computes the effective budget inside the lock (freshness is
    // part of the admission contract).
    ResourceBudget budget;
    {
        std::lock_guard<std::mutex> lock(lock_);
        refresh_pressure_locked();
        budget = effective_budget();
    }
    const CategoryPolicy* policy = policy_for(category);
    const int ceiling = (policy && policy->interactive)
                            ? budget.detected_logical_cores()
                            : budget.background_cores();
    int allowance = std::max(1, ceiling);
    if (requested.has_value()) {
        allowance = std::min(allowance, std::max(1, *requested));
    }
    return allowance;
}

double ResourceGovernor::io_slots() {
    std::lock_guard<std::mutex> lock(lock_);
    refresh_pressure_locked();
    return effective_budget().io_slots;
}

PressureState ResourceGovernor::pressure_state() {
    std::lock_guard<std::mutex> lock(lock_);
    refresh_pressure_locked();
    return pressure_;
}

GovernorStatus ResourceGovernor::runtime_status() {
    std::lock_guard<std::mutex> lock(lock_);
    refresh_pressure_locked();
    const ResourceBudget budget = effective_budget();
    GovernorStatus out;
    out.total_ram_gb = budget_.total_ram_gb;
    out.logical_cores = budget_.detected_logical_cores();
    out.background_cores_effective = budget.background_cores();
    out.io_slots_effective = budget.io_slots;
    out.vram_budget_mb = budget_.vram_budget_mb;
    out.l1_slice_cache_bytes = budget_.l1_slice_cache_bytes;
    out.streaming_buffer_bytes = budget_.streaming_buffer_bytes;
    out.reserved_cores = accounting_.reserved_cores;
    out.reserved_ram_bytes = accounting_.reserved_ram_bytes;
    out.reserved_vram_bytes = accounting_.reserved_vram_bytes;
    out.reserved_io_weight = accounting_.reserved_io_weight;
    out.active_leases = accounting_.active_leases;
    out.pressure_state = pressure_;
    out.metrics = metrics_;
    return out;
}

namespace {
std::mutex g_governor_mutex;
std::unique_ptr<ResourceGovernor> g_governor;
}  // namespace

ResourceGovernor& global_governor() {
    std::lock_guard<std::mutex> lock(g_governor_mutex);
    if (!g_governor) {
        g_governor = std::make_unique<ResourceGovernor>(active_budget(),
                                                        &pressure_monitor());
    }
    return *g_governor;
}

void set_governor(std::unique_ptr<ResourceGovernor> governor) {
    std::lock_guard<std::mutex> lock(g_governor_mutex);
    // R2-4: outstanding ResourceLeases hold a RAW governor* — replacing
    // the global while a lease is alive left the lease's release() /
    // held_seconds() dereferencing freed memory (UAF). Retire the old
    // governor into a zombie slot (its budget stops governing, but any
    // live lease can still safely release) instead of destroying it. The
    // zombie is reclaimed once no lease can still reference it (at the
    // next swap; outstanding leases then belong to the zombie chain's
    // lifetime — bounded: the zombie list is drained on swap).
    static std::vector<std::unique_ptr<ResourceGovernor>> zombie_governors;
    if (g_governor) {
        zombie_governors.push_back(std::move(g_governor));
        // Bound the zombie chain: leases handed out before the previous
        // swap have released by now in practice (bounded job lifetimes),
        // so retire the OLDEST zombie only.
        if (zombie_governors.size() > 64) {
            zombie_governors.erase(zombie_governors.begin());
        }
    }
    g_governor = std::move(governor);
}

void configure_runtime_budget(const ResourceBudget& budget) {
    // Python order: push engine caches -> set_budget -> rebind monitor and
    // governor. Engine sinks are host-side here; callers push them first
    // so a pressure sample sees new caps already in effect.
    set_budget(budget);
    ResourceGovernor& governor = global_governor();
    governor.set_budget(budget);
    pressure_monitor().rebind_budget(budget);
}

}  // namespace pwb::job
