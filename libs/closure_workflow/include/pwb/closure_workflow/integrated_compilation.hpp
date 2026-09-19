#pragma once

// C++ port of paleo_workbench/workflow/integrated_compilation.py (§12) —
// the evidence-set-driven Stage-3 computational fusion consumer that
// CONV-33 findings A3 left to the consuming closure line.
//
// Pipeline: fusion_inputs_from_document → build_fusion_model →
// factor_fusion::fuse (the CONV-24 kernel — NO fusion science is
// implemented or altered here) → optional catalog registration.
//
// Determinism contract — nothing is silently defaulted:
//   * weights omitted → equal weights (1.0 each);
//   * classes omitted → 低/中/高 at equal thirds [1/3, 2/3];
//   * normalizations omitted → per-factor minmax over each grid's own
//     finite range;
// and every applied default is recorded under qc["defaults"].
//
// Degraded mode is honest: without a catalog the product is NOT
// registered — registered=false with an explicit reason, never a fake
// version pin. Pin-vs-current mismatches ride the QC
// ("pinned_version_mismatches", V9 P1-7): the fusion used the current
// grid while the evidence set pinned older versions.
//
// Host seams (the byte-loading the closure does not own): Python loads
// grids via catalog.grid_artifact (npz bytes) and
// project.factor_grid_artifacts (live cache → npz → inline). Those
// storage stacks belong to the data/science lines; the C++ consumer
// takes them as typed std::function seams and implements the full
// pin/current/live resolution + fail-closed aggregation itself — a seam
// returning nullopt is a REFUSAL, never a silent substitute.
//
// Qt-free, Python-free.

#include <pwb/domain/json.hpp>
#include <pwb/factor_fusion/factor_grid.hpp>
#include <pwb/factor_fusion/fusion.hpp>
#include <pwb/workflow_runtime/catalog_seam.hpp>

#include <functional>
#include <map>
#include <optional>
#include <string>
#include <vector>

namespace pwb::closure_workflow {

using pwb::domain::Json;
using pwb::factor_fusion::FactorGrid;
using pwb::factor_fusion::FusionModel;
using pwb::factor_fusion::FusionResult;
using pwb::factor_fusion::Normalization;
using pwb::workflow_runtime::CatalogRepository;

inline constexpr const char* kDefaultFusionClassNames[] = {"低", "中", "高"};
inline constexpr double kDefaultFusionClassThresholds[] = {1.0 / 3.0,
                                                           2.0 / 3.0};
inline constexpr const char* kDefaultFusionDefaultClass = "未定";
inline constexpr const char* kDefaultFusionModelName = "综合证据融合";

// Host grid-loading seams (documented above).
struct IntegratedGridSeams {
    // Load a PINNED catalog version's grid artifact; nullopt == unloadable.
    std::function<std::optional<FactorGrid>(const std::string& version_id)>
        grid_from_version;
    // Load the task's CURRENT grid (live cache → npz artifact → inline);
    // nullopt == unresolvable.
    std::function<std::optional<FactorGrid>(const Json& task)> grid_for_task;
};

// Resolve every `factor:<task>:<version>` evidence entry to its grid
// (integrated_compilation.py L113). When a selector carries a pinned
// version different from the task's current grid, that artifact is the
// runtime input if it loads (#1271); a missing pin fails closed when the
// task already has a current version (refuse to fuse "current" as the
// pin). Throws std::invalid_argument listing EVERY unresolvable factor
// task — never a silent partial evidence set.
[[nodiscard]] std::map<std::string, FactorGrid> fusion_inputs_from_document(
    const Json& document, const std::vector<std::pair<std::string, std::string>>& evidence_set,
    std::vector<std::string>* mismatches, CatalogRepository* catalog,
    const IntegratedGridSeams& seams);

// Build a weighted-evidence FusionModel from a Compilation Input Set
// (integrated_compilation.py L312). Evidence order is task-id-sorted, so
// the model fingerprint is deterministic for one evidence content.
// Throws std::invalid_argument on every Python ValueError branch.
[[nodiscard]] FusionModel build_fusion_model(
    const std::vector<std::pair<std::string, std::string>>& evidence_set,
    const std::map<std::string, FactorGrid>& factor_results,
    const std::optional<std::map<std::string, double>>& weights = std::nullopt,
    const std::optional<std::map<std::string, Normalization>>& normalizations =
        std::nullopt,
    const std::string& default_class = kDefaultFusionDefaultClass,
    std::optional<std::vector<std::string>> class_names = std::nullopt,
    std::optional<std::vector<double>> class_thresholds = std::nullopt,
    const std::string& name = kDefaultFusionModelName,
    const Json& weight_provenance = Json(nullptr));

// §12 production entry (run_integrated_fusion L529): build + fuse +
// (optionally) register the integrated fusion product. Returns the role-
// ready summary dict; `registration` carries the honest outcome.
struct IntegratedRunOutput {
    Json summary;
    FusionResult result;
};

[[nodiscard]] IntegratedRunOutput run_integrated_fusion(
    const Json& document,
    const std::vector<std::pair<std::string, std::string>>& evidence_set,
    CatalogRepository* catalog, const IntegratedGridSeams& seams,
    const std::optional<std::map<std::string, double>>& weights = std::nullopt,
    const std::optional<std::map<std::string, Normalization>>& normalizations =
        std::nullopt,
    std::optional<std::vector<std::string>> class_names = std::nullopt,
    std::optional<std::vector<double>> class_thresholds = std::nullopt,
    bool register_output = true,
    const std::string& name = kDefaultFusionModelName,
    const Json& weight_provenance = Json(nullptr));

// GridStatistics over the finite cells (float64 accumulation; NaN when
// the grid has no finite cell) — factor_grid_result.py L40 parity.
[[nodiscard]] Json grid_statistics_json(const FactorGrid& grid);

// Grid artifact payload (the catalog seam's string transport): the C++
// container is a Json document carrying axes / float grid / provenance
// (Python writes .npz; the checksum — not the container — is the
// identity, the catalog_seam.hpp documented divergence).
[[nodiscard]] std::string encode_grid_artifact(const FactorGrid& grid,
                                               const std::string& quantity);

}  // namespace pwb::closure_workflow
