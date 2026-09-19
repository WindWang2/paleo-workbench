// Qt-free adapter from cartography styles to the QGIS render bridge
// payloads (CONV-27).
//
// The vendored C++ bridge (native/qgis_render_bridge, linked against QGIS)
// already owns every QgsSymbol/QgsRenderer/QgsTextFormat/QgsColorRampShader
// realization: build_scalar_renderer_xml, build_renderer_from_spec /
// legacy_style_to_renderer_xml, apply_renderer_style, apply_label_style.
// This adapter emits its INPUTS — no second QGIS wrapper lives here (D-5):
//
//   * scalar_renderer_payload  — the JSON payload consumed by the C++
//     build_scalar_renderer_xml (ramp/mode/items/min/max/opacity/...);
//   * legacy_renderer_style    — the flat style dict shape the bridge's
//     legacy_style_to_renderer_xml / build_renderer_from_spec parse
//     (renderer -> renderer_kind, field -> classification_field, ...);
//   * flatten_qgis_style       — the persisted-style promotion + unit
//     conversions of map_render_backend._flatten_qgis_style (label size
//     px -> pt at 72/96, halo width px -> buffer mm at 25.4/96,
//     buffer_color fallback from halo_color); non-object inputs raise
//     (Python dict() construction would);
//   * QgisStylePayload         — the versioned authoritative payload model
//     (qgis_style.QgisStylePayload) with revision bumping;
//   * symbol_renderer_spec     — a geological symbol's renderer_hint as a
//     categorized/single bridge spec (rules value/stroke/stroke_width/
//     line_pattern/label + classification_field).
#pragma once

#include <pwb/cartography/geological_symbols.hpp>
#include <pwb/cartography/scalar_style.hpp>
#include <pwb/cartography/vector_style.hpp>
#include <pwb/domain/json.hpp>

#include <optional>
#include <string>

namespace pwb::cartography {

using Json = pwb::domain::Json;

// ---- scalar renderer payload (bridge build_scalar_renderer_xml input) ------

struct ScalarRendererStats {
    std::vector<double> values;    // raw grid values (finite filter applied here)
    std::optional<double> min;     // explicit stats override the data scan
    std::optional<double> max;
};

// encode_scalar_renderer_xml payload assembly (same field order; the XML
// itself is authored by the C++ bridge from this payload). Degenerate spans
// widen max to min + 1 exactly like the Python entry point.
Json scalar_renderer_payload(const ScalarStyleSpec& spec,
                             const ScalarRendererStats& stats,
                             const std::string& crs);

// ---- legacy vector style -> bridge spec dict ---------------------------------

// VectorStyle.to_dict() shape with the bridge's alias keys (renderer_kind,
// classification_field); labels keep the flat label_* names the bridge's
// apply_label_style reads after _flatten_qgis_style.
Json legacy_renderer_style(const VectorStyle& style);

// A geological symbol's renderer_hint as a bridge spec dict: categorized
// symbols emit classification_field + rules (name/expression/label/
// fill|stroke/stroke_width), single symbols emit the flat fallback style.
Json symbol_renderer_spec(const std::string& symbol_id);

// ---- persisted style flattening -----------------------------------------------

// Port of map_render_backend._flatten_qgis_style: promote a non-blank
// qgis_style.renderer_xml / labeling_xml to top level, convert label size
// px->pt (x72/96), add buffer mm (x25.4/96) from a non-zero halo_width when
// no explicit buffer exists, fall back buffer_color <- halo_color, and drop
// the qgis_style key. Non-object inputs pass through unchanged.
Json flatten_qgis_style(const Json& style);

// ---- authoritative payload model (qgis_style.QgisStylePayload) -------------------

inline constexpr long long kQgisStyleSchemaVersion = 1;

struct QgisStylePayload {
    std::string renderer_xml;   // required non-blank
    std::string labeling_xml;
    std::string name;
    std::vector<std::string> tags;
    long long revision = 1;
    long long schema_version = kQgisStyleSchemaVersion;

    // Throws std::invalid_argument with the Python __post_init__ messages
    // when renderer_xml is blank or schema_version is not the current one
    // (revision itself is not validated here — Python clamps it on load).
    void validate() const;
    QgisStylePayload bumped() const;
    Json to_dict() const;
    // Tolerant parse; nullopt for absent payloads (Python from_dict -> None).
    static std::optional<QgisStylePayload> from_dict(const Json& data);
};

}  // namespace pwb::cartography
