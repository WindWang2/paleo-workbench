#pragma once

// CONV-30 — bounded job scheduler, Qt-free core.
//
// Port of paleo_workbench/runtime/task_scheduler.py (TaskScheduler) with
// the frozen #1081 / P2-A / V9 contracts:
//
//  - BOUNDED CONCURRENCY: exactly max_workers background lanes plus
//    interactive_workers interactive lanes are constructed up front and
//    joined on shutdown. There is no unbounded thread creation anywhere in
//    the runtime; lanes are strict (a lane never runs work classified for
//    the other lane) so a long background job cannot delay interactive
//    submissions (Python <50 ms queue-delay budget).
//  - PRIORITY + AGING: a heap of (-priority, seq) with FIFO order inside a
//    priority level; a queued job's effective priority grows while it waits
//    (aging: +5 per 5 s waiting, capped at +50) so background work is never
//    starved forever.
//  - DEDUPE + SUPERSEDE: a task_key identifies one logical job. Resubmitting
//    a still-QUEUED key supersedes it (old job cancelled, its on_cancel
//    unwinds — #1224: a cancelled request must never make the NEXT request
//    hang). Resubmitting a RUNNING/CANCELLING key throws JobSubmitError
//    ("duplicate.task_key").
//  - COOPERATIVE CANCEL: cancel() on a queued job drops it; on a running
//    job it flips state to cancelling and arms the token. A job that
//    returns after cancellation is recorded cancelled with a partial
//    result. Cancel-during-cancel is accepted (idempotent).
//  - ADMISSION HOOK: before a queued job starts, the hook may reserve
//    resources and return a lease (any non-null shared_ptr); a null lease
//    defers the job (stays queued, retried). The hook runs WITHOUT the
//    scheduler lock; leases are released at terminal state.
//  - CALLBACKS BEFORE TERMINAL: on_done/on_fail/on_cancel run before the
//    terminal state lands, without the scheduler lock held.
//  - BOUNDED HISTORY: at most history_limit finished cells are retained;
//    the oldest are evicted (live JobHandles keep their own cell alive).
//  - SHUTDOWN: stops accepts (JobSubmitError "runtime.shutdown"), cancels
//    queued jobs, arms every running token, optionally joins workers within
//    a timeout. The destructor drains (Python used daemon threads; C++
//    cannot abandon threads, so destruction joins — host code should call
//    shutdown() explicitly on close to keep the wait bounded).
//
// Self-wait detection (TaskRuntime v3 precedent): JobHandle::wait() from
// the job's own worker thread throws std::logic_error instead of
// deadlocking.

#include <condition_variable>
#include <filesystem>
#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

#include "pwb/job_runtime/job_contract.hpp"

namespace pwb::job {

// AdmissionLease (the admission-hook lease protocol) lives in
// job_contract.hpp since the Wave D target split — the governor mints
// leases without linking the scheduler.

class JobScheduler {
public:
    using Clock = std::function<double()>;  // monotonic seconds
    using AdmissionHook =
        std::function<std::shared_ptr<AdmissionLease>(const JobSpec&, const std::string& job_id)>;
    // Lane classification override (Python is_interactive); defaults to the
    // category policy table.
    using InteractivePredicate = std::function<bool(const JobSpec&)>;

    struct Options {
        int max_workers = 1;         // background lanes (I/O-heavy default 1)
        int interactive_workers = 0;  // dedicated interactive lanes
        std::size_t history_limit = 200;
        double aging_interval_s = 5.0;  // TaskScheduler.AGING_INTERVAL_S
        int aging_step = 5;             // TaskScheduler.AGING_STEP
        int aging_max_boost = 50;       // TaskScheduler.AGING_MAX_BOOST
    };

    JobScheduler(Options options, Clock clock = {});
    ~JobScheduler();

    JobScheduler(const JobScheduler&) = delete;
    JobScheduler& operator=(const JobScheduler&) = delete;

    // Submits one job. Throws JobSubmitError("runtime.shutdown") after
    // shutdown began; throws JobSubmitError("duplicate.task_key") when the
    // key is already running/cancelling.
    [[nodiscard]] JobHandle submit(JobSpec spec);

    // Cooperative cancel (see JobHandle::cancel). Returns false when the id
    // is unknown or already terminal.
    [[nodiscard]] bool cancel(const std::string& job_id);

