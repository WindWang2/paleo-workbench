// Role registry — the single authority for entity↔asset link roles
// (paleo_workbench/project/roles.py parity; V14-DATA-LINEAGE port).
//
// The registry is *descriptive guidance* for ingest inference, conflict
// detection and UI grouping — deliberately NOT an admission gate: documents
// with unknown roles (older/newer app versions) must always load and
// round-trip. Lookups classify, never reject. Role names repeat across
// entity types (tops for wells AND geological entities, horizon for surveys
// AND geological entities), so the authoritative index is scoped by
// (entity_type, role); bare-role lookup prefers the well vocabulary
// (first in build order, the most common lookup surface).
#pragma once

#include <string>
#include <string_view>
#include <vector>

namespace pwb::data {

// One link role and its business semantics (roles.py RoleDefinition).
struct RoleDefinition {
    std::string_view role;
    std::vector<std::string_view> entity_types;
    std::string_view cardinality = "0..N";      // "0..1" | "0..N"
    std::string_view primary_policy = "optional";  // none|optional|required_single
    bool ordered = false;                       // ordinal is meaningful
    std::string_view display;                   // zh label; "" → callers use role
    std::string_view stage_default = "raw";
    std::vector<std::string_view> format_hints; // ingest inference hints (".las"…)

    bool applies_to(std::string_view entity_type) const {
        for (auto candidate : entity_types) {
            if (candidate == entity_type) return true;
        }
        return false;
    }
};

// The definition for `role`; unknown roles get the permissive fallback
// (other / 0..N / none). `entity_type` (optional) selects the per-entity
// definition when the role name repeats across vocabularies.
const RoleDefinition* role_definition(std::string_view role,
                                      std::string_view entity_type = {});

bool known_role(std::string_view role);

// Ordered role vocabulary for one entity type (UI grouping order; "other"
// last). Unknown entity types → {"other"}.
std::vector<std::string_view> roles_for_entity_type(
    std::string_view entity_type);

bool cardinality_allows_multiple(std::string_view role);
bool primary_required(std::string_view role);

// Well / survey / geological vocabularies in registry order (spans of the
// internal table; stable for the process lifetime).
const std::vector<std::string_view>& well_roles();
const std::vector<std::string_view>& survey_roles();
const std::vector<std::string_view>& geological_roles();

// Display label for a role under an entity type: registry display when
// non-empty, else the role name itself (roles.py `display or role`).
std::string role_display(std::string_view role,
                         std::string_view entity_type = {});

}  // namespace pwb::data
