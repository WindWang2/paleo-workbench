#pragma once

// Internal helpers shared by the single-scene SVG exporter (svg.cpp) and the
// paginated exporter (pagination.cpp). NOT part of the public API; lives in the
// export_vector translation units only. The shared geometric emitter
// (append_defs + append_layer_body) guarantees the paginated pages use exactly
// the same per-layer emission as SvgExporter::write (ADR 0048).

#include <string>
#include <string_view>

#include <welllog/core/units.hpp>
#include <welllog/scene/scene.hpp>

namespace welllog::svg_internal {

// Appends a double using the engine's deterministic shortest-round-trip format
// (the same format every other SVG emitter uses, so paginated output matches).
void append_number(std::string &output, double value);

// Appends an integer deterministically.
void append_integer(std::string &output, std::uint64_t value);

// Appends an XML-attribute-escaped copy of `value`.
void append_xml_attribute(std::string &output, std::string_view value);

// Appends an SVG #rrggbb colour (alpha ignored — emitted separately as opacity).
void append_color(std::string &output, RgbaColor color);

// Emits the <defs> block (track clipPaths, pattern tiles, glyph outline paths).
void append_defs(std::string &output, const PreparedScene &scene);

// Emits the per-track, per-layer <g> body (the single geometric emitter shared
// by both exporters). Each track <g> is clipped to its own track clip.
void append_layer_body(std::string &output, const PreparedScene &scene);

// Appends one plain <text> element tagged with a data-export-role, used by the
// paginated exporter for synthesized page header/footer/legend strings.
void append_text_element(std::string &output, std::string_view role,
                         double x_mm, double y_mm, std::string_view body,
                         double font_size_mm = 3.0);

} // namespace welllog::svg_internal
