#pragma once

// V14-CONSTRAINT-FACTOR — the production binding of the factor-prepare
// scheduler (pwb::ui_workers::run_factor_prepare_schedule) to the REAL
// native scientific kernels:
//
//   classify_fn  -> factor_host fingerprints (fingerprints_for_task glue:
//                   constraint resolution + build_factor_fingerprints +
//                   classify_factor_recompute, memoized per request)
//   batch_fn     -> per-task isolated interpolation
//                   (mapping::normalize_factor_samples ->
//                    mapping::interpolate_factor [idw|kriging] |
//                    mapping::constrained_idw::generate_constrained_idw)
//                    + the _attach_result_to_task contract (task JSON patch,
//                    quality metrics, fingerprints, live grid store)
//   group_key_fn -> factor_host plan digest (plain-IDW geometry groups)
//   grid_peek_fn -> LiveFactorGridStore::peek
//
// Plus the host-side commit (commit_prepare_batch_result — the only writer
// of project.factor_map_tasks during a prepare run) with the stale-input
// re-verification guard, the factor_map catalog registration
// (register_factor_map_run C++ port over the workflow_runtime catalog seam)
// and the contour-draft commit upgrade (id-preserving upsert +
// apply-to-paleomap_documents line features).
//
// Honesty rules (see docs/development/v14-constraint-factor/02-architecture):
//   * 样条/方向趋势 have no native kernel -> per-task failure with an
//     explicit "未原生接入" reason; never a fabricated grid.
//   * plain IDW/kriging do not consume break lines in the native kernels
//     (the geoviz fault-LOS path is not ported) and kriging has no
//     anisotropy input -> tasks with active break/direction constraints
//     under those backends fail closed instead of silently ignoring the
//     constraint while fingerprinting it as consumed.
//   * constrained_idw requires >=3 valid wells and a boundary ring
//     (engine contract); missing boundary fails with the engine text.
//
// Qt-free, Python-free. Thread model: the seams run on the worker thread;
// commit_prepare_batch_result runs on the GUI thread (it mutates the live
// project document and, optionally, the thread-confined catalog seam).

#include <pwb/domain/json.hpp>
#include <pwb/ui_workers/factor_prepare.hpp>
#include <pwb/workflow_runtime/catalog_seam.hpp>

#include <ctime>
#include <filesystem>
#include <iomanip>
#include <memory>
#include <optional>
#include <sstream>
#include <string>
#include <vector>

namespace pwb::factor_production {

using pwb::domain::Json;

// ------------------------------------------------------------- live grids --

// Sealed per-task grid payload (factor_grid_artifacts.py live-cache core:
// the canonical numeric result while unsaved; task.parameters never carries
// grid arrays). float64 axes + float32 z (NaN = nodata), row-major.
struct LiveGridEntry {
    std::vector<double> grid_x;
    std::vector<double> grid_y;
    std::vector<float> grid_z;
    std::vector<float> variance_grid;  // empty for IDW
    std::string result_fingerprint;
    Json metadata = Json::object();    // grid_metadata descriptor
};

// LRU keyed by task id. Caps: PALEO_LIVE_FACTOR_GRIDS_MAX entries (64),
// PALEO_LIVE_FACTOR_GRIDS_MAX_BYTES payload bytes (256 MiB). Thread-safe:
// the parallel group path peeks/stores from worker threads.
class LiveFactorGridStore {
public:
    LiveFactorGridStore();

    // store() replaces any previous entry for the task (#834 clear-then-set).
    void store(const std::string& task_id, LiveGridEntry grid);
    [[nodiscard]] std::optional<LiveGridEntry> peek(
        const std::string& task_id) const;
    void clear(const std::string& task_id);
    // Evict only when the cached entry still carries `fingerprint`
    // (#881: a run that produced no grid clears nothing — pass the
    // fingerprint of the FAILED run's absent grid as "" and nothing moves).
    bool clear_if_fingerprint(const std::string& task_id,
                              const std::string& fingerprint);
    [[nodiscard]] bool has(const std::string& task_id) const;
    [[nodiscard]] std::size_t size() const;

