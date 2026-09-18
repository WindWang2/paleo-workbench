// Qt-free map template library (CONV-27).
//
// Port + extension of paleo_workbench/mapping/geological_pipeline/templates.py.
// The factor-map factory is Python-parity (oracle-frozen geometry); the
// facies/prediction/constraint/comprehensive factories are C++-authored
// compositions built from the SAME page/component vocabulary (D-4):
//
//   TemplatePage        — reusable page geometry (paper, margins, title rail,
//                         legend rail, dpi);
//   component builders  — add_title_block / add_subtitle / add_main_map /
//                         add_north_arrow / add_scale_bar / add_legend_rail /
//                         add_colorbar / add_datasource, each appending one
//                         pwb::mapping_document::ComposerElement with the
//                         established element ids and z-order;
//   template factories  — five standard map compositions assembled from the
//                         components above.
//
// Element properties stay JSON-safe: a nested map document is serialized as
// the composer stub {"__ref__": "map_document", "id", "layer_count"}
// (composer/models._serialize_property_value), never as a full document.
#pragma once

#include <pwb/cartography/color_ramps.hpp>
#include <pwb/mapping_document/composition.hpp>
#include <pwb/mapping_document/map_document.hpp>
#include <pwb/domain/json.hpp>

#include <array>
#include <optional>
#include <string>
#include <vector>

namespace pwb::cartography {

using Json = pwb::domain::Json;
using pwb::mapping_document::Composition;
using pwb::mapping_document::ComposerElement;

// ---- reusable page geometry ------------------------------------------------

struct TemplatePage {
    std::string paper_size = "A4";
    std::string orientation = "landscape";
    double width_mm = 297.0;
    double height_mm = 210.0;
    double margin_x_mm = 12.0;
    double margin_y_mm = 10.0;
    double title_height_mm = 14.0;
    double legend_width_mm = 45.0;
    double legend_max_height_mm = 80.0;
    double dpi = 300.0;

    // templates.py geometry: A4 landscape 297x210 / portrait 210x297.
    static TemplatePage a4(const std::string& paper_size,
                           const std::string& orientation);
    // Main-map rectangle: full width minus margins minus the legend rail.
    std::array<double, 4> main_map_rect() const;  // {x, y, w, h}
    std::array<double, 4> legend_rect() const;
};

// ---- component builders (append one element each) ---------------------------

// z=10 TITLE element with {"text": text}.
void add_title_block(Composition& doc, const TemplatePage& page,
                     const std::string& text);
// z=9 SUBTITLE element (C++ component vocabulary extension).
void add_subtitle(Composition& doc, const TemplatePage& page,
                  const std::string& text);
// z=1 MAIN_MAP element holding the composer stub of the map document plus
// its extent.
void add_main_map(Composition& doc, const TemplatePage& page,
                  const std::string& map_document_id,
                  long long map_layer_count,
                  const std::array<double, 4>& extent);
// z=15 NORTH_ARROW in the map's upper-left corner (10x14 mm offset 5,5).
void add_north_arrow(Composition& doc, const TemplatePage& page);
// z=15 SCALE_BAR in the map's lower-left corner (30x8 mm); length_km is
// max(5, int(span/4)) when span > 10 else 10.
void add_scale_bar(Composition& doc, const TemplatePage& page,
                   double extent_x_span);
// z=10 LEGEND rail to the right of the map (45 mm wide, <= 80 mm high).
void add_legend_rail(Composition& doc, const TemplatePage& page);
// z=11 COLORBAR under the legend rail (C++ component extension); the
// ramp/factor vocabulary rides the properties dict verbatim.
void add_colorbar(Composition& doc, const TemplatePage& page,
                  const std::string& title, const std::string& units,
                  double vmin, double vmax);
// z=12 DATASOURCE footnote strip along the bottom (C++ component extension).
void add_datasource(Composition& doc, const TemplatePage& page,
                    const std::string& text);

// ---- input description --------------------------------------------------------

// Host-side description of the map document a template is instantiated from.
// The composer stub keeps only (id, layer_count); nothing else crosses.
struct TemplateMapInput {
    std::string map_document_id;
    std::string map_document_title;
    long long map_layer_count = 0;
    std::array<double, 4> extent{0.0, 0.0, 1.0, 1.0};
};

struct TemplateRequest {
    std::string template_name;  // see template_catalog()
    TemplateMapInput map;
    std::string title;        // optional; falls back to map title / default
    std::string factor_name;
    std::string unit;
    std::string paper_size = "A4";
    std::string orientation = "landscape";
};

// ---- template factories -------------------------------------------------------

// Python-parity factory (templates.create_geological_factor_map_template):
// title + main map + north arrow + scale bar + legend.
Composition geological_factor_map_template(const TemplateRequest& request);
// C++-authored variants sharing the same components: facies legend block,
// prediction colorbar, constraint fault-symbol block, comprehensive union.
Composition facies_map_template(const TemplateRequest& request);
Composition prediction_map_template(const TemplateRequest& request);
Composition constraint_map_template(const TemplateRequest& request);
Composition comprehensive_map_template(const TemplateRequest& request);

// ---- product API -----------------------------------------------------------------

// The template catalog: [{"name", "title", "description"}] in registry
// order (5 standard maps).
Json template_catalog();

// Resolve a catalog name to its factory; throws std::out_of_range for
// unknown names.
Composition instantiate_template(const TemplateRequest& request);

}  // namespace pwb::cartography
