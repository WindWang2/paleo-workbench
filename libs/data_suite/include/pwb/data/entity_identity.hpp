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

    // The index maps hold pointers into the deque; a copied registry would
    // keep pointing at the ORIGINAL's storage. Move-only.
    WellRegistry(const WellRegistry&) = delete;
    WellRegistry& operator=(const WellRegistry&) = delete;
    WellRegistry(WellRegistry&&) = default;
    WellRegistry& operator=(WellRegistry&&) = default;

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

    SurveyRegistry(const SurveyRegistry&) = delete;
    SurveyRegistry& operator=(const SurveyRegistry&) = delete;
    SurveyRegistry(SurveyRegistry&&) = default;
    SurveyRegistry& operator=(SurveyRegistry&&) = default;

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
// note, metadata — plus `ordinal` (V14: role-internal ordering, e.g.
// multi-LAS load order; schema default 0 keeps old documents identical).
// ordinal < 0 on update = leave the stored value unchanged.
LinkUpsert upsert_entity_asset_link(domain::Json& project_root,
                                    std::string_view entity_type,
                                    std::string_view entity_id,
                                    std::string_view asset_id,
                                    std::string_view role, bool is_primary,
                                    bool unresolved = false,
                                    std::string_view note = "",
                                    int ordinal = 0);

// asset ids bound to (entity_type, entity_id, role); role "" = any role.
std::vector<std::string> asset_ids_for_entity(
    const domain::Json& project_root, std::string_view entity_type,
    std::string_view entity_id, std::string_view role = "");

// ---- governance edits (link/role write path; conv-governance) -------------

// True when the (entity_type, entity_id) node exists in its section
// (wells / seismic_surveys / geological_entities / auxiliary_entities).
bool entity_exists(const domain::Json& project_root,
                   std::string_view entity_type, std::string_view entity_id);

// Remove the (entity_type, entity_id, asset_id) link row(s); role "" drops
// every role of that pair, a non-empty role only the exact row (upsert's
// key). Returns the number of removed rows. History stays explainable:
// callers soft-delete via catalog tombstones, this is the explicit unlink.
int remove_entity_asset_link(domain::Json& project_root,
                             std::string_view entity_type,
                             std::string_view entity_id,
                             std::string_view asset_id,
                             std::string_view role = "");

enum class LinkRoleEdit { Ok, NotFound, Conflicts };

// Move one link row's role. The row keeps its identity (id, is_primary,
// unresolved, ordinal, note, metadata, created_at) — only `role` changes,
// and a primary row demotes sibling primaries of the NEW role (the upsert
// invariant). Conflicts (never a silent merge) when the pair already has a
// row with new_role — the caller surfaces it.
LinkRoleEdit set_link_role(domain::Json& project_root,
                           std::string_view entity_type,
                           std::string_view entity_id,
                           std::string_view asset_id,
                           std::string_view old_role,
                           std::string_view new_role);

// ---- link read views + entity domain ops (project/domain.py parity) -------

// Stable read view of one link row (missing fields → schema defaults).
struct EntityLinkView {
    std::string id;
    std::string entity_type;
    std::string entity_id;
    std::string asset_id;
    std::string role;
    bool is_primary = false;
    bool unresolved = false;
    int ordinal = 0;
    std::string note;
};

std::vector<EntityLinkView> links_for_entity(
    const domain::Json& project_root, std::string_view entity_type,
    std::string_view entity_id);
std::vector<EntityLinkView> links_for_asset(
    const domain::Json& project_root, std::string_view asset_id);

// (entity_type, entity_id) pairs attached to asset_id; entity_type ""
// (default) = every entity type.
std::vector<std::pair<std::string, std::string>> entity_ids_for_asset(
    const domain::Json& project_root, std::string_view asset_id,
    std::string_view entity_type = "");

// spatial_scope == "reference" for the well node with this id.
bool is_reference_well(const domain::Json& project_root,
                       std::string_view well_id);

struct LinkPruneResult {
    int removed_links = 0;
    int pruned_wells = 0;
};

// Drop every link pointing at asset_id (asset removed from catalog);
// returns the number of links removed.
int remove_links_for_asset(domain::Json& project_root,
                           std::string_view asset_id);

// Remove one well node and every link owned by that well.
LinkPruneResult remove_well_entity(domain::Json& project_root,
                                   std::string_view well_id);

// Unlink the removed assets and drop REFERENCE wells that lose every link.
// Only wells touched by one of the removed links are candidates, and only
// reference wells with no remaining entity links are pruned — manually
// maintained/unrelated wells and reference wells shared by another imported
// file survive (domain.py remove_asset_links_and_prune_reference_wells).
LinkPruneResult remove_asset_links_and_prune_reference_wells(
    domain::Json& project_root, const std::vector<std::string>& asset_ids);

// ---- role inference (project/roles.py infer_role_for_type) ----------------

// Best registry role for a scanner-classified type + optional
// extension/filename hints; "" when no mapping applies (caller keeps its
// legacy default). Never guesses identity: filename tokens only fire for
// generically-typed files.
std::string infer_role_for_type(std::string_view resource_type,
                                std::string_view file_suffix = {},
                                std::string_view file_name = {});

}  // namespace pwb::data
