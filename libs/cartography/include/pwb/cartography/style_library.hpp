// Qt-free geological style library V1 (CONV-27).
//
// Port of paleo_workbench/mapping/geological_style_library.py: the 12-entry
// named style library (well_symbols/facies_fills/contour/fault/horizon/
// uncertainty/boundary/reference/annotation), StyleEntry serialization and
// the data-level apply semantics (style payload + style_binding + the layer
// opacity hint fold). Python semantics preserved, including:
//   * the versioned document {"schema_version": 1, "styles": [...]};
//   * load rejects other schema versions with the exact Python message;
//   * style_entry() lookups raise with the available-keys message.
// apply_style_entry() is the data-level form of apply_style_to_layer: the
// layer object stays host-side, so the C++ function folds the opacity hint
// into an output parameter instead of touching a QgsMapLayer.
#pragma once

#include <pwb/cartography/vector_style.hpp>
#include <pwb/domain/json.hpp>

#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace pwb::cartography {

using Json = pwb::domain::Json;

struct StyleEntry {
    std::string key;
    std::string category;
    std::string title;
    VectorStyle style;
    Json binding;              // traceability dict, verbatim
    std::string legend_label;
    std::optional<double> opacity_hint;

    Json to_dict() const;
    static StyleEntry from_dict(const Json& data);
};

inline constexpr long long kStyleLibrarySchemaVersion = 1;

// The 9 category strings in declaration order.
const std::vector<std::string>& style_library_categories();

// The 12 V1 entries keyed "{category}.{key}" in definition order.
const std::vector<std::pair<std::string, StyleEntry>>&
geological_style_library();

// Lookup "{category}.{key}"; throws std::out_of_range with the Python
// KeyError message (available keys filtered by category prefix, sorted).
const StyleEntry& style_entry_lookup(const std::string& category,
                                     const std::string& key);

// Data-level apply_style_to_layer: writes entry.style.to_dict() plus the
// "style_binding" key into style_payload and folds the opacity hint into
// layer_opacity (min(layer_opacity, hint) when the hint is set).
void apply_style_entry(Json& style_payload, double& layer_opacity,
                       const StyleEntry& entry);

// Versioned library documents (save/load contract).
Json style_library_document();  // {"schema_version": 1, "styles": [...]}
// Parse a (possibly project-extended) library document; throws
// std::invalid_argument on schema mismatch. Returns entries keyed
// "{category}.{key}".
std::vector<std::pair<std::string, StyleEntry>> parse_style_library_document(
    const Json& document);

}  // namespace pwb::cartography
