#pragma once

// CONV-30 — job contract for the product-wide C++ job runtime.
//
// Faithful port of the frozen Python contract in
// paleo_workbench/runtime/task_scheduler.py (the global heavy-task
// scheduler, #1081): the seven-state machine, cooperative cancellation,
// progress reporting, task_key dedupe/supersede semantics, and the
// resource-hint vocabulary. This header is Qt-free and Python-free; the
// scheduler lives in job_scheduler.hpp and the GUI hop lives in the
// pwb_job_qt target (qt/job_bridge.hpp).
//
// Frozen behavioral contracts carried over verbatim from Python:
//  - states: queued/running/cancelling/done/degraded/failed/cancelled;
//    "cancelling" makes a cancel-requested RUNNING task visibly distinct
//    (V9 goal §27); "degraded" is success WITH caveats and is never
//    reported as plain done;
//  - cancellation is cooperative: the callable observes its token at safe
//    points. A task that returns after the event was set has its return
//    value recorded as a partial result and lands cancelled — never done;
//  - progress ratios clamp to [0, 1]; a throwing progress callback must
//    never kill the task;
//  - completion callbacks run BEFORE the terminal state lands, so observers
//    that see done/degraded can rely on the on_done side effects having
//    completed already;
//  - the scheduler never deletes a task's work dir (crash-safe partial
//    results; release is explicit).

#include <any>
#include <atomic>
#include <condition_variable>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <stop_token>
#include <string>
#include <thread>
#include <utility>

namespace pwb::job {

// ---------------------------------------------------------------- states --

enum class JobState : std::uint8_t {
    queued,
    running,
    cancelling,  // cancel requested on a RUNNING task; worker still yields
    done,
    degraded,  // completed WITH caveats — never reported as plain done
    failed,
    cancelled,
};

[[nodiscard]] inline const char* to_string(JobState state) noexcept {
    switch (state) {
    case JobState::queued:
        return "queued";
    case JobState::running:
        return "running";
    case JobState::cancelling:
        return "cancelling";
    case JobState::done:
        return "done";
    case JobState::degraded:
        return "degraded";
    case JobState::failed:
        return "failed";
    case JobState::cancelled:
        return "cancelled";
    }
    return "?";
}

[[nodiscard]] inline bool is_terminal(JobState state) noexcept {
    return state == JobState::done || state == JobState::degraded ||
           state == JobState::failed || state == JobState::cancelled;
}

// Raised by check_cancelled() and used by tasks that abort at a safe point
// (parity with Python's TaskCancelled). The scheduler translates it into the
// cancelled terminal state, never into failed.
class JobCancelled : public std::exception {
public:
    explicit JobCancelled(std::string job_id) : job_id_(std::move(job_id)) {}
    [[nodiscard]] const char* what() const noexcept override {
        return "job cancelled";
    }
    [[nodiscard]] const std::string& job_id() const noexcept {
        return job_id_;
    }

private:
    std::string job_id_;
};

// Raised by submit() for programming/contract errors (parity with Python's
// ValueError/RuntimeError on submit). `code` is a stable identifier for
// callers that branch on it: "runtime.shutdown", "duplicate.task_key".
class JobSubmitError : public std::runtime_error {
public:
    JobSubmitError(std::string code, std::string message)
        : std::runtime_error(std::move(message)), code_(std::move(code)) {}
    [[nodiscard]] const std::string& code() const noexcept {
        return code_;
    }

private:
    std::string code_;
};

// ---------------------------------------------------------- cancellation --

// Cooperative cancel token (parity of threading.Event usage in
// TaskContext). Copyable — every copy controls the same stop state.
class CancellationToken {
public:
    CancellationToken()
        : source_(std::make_shared<std::stop_source>()) {}

    [[nodiscard]] bool is_cancelled() const noexcept {
        return source_->stop_requested();
    }

    // Idempotent; safe from any thread (R3-F8 parity: cancel-during-cancel
    // must never surface as a failure).
    void cancel() const noexcept {
        source_->request_stop();
    }

    // Wait that wakes early on cancel; granularity mirrors Python's 50 ms
    // poll so interruptible sleeps stay responsive without busy spinning.
    // Returns true when the token was cancelled before the timeout elapsed.
    [[nodiscard]] bool sleep_interruptible(double seconds) const;

    // Throws JobCancelled when cancelled (parity of TaskContext
    // .check_cancelled()).
    void check_cancelled() const;

    [[nodiscard]] std::stop_token stop_token() const {
        return source_->get_token();
    }

private:
    std::shared_ptr<std::stop_source> source_;
};

// ------------------------------------------------------------ snapshot --

// Thread-safe point-in-time view of one job (parity of TaskHandle fields;
// `result` stays type-erased inside the runtime — snapshots carry only the
// queryable scalars, mirroring how the Python TaskCenter polls statuses()).
struct JobSnapshot {
    std::string job_id;
    std::string task_key;
    std::string kind;
    std::string title;
    JobState state{JobState::queued};
    double progress{0.0};
    std::string message;
    std::string error;  // terminal failures only
    bool cancel_requested{false};  // cancel() raced the claim window
    double submitted_at{0.0};
    std::optional<double> started_at;
    std::optional<double> finished_at;

