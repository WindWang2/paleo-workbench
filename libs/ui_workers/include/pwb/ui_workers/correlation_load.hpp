#pragma once

// UI-04 — CorrelationLoadWorker core.
// Port of paleo_workbench/ui/pages/correlation_load_worker.py +
// workflow/stratigraphy_correlation.py::load_correlation_wells.
//
// Signal contract (Python parity):
//   run(): cancel-event check -> loader(project, resource_ids, max_wells)
//        -> exception w/ cancel -> cancelled; exception w/o cancel ->
//        failed("Class: msg"); post-load cancel check -> cancelled; else
//        finished((logs, names, loaded_ids, warnings)).
// The loader itself is NOT cancel-checked internally (threading.Event is
// boundary-only in Python — same cooperative surface here).

#include <any>
#include <functional>
#include <optional>
#include <string>
#include <vector>

#include <pwb/job_runtime/job_contract.hpp>
#include <pwb/ui_workers/viz_resolve.hpp>
#include <pwb/ui_workers/worker_common.hpp>

namespace pwb::ui_workers {

// The project fields load_correlation_wells reads.
struct CorrelationProjectSlice {
    std::vector<ResourceSlice> resources;
    std::string project_root;
    // project.prediction_tasks[-1] if any — type-erased (the merge seam
    // owns the concrete type). has_value() == "task is not None".
    std::any prediction_task;
    bool attach_prediction_facies = true;
};

// Seam bundle for the loader internals.
struct CorrelationSeams {
    // VizAdapter.resolve — (ref, project-slice) -> payload.
    std::function<VizPayloadSlice(const VizRefSlice&,
                                  const CorrelationProjectSlice&)>
        resolve_fn;
    // merge_prediction_onto_well_log(data, task) — default: identity.
    std::function<std::any(const std::any& well_log, const std::any& task)>
        merge_prediction_fn;
    // getattr(data, "well_name", "") — used for the names list.
    std::function<std::string(const std::any& well_log)> well_name_fn;
};

// (logs, names, loaded_ids, warnings) — the finished payload tuple.
struct CorrelationLoadResult {
    std::vector<std::any> logs;
    std::vector<std::string> names;
    std::vector<std::string> loaded_ids;
    std::vector<std::string> warnings;
};

struct CorrelationLoadInput {
    CorrelationProjectSlice project;
    std::optional<std::vector<std::string>> resource_ids;
    int max_wells = 8;
    CorrelationSeams seams;
    // Worker-level loader override (Python `loader=` — tests inject fakes).
    // Empty -> load_correlation_wells below.
    std::function<CorrelationLoadResult(const CorrelationLoadInput&)>
        loader_fn;
};

// list_well_log_resources — well_log resources sorted by (name or "", id).
std::vector<ResourceSlice> list_well_log_resources(
    const std::vector<ResourceSlice>& resources);

// load_correlation_wells — the full loader port: sorted well_log resources,
// optional id filter, max(1, max_wells) cap, ref_from_resource ->
// resolve_fn -> optional prediction merge -> four aligned lists.
// Warnings: "跳过 {name}: 不支持可视化" / "跳过 {name}: {message or
// '无法加载 LAS'}".
CorrelationLoadResult load_correlation_wells(
    const CorrelationLoadInput& input);

// Worker-body parity: pre-cancel -> loader -> (exception+cancel -> cancel;
// exception -> py-style failure) -> post-cancel -> result.
CorrelationLoadResult run_correlation_load(const CorrelationLoadInput& input,
                                           job::JobContext& ctx);

// JobSpec builder — kind "load.correlation". on_done receives
// CorrelationLoadResult; on_fail the "Class: msg" text.
job::JobSpec make_correlation_load_job_spec(
    CorrelationLoadInput input,
    std::function<void(const CorrelationLoadResult&)> on_done = {},
    std::function<void(const std::string&)> on_fail = {},
    std::function<void()> on_cancel = {});

}  // namespace pwb::ui_workers