    // Last completed batch DTO (worker thread → GUI-thread commit
    // handoff): the page's PrepareResultView carries only the label
    // counters, the commit needs the staged task patches + grids.
    void stash_last_result(
        std::shared_ptr<const ui_workers::FactorPrepareBatchResult> result);
    [[nodiscard]] std::optional<ui_workers::FactorPrepareBatchResult>
    take_last_result();
    // Session teardown (project switch): drop every entry + the stash
    // (Python clear_session_caches parity — caches never leak across
    // projects).
    void clear_all();

private:
    struct Impl;
    std::shared_ptr<Impl> impl_;
};

// --------------------------------------------------------- slice builder --

// Project JSON root -> the narrow scientific slice the scheduler consumes.
// Every FactorTaskSlice keeps its original task JSON in `source_json`
// (unknown fields survive the round trip: the commit replaces the live
// task with the patched source, Python's deep-copy patch semantics);
// parameters["sample_points"] is loaded as vector<map<string,any>>
// (the synthetic-points seam convention — param_truthy parity).
ui_workers::PrepareProjectSlice build_prepare_slice(const Json& project_root);

// --------------------------------------------------------------- kernels --

struct FactorPrepareKernelConfig {
    // 0 -> derive from PALEO_PREPARE_WORKERS (clamp 1..4) and hardware
    // concurrency; never assumes >= 4 cores.
    int max_workers = 0;
    std::string generator_version =
        ui_workers::kFactorInterpGeneratorVersion;
};

// Fully-bound seams over the real kernels. `grids` must outlive the run.
[[nodiscard]] ui_workers::FactorPrepareSeams make_factor_prepare_seams(
    std::shared_ptr<LiveFactorGridStore> grids,
    const FactorPrepareKernelConfig& config = {});

// Well-table bridge (workflow/well_table.py leaves): the value column a
// factor type reads (砂地比->R_s, 地层厚度->H_t, 砂岩厚度->H_s, else z) and
// the QC-passing sample-point export from a well table JSON.
[[nodiscard]] std::string value_key_for_factor_type(
    const std::string& factor_type);
[[nodiscard]] Json sample_points_from_well_table(
    const Json& well_table, bool include_flagged = false,
    const std::string& value_key_override = "");

// ------------------------------------------------------- host-side commit --

struct CommitPrepareReport {
    std::vector<std::string> discarded;          // task ids (Python contract)
    int applied = 0;
    std::vector<std::string> registered_version_ids;
    std::vector<std::string> registration_errors;
};

// commit_prepare_batch_result — GUI-thread writer. Generation gating is
// the page's job (it calls this only for the current generation); the
// function re-checks `expected_generation` against `result.generation` and
// discards everything on mismatch (fingerprint-conditional eviction only).
// `catalog` may be null: honest degradation (tasks commit, no versions).
[[nodiscard]] CommitPrepareReport commit_prepare_batch_result(
    Json& project_root,
    const ui_workers::FactorPrepareBatchResult& result,
    int expected_generation,
    LiveFactorGridStore& grids,
    workflow_runtime::CatalogRepository* catalog = nullptr,
    const std::string& project_crs = "");

// ------------------------------------------------------------ contour commit --

// Python commit_contour_drafts port: id-preserving upsert into
// project.contour_drafts + apply each draft to its map document
// (paleomap_documents line features, role "contour"). Returns the number
// of drafts created or updated.
int commit_contour_drafts_full(Json& project_root, const Json& drafts_array);

// ------------------------------------------------- persistent run catalog --

// RuntimeStore persistence twin for the factor provenance rail: same
// `<root>.json` document shape as closure_workflow::FileCatalogRepository
// (store_version:1 + assets/versions/runs), written atomically per
// mutation, reopened on project switch. Until the cpp-close-02 closure
// joins platform configures this keeps ONE catalog seam
// (workflow_runtime::CatalogRepository) with one on-disk contract — the
// 02-line repository can reopen the same file later.
class PersistentRuntimeCatalog : public pwb::workflow_runtime::RuntimeStore {
public:
    // Real timestamps for a production provenance rail.
    PersistentRuntimeCatalog()
        : RuntimeStore([] {
              const std::time_t now = std::time(nullptr);
              std::tm tm{};
              gmtime_r(&now, &tm);
              std::ostringstream out;
              out << std::put_time(&tm, "%Y-%m-%dT%H:%M:%S+00:00");
              return out.str();
          }) {}

