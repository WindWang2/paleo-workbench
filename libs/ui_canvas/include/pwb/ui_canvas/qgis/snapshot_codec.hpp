// UI-15 — QGIS snapshot codec: map the Qt-free wire dicts produced by
// snapshot_encoder onto the bridge's VectorLayerSpec records
// (bindings.cpp parse_layers parity), plus the legacy style migration and
// renderer_info helpers the Python module level exposes.
//
// Lives in the QGIS target: VectorLayerSpec is a bridge type and
// build_renderer_from_spec / renderer_from_xml pull in QGIS headers.
#pragma once

#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/ui_canvas/map_render_backend.hpp>

#include "qgis_render_bridge.hpp"

namespace pwb::ui_canvas::qgis {

using Json = pwb::domain::Json;

// bindings.cpp parse_layers parity for ONE layer dict. Required keys
// (id/name/crs/revisions/visible/opacity) raise std::invalid_argument —
// the pybind cast-error surface. `kind:"raster"` layers read source_path
// and raster_renderer_xml; vector layers read style{...}, scale_range,
// features[] or delta{...}.
pwb::qgis_render::VectorLayerSpec layer_spec_from_json(const Json& data);

// The whole encoded list → specs (parse_layers loop parity).
std::vector<pwb::qgis_render::VectorLayerSpec> layer_specs_from_json(
    const Json& layers);

// legacy_style_to_renderer_xml parity: build a renderer from the flat
// legacy style dict + geometry name and serialize it. Returns "" when the
// codec produced no renderer (py::none parity).
std::string legacy_style_to_renderer_xml(const Json& style,
                                         const std::string& geometry_type);

// renderer_info parity: {"type", "symbol_count"} for a serialized
// renderer payload, or a null Json when it does not parse (py::none).
Json renderer_info(const std::string& renderer_xml);

}  // namespace pwb::ui_canvas::qgis
