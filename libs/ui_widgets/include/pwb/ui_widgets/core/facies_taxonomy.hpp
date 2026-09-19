#pragma once

// UI-02 — facies / sub-facies / micro-facies three-level taxonomy,
// ported from paleo_workbench/mapping/facies_taxonomy.py (Qt-free).
//
// The vocabulary is a nested name tree {facies: {sub_facies: {micro_facies:
// {}}}} — names are identities (unique per parent, repeatable across
// levels). Two sources (grill Q1-d): builtin resources/facies_taxonomy.json
// and the project override (ProjectDocument.facies_taxonomy).

#include <nlohmann/json.hpp>

#include <map>
#include <string>
#include <tuple>
#include <vector>

namespace pwb::ui_widgets::core {

// Level keys aligned with the reference GeoJSON `level` attribute.
inline const std::vector<std::string> kFaciesLevelKeys = {
    "facies", "sub_facies", "micro_facies"};

inline const std::map<std::string, std::string> kLevelLabels = {
    {"facies", "相"}, {"sub_facies", "亚相"}, {"micro_facies", "微相"}};

// Domain field aliases per level (first = template schema canonical name).
// Facies-family layers persist either facies*/facies*_name — style/swap
// must resolve against the layer's actual fields.
inline const std::map<std::string, std::vector<std::string>>
    kFaciesFieldAliases = {
        {"facies", {"facies", "facies_name"}},
        {"sub_facies", {"sub_facies", "sub_facies_name"}},
        {"micro_facies", {"micro_facies", "micro_facies_name"}},
};

// The field name actually usable for `level` within `available`; "" when
// none is present (never guess one alias over another).
[[nodiscard]] std::string resolve_facies_field(
    const std::string& level, const std::vector<std::string>& available);

class FaciesTaxonomy {
public:
    FaciesTaxonomy() = default;
    explicit FaciesTaxonomy(const nlohmann::ordered_json& tree,
                            std::string source = "builtin");

    // Builtin vocabulary: <resources_dir>/facies_taxonomy.json
    // (empty taxonomy when unreadable — honest degradation).
    static FaciesTaxonomy builtin(const std::string& resources_dir);

    // Project vocabulary: non-empty override section wins, else builtin.
    // `override_section` is ProjectDocument.facies_taxonomy (may be null).
    static FaciesTaxonomy from_project(
        const nlohmann::json& override_section,
        const std::string& resources_dir);

    // Reference-facies-map GeoJSON features -> vocabulary via the
    // level + parent_id attribute chain (orphans skipped).
    static FaciesTaxonomy from_geojson_features(const nlohmann::json& features);

    // Selectable names at `level`; `parents` is the chosen chain
    // (facies [-> sub_facies]). Incomplete chain or a parent missing from
    // the tree -> ALL names at that level (never guess, never silently
    // clear caller state).
    [[nodiscard]] std::vector<std::string> names(
        const std::string& level,
        const std::vector<std::string>& parents = {}) const;

    [[nodiscard]] bool has(const std::string& name, const std::string& level,
                           const std::vector<std::string>& parents = {}) const;

    // Deepest selected level (empty selection = "facies" placeholder).
    static std::string selection_level(
        const std::map<std::string, std::string>& selection);

    // Feature three-field attributes -> selector initial values
    // (missing -> ""). JSON attributes coerce like Python str(v or "").
    static std::map<std::string, std::string> selection_from_attributes(
        const nlohmann::json& attributes);

    [[nodiscard]] nlohmann::ordered_json to_project_dict() const;
    [[nodiscard]] std::tuple<int, int, int> counts() const;
    [[nodiscard]] bool is_empty() const { return tree_.empty(); }
    [[nodiscard]] explicit operator bool() const { return !tree_.empty(); }

    std::string source = "builtin";

private:
    nlohmann::ordered_json tree_;
};

}  // namespace pwb::ui_widgets::core
