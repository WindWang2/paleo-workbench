// V14-DATA-LINEAGE (P4) — ingest_plan_rows adapter implementation.
// Compiled ONLY when Pwb::Data joined the configure (additive
// PWB-V14-DATA-LINEAGE block in libs/ui_pages_data/CMakeLists.txt).
#include <pwb/ui_pages_data/ingest_plan_rows.hpp>

#include <pwb/data/ingest_plan.hpp>
#include <pwb/data/role_registry.hpp>

namespace pwb::ui_pages_data {

std::vector<PlanItemRow> ingest_plan_rows(const pwb::data::IngestPlan& plan) {
    std::vector<PlanItemRow> rows;
    rows.reserve(plan.items.size());
    for (std::size_t i = 0; i < plan.items.size(); ++i) {
        const pwb::data::PlannedItem& item = plan.items[i];
        PlanItemRow row;
        row.plan_index = i;
        row.path = item.path.string();
        row.filename = item.path.filename().string();
        row.type = item.type;
        row.format = item.format;
        row.role = item.role.empty() ? kPlanRoleOther : item.role;
        row.entity_type = item.identity.entity_type;
        row.entity_id = item.identity.entity_id;
        row.entity_name = item.identity.entity_name;
        row.new_entity = item.identity.new_entity;
        row.strategy = item.identity.strategy;
        row.ambiguous = item.identity.strategy == "ambiguous";
        row.decision =
            item.decision.empty() ? kPlanDecisionPending : item.decision;
        row.include = true;
        row.duplicate = !item.duplicate_of_version.empty();
        row.duplicate_of_version = item.duplicate_of_version;
        row.primary = item.primary;
        row.notes = item.note;

        // Registry vocabulary for the PROPOSED entity type ("other" last;
        // unknown entity types degrade to {"other"} — registry contract).
        const auto vocabulary =
            pwb::data::roles_for_entity_type(row.entity_type);
        row.allowed_roles.reserve(vocabulary.size());
        for (auto role : vocabulary) row.allowed_roles.emplace_back(role);
        row.primary_required = pwb::data::primary_required(row.role);
        rows.push_back(std::move(row));
    }
    return rows;
}

void apply_plan_rows(pwb::data::IngestPlan& plan,
                     const std::vector<PlanItemRow>& rows) {
    for (const auto& row : rows) {
        if (row.plan_index >= plan.items.size()) continue;
        pwb::data::PlannedItem& item = plan.items[row.plan_index];
        item.role = row.role;
        // An excluded row NEVER executes regardless of its decision
        // string (the review model's include flag is the user's final
        // word; validation() already accounts for it).
        if (!row.include) {
            item.decision = kPlanDecisionSkip;
        } else {
            item.decision = row.decision;
        }
        // Carry the reviewed primary proposal back: the model's
        // single-primary recomputation is the slot invariant the executor
        // binds from, so dropping it would silently discard the preview.
        item.primary = row.primary;
    }
}

}  // namespace pwb::ui_pages_data
