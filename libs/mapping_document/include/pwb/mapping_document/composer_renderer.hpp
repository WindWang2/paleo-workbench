#pragma once

// Native composer SVG renderer (V14-COMPILATION-PUBLISH).
//
// Faithful port of paleo_workbench/mapping/composer/renderer.py
// (MapComposerRenderer.render_to_svg) — the composition preview/export
// vector engine that #1433 left unwired (the panel's honest
// "预览渲染失败" surface).
//
// Output contract (frozen by tools/oracle/generate_composer_fixtures.py):
//   * SVG root: viewBox="0 0 {width_mm} {height_mm}" (millimetre scene),
//     width/height in px at the 96-DPI authoring baseline
//     (1mm = 3.7795275591px);
//   * white page rect with a #333 0.5mm frame first, then every visible
//     element in stable z_index order, locked elements followed by the
//     blue corner marker;
//   * all user text html-escaped; numbers follow the Python formatting
//     regime (%.2f geometry, :g value labels, repr-shortest floats);
//   * unbound components render honest dashed placeholders — the engine
//     never fabricates map content.
//
// Live-content seams (the host supplies what JSON cannot carry — the
// live map document of the mapping page). A seam that is absent, or
// returns "not bound", degrades exactly like Python's unbound branches:
//   * frame_content  — MAIN_MAP / INSET_MAP / PROFILE raster or vector
//     fragments (mm page space);
//   * legend_entries — live-layer legend extraction (order is the host's
//     canonical layer order);
//   * palette_stops  — colour-ramp resolution for COLORBAR (absent ⇒ the
//     documented 2-stop default).
// Elements carrying pure-JSON dict layers + extent render through the
// kernel's own vector path (Python renderer branch 3).
//
// Qt-free, Python-free.

#include <pwb/mapping_document/composition.hpp>

#include <array>
#include <functional>
#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace pwb::mapping_document {

// One legend entry (renderers.py LegendItem subset used by the SVG legend).
struct ComposerLegendEntry {
    std::string label;
    std::string color = "#4fc3f7";
    std::string symbol_type = "polygon";  // polygon | line | point | gradient
    std::string stroke_color = "#333333";
    double stroke_width = 0.5;
    // gradient stops: array of [pos, color] pairs (pos in 0..1).
    Json gradient_stops;  // array payload (may be null/empty)
};

// Live-content seams for map frames (see file header).
struct ComposerRenderSeams {
    struct FrameContent {
        bool bound = false;
        // Raster content: base64 PNG (no data-URI prefix), drawn inside
        // the frame with preserveAspectRatio="xMidYMid meet".
        std::string png_b64;
        // Vector fragments already in page millimetres (z-ordered).
        std::vector<std::string> svg_fragments;
        // Extent actually rendered (map CRS); used for parity assertions.
        std::array<double, 4> extent{0.0, 0.0, 0.0, 0.0};
        bool has_extent = false;
    };
    std::function<FrameContent(const ComposerElement& map_frame)> frame_content;

    std::function<std::vector<ComposerLegendEntry>(const ComposerElement& element)>
        legend_entries;

    using ColorStops = std::vector<std::pair<double, std::string>>;
    std::function<bool(const std::string& ramp_name, ColorStops& stops)> palette_stops;
};

// Render one composition document to a complete SVG document string.
// Never throws for missing content (honest placeholders instead).
[[nodiscard]] std::string render_composition_to_svg(
    const Composition& doc, const ComposerRenderSeams& seams = {});

// Re-anchor the authoring SVG's physical size (export.py
// _composition_svg): the viewBox stays in mm; the width/height attributes
// become "{mm}mm" so the exported page is physically sized.
[[nodiscard]] std::string reanchor_composition_svg(const std::string& svg,
                                                   double width_mm,
                                                   double height_mm);

// The 96-DPI authoring baseline (25.4 / 96 mm per logical pixel) and the
// px-per-mm fold — exposed so hosts and tests share the exact constants.
inline constexpr double kComposerMmPerLogicalPx = 25.4 / 96.0;
inline constexpr double kComposerPxPerMm = 3.7795275591;

}  // namespace pwb::mapping_document