    [[nodiscard]] bool is_terminal() const noexcept {
        return JobState::done == state || JobState::degraded == state ||
               JobState::failed == state || JobState::cancelled == state;
    }
};

// ------------------------------------------------------------- context --

struct JobCell;   // forward — JobContext carries its own cell for self_handle
class JobHandle;  // forward — self_handle() returns one

// Cooperative control handle passed to every job callable (parity of
// TaskContext). Lives on the worker thread for the duration of the run.
class JobContext {
public:
    JobContext(std::string job_id, CancellationToken token)
        : job_id_(std::move(job_id)), token_(std::move(token)) {}

    [[nodiscard]] const std::string& job_id() const noexcept {
        return job_id_;
    }
    [[nodiscard]] const CancellationToken& token() const noexcept {
        return token_;
    }

    // ratio = done/total when total is given (and non-zero), else done;
    // clamped to [0, 1] (Python parity).
    void report_progress(double done, std::optional<double> total = {},
                         std::string message = {});

    [[nodiscard]] bool sleep_interruptible(double seconds) const {
        return token_.sleep_interruptible(seconds);
    }
    void check_cancelled() const {
        token_.check_cancelled();
    }

    // Handle to the running job itself. wait() from the job's own worker
    // thread throws std::logic_error (self-wait deadlock detection) — a
    // job CAN safely wait on itself once terminal (no-op) or use
    // snapshot()/cancel() on it.
    [[nodiscard]] JobHandle self_handle() const;

private:
    friend class JobScheduler;
    std::string job_id_;
    CancellationToken token_;
    std::function<void(double, const std::string&)> progress_sink_;
    std::shared_ptr<JobCell> self_cell_;
};

// ----------------------------------------------------------- job spec --

// Budget-derived lane/classification vocabulary (resource hint). The policy
// table (base priority, interactivity, io weight, cpu cores) is ported in
// job_categories.hpp; a job carries its `kind` string and optional explicit
// priority override.
struct JobSpec {
    // runs on a worker thread: callable(ctx) -> result (type-erased).
    std::function<std::any(JobContext&)> run;
    std::string kind = "io";
    std::string title;
    // dedupe key; empty -> unique (parity of TaskSpec.task_key=None).
    std::string task_key;
    int priority = 0;  // explicit bump on top of the category base
    // result-level degraded predicate — true ⇒ the job finishes degraded
    // (success with caveats), never plain done (V9 goal §27 parity).
    std::function<bool(const std::any&)> degraded_when;
    std::function<void(const std::any&)> on_done;
    std::function<void(const std::string&)> on_fail;
    std::function<void()> on_cancel;
    // per-report progress hook (worker thread; exceptions swallowed so a
    // bad observer can never kill a task).
    std::function<void(double, const std::string&)> on_progress;
};

// ------------------------------------------------------------- handle --

class JobScheduler;

// Shared per-job cell: the JobHandle's view plus the scheduler's bookkeeping.
// All mutations happen under the cell mutex; scheduler-level bookkeeping
// runs under the scheduler mutex (lock order: scheduler mutex -> cell mutex).
// `state` reads taken outside any lock are not allowed — use snapshot()/the
// scheduler helpers.
struct JobCell {
    mutable std::mutex mutex;
    mutable std::condition_variable terminal_cv;
    JobSnapshot snapshot;
    CancellationToken token;
    std::any result;  // terminal success/degraded/cancel(partial)
    // Worker identity for self-wait detection (TaskRuntime v3 precedent):
    // set on claim; wait() from the worker thread on a non-terminal job
    // would deadlock, so it throws std::logic_error instead.
    std::atomic<std::thread::id> worker_id{std::thread::id{}};
    // Scheduler clock snapshot (queued-cancel timestamps when the handle
    // path finishes a job before any worker sees it).
    std::function<double()> clock;
    // Immutable after submit() (workers read concurrently).
    std::unique_ptr<JobSpec> spec;
};

// Query/cancel handle. Copyable; may outlive the scheduler (snapshots stay
// readable, waits return immediately once the scheduler is gone — the cells
// are kept alive by the shared_ptr).
class JobHandle {
public:
    JobHandle() = default;

    [[nodiscard]] bool valid() const noexcept { return cell_ != nullptr; }
    [[nodiscard]] std::string job_id() const;
    // Cooperative cancel: queued jobs drop, running jobs get the token set.
    // No-op (false) once terminal. Never throws.
    bool cancel() const;
    // Blocks until terminal; throws std::logic_error when called from the
    // job's own worker thread while the job is not terminal (self-wait).
    void wait() const;
    [[nodiscard]] bool wait_for(double timeout_seconds) const;
    [[nodiscard]] JobSnapshot snapshot() const;
    // Terminal result access. Returns nullptr when absent (not terminal /
    // failed / evicted). T is the type the callable returned.
    template <typename T>
    [[nodiscard]] const T* try_result() const {
        if (cell_ == nullptr) return nullptr;
        std::lock_guard<std::mutex> guard(cell_->mutex);
        return std::any_cast<T>(&cell_->result);
    }

private:
    friend class JobScheduler;
    friend class JobContext;  // self_handle() wraps the running job's cell
    explicit JobHandle(std::shared_ptr<JobCell> cell) : cell_(std::move(cell)) {}
    [[nodiscard]] JobState raw_state() const;
    std::shared_ptr<JobCell> cell_;
};

}  // namespace pwb::job
