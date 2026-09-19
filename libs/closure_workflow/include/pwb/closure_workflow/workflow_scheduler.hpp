#pragma once

// cpp-close-02 — the workflow scheduler face (engine.py
// submit_to_scheduler L362 + scheduler-token sync), completing the
// CONV-32 deferral (32-findings D5) at the closure level:
//
//   * ONE queue authority: a workflow run is submitted as a single job on
//     the host's job::JobScheduler (the app's single heavy queue) — never
//     a second queue;
//   * scheduler-side cooperative cancellation propagates into the engine
//     token (Python _SyncedToken): job cancel → engine CancelToken at the
//     engine's poll points (loop head / guard / backoff waits) and at
//     every node boundary via the update callback;
//   * on_done / on_fail / on_cancel forward the terminal WorkflowRun or
//     failure, mirroring the TaskSpec callback contract.
//
// Honest scope note: the engine's internal per-node pool
// (_drive_parallel) stays a documented CONV-32 deferral — the C++
// RunEngine drive loop is sequential regardless of spec.max_concurrency,
// and Python's own production path defaults to max_concurrency == 1
// (sequential _drive_sequential). Runs PARALLELIZE across the scheduler
// pool; nodes within one run execute in dependency order.
//
// Qt-free, Python-free.

#include <pwb/job_runtime/job_scheduler.hpp>
#include <pwb/workflow_engine/run_engine.hpp>

#include <atomic>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <string>

namespace pwb::closure_workflow {

// Terminal payload carried in the job result std::any (kind-checked by
// on_done consumers).
struct WorkflowRunOutcome {
    std::string run_id;
    std::string state;  // RunState value string ("completed"/"failed"/…)
    bool failed = false;
    std::string error;  // failure message when failed
};

// Submits whole-workflow-run jobs on the host scheduler.
class WorkflowScheduler {
public:
    struct Options {
        // Dedupe key; empty → unique (parity of task_key=None). A resubmit
        // while one is running throws JobSubmitError("duplicate.task_key").
        std::string task_key;
        // Python submit_to_scheduler default priority=20.
        int priority = 20;
        bool reverify_cache = true;
        bool use_cache = true;
        // Resume a RUNNING/INTERRUPTED run through the crash mapping
        // (engine.resume) instead of run() — the reopen-recovery path.
        bool resume = false;

        Options() {}
        Options(std::string task_key, int priority)
            : task_key(std::move(task_key)), priority(priority) {}
    };

    WorkflowScheduler(pwb::job::JobScheduler& scheduler,
                      pwb::workflow_engine::RunEngine& engine,
                      pwb::workflow_engine::WorkflowRunStore& store)
        : scheduler_(scheduler), engine_(engine), store_(store) {}

    // Submit the stored run as ONE background.compute job. Returns the
    // job handle (cancel() propagates into the engine token).
    // LIFETIME: *context (when non-null) must stay valid until the job
    // reaches a terminal state — Python's closure keeps the ActionContext
    // alive the same way; callers typically hold it for the process
    // lifetime of the open project.
    [[nodiscard]] pwb::job::JobHandle submit(
        const std::string& run_id,
        const pwb::workflow_engine::RunContext* context,
        const Options& options = Options());

    // Cancel the engine token of an in-process submission (the
    // run_id-keyed side channel Python keeps in _pending_tokens); returns
    // false when the run is not currently driven by this scheduler.
    [[nodiscard]] bool cancel(const std::string& run_id);

private:
    pwb::job::JobScheduler& scheduler_;
    pwb::workflow_engine::RunEngine& engine_;
    pwb::workflow_engine::WorkflowRunStore& store_;
    // run_id → engine token shared with the in-flight job (the
    // _pending_tokens parity; guarded by the scheduler's own mutex rules —
    // tokens are only flipped, never destroyed while registered).
    std::mutex mutex_;
    std::map<std::string, std::shared_ptr<pwb::workflow_engine::CancelToken>>
        pending_;
};

}  // namespace pwb::closure_workflow
