// review_versioning — workflow/versioning.py parity over the project JSON
// tree: expert sign-off of map drafts (ISS-DOM-04). The VersionSet lifecycle
// (open → final → superseded), snapshot fingerprints, the demo-draft /
// lineage finalize guards and the compilation-run status machine live here;
// the report/QC half lives in review_qc_core.hpp.

#pragma once

#include "pwb/domain/errors.hpp"
#include "pwb/domain/json.hpp"

#include <string>

namespace pwb::closure_review {

// build_snapshot parity: a point-in-time snapshot of one map document —
// counts, the linked contour draft, the map's latest QC report id/status
// and the content fingerprint. Deterministic given the document.
domain::Json build_snapshot(const domain::Json& root,
                            const domain::Json& map_document,
                            const std::string& note,
                            const std::string& created_by,
                            const std::string& iso_now);

// finalize_map_version parity: guard (demo draft / non-production /
// lineage-untracked documents refuse), optional require_qc_pass gate,
// supersede prior finals for the horizon, append the snapshot, flip the
// linked contour draft to final, and advance the active compilation run
// toward export_ready. Returns the stored VersionSet JSON. Unknown doc →
// NotFound; guard refusal → InvalidArgument with the Python message text.
domain::Result<domain::Json> finalize_map_version_on_document(
    domain::Json& root, const std::string& doc_id, const std::string& note,
    const std::string& finalized_by, bool require_qc_pass,
    const std::string& iso_now);

}  // namespace pwb::closure_review
