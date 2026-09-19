#pragma once

// UI-04 — ContourDraftWorker core.
// Port of paleo_workbench/ui/pages/contour_draft_worker.py +
// workflow/contour_draft.py.
//
// Signal/progress contract (Python parity):
//   run(): token check -> compile_contour_drafts_for_project(snapshot,
//          apply_to_map=False) -> token check -> completed(ContourDraftResult)
//          | cancelled | failed("Class: msg"); terminal() always.
// There is no progress signal in this worker.
// upsert_contour_draft mutates the SNAPSHOT's contour_drafts ledger during
// compile (same as Python: upsert happens even with apply_to_map=False);
// the map-document apply (commit_contour_drafts) stays host-side.

#include <any>
#include <functional>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include <pwb/job_runtime/job_contract.hpp>
#include <pwb/ui_workers/worker_common.hpp>

namespace pwb::ui_workers {

inline constexpr const char* kContourDraftGeneratorVersion = "contour-draft-v2";
inline constexpr int kContourDefaultNLevels = 8;

// ContourSegment (project/models.py) — level isoline polyline.
struct ContourSegmentSlice {
    std::string id;
    double level = 0.0;
    std::vector<std::pair<double, double>> coordinates;
    bool closed = false;
    std::map<std::string, std::any> properties;
};

// ContourDraft (project/models.py) — the fields the compile path sets.
struct ContourDraftSlice {
    std::string id;
    std::string name;
    std::string target_horizon;
    std::string factor_type;
    std::string linked_factor_task_id;
    std::vector<double> levels;
    std::vector<ContourSegmentSlice> segments;
    int source_grid_n = 0;
    std::string source_backend;
    std::pair<double, double> source_value_range{0.0, 0.0};
    std::string status;  // "draft" | "editing"
    std::string generator_version;
    std::string updated_at;
    std::string linked_map_document_id;
};

// The geoviz extract_contour_lines seam (contourpy serial, line_type=
// "Separate"): grid axes + z + levels -> level -> polylines. Unbound ->
// KernelUnavailable (never substituted with a different algorithm).
using ExtractLinesFn = std::function<
    std::map<double, std::vector<std::vector<std::pair<double, double>>>>(
        const std::vector<double>& grid_x, const std::vector<double>& grid_y,
        const Grid2D& grid_z, const std::vector<double>& levels,
        const job::CancellationToken& token)>;

// Deterministic id source for draft/segment ids (the Python pydantic
// default_factory is _id()); the oracle injects recorded ids in call order.
using IdFn = std::function<std::string()>;

// suggest_nice_levels_from_range — contour_draft.py verbatim (nice
// 1/2/2.5/5x10^k ladder, endpoints excluded, guard 512).
std::vector<double> suggest_nice_levels_from_range(double lo, double hi,
                                                   int n_levels =
                                                       kContourDefaultNLevels);

// geoviz suggest_levels — raw linspace fallback (endpoints excluded,
// round(v,6)); used when the nice ladder degenerates.
std::vector<double> suggest_levels_fallback(double lo, double hi,
                                            int n_levels =
                                                kContourDefaultNLevels);

// suggest_nice_levels — nice ladder over finite grid cells, linspace
// fallback (contour_draft.py port).
std::vector<double> suggest_nice_levels(const Grid2D& grid_z,
                                        int n_levels = kContourDefaultNLevels);

// upsert_contour_draft — replace same-factor/horizon draft or append;
// stable id + refreshed updated_at when replacing. Mutates `existing`.
ContourDraftSlice upsert_contour_draft(ContourDraftSlice draft,
                                       std::vector<ContourDraftSlice>& existing,
                                       const std::string& updated_at);

// line_features_from_contour_draft — map-edit line_features dicts
// (role=contour). Keys match the Python dict shape.
std::vector<std::map<std::string, std::any>> line_features_from_contour_draft(
    const ContourDraftSlice& draft);

// contour_draft_from_factor_task — the full single-task pipeline:
// grid resolution -> finite check -> level pick -> stored engine contours
// short-circuit -> extract seam -> ContourDraft.
ContourDraftSlice contour_draft_from_factor_task(
    const FactorTaskSlice& task,
    const std::optional<std::vector<double>>& levels,
    int n_levels, const std::optional<std::string>& name,
    const job::CancellationToken& token, const ExtractLinesFn& extract_lines_fn,
    const IdFn& id_fn);

// compile_contour_draft_from_task — draft + snapshot-ledger upsert
// (apply_to_map is permanently false in the worker path; the map apply is
// host-side commit_contour_drafts).
ContourDraftSlice compile_contour_draft_from_task(
    const FactorTaskSlice& task, std::vector<ContourDraftSlice>& ledger,
    const std::optional<std::vector<double>>& levels, int n_levels,
    const job::CancellationToken& token, const ExtractLinesFn& extract_lines_fn,
    const IdFn& id_fn, const std::string& updated_at);

// compile_contour_drafts_for_project — per-task cancel check, id filter,
// only_complete status gate, ValueError/ImportError per-task skip, final
// cancel check. Returns the drafts created this call (ledger mutated).
std::vector<ContourDraftSlice> compile_contour_drafts_for_project(
    const std::vector<FactorTaskSlice>& factor_map_tasks,
    std::vector<ContourDraftSlice>& ledger,
    const std::optional<std::set<std::string>>& task_ids, bool only_complete,
    int n_levels, const job::CancellationToken& token,
    const ExtractLinesFn& extract_lines_fn, const IdFn& id_fn,
    const std::string& updated_at);

// ---------------------------------------------------------------------------
// Worker input/output + job spec.
// ---------------------------------------------------------------------------

// The narrow snapshot (#850-6): factor tasks SHARED (list copy, same
// objects) + contour_drafts ledger copied — nothing else.
struct ContourDraftInput {
    std::vector<FactorTaskSlice> factor_map_tasks;
    std::vector<ContourDraftSlice> contour_drafts;
    ExtractLinesFn extract_lines_fn;
    IdFn id_fn;                // empty -> deterministic "__cpp_id_N" sequence
    std::string updated_at;    // "" -> host pins; oracle injects fixed stamps
    int n_levels = kContourDefaultNLevels;
};

// ContourDraftResult (worker file): drafts + count.
struct ContourDraftResult {
    std::vector<ContourDraftSlice> drafts;
    // The compiled ledger (snapshot-side upsert effects) so the host commit
    // can mirror the exact post-run state.
    std::vector<ContourDraftSlice> ledger;
    [[nodiscard]] int count() const { return static_cast<int>(drafts.size()); }
};

// Worker-body parity: cancel check -> compile -> cancel check -> result.
ContourDraftResult run_contour_drafts(const ContourDraftInput& input,
                                      job::JobContext& ctx);

// JobSpec builder — kind "compute.contour_draft". on_done receives the
// ContourDraftResult; on_fail the "Class: msg" text; on_terminal fires on
// every terminal path (Python `terminal` parity).
job::JobSpec make_contour_draft_job_spec(
    ContourDraftInput input,
    std::function<void(const ContourDraftResult&)> on_done = {},
    std::function<void(const std::string&)> on_fail = {},
    std::function<void()> on_cancel = {},
    std::function<void()> on_terminal = {});

}  // namespace pwb::ui_workers
