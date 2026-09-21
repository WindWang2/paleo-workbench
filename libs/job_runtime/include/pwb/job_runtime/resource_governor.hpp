#pragma once

// CONV-34 — process-wide resource governor, ported 1:1 from
// paleo_workbench/runtime/resource_governor.py (frozen in
// governor_oracle.json; replayed in job_runtime.governor_oracle).
//
// The governor is the single authority that turns ResourceBudget caps
// into admission decisions. It owns no workers or queues — the
// JobScheduler keeps its role as the one heavy queue; pools and engines
// keep their own threads. Every consumer asks the governor before
// claiming resources:
//
// - try_admit()  — non-blocking reservation check (deferred work stays
//                  queued; aging prevents starvation);
// - admit()      — raises ResourceExhausted with an explainable reason;
// - cpu_allowance() — the one question parallelism knobs ask instead of
//                  calling hardware_concurrency() themselves.
//
// All accounting sits behind one lock; admission decisions are pure
// counter checks (microseconds) so interactive latency is unaffected.

#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <string>

#include "pwb/job_runtime/job_categories.hpp"
#include "pwb/job_runtime/memory_pressure.hpp"
#include "pwb/job_runtime/resource_budget.hpp"

namespace pwb::job {

// Admission refusal with an explainable, UI-recoverable reason.
class ResourceExhausted : public std::runtime_error {
public:
    ResourceExhausted(std::string reason, bool retryable, std::string pressure)
        : std::runtime_error(reason),
          reason_(std::move(reason)),
          retryable_(retryable),
          pressure_(std::move(pressure)) {}

    [[nodiscard]] const std::string& reason() const noexcept { return reason_; }
    // retryable=false means waiting cannot help (pressure shedding).
    [[nodiscard]] bool retryable() const noexcept { return retryable_; }
    [[nodiscard]] const std::string& pressure() const noexcept { return pressure_; }

private:
    std::string reason_;
    bool retryable_;
    std::string pressure_;
};

// Resource claim of one task. Estimates are best-effort, never
// pre-allocation hints — they gate admission exactly like the budget's
// advisory caps always have.
struct TaskRequest {
    JobCategory category = JobCategory::background_io;
    std::optional<int> priority;        // nullopt -> category base priority
    std::string title;
    double estimated_cpu_cores = 1.0;
    std::int64_t estimated_ram_bytes = 0;
    std::int64_t estimated_vram_bytes = 0;
    std::optional<double> io_weight;    // nullopt -> category default
    bool cancellable = true;
    std::string task_id;

    [[nodiscard]] static TaskRequest from_kind(
        const std::string& kind,
        std::optional<int> priority = {},
        std::string title = {},
        double estimated_cpu_cores = 1.0,
        std::int64_t estimated_ram_bytes = 0,
        std::int64_t estimated_vram_bytes = 0,
        std::string task_id = {});

    [[nodiscard]] int effective_priority() const;
    [[nodiscard]] double effective_io_weight() const;
};

class ResourceGovernor;

// Reservation returned by a successful admission. RAII: destruction
// releases (the Python "release() is required" contract, made safe);
// release() itself is idempotent.
class ResourceLease {
public:
    ~ResourceLease() { release(); }
    ResourceLease(const ResourceLease&) = delete;
    ResourceLease& operator=(const ResourceLease&) = delete;
    ResourceLease(ResourceLease&&) = delete;
    ResourceLease& operator=(ResourceLease&&) = delete;

    void release();
    [[nodiscard]] double held_seconds() const;
    [[nodiscard]] const TaskRequest& request() const { return request_; }

private:
    friend class ResourceGovernor;
    ResourceLease(TaskRequest request, ResourceGovernor& governor,
                  double acquired_at)
        : request_(std::move(request)),
          governor_(&governor),
          acquired_at_(acquired_at) {}

