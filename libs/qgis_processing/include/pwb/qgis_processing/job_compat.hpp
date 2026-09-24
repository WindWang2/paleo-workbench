#pragma once

// JobSpec → QgsTaskManager compat seam (Wave C).
//
// Many worker bodies in the tree are still expressed as job::JobSpec
// callables (ui_workers spec builders, inline page specs). This header
// adapts them onto the task bridge so consumers migrate owners without
// rewriting bodies:
//
//   * body_from_job_spec — wraps spec.run in a PaleoFunctionTask::Body.
//     JobContext calls map onto PaleoTaskBodyContext:
//       report_progress(done, total, msg) → task progress + stage tag
//       token()/check_cancelled()         → cooperative cancel via a
//                                            20 ms isCanceled watcher
//                                            (scheduler poll parity)
//       JobCancelled thrown by the body    → cancelled outcome
//     spec.degraded_when → mark_degraded; spec.on_done/on_fail/on_cancel
//     fire on the task thread (worker-side, scheduler parity).
//   * start_job_spec — drives a PwbTaskOwner with one call (kind/title/
//     task_key lifted from the spec) and delivers a CompatJobOutcome that
//     keeps the job::qtbridge::JobOutcome shape (state/error/std::any
//     result) so finish slots survive the migration unchanged.
//
// Result delivery: the std::any payload travels through a stash written
// on the task thread before the body returns and read by the finish slot
// after the terminal hop — including cancelled-with-partial runs (D6
// parity: a body that returns after the token was set lands cancelled
// with the partial result recorded in `result`).

#include <any>
#include <functional>
#include <memory>
#include <string>

#include <pwb/job_runtime/job_contract.hpp>
#include <pwb/qgis_processing/task_bridge.hpp>

namespace pwb::qgis_processing {

// job::qtbridge::JobOutcome vocabulary mapped from a PaleoTaskOutcome.
// `result` carries the stashed std::any for done/degraded AND cancelled
// (partial); failed leaves it empty (the error text is authoritative).
struct CompatJobOutcome {
    job::JobState state = job::JobState::cancelled;
    std::string error;
    std::any result;
};

// Wraps `spec.run` as a task body. `result_stash` (when given) receives
// the terminal std::any — pass the same stash the finish slot reads.
[[nodiscard]] PaleoFunctionTask::Body body_from_job_spec(
    job::JobSpec spec, std::shared_ptr<std::any> result_stash = nullptr);

// One-call owner drive: start_job_spec(owner, spec, on_finished[, progress])
// is the drop-in for the retired owner.start(scheduler, spec, finish[,
// progress]) — kind/title/task_key ride the spec; progress maps
// (fraction, stage) onto the owner's Progress callback.
void start_job_spec(
    PwbTaskOwner& owner, job::JobSpec spec,
    std::function<void(const CompatJobOutcome&)> on_finished,
    PwbTaskOwner::Progress on_progress = nullptr);

}  // namespace pwb::qgis_processing
