#pragma once

// C++ port of paleo_workbench/workflow/map_product.py (P1-D) — the catalog
// OUTPUT orchestration face CONV-33 findings A3 left to the consuming
// closure line (this library). A MapProduct composes validated factor maps
// + interpretation references + manual adjustments into ONE catalog OUTPUT
// version carrying the complete lineage.
//
// Fail-closed discipline (compile_map_production rules), verbatim:
//   * synthetic/mock factor inputs are refused — never laundered into a
//     product;
//   * a factor task without a persisted grid version has nothing
//     reproducible to compose and is refused;
//   * every input factor grid version lands in the run's
//     input_version_ids;
//   * without a catalog the assembly refuses (a product without lineage
//     is exactly the orphan the lifecycle exists to prevent);
//   * the run books RUNNING first and completes only after the output
//     version registers (#1219 — a death between the two saves leaves a
//     failed run, never a completed ghost).
//
// Records live in the portable project tree section `map_products` as Json
// objects (field order = project/models.py MapProductRecord declaration
// order); this header exposes the typed facade over them. Versioning of
// the products themselves rides the catalog (immutable versions + run
// lineage); the record is the project-side index.
//
// Documented divergences (kept honest, never fabricating passes):
//   * product_qa's unified staleness verdict calls the Python
//     interpretation.staleness.evaluate_verdict surface whose mapping
//     dependency (MappingDependencyService) is unported (32-findings A3);
//     C++ lands the Python catch-path (QA warning "产品新鲜度评估失败")
//     instead of a silent pass.
//   * Python stages a payload FILE; the C++ catalog seam transports the
//     payload BYTES (identity is the checksum, location incidental — the
//     catalog_seam.hpp documented divergence).
//   * promote_map_product needs the catalog promote transaction family
//     (line-01 territory); the C++ facade takes it as an injected
//     std::function and refuses fail-closed when absent.
//
// Qt-free, Python-free.

#include <pwb/domain/json.hpp>
#include <pwb/workflow_runtime/catalog_seam.hpp>
#include <pwb/project/version_models.hpp>

#include <functional>
#include <optional>
#include <string>
#include <vector>

namespace pwb::closure_workflow {

using pwb::domain::Json;
using pwb::workflow_runtime::CatalogRepository;

inline constexpr const char* kMapProductGeneratorId = "map-product-v1";

// Python QA severity vocabulary (goal §30). BLOCKER blocks publish.
inline constexpr const char* kQaInfo = "info";
inline constexpr const char* kQaWarning = "warning";
inline constexpr const char* kQaError = "error";
inline constexpr const char* kQaBlocker = "blocker";

// V9 lifecycle ladder (goal §31).
inline constexpr const char* kLifecycleDraft = "draft";
inline constexpr const char* kLifecycleReviewed = "reviewed";
inline constexpr const char* kLifecycleFrozen = "frozen";
inline constexpr const char* kLifecyclePublished = "published";
inline constexpr const char* kLifecycleSuperseded = "superseded";

inline constexpr const char* kProductStatusFinal = "final";
inline constexpr const char* kProductStatusSuperseded = "superseded";

// ---------------------------------------------------------------------------
// MapProductAssembly — declarative recipe for one product build.
// ---------------------------------------------------------------------------

struct MapProductAssembly {
    std::string product_name;
    std::vector<std::string> factor_task_ids;
    std::vector<std::string> interpretation_refs;
    std::optional<std::string> composition_ref;
    std::string adjustments_note;
    std::string notes;
    // Manual adjustments are recorded as free-form entries (author, what,
    // why) — the honest representation of expert editing before
    // finalization.
    Json manual_adjustments = Json::array();
    // V9 (P1-6): the computational interpretation is composable into the
    // product — fusion seed version, integrated interpretation record, and
    // the pinned compilation input set join the recipe + fingerprint.
    std::string fusion_version_id;
    std::string integrated_interpretation_id;
    std::string input_set_id;

