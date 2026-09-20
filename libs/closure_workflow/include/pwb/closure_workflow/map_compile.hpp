// C++ port of paleo_workbench/pipeline/compile_map.py +
// compile_map_production.py — the two PaleoMapDocument compilers behind
// the WorkflowCore services_.compile_map_draft / compile_map_production
// seams (UI-14). Both operate on the portable project root Json tree
// (paleomap_documents / compilation_runs / prediction_tasks /
// factor_map_tasks / stratigraphy / resources / coordinate sections).
//
// Draft compiler (18c): deterministic demo-grade — always produces an
// editable draft, placeholder square when inputs are empty, same seed +
// regions → same geometry, idempotent demo-doc replacement.
//
// Production compiler: fail-closed — requires VECTOR_POLYGONS geometry,
// never invents placeholder squares, refuses demo/untrusted inputs unless
// explicitly allowed, and registers map_compile DataRun lineage BEFORE
// the document is appended (H3: a production doc never commits while the
// catalog holds no lineage for it).
//
// Documented divergences (honest, never faking parity):
//   * Python stages a temp payload FILE for register_result_asset; the
//     C++ catalog seam transports payload BYTES (catalog_seam.hpp).
//   * Python path-2 (CatalogPort register_map_compile_run helper) has no
//     distinct C++ surface — CatalogRepository already exposes the
//     register_run/register_result_asset primitives every adapter
//     implements, so all catalogs take the path-1 shape.
//   * get_catalog() process-global fallback is the HOST's job: pass the
//     resolved repository (or nullptr for the explicit degrade).
#pragma once

#include <pwb/domain/json.hpp>
#include <pwb/project/version_models.hpp>  // IdFactory / default_make_id

#include <functional>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>

namespace pwb::workflow_runtime {
class CatalogRepository;
}

namespace pwb::closure_workflow {

using pwb::domain::Json;

inline constexpr std::string_view kDemoMapGenerator =
    "deterministic-map-draft-v1";
inline constexpr std::string_view kProductionMapGenerator =
    "production-map-from-spatial-v1";

// pipeline.compile_map_production.ProductionMapError (ValueError
// analogue — callers catch std::exception either way).
class ProductionMapError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

// compile_map.compile_map_draft(project, *, target_horizon=None,
// prediction_task_id=None, seed=0) → the attached PaleoMapDocument dict
// (copy; project_root["paleomap_documents"] is already mutated and the
// last compilation_run's active pointer is already set). Never throws
// for empty inputs — a placeholder draft is the designed outcome.
Json compile_map_draft(
    Json& project_root,
    const std::optional<std::string>& target_horizon = std::nullopt,
    const std::optional<std::string>& prediction_task_id = std::nullopt,
    int seed = 0,
    project::IdFactory make_id = project::IdFactory{&project::default_make_id});

// catalog.get_model_version_by_id capability seam (D-P2 trust check).
struct ModelVersionTrust {
    std::string status;
    bool demo_only = false;
};
// std::nullopt → "not found" (→ 声明的模型版本不存在); a thrown
// std::exception is ALSO folded into that error with its message, like
// Python's `except Exception as exc` capture.
using ModelVersionResolver =
    std::function<std::optional<ModelVersionTrust>(const std::string&)>;

struct ProductionMapCompileOptions {
    std::optional<std::string> target_horizon;
    std::optional<std::string> prediction_task_id;
    // Explicit payload (compile without a resolvable task); nullptr →
    // _payload_from_task on the resolved task. Presence also controls
    // linked-task eligibility (is-not-None parity, not truthiness).
    const Json* prediction_payload = nullptr;
    std::optional<std::string> map_crs;
    // Catalog seam — path-1 surface (register_run + register_result_asset
    // + update_run_status + list_runs/resolve_version for the
    // _versions_for_domain_tasks input resolution). nullptr → the Python
    // no-catalog degrade (production:false, lineage "untracked").
    workflow_runtime::CatalogRepository* catalog = nullptr;
    // get_model_version_by_id equivalent. Non-null catalog + EMPTY
    // resolver reproduces `verifier is None` → "无法验证其生产状态".
    ModelVersionResolver model_version_resolver;
    std::optional<std::string> prediction_version_id;
    bool allow_demo_task = false;
    project::IdFactory make_id{&project::default_make_id};
};

// compile_map_production(...) → the attached PaleoMapDocument dict.
// Throws ProductionMapError on every refusal/failure path; the project
// root is left untouched when lineage registration fails (the doc is
// never appended — H3).
Json compile_map_production(Json& project_root,
                            const ProductionMapCompileOptions& options);

}  // namespace pwb::closure_workflow
