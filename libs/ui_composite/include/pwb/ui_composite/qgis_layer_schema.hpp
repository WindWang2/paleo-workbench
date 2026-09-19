#pragma once

// Port of paleo_workbench/mapping/qgis_layer_schema.py (UI-13):
// GeologicalLayerSpec → QGIS layer schema wire adapter.
//
// Converts the pure-domain spec into the ``fields_json`` payload accepted
// by the qgis_render_bridge mirror upsert, so QgsFields / field
// constraints / value domains / defaults / editor widgets on the QGIS
// side are generated from the SAME spec the core validates — never a
// second, divergent field set.
//
// Pure functions; no bridge import required to *compute* the wire.
// Qt-free.

#include <string>

#include <pwb/domain/json.hpp>
#include <pwb/ui_composite/geological_layer_spec.hpp>

namespace pwb::ui_composite {

using pwb::domain::Json;

// geometry_kind (spec vocabulary) → QGIS provider geometry type names
// (memory-provider / QgsWkbType string forms). Polygon layers mirror as
// MultiPolygon so single/multi features share one WKB type.
// Unknown kind → throws std::invalid_argument (Python ValueError parity).
std::string qgis_geometry_type_name(const std::string& geometry_kind);

// spec field kind → QMetaType name used by QgsField / QVariant type name.
// Unknown kind → throws std::invalid_argument.
std::string qgs_field_type_for_kind(const std::string& kind);

// Wire form of the spec's field schema for the bridge mirror upsert.
// Each entry: name/type/alias/editor_widget + optional length/precision/
// constraints/domain/default — exactly what QgsField +
// QgsFieldConstraints + QgsEditorWidgetSetup need on the C++ side.
Json fields_json_for_spec(const GeologicalLayerSpec& spec);

// Full mirror-creation wire fragment for a role: geometry type name +
// fields_json + raster marker + renderer binding. Unknown role → throws
// std::out_of_range (via spec_for_role).
Json schema_wire_for_role(const std::string& role_value);

}  // namespace pwb::ui_composite
