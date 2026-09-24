#pragma once

// cpp-close-02 — the workflow scheduler face (engine.py
// submit_to_scheduler L362 + scheduler-token sync), completing the
// CONV-32 deferral (32-findings D5) at the closure level:
//
//   * ONE queue authority: a workflow run is submitted as ONE background
//     body through the host's RunSubmitter (the app's QgsTaskManager
//     bridge or a thread pool) — never a second queue and never a
//     private scheduler;
//   * cooperative cancellation flows through the engine token: cancel()
//     (the run_id-keyed side channel, Python _pending_tokens) flips the
//     engine CancelToken at the engine's poll points (loop head / guard /
//     backoff waits) and at every node boundary via the update callback;
//   * the returned future carries the terminal WorkflowRunOutcome (or the
//     failure exception) — the wait/observe surface the job handle used
//     to provide.
//
// Honest scope note: the engine's internal per-node pool
// (_drive_parallel) stays a documented CONV-32 deferral — the C++
// RunEngine drive loop is sequential regardless of spec.max_concurrency,
// and Python's own production path defaults to max_concurrency == 1
// (sequential _drive_sequential). Runs PARALLELIZE across submitter
// threads; nodes within one run execute in dependency order.
//
// Qt-free, Python-free, scheduler-free.

#include <pwb/workflow_engine/run_engine.hpp>

#include <atomic>
#include <functional>
#include <future>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <utility>

namespace pwb::closure_workflow {

// Terminal payload carried in the run future (kind-checked by on_done
// consumers).
struct WorkflowRunOutcome {
    std::string run_id;
    std::string state;  // RunState value string ("completed"/"failed"/…)
    bool failed = false;
    std::string error;  // failure message when failed
};

// Submits whole-workflow-run jobs on the host executor.
class WorkflowScheduler {
public:
    // The host's background-execution seam: `submit(body)` must run
    // `body` (eventually, exactly once) on a NON-calling thread — the
    // synchronous-blocking parity the retired job submission had. The
    // product binds the QgsTaskManager bridge (PwbTaskOwner /
    // PaleoFunctionTask::Body); tests bind a thread-pool or detached
    // std::thread submitter.
    using RunSubmitter = std::function<void(std::function<void()> body)>;

    struct Options {
        // Dedupe/documentation key; empty → unique. (Admission-level
        // dedupe is the executor's policy now — the QGIS gate enforces
        // task_key supersede when the product submitter carries it.)
        std::string task_key;
        int priority = 20;  // Python submit_to_scheduler default priority=20.
        bool reverify_cache = true;
        bool use_cache = true;
        // Resume a RUNNING/INTERRUPTED run through the crash mapping
        // (engine.resume) instead of run() — the reopen-recovery path.
        bool resume = false;

        Options() {}
        Options(std::string task_key, int priority)
            : task_key(std::move(task_key)), priority(priority) {}
    };

    WorkflowScheduler(RunSubmitter submitter,
                      pwb::workflow_engine::RunEngine& engine,
                      pwb::workflow_engine::WorkflowRunStore& store)
        : submitter_(std::move(submitter)), engine_(engine), store_(store) {}

    // Submit the stored run as ONE background body. The returned future
    // holds the terminal WorkflowRunOutcome (or the failure exception —
    // .get() rethrows). LIFETIME: *context (when non-null) must stay
    // valid until the run reaches a terminal state — Python's closure
    // keeps the ActionContext alive the same way; callers typically hold
    // it for the process lifetime of the open project.
    [[nodiscard]] std::future<WorkflowRunOutcome> submit(
        const std::string& run_id,
        const pwb::workflow_engine::RunContext* context,
        const Options& options = Options());

    // Cancel the engine token of an in-process submission (the
    // run_id-keyed side channel Python keeps in _pending_tokens); returns
    // false when the run is not currently driven by this scheduler.
    [[nodiscard]] bool cancel(const std::string& run_id);

private:
    RunSubmitter submitter_;
    pwb::workflow_engine::RunEngine& engine_;
    pwb::workflow_engine::WorkflowRunStore& store_;
    // run_id → engine token shared with the in-flight body (the
    // _pending_tokens parity; guarded by the scheduler's own mutex rules —
    // tokens are only flipped, never destroyed while registered).
    std::mutex mutex_;
    std::map<std::string, std::shared_ptr<pwb::workflow_engine::CancelToken>>
        pending_;
};

}  // namespace pwb::closure_workflow
