#pragma once

// Real port of paleo_workbench/workflow/current_context.py
// resolve_current_project_version_context (CONV-33 findings A3 leftover —
// the "五段注入面" the orchestration slice left to the consuming closure
// line). This is the PROJECT glue the C++ data face lacked:
//
//   1. Catalog asset current pointers (the repository plays the
//      DataCatalogService role — list_assets carries current_version_id).
//   2. project.horizon_interpretations[].current_version_id
//      (+ expected identity generator "horizon-interp-v1").
//   2b. project.correlation_interpretations[] (Stage 12) — also
//       mark_domain_product_current + superseded-tip deselection
//       (issue #373 / C15), generator "strat-corr-v1".
//   2c. project.fault_interpretations[] — same domain-tip discipline,
//       generator "fault-interp-v1".
//   3. project.factor_map_tasks[].grid_artifact_version_id (the current
//      product pointer; historical per-run assets must not stay selected)
//      + scientific expected identity (factor_type / target_horizon /
//      method + known parameter keys).
//   4. project.prediction_tasks[] expected identity (adapter_kind /
//      threshold / model_ref from model_metadata).
//   5. extra_selected overrides (last write wins).
//
// Python reads model attributes through getattr reflection over the
// global catalog.runtime singleton; the C++ composition root injects the
// repository and the project is the portable .paleo.json Json tree
// (missing/typed-wrong sections read as empty — the pydantic-model
// `or []` parity used across this library). The degraded "no service →
// last version per asset" inference is the compose_freshness surface in
// service.cpp and is deliberately NOT re-implemented here: with one
// repository the service branch is the only branch (documented
// divergence; Python's degraded mode exists for test doubles only).
//
// Qt-free, Python-free.

#include <pwb/domain/json.hpp>
#include <pwb/workflow_runtime/catalog_seam.hpp>
#include <pwb/workflow_runtime/current_context.hpp>

#include <map>
#include <string>

namespace pwb::workflow_runtime {

using pwb::domain::Json;

// Resolve the deterministic current-version context for the open project.
// *catalog may be null (Python catalog=None): project refs then land as
// bare selected version ids without asset resolution. *project may be
// null (Python project=None): only the catalog pointers +
// *extra_selected shape the context.
[[nodiscard]] CurrentProjectVersionContext
resolve_current_project_version_context(
    CatalogRepository* catalog, const Json* project,
    const std::map<std::string, std::string>& extra_selected = {});

}  // namespace pwb::workflow_runtime
