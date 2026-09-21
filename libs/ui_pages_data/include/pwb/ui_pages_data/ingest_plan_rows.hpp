// V14-DATA-LINEAGE (P4) — the Pwb::Data-side adapter for the Qt-free
// IngestPlanModel (ingest_plan_model.hpp documents why the split exists:
// pwb_ui_pages_data links only Pwb::Domain, so the model speaks plain
// PlanItemRow DTOs and THIS header/source — compiled under
// `if(TARGET Pwb::Data)` in libs/ui_pages_data/CMakeLists.txt — is the
// only place that sees pwb::data types).
#pragma once

#include <pwb/ui_pages_data/ingest_plan_model.hpp>

#include <vector>

namespace pwb::data {
struct IngestPlan;
}  // namespace pwb::data

namespace pwb::ui_pages_data {

// Project a built domain plan onto review rows: role vocabulary +
// primary policy resolved through pwb::data::roles_for_entity_type /
// primary_required for the item's proposed entity_type.
std::vector<PlanItemRow> ingest_plan_rows(const pwb::data::IngestPlan& plan);

// Apply the reviewed rows back onto a plan COPY ahead of
// pwb::data::execute_ingest_plan: decision + role per item; rows the
// reviewer excluded (include=false) or left pending become "skip" —
// only explicitly accepted (or as_new_version) items execute.
void apply_plan_rows(pwb::data::IngestPlan& plan,
                     const std::vector<PlanItemRow>& rows);

}  // namespace pwb::ui_pages_data
