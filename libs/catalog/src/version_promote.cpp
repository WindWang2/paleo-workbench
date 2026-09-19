// Frozen promote-run / promote-metadata shapes (conv-31b; service.py
// promote_version / promote_asset 3665-3759 — R7 recon contract, frozen in
// 31b-findings).
//
// This TU implements the PURE assembly shapes only. The two orchestration
// pieces the task associates with promote_version live elsewhere by
// freeze decision and are consumed, not re-declared, here:
//   * staging-lease key — findings §C-7 / ruling D-10: the single source
//     is working_copy.hpp's staging_target(project_path, stage, asset_id)
//     ("<proj>.artifacts/<outputs>/<asset_id>", ON-DISK dir name, NOT
//     stage.value); this header deliberately declares no target builder.
//   * #849-1 in-lock version-number reassignment — the build-time
//     estimate is discarded and the number re-computed inside the commit
//     window via CatalogDocument::next_version_number (models.cpp,
//     delivered); promote_version_realloc in the oracle pins the shape
//     ([1,2] → promote → 3 → promote → 4, never [3,3]).
// The full orchestration (resolve_path → trashed/payload gates → lease →
// copy via place_managed_file(keep_source=true) → reassignment → single
// save with dirty assets+versions+runs → _rollback on failure) is the
// service layer's job over these shapes.
#include "pwb/catalog/version_promote.hpp"

#include "pwb/catalog/refs.hpp"
#include "pwb/domain/ids.hpp"

namespace pwb::catalog {

namespace {

// Absent optionals serialize as JSON null (Python None), not as an
// omitted key — the oracle's promote_version_shape pins note: null.
domain::Json optional_text(const std::optional<std::string>& value) {
    return value.has_value() ? domain::Json(*value)
                             : domain::Json(nullptr);
}

}  // namespace

DataRun make_promote_run(const domain::VersionId& source_id,
                         const PromoteOptions& options) {
    DataRun run;
    run.id = domain::RunId(domain::make_id("run_"));  // run_<12hex>
    run.operation = "promote";
    run.input_version_ids = {source_id};
    // Dict-literal key order: to_stage, reviewed_by, note (ordered_json
    // keeps insertion order; to_stage uses the WIRE value "output", not
    // the on-disk dir name "outputs" — the dir-name rule is lease-key
    // only, R3#1).
    run.parameters = domain::Json::object();
    run.parameters["to_stage"] =
        std::string(domain::to_string(options.to_stage));
    run.parameters["reviewed_by"] = optional_text(options.reviewed_by);
    run.parameters["note"] = optional_text(options.note);
    run.status = "completed";  // DataRun default, explicit for the freeze
    run.created_at = utc_now_iso();
    // output_version_ids stays empty — the orchestrator backfills it with
    // the new version id after the build (service.py H-6).
    return run;
}

domain::Json make_promote_version_metadata(const domain::VersionId& source_id,
                                           const PromoteOptions& options) {
    domain::Json out = domain::Json::object();
    out["promoted_from"] = source_id.str();
    out["reviewed_by"] = optional_text(options.reviewed_by);
    out["note"] = optional_text(options.note);
    return out;
}

}  // namespace pwb::catalog
