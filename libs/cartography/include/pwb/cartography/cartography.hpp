// Cartography product API facade (CONV-27).
//
// One entry point for the product C++ runtime: color ramps resolve through
// color_ramps.hpp (get_color_ramp/list_color_ramps), symbols through
// geological_symbols.hpp, scalar styling through scalar_style.hpp; this
// header adds style validation/application and the preset catalog. The QGIS
// path is the bridge payload adapter (qgis_adapter.hpp) feeding
// native/qgis_render_bridge. Everything is Qt-free and Python-free.
#pragma once

#include <pwb/cartography/color_ramps.hpp>
#include <pwb/cartography/geological_symbols.hpp>
#include <pwb/cartography/qgis_adapter.hpp>
#include <pwb/cartography/scalar_style.hpp>
#include <pwb/cartography/style_library.hpp>
#include <pwb/cartography/templates.hpp>
#include <pwb/cartography/vector_style.hpp>
#include <pwb/domain/json.hpp>

#include <string>
#include <vector>

namespace pwb::cartography {

using Json = pwb::domain::Json;

// ---- ramps ---------------------------------------------------------------------

inline std::vector<std::string> list_color_ramps_api() {
    return list_color_ramps();
}

// ---- style validation ------------------------------------------------------------

// Structured validation of a persisted style payload: parses VectorStyle
// (tolerant by contract), and reports hard errors only for non-object
// payloads or out-of-range numerics that downstream renderers reject.
// Returns {"ok": bool, "errors": [...], "normalized": {VectorStyle dict}}.
Json validate_style(const Json& style);

// Data-level application of a named preset or V1 library entry to a style
// payload + opacity pair (apply_style_entry semantics, D-8). preset_kind is
// "preset" (map_styles STYLE_LIBRARY names) or "library" (V1
// "{category}.{key}"). Throws std::out_of_range for unknown names.
void apply_style(Json& style_payload, double& layer_opacity,
                 const std::string& preset_kind, const std::string& name);

// The 8 named presets with their dumped VectorStyle dicts.
Json style_preset_catalog();

}  // namespace pwb::cartography
