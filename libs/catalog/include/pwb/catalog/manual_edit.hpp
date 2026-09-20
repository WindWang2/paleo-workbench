// Manual-edit provenance (V14-DATA-LINEAGE) — catalog/lifecycle.py
// register_manual_edit_run / complete_manual_edit_run parity (the pure
// assembly halves; the mutating halves live on the service/closure layer).
//
// A manual edit MUST NOT form a provenance black hole: the run is
// registered BEFORE committing the working copy (status "running", input
// versions + typed input ports + business context parameters), the commit
// carries run.id, and completion attaches the committed versions as typed
// output ports and closes the run (failed when nothing landed — no phantom
// RUNNING rows). The actor is never fabricated: absent user → the field is
// simply omitted (unknown), matching lifecycle.py.
#pragma once

#include "pwb/catalog/models.hpp"

#include <string>
#include <string_view>
#include <vector>

namespace pwb::catalog {

inline constexpr std::string_view kManualEditOperation = "manual_edit";
inline constexpr std::string_view kManualEditGenerator =
    "paleo-workbench/manual-edit";

// Maps an entity business role onto a typed-lineage port role (open
// vocabulary — unknown roles pass through verbatim; "" → "").
std::string port_role_for_business_role(std::string_view business_role);

struct ManualEditRequest {
    std::vector<std::string> source_version_ids;
    std::string entity_type;
    std::string entity_id;
    std::string business_role;
    std::string actor;   // "" → omitted (never fabricated)
    std::string note;
    bool as_new_asset = false;
    domain::Json extra_parameters = domain::Json::object();
};

// Pure assembly + validation over the document. Every source id must
// reference a known COMMITTED version (working-copy payloads are not
// provenance anchors); violations return an error instead of a run. The
// returned run has status "running", no outputs, typed input ports when a
// business role maps to a port role, and parameters carrying the business
// context (entity_type/entity_id/business_role/as_new_asset + optional
// actor/note + extra).
domain::Result<DataRun> build_manual_edit_run(const CatalogDocument& document,
                                              const ManualEditRequest& request);

struct ManualEditCompletion {
    std::vector<std::string> committed_version_ids;
    std::string business_role;
    int failed_count = 0;
};

// Pure completion step for an existing run row: attaches typed output
// ports (role manual_edit output or the business role's mapped role) for
// the committed versions, extends the flat output list, sets status
// complete/failed and records failed_checkouts when non-zero. Terminal
// statuses are refused (the caller's single-writer core guards ordering;
// this helper stays pure).
domain::Result<DataRun> apply_manual_edit_completion(
    const DataRun& run, const ManualEditCompletion& completion);

}  // namespace pwb::catalog
