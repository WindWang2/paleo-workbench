#pragma once
// CONV-32 — FactorProduct projection (workflow/interpretation/factor_product.py
// port): the read-only domain identity of one single-factor analysis. grid /
// contours / polygons / uncertainty / QC are artifacts of the SAME product;
// the write path stays with factor_interpolation / factor_grid_artifacts /
// catalog.lifecycle. Identity = FactorMapTask.id, payload authority = catalog
// version / npz artifact / live cache — this projection never copies payload.
//
// Seam mapping (Python duck-typed collaborators -> C++ function views):
//   document.factor_map_tasks  -> Json array of task dicts (id/name/method/
//                                 parameters/quality_metrics/grid_metadata/
//                                 grid_artifact_version_id/source_kind/
//                                 generator_version[/created_at])
//   catalog.resolve_version    -> CatalogResolver::resolve_version
//   catalog.resolve_run        -> CatalogResolver::resolve_run
//   workspace_state.maturity_of-> WorkspaceView::maturity_of (null function
//                                 behaves like MappingWorkspaceState(): "draft")
//   freshness entry (deps svc) -> FreshnessEntry (status already the VALUE
//                                 string of the Python enum).
#include <pwb/domain/json.hpp>

#include <functional>
#include <map>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace pwb::workflow_interpretation {

using domain::Json;

// catalog.resolve_version(version_id) payload (only run linkage needed here).
struct VersionRunInfo {
    std::string run_id = "";
};

// catalog.resolve_run(run_id) payload (lineage inputs).
struct RunInfo {
    std::vector<std::string> input_version_ids;
};

// Exception-throwing seams are caught by the projection (missing lineage ->
// honest empty fields), mirroring Python's except-Exception blocks.
struct CatalogResolver {
    std::function<std::optional<VersionRunInfo>(const std::string& version_id)>
        resolve_version;
    std::function<std::optional<RunInfo>(const std::string& run_id)> resolve_run;
};

// artifact_key -> maturity ("draft"/"reviewed"/"frozen"/"published").
struct WorkspaceView {
    std::function<std::string(const std::string& artifact_key)> maturity_of;
};

// dependencies-service freshness entry; "" status = 未评估.
struct FreshnessEntry {
    std::string status;  // already the enum VALUE string
    std::string detail;
};

struct FactorArtifactRef {
    std::string artifact;  // grid | contours | polygons | uncertainty | qc
    bool present = false;
    std::string version_id;
    // Honest reason when present=false (never silently missing).
    std::string absent_reason;

    // Keys: artifact, present, version_id, absent_reason.
    [[nodiscard]] Json to_json() const;
};

struct FactorProduct {
    std::string factor_id;  // = FactorMapTask.id
    std::string name;
    std::string factor_type;
    std::string factor_family;
    std::string target_horizon;
    // Engine-canonical algorithm id (via canonical_algorithm_id).
    std::string algorithm_id;
    std::string method_label;  // raw method string recorded on the task
    Json parameters = Json::object();
    std::string unit;
    bool unit_declared = false;
    std::string crs;
    bool crs_declared = false;
    std::vector<long long> grid_shape;  // (height, width) ints only
    std::vector<std::string> input_version_ids;
    std::string grid_version_id;
    std::string run_id;
    std::string source_kind;
    std::string generator_version;
    Json qc = Json::object();  // known keys only, fixed order
    std::string maturity = "draft";
    std::string freshness;
    std::string freshness_detail;
    std::vector<FactorArtifactRef> artifacts;  // always 5, fixed order
    Json constraint_pins = Json::array();
    std::string created_at;

    [[nodiscard]] bool is_mock() const;  // source_kind in {mock, mixed}
    [[nodiscard]] bool has_uncertainty() const;
    // Miss -> {kind, false, "", "not part of this product"}.
    [[nodiscard]] FactorArtifactRef artifact(std::string_view kind) const;
    // Frozen 22-key order (parameters intentionally NOT serialized).
    [[nodiscard]] Json to_json() const;
};

// 因子类型 → 家族 key（FACTOR_FAMILIES 反查；未知→""，不猜）。
[[nodiscard]] std::string factor_family_for_type(const std::string& factor_type);

// Task missing -> nullopt.
[[nodiscard]] std::optional<FactorProduct> factor_product_for_task(
    const Json& tasks_array, const std::string& task_id,
    const CatalogResolver& catalog = {},
    const WorkspaceView& workspace_state = {},
    std::optional<FreshnessEntry> freshness_entry = std::nullopt);

// Batch projection; freshness precomputed per task id (seam replaces the
// Python-internal MappingDependencyService evaluation); skips nullopt.
[[nodiscard]] std::vector<FactorProduct> factor_products(
    const Json& tasks_array,
    const std::map<std::string, FreshnessEntry>& freshness_by_task,
    const CatalogResolver& catalog = {},
    const WorkspaceView& workspace_state = {});

}  // namespace pwb::workflow_interpretation
