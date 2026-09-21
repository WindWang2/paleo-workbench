#pragma once

// CONV-35 — GeoJSON vector metadata + three-layer facies-result grouping,
// ported 1:1 from paleo_workbench/resources/geojson_layers.py (frozen in
// facies_groups_oracle.json; replayed in ui_data_core.facies_groups).
//
// A 相图 product is three sibling GeoJSON layers — 相 / 亚相 / 微相 —
// that become a single "output" artifact only when the group is complete.
// Role detection folds an explicit metadata claim, the parsed document
// summary and the filename convention into one effective role; group
// identity reuses the product id when annotated, else a stable digest of
// directory + role-stripped stem.

#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/ui_data_core/asset_view.hpp>

namespace pwb::ui_data_core {

// role -> (display label, hierarchy level) — FACIES_LAYER_SPECS parity.
[[nodiscard]] const std::pair<std::string, int>*
facies_layer_spec(std::string_view role);

// Explicit role normalization over the alias table (layer_role /
// facies_level / … values). Non-string scalars can never match an alias
// (Python str(value) on a dict/list produces repr text — also never a
// match) so only strings participate.
[[nodiscard]] std::optional<std::string> normalize_facies_layer_role(
    const domain::Json& value);

// Filename-convention role inference (case-insensitive alias substring
// over the stem).
[[nodiscard]] std::optional<std::string>
facies_layer_role_from_name(std::string_view filename);

// Hierarchy metadata inferred from a conventional layer filename —
// {} when no role matches.
[[nodiscard]] domain::Json
facies_layer_summary_from_name(std::string_view filename);

// Bounded, UI-friendly metadata for one parsed GeoJSON document
// (geojson_valid / geojson_error / geometry_types / role fields /
// facies_product_source_id).
[[nodiscard]] domain::Json
geojson_document_summary(const domain::Json& payload,
                         std::string_view filename);

// Effective hierarchy role of a layer (parsed summary folded with the
// filename convention; a parse failure is never promoted).
[[nodiscard]] std::optional<std::string>
facies_layer_role(const ResourceItem& resource);

// Raw grouping key — "id:<explicit>" or "path:<parent>:<role-stripped
// stem>" — exposed so callers/tests can rekey or normalize the digest.
[[nodiscard]] std::optional<std::string>
facies_group_key(const ResourceItem& resource);

// Stable digest of a grouping key — "facies_product_<sha256[:16]>".
[[nodiscard]] std::string facies_group_id(const std::string& group_key);

// The clicked 相图 layer plus its same-group siblings, ordered
// 相→亚相→微相. Layers without a recognizable role never join a group
// (the clicked layer alone is returned).
[[nodiscard]] std::vector<const ResourceItem*>
facies_group_members(const ResourceItem& resource,
                     const std::vector<const ResourceItem*>& resources);

// Annotate complete 相/亚相/微相 GeoJSON sibling groups in-place:
// facies_product_group_id / facies_product_complete /
// facies_product_layer_count on every grouped member; artifact_role +
// tags on members of complete groups. Returns the incomplete-group
// warnings (only when a group has ≥2 members and touches `added`).
[[nodiscard]] std::vector<std::string> annotate_facies_product_groups(
    const std::vector<ResourceItem*>& added,
    const std::vector<ResourceItem*>& existing = {});

}  // namespace pwb::ui_data_core
