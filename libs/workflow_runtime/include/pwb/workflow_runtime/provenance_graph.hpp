#pragma once

// C++ port of paleo_workbench/workflow/provenance_graph.py (CONV-26) —
// unified product lifecycle provenance graph (V8 M10). One pure-data API
// composing the EXISTING authorities (catalog lineage, run freshness,
// constraint lifecycle pins, map-product records) into the dependency
// narrative the Inspector / lineage explorer renders. No second authority:
// every node carries the id of the owning system; every edge derives from
// recorded lineage, never inferred. Missing pieces are reported as gap
// entries — a provenance gap is data, not an exception.
//
// Document seam: the project is a Json view:
//   {"map_products": [record…], "factor_map_tasks": [task…]}
//   record = {"id", "product_name", "frozen", "status",
//             "superseded_by"?, "factor_task_ids": [task ids]}
//   task   = {"id", "name", "method", "source_kind",
//             "grid_artifact_version_id"?,
//             "parameters": {"constraint_pins": [pin…]}}
//
// Qt-free, Python-free.

#include <pwb/domain/json.hpp>
#include <pwb/workflow_runtime/catalog_seam.hpp>

#include <optional>
#include <string>

namespace pwb::workflow_runtime {

using pwb::domain::Json;

// Explain one product (or every product) from RAW to publish:
// {"nodes": […], "edges": […], "gaps": […]}. Product records contribute
// their factor tasks' grid versions, the constraint state each task pinned;
// the catalog contributes fusion run lineage (repository == nullptr skips
// that section without a gap, mirroring Python catalog_service=None).
// (Non-const pointer: the CatalogRepository interface is not const-correct
// yet — a read-only catalog adapter branch will fix that upstream.)
Json build_product_lifecycle_graph(const Json& project,
                                   CatalogRepository* repository,
                                   const std::optional<std::string>& product_id =
                                       std::nullopt);

}  // namespace pwb::workflow_runtime
