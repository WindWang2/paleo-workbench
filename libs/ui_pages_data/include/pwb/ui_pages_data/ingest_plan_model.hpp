// V14-DATA-LINEAGE (P4) — review-state model over a built ingest plan.
//
// The two-phase ingest flow (data_suite build_ingest_plan → user review →
// execute_ingest_plan) needs an editable review surface between the pure
// build and the mutating execute. This model owns that review state:
// one row per planned item with decision / role / include mutations,
// the single-primary invariant PREVIEW for primary_required roles, and
// honest validation issues (never a fabricated green light).
//
// Dependency boundary (deliberate): this core compiles in the Qt-free,
// Pwb::Data-free target pwb_ui_pages_data, so it takes PLAIN DTOs —
// PlanItemRow carries the role vocabulary (allowed_roles) and the
// primary_required flag the data-suite registry computes. The adapter
// that produces rows from a pwb::data::IngestPlan lives in
// ingest_plan_rows.hpp/.cpp, compiled only where Pwb::Data is visible.
#pragma once

#include <cstddef>
#include <string>
#include <vector>

namespace pwb::ui_pages_data {

// Decision vocabulary — data-suite PlannedItem.decision (conv-26).
inline constexpr const char* kPlanDecisionPending = "pending";
inline constexpr const char* kPlanDecisionAccept = "accept";
inline constexpr const char* kPlanDecisionSkip = "skip";
inline constexpr const char* kPlanDecisionAsNewVersion = "as_new_version";

inline constexpr const char* kPlanRoleOther = "other";

// One reviewable planned item (adapter-filled from pwb::data::PlannedItem).
struct PlanItemRow {
    // Identity of the planned file (plan-order index preserved).
    std::size_t plan_index = 0;
    std::string path;      // absolute, display form
    std::string filename;  // path filename
    std::string type;      // scanner classification ("", never guessed)
    std::string format;

    // Inferred role + the editable vocabulary for the proposed entity
    // type (roles_for_entity_type + "other"; registry order). A role
    // outside this list is a validation issue, never silently coerced.
    std::string role = kPlanRoleOther;
    std::vector<std::string> allowed_roles;

    // Proposed entity (identity proposal; entity_id "" = unresolved/new).
    std::string entity_type;  // well | seismic_survey | geological_entity | ""
    std::string entity_id;
    std::string entity_name;
    bool new_entity = false;
    std::string strategy;  // canonical_name | uwi | directory_hint | none | ambiguous | ...
    bool ambiguous = false;

    // Review state.
    std::string decision = kPlanDecisionPending;
    bool include = true;

    // Duplicate verdict from the build phase ("" = not a duplicate).
    bool duplicate = false;
    std::string duplicate_of_version;

    // Primary proposal (single-primary invariant preview target).
    bool primary_required = false;  // registry policy for (entity_type, role)
    bool primary = false;           // plan proposal, recomputed on review

    std::string notes;  // plan note (bundle / identity note)
};

// Count snapshot for summary lines.
struct PlanSummary {
    int total = 0;
    int included = 0;
    int pending = 0;
    int accepted = 0;
    int skipped = 0;
    int as_new_version = 0;
    int duplicates = 0;
    int primary_slots = 0;  // accepted primary_required slots with a primary
};

// Review-state model over a plan COPY (the plan itself is never mutated
// here; the dialog/host applies rows back before execute through
// apply_plan_rows in ingest_plan_rows.hpp).
class IngestPlanModel {
public:
    explicit IngestPlanModel(std::vector<PlanItemRow> rows);

    const std::vector<PlanItemRow>& rows() const { return rows_; }
    std::vector<PlanItemRow>& mutable_rows() { return rows_; }
    std::size_t size() const { return rows_.size(); }
    const PlanItemRow* row(std::size_t index) const;
    bool empty() const { return rows_.empty(); }

    // Mutations (no-ops on out-of-range indices; roles outside the row's
    // vocabulary are stored as-is and surface via validation()).
    void toggle_include(std::size_t index);
    void set_decision(std::size_t index, const std::string& decision);
    void set_role(std::size_t index, const std::string& role);
    void set_all_decisions(const std::string& decision);

    // Recompute the primary proposal per (entity, role): when
    // primary_required(role) and exactly ONE accepted+included item
    // remains for the slot, that item becomes the primary preview and
    // every sibling clears. Ambiguous slots (>1 accepted) keep the
    // plan-built proposal and are reported by validation().
    void recompute_primary();

    // Honest issue strings (Chinese, user-facing). Empty vector = the
    // review state is executable. Covers: no accepted items, role
    // vocabulary violations, entity resolution failures (unresolved /
    // ambiguous / missing id), primary-slot competition.
    std::vector<std::string> validation() const;

    PlanSummary summary() const;

private:
    bool effectively_accepted(const PlanItemRow& row) const;

    std::vector<PlanItemRow> rows_;
};

}  // namespace pwb::ui_pages_data
