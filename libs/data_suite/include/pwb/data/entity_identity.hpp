// Entity identity resolution over the project document (conv-26; the
// deterministic subset of paleo_workbench/project/domain.py the ingest plan
// drives): normalize_well_name, WellRegistry/SurveyRegistry indexed views,
// the resolve_well chain (persisted_id → uwi → canonical_name/alias →
// explicit mapping, ambiguous hits never merge silently), entity↔asset link
// upsert with the single-primary invariant, and infer_role_for_type
// (project/roles.py registry semantics).
//
// All readers work on the ProjectDocument JSON tree (`wells`,
// `seismic_surveys`, `geological_entities`, `entity_asset_links`,
// `workarea.metadata.well_identity_overrides`); nothing here touches disk.
//
// Normalization boundary (declared, conv-15 D6 lineage): Python
// normalize_well_name is NFKC + casefold; this port is the bounded ASCII
// fold + separator collapse — identical for ASCII names and caseless
// scripts, verbatim for non-ASCII cased letters.
#pragma once

#include "pwb/domain/json.hpp"

#include <deque>
#include <optional>
#include <string>
#include <string_view>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace pwb::data {

// project/domain.py normalize_well_name (bounded fold; see header note).
std::string normalize_well_name(std::string_view name);

// ---- well registry (read view over project.wells) ------------------------

struct WellRecord {
    std::string id;
    std::string name;
    std::string uwi;
    std::vector<std::string> aliases;

    // All normalized identity keys this well answers to (name, uwi,
    // "uwi:<uwi>", aliases); empty strings dropped.
    std::unordered_set<std::string> match_keys() const;
};

// O(1) lookup view; by_key returns nullptr for AMBIGUOUS keys (two+ wells
// sharing a normalized identity) — callers go through resolve_well so
// duplicate wells never merge by accident.
class WellRegistry {
public:
    WellRegistry() = default;
    // Indexes every wells[] node that carries a non-empty id.
    explicit WellRegistry(const domain::Json& wells);

    void add(WellRecord well);

    const WellRecord* by_id(const std::string& well_id) const;
    const WellRecord* by_key(const std::string& key) const;
    std::vector<const WellRecord*> find_all_by_name(
        const std::string& name) const;
    std::size_t size() const { return order_.size(); }

private:
    // Stable storage — the index maps hold raw pointers, and a deque keeps
    // element addresses across push_back (a vector would invalidate them).
    std::deque<WellRecord> wells_;
    std::unordered_map<std::string, WellRecord*> by_id_;
    std::unordered_map<std::string, WellRecord*> by_key_;
    std::unordered_set<std::string> ambiguous_keys_;
    // Multi-valued normalized key → wells answering to it (insertion order).
    std::unordered_map<std::string, std::vector<WellRecord*>> index_;
    std::vector<WellRecord*> order_;
};

// ---- survey registry (read view over project.seismic_surveys) -----------

struct SurveyRecord {
    std::string id;
    std::string name;
};

class SurveyRegistry {
public:
    SurveyRegistry() = default;
    explicit SurveyRegistry(const domain::Json& surveys);

    const SurveyRecord* by_id(const std::string& survey_id) const;
    // by_key is first-wins (Python SurveyRegistry has no ambiguity guard).
    const SurveyRecord* by_key(const std::string& key) const;

private:
    std::deque<SurveyRecord> surveys_;  // pointer-stable storage (see above)
    std::unordered_map<std::string, SurveyRecord*> by_id_;
    std::unordered_map<std::string, SurveyRecord*> by_key_;
};

// ---- resolution chain -----------------------------------------------------

struct ResolutionOutcome {
    bool matched = false;
    bool ambiguous = false;
    std::string well_id;
    std::string survey_id;
    std::string strategy;  // persisted_id | uwi | canonical_name | alias |
                           // explicit_mapping | ambiguous_name | none
    std::vector<std::string> candidates;
};

// resolve_well over the project tree: persisted id → UWI → normalized
// canonical name (exactly one holder) → alias (uwi matches an alias) →
// explicit mapping (overrides arg, else workarea.metadata overrides).
// Ambiguity is reported, never auto-merged.
ResolutionOutcome resolve_well(const domain::Json& project_root,
                               const WellRegistry* registry,
                               std::string_view name, std::string_view uwi = {},
                               std::string_view well_id = {},
                               const std::optional<domain::Json>& overrides =
                                   std::nullopt);

// ---- entity ↔ asset links (single-primary invariant) ---------------------

struct LinkUpsert {
    bool created = false;   // a new link row was appended
    bool changed = false;   // an existing row was mutated (incl. demotions)
    std::size_t index = 0;  // position in the links array
};

// Create/update the (entity_type, entity_id, asset_id, role) link on
// project_root["entity_asset_links"] (created on demand). Idempotent;
// flipping is_primary on demotes sibling primaries of the same
// (entity_type, entity_id, role). Link rows keep the Python field set:
// id, entity_type, entity_id, asset_id, role, is_primary, unresolved,
// note, metadata.
LinkUpsert upsert_entity_asset_link(domain::Json& project_root,
                                    std::string_view entity_type,
                                    std::string_view entity_id,
                                    std::string_view asset_id,
                                    std::string_view role, bool is_primary,
                                    bool unresolved = false,
                                    std::string_view note = "");

// asset ids bound to (entity_type, entity_id, role); role "" = any role.
std::vector<std::string> asset_ids_for_entity(
    const domain::Json& project_root, std::string_view entity_type,
    std::string_view entity_id, std::string_view role = "");

// ---- role inference (project/roles.py infer_role_for_type) ----------------

// Best registry role for a scanner-classified type + optional
// extension/filename hints; "" when no mapping applies (caller keeps its
// legacy default). Never guesses identity: filename tokens only fire for
// generically-typed files.
std::string infer_role_for_type(std::string_view resource_type,
                                std::string_view file_suffix = {},
                                std::string_view file_name = {});

}  // namespace pwb::data
