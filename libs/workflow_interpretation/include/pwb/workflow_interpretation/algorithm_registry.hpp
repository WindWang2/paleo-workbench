#pragma once
// CONV-32 — AlgorithmSpec registry (interpretation/algorithm_registry.py
// port): the single authority for algorithm capability declarations.
// Constraint support projects from constraint_capabilities.hpp (engine
// vocabulary). Frozen 9-entry table; alias index rebuilt on register.
#include <pwb/domain/json.hpp>
#include <pwb/workflow_interpretation/constraint_capabilities.hpp>

#include <map>
#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace pwb::workflow_interpretation {

using domain::Json;

struct AlgorithmSpec {
    std::string algorithm_id;
    std::string family;  // "interpolation" | "fusion"
    std::string display_label;
    std::vector<std::string> aliases;
    std::string ui_label;  // "" ⇒ to_dict falls back to display_label
    Json parameter_schema = Json::object();
    // kind.value -> (level.value, note) — only declared cells projected.
    std::map<std::string, std::pair<std::string, std::string>> supported_constraints;
    bool supports_cancel = true;
    bool requires_crs = true;
    bool requires_unit = false;
    bool produces_uncertainty = false;
    std::string backend;
    std::vector<std::string> prerequisites;
    std::string notes;  // NOT serialized in to_dict

    [[nodiscard]] ConstraintSupport constraint_support(ConstraintKind kind) const;
    [[nodiscard]] Json to_dict() const;  // exact 13-key order, no "notes"
};

// ALGORITHMS — insertion order: kriging, idw, constrained_idw, spline,
// directional, linear, nearest, rbf, factor_fusion.
[[nodiscard]] const std::map<std::string, AlgorithmSpec>& algorithms();
// Replace-or-insert + alias index rebuild (test/extension hook).
void register_algorithm(const AlgorithmSpec& spec);
// strip() only — NO alias resolution, NO case-fold; nullptr if absent.
[[nodiscard]] const AlgorithmSpec* get_algorithm(const std::string& id);
// Case-folded alias/id resolution; throws AlgorithmValueError
// ("empty algorithm reference" / "unknown algorithm: '<ref>'").
[[nodiscard]] std::string canonical_algorithm_id(const std::string& ref);
[[nodiscard]] std::string display_label(const std::string& algorithm_id);
// UI_INTERPOLATION_METHODS order, ui_label-or-display_label values.
[[nodiscard]] std::vector<std::string> ui_interpolation_methods();
[[nodiscard]] std::map<std::string, std::string> interpolation_algorithm_labels();
// ("kriging","idw","constrained_idw","spline","directional")
[[nodiscard]] const std::vector<std::string>& ui_interpolation_method_ids();

}  // namespace pwb::workflow_interpretation