    // Deterministic content fingerprint over the assembly's inputs
    // (map_product.py L50-66). Order-sensitive by design: the same factors
    // assembled in a different order are a different scientific statement.
    // sha256 over python_dumps_sorted(payload) — oracle-frozen bytes.
    [[nodiscard]] std::string scientific_fingerprint(
        const Json& project) const;
};

// ---------------------------------------------------------------------------
// Results
// ---------------------------------------------------------------------------

struct MapProductResult {
    std::string product_name;
    std::string record_id;
    std::string output_version_id;
    std::string run_id;
    std::string scientific_fingerprint;
    std::optional<std::string> superseded_record_id;
};

// ---------------------------------------------------------------------------
// Assembly (map_product.py assemble_map_product L177)
// ---------------------------------------------------------------------------

struct AssembleDeps {
    // Required: refuse without it (ValueError "map product assembly
    // requires the data catalog").
    CatalogRepository* catalog = nullptr;
    // Payload bytes the caller staged (typically the serialized composition
    // + product manifest). Empty == Python's missing/unstaged file →
    // ValueError "map product assembly needs a staged payload file".
    std::string payload_json;
    // Output format tag (Python: the staged file's suffix); default "json".
    std::string payload_format = "json";
    // Id / timestamp seams (project ModelClock; tests inject determinism).
    pwb::project::ModelClock clock{};
};

// Validate the assembly, then register the OUTPUT version + run. Throws
// std::invalid_argument (Python ValueError parity) on every fail-closed
// gate; appends the new MapProductRecord to project["map_products"].
// Throws std::runtime_error when the output registration failed after
// booking the run (the run is landed "failed" first — #1219).
[[nodiscard]] MapProductResult assemble_map_product(
    Json& project, const MapProductAssembly& assembly,
    const AssembleDeps& deps);

// Stage the product manifest payload (write_product_manifest parity): the
// Json producers without a serialized composition pass to assemble. The
// C++ seam stages BYTES, so this returns the manifest Json (the caller
// serializes/stores it); factor ids missing from the project are skipped
// (walrus parity).
[[nodiscard]] Json build_product_manifest(
    const Json& project, const std::string& product_name,
    const std::vector<std::string>& factor_task_ids);

// assembly_from_workspace (L81): factor ids from the active Compilation
// Input Set's evidence view; V9 lineage refs auto-carried from the project
// integrated interpretations.
[[nodiscard]] MapProductAssembly assembly_from_workspace(
    const Json& project, const std::string& product_name,
    const std::vector<std::string>& interpretation_refs = {},
    std::optional<std::string> composition_ref = std::nullopt);

// ---------------------------------------------------------------------------
// Record facade (project["map_products"] entries)
// ---------------------------------------------------------------------------

// find_map_product: project-side registry lookup (records are the only
// index); nullopt when absent.
[[nodiscard]] std::optional<Json> find_map_product(
    const Json& project, const std::string& record_id);

// effective_lifecycle (L480): explicit field first, legacy-flag
// reconciliation fallback.
[[nodiscard]] std::string effective_lifecycle(const Json& record);

// _record_is_frozen (L456).
[[nodiscard]] bool record_is_frozen(const Json& record);

// product_staleness (L825): fingerprint vs the CURRENT project inputs.
[[nodiscard]] Json product_staleness(const Json& record, const Json& project);

// compare_map_products (L716): diff two records across every
// lifecycle-relevant dimension (the 版本差异 face).
[[nodiscard]] Json compare_map_products(const Json& a, const Json& b,
                                        const Json& project,
                                        CatalogRepository* catalog);

// product_qa (L507): input/provenance checks + severity-graded findings.
// The record's product_qa field is updated in place (report attached).
[[nodiscard]] Json product_qa(Json& record, const Json& project,
                              CatalogRepository* catalog);

// review_map_product (L609): draft → reviewed (needs QA without
// ERROR/BLOCKER). Throws std::invalid_argument (ValueError parity).
[[nodiscard]] Json review_map_product(Json& record, const Json& project,
                                      CatalogRepository* catalog);

// clone_map_product (L633): same inputs, independently evolvable identity;
// references the SAME catalog versions. Appends the clone. Throws on
// frozen/superseded sources.
[[nodiscard]] Json clone_map_product(const Json& record, Json& project,
                                     pwb::project::ModelClock clock = {},
                                     std::optional<std::string> new_name = std::nullopt,
                                     std::optional<std::string> notes = std::nullopt);

// rerun_map_product (L668): re-assemble from the CURRENT project state;
// the original record is marked superseded by the new one.
[[nodiscard]] MapProductResult rerun_map_product(
    Json& project, const Json& record, const AssembleDeps& deps,
    std::optional<MapProductAssembly> assembly = std::nullopt);

// freeze_map_product (L860): V9 ladder — freeze requires REVIEWED;
// unfreeze returns to draft; PUBLISHED is immutable.
void freeze_map_product(Json& record, bool frozen = true);

// supersede_map_product (L891): explicit, no re-assembly; the first
// successor wins.
void supersede_map_product(Json& record, const Json& successor);

// promote_map_product (L912): thin facade over the catalog authority —
// injected because the promote transaction family belongs to the catalog
// line. The function receives the source version id and returns the new
// immutable version id.
using PromoteFn = std::function<std::string(const std::string& version_id)>;
[[nodiscard]] std::string promote_map_product(const Json& record,
                                              const PromoteFn& promote);

// publish_map_product (L930): the publish gate — refuses stale /
// superseded / unverifiable products; warnings recorded, ``accept_warnings
// == false`` refuses on them too. Throws std::invalid_argument (Python
// ValueError parity "product cannot be published: ...") and lands the
// record PUBLISHED only when clean.
[[nodiscard]] Json publish_map_product(
    Json& record, const Json& project, CatalogRepository* catalog,
    bool accept_warnings = true,
    std::optional<std::string> export_path = std::nullopt);

}  // namespace pwb::closure_workflow