    // Load `<root>.json` (missing → fresh store); throws on a corrupt or
    // wrong-store_version file (fail-closed over provenance).
    void open(const std::filesystem::path& root);

    // Every mutator override persists after the base mutation.
    std::string register_run(
        const std::string& operation,
        const std::vector<std::string>& input_version_ids,
        const Json& parameters,
        const std::optional<std::string>& generator_version,
        const std::string& status = "running",
        const std::optional<std::string>& domain_task_id = std::nullopt,
        const std::optional<std::string>& input_snapshot_hash = std::nullopt,
        const std::optional<std::string>& actor = std::nullopt) override;
    pwb::workflow_runtime::RegisteredAssetVersion register_result_asset(
        const std::string& name, const std::string& type,
        const std::string& format, const Json& asset_metadata,
        const std::string& payload_json, const std::string& stage,
        const std::string& run_id, const Json& version_metadata) override;
    std::string register_version(
        const std::string& asset_id, const std::string& payload_json,
        const std::string& stage,
        const std::vector<std::string>& parent_version_ids,
        const std::string& run_id, const Json& metadata) override;
    void update_run_status(const std::string& run_id,
                           const std::string& status) override;
    void update_run_status(const std::string& run_id,
                           const std::string& status,
                           const Json& extra_parameters) override;
    void set_current_version(const std::string& asset_id,
                             const std::string& version_id) override;
    void attach_run_output(const std::string& run_id,
                           const std::string& version_id) override;

private:
    void flush();

    std::filesystem::path file_;
};

// ------------------------------------------------------ well-table exports --

// run_well_table_qc port (MAD modified z-scores, threshold 3.5): mutates the
// table rows' qc_flag/qc_z_star/b_i and returns the summary counts
// {ok, outlier, invalid_ratio, missing}.
[[nodiscard]] Json run_well_table_qc(Json& well_table,
                                     const std::string& value_key);

// sync_well_table_to_linked_tasks: write the QC-passing sample points back
// onto every task whose parameters.well_table_id == table.id (plus the
// legacy single-unbound-task adoption). Returns the updated task ids.
[[nodiscard]] std::vector<std::string> sync_well_table_to_linked_tasks(
    Json& project_root, const Json& well_table,
    const std::string& value_key);

// --------------------------------------------------- cross-well context --

// One well's sampled value on one factor surface (the map ↔ profile
// linkage data: NaN value = off-grid / nodata).
struct WellFactorSample {
    std::string well;
    double x = 0.0;
    double y = 0.0;
    std::string task_id;
    std::string factor_type;
    std::string target_horizon;
    double value = std::numeric_limits<double>::quiet_NaN();
    std::string version_id;
};

// The linkage provider: bilinear-sample every COMPLETE factor task's grid
// (live cache → catalog version payload → legacy inline parameters) at
// each well position. This is the scientific context the cross-well dock
// consumes — no rendering, no well-engine rewrites.
[[nodiscard]] std::vector<WellFactorSample> sample_factor_context(
    const Json& project_root,
    const std::vector<std::pair<std::string, std::array<double, 2>>>& wells,
    const LiveFactorGridStore* grids,
    workflow_runtime::CatalogRepository* catalog);

}  // namespace pwb::factor_production
