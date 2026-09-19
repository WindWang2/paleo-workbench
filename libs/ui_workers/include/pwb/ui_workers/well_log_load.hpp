#pragma once

// UI-04 — WellLogLoadWorker core (#1224 honest cancellation).
// Port of paleo_workbench/ui/pages/well_log_load_worker.py.
//
// Signal contract (Python parity):
//   * cancel() sets the event and emits cancelling() ONCE iff the
//     non-interruptible parse is in flight;
//   * run(): pre-cancel -> cancelled (no parse, no cancelling);
//     parse in flight -> resolve(ref, project, cancel) ->
//     WellLogLoadCancelled/event -> cancelled; other exc -> failed;
//     late successful payload -> DISCARDED (cancelled, never finished);
//   * _parse_started clears in `finally` — a post-run cancel() cannot
//     emit a spurious cancelling (review R1-P2).

#include <any>
#include <atomic>
#include <functional>
#include <memory>
#include <string>
#include <vector>

#include <pwb/job_runtime/job_contract.hpp>
#include <pwb/ui_workers/viz_resolve.hpp>
#include <pwb/ui_workers/worker_common.hpp>

namespace pwb::ui_workers {

// The cross-thread phase state — Python's _cancel_event + _parse_started
// pair. `cancel_requested` is the worker-level cancel surface (the
// threading.Event); the JobContext token is checked alongside it so both
// cancel surfaces behave identically at the checkpoints.
struct WellLogLoadPhase {
    std::atomic<bool> cancel_requested{false};
    std::atomic<bool> parse_active{false};
    std::atomic<bool> cancelling_sent{false};
};
using WellLogLoadPhasePtr = std::shared_ptr<WellLogLoadPhase>;

// worker.cancel() parity: set the event; emit the honest "正在结束" hint
// exactly once when the parse is mid-flight. `hook` is the cancelling
// signal (GUI-thread delivery is the caller's concern, like Python's
// queued Signal).
void request_well_log_cancel(const WellLogLoadPhasePtr& phase,
                             const std::function<void()>& on_cancelling);

struct WellLogLoadInput {
    VizRefSlice ref;
    std::vector<ResourceSlice> resources;
    std::string project_root;
    // The resolve seam — default resolve path (viz_resolve) uses `load_fn`.
    // `resolve_fn` replaces the whole call (adapter injection parity).
    std::function<VizPayloadSlice(const VizRefSlice&,
                                  const std::vector<ResourceSlice>&,
                                  const std::string& project_root,
                                  const std::function<bool()>&)>
        resolve_fn;
    WellLogLoadFn load_fn;
    WellLogLoadPhasePtr phase =
        std::make_shared<WellLogLoadPhase>();
};

// The finished payload — the resolved VizPayload slice.
struct WellLogLoadResult {
    VizPayloadSlice payload;
};

// run() parity: pre-cancel -> JobCancelled (Python cancelled.emit);
// parse_active window around the resolve; WellLogLoadCancelled or
// flag-at-return -> JobCancelled (cancelled + late result discarded =
// scheduler cancelled-with-partial, but the payload never reaches on_done
// — it is dropped BEFORE returning, matching "finished never fires");
// other exception -> "Class: msg" via with_py_errors.
WellLogLoadResult run_well_log_load(const WellLogLoadInput& input,
                                    job::JobContext& ctx);

// JobSpec builder — kind "load.well_log". on_done receives
// WellLogLoadResult; the cancelling hint rides `phase` +
// request_well_log_cancel (the caller wires JobHandle::cancel +
// request_well_log_cancel together — same as Python's worker.cancel()).
job::JobSpec make_well_log_load_job_spec(
    WellLogLoadInput input,
    std::function<void(const WellLogLoadResult&)> on_done = {},
    std::function<void(const std::string&)> on_fail = {},
    std::function<void()> on_cancel = {});

}  // namespace pwb::ui_workers