    // Promotes a queued job (user started browsing what it feeds). Without
    // an explicit priority: +10 (Python parity).
    [[nodiscard]] bool boost(const std::string& job_id,
                             std::optional<int> priority = {});
    int boost_matching(const std::string& kind, std::optional<int> priority = {});

    [[nodiscard]] std::optional<JobSnapshot> snapshot(const std::string& job_id) const;
    [[nodiscard]] JobHandle handle(const std::string& job_id) const;
    [[nodiscard]] std::vector<JobSnapshot> statuses() const;
    [[nodiscard]] int active_count() const;
    [[nodiscard]] bool idle() const;

    // Scratch dir owned by the job. Survives cancel/crash; released only
    // via release_work_dir (crash-safe partial results, Python parity).
    [[nodiscard]] std::filesystem::path work_dir(const std::string& job_id);
    void release_work_dir(const std::string& job_id);

    void set_admission(AdmissionHook hook);
    void set_interactive_predicate(InteractivePredicate predicate);
    void set_work_root(std::filesystem::path root);

    // Stop accepting work; cancel queued jobs; arm running tokens. With
    // wait=true: joins the workers. A timeout bounds the DRAIN WAIT only —
    // if jobs are still running past it, shutdown returns without joining
    // and the residue is joined by a later shutdown()/the destructor
    // (jthreads cannot be abandoned — the documented C++ counterpart of
    // Python's daemon threads). Idempotent.
    void shutdown(bool wait = true, std::optional<double> timeout_s = {});
    // Blocks until no job is running and the queue is empty.
    void wait_idle();

    [[nodiscard]] int worker_count() const {
        return options_.max_workers + options_.interactive_workers;
    }

    // Aging formula, exposed for the policy oracle replay (same arithmetic
    // as Python's TaskScheduler._effective_priority): floor(wait/interval)
    // * step, capped at max_boost, added to the base priority.
    [[nodiscard]] static int aged_priority(int base_priority, double wait_s,
                                           const Options& options);

private:
    struct QueueEntry {
        int priority;        // effective (aging-adjusted) priority
        std::uint64_t seq;   // FIFO tiebreak
        std::string job_id;
    };
    struct Candidate {
        QueueEntry entry;
        std::shared_ptr<JobCell> cell;
    };

    // Max-heap comparator: highest priority first, FIFO (lowest seq)
    // inside a priority level.
    static bool queue_order(const QueueEntry& a, const QueueEntry& b) {
        if (a.priority != b.priority) return a.priority < b.priority;
        return a.seq > b.seq;
    }

    void worker_loop(int lane);
    void run_job(const std::shared_ptr<JobCell>& cell);
    void finish_locked(const std::shared_ptr<JobCell>& cell, JobState state);
    // `held_cell`: finishing cell whose mutex the caller already holds.
    void evict_history_locked(const JobCell* held_cell);
    [[nodiscard]] int effective_priority(const JobCell& cell) const;
    void rekey_heap_locked();
    [[nodiscard]] bool job_is_interactive(const JobSpec& spec) const;
    void release_lease(const std::string& job_id);
    [[nodiscard]] std::shared_ptr<JobCell> find_active_by_key_locked(
        const std::string& key) const;

    Options options_;
    Clock clock_;
    mutable std::mutex mutex_;
    std::condition_variable wakeup_cv_;
    std::condition_variable idle_cv_;
    std::vector<QueueEntry> heap_;  // max-heap by (priority, FIFO seq)
    std::uint64_t seq_ = 0;
    double last_rekey_{0.0};
    std::unordered_map<std::string, std::shared_ptr<JobCell>> cells_;
    std::unordered_map<std::string, std::shared_ptr<AdmissionLease>> leases_;
    std::unordered_map<std::string, std::filesystem::path> work_dirs_;
    AdmissionHook admission_;
    InteractivePredicate interactive_predicate_;
    std::filesystem::path work_root_;
    bool shutdown_ = false;
    int running_ = 0;
    std::vector<std::jthread> workers_;
};

// Process-wide scheduler parity of get_scheduler(): background I/O
// concurrency 1 plus one dedicated interactive lane. Product code goes
// through pwb_job_qt's JobCenter; this singleton exists for parity tests
// and non-GUI hosts.
[[nodiscard]] JobScheduler& global_scheduler();
// Test/teardown helper: shut down and forget the singleton.
void reset_global_scheduler();

}  // namespace pwb::job