    TaskRequest request_;
    ResourceGovernor* governor_;
    double acquired_at_;
    std::optional<double> released_at_;
};

struct GovernorMetrics {
    std::int64_t admitted = 0;
    std::int64_t deferred = 0;
    std::int64_t rejected = 0;
    std::int64_t released = 0;
    std::int64_t pressure_rejections = 0;
    double total_hold_seconds = 0.0;
    double max_hold_seconds = 0.0;
};

// Read-only point-in-time view (runtime_status parity; POD so the kernel
// stays Domain-free — hosts serialize as needed).
struct GovernorStatus {
    double total_ram_gb = 0.0;
    int logical_cores = 0;
    int background_cores_effective = 0;
    double io_slots_effective = 0.0;
    int vram_budget_mb = 0;
    std::int64_t l1_slice_cache_bytes = 0;
    std::int64_t streaming_buffer_bytes = 0;
    double reserved_cores = 0.0;
    std::int64_t reserved_ram_bytes = 0;
    std::int64_t reserved_vram_bytes = 0;
    double reserved_io_weight = 0.0;
    std::int64_t active_leases = 0;
    PressureState pressure_state = PressureState::normal;
    GovernorMetrics metrics;
};

class ResourceGovernor {
public:
    explicit ResourceGovernor(ResourceBudget budget,
                              MemoryPressureMonitor* monitor = nullptr,
                              Clock clock = {});

    [[nodiscard]] const ResourceBudget& budget() const { return budget_; }
    void set_budget(const ResourceBudget& budget);

    // Reserve resources if available; nullptr means "defer, retry later"
    // (the task simply stays queued — deferral is not an error).
    [[nodiscard]] std::unique_ptr<ResourceLease> try_admit(const TaskRequest& request);

    // Reserve resources or throw ResourceExhausted. retryable tells the
    // caller whether waiting could help (capacity) or not (pressure shed).
    [[nodiscard]] std::unique_ptr<ResourceLease> admit(const TaskRequest& request);

    // Cores a NEW parallel pipeline of `category` may use — the
    // pressure-scaled background ceiling (interactive categories: the full
    // pool), never more than `requested` when given.
    [[nodiscard]] int cpu_allowance(JobCategory category,
                                    std::optional<int> requested = {});
    [[nodiscard]] double io_slots();
    // Intra-op threads for a new ONNX session (INFERENCE category).
    [[nodiscard]] int onnx_thread_allowance() {
        return cpu_allowance(JobCategory::inference);
    }

    [[nodiscard]] PressureState pressure_state();
    [[nodiscard]] GovernorStatus runtime_status();

private:
    friend class ResourceLease;
    void release_lease(const ResourceLease& lease);
    void refresh_pressure_locked();
    // Returns a refusal reason or nullopt when admissible.
    std::optional<std::string> check_locked(const TaskRequest& request) const;
    void acquire_locked(const TaskRequest& request);
    // Budget with pressure-scaled CPU/IO columns (RAM caps unchanged).
    [[nodiscard]] ResourceBudget effective_budget() const;
    [[nodiscard]] double now() const { return clock_(); }

    ResourceBudget budget_;
    MemoryPressureMonitor* monitor_;  // not owned; nullptr = unmonitored
    Clock clock_;
    mutable std::mutex lock_;
    struct Accounting {
        double reserved_cores = 0.0;
        std::int64_t reserved_ram_bytes = 0;
        std::int64_t reserved_vram_bytes = 0;
        double reserved_io_weight = 0.0;
        double interactive_cores = 0.0;
        std::int64_t active_leases = 0;
    } accounting_;
    GovernorMetrics metrics_;
    PressureState pressure_ = PressureState::normal;
};

// Process-wide governor over the active budget (lazily created).
[[nodiscard]] ResourceGovernor& global_governor();
// Test/teardown helper; nullptr resets to lazy default.
void set_governor(std::unique_ptr<ResourceGovernor> governor);

// One stable configuration path: budget -> governor + monitor rebind.
// Python's configure_runtime_budget also pushes engine caches — those
// engines are host-side in C++, so sinks arrive via the caller (see
// governance.hpp).
void configure_runtime_budget(const ResourceBudget& budget);

}  // namespace pwb::job
