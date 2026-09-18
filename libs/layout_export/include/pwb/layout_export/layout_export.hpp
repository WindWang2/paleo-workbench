// Qt-free layout-export kernel (CONV-27).
//
// Port of the composition → layout-spec behavior layer that CONV-02
// explicitly deferred (ledger 02-decisions.md D-01):
//   paleo_workbench/mapping/layout_export.py — build_layout_spec,
//   hybrid_element_types, the legend-backed mirror gates, the export pixel
//   budget and LayoutExportReport. The C++ document model is the CONV-02
//   kernel's pwb::mapping_document::Composition (same wire contract as
//   MapCompositionDocument), so no second composition authority exists.
//
// Behavior parity with Python is frozen by tools/oracle/
// generate_layout_export_fixtures.py and replayed in layout_export_tests.
// Documented deviations (27-decisions.md):
//   * D-03: no composer SVG fallback engine — when the Python path would
//     degrade to composer_fallback the C++ orchestration returns an honest
//     ok=false report (failure diagnostics) instead of a second renderer;
//   * D-04: mirror_layers JSON accepts null / layer array / {"layers":[..]}
//     (the only shapes that exist on the JSON wire).
#pragma once

#include <pwb/domain/json.hpp>
#include <pwb/mapping_document/composition.hpp>

#include <array>
#include <filesystem>
#include <functional>
#include <string>
#include <vector>

namespace pwb::layout_export {

using Json = pwb::domain::Json;
using pwb::mapping_document::Composition;
using pwb::mapping_document::ComposerElement;

// ---------------------------------------------------------------------------
// Element classification (layout_export.py tables, keyed by element_type
// value strings; unknown values fall through every bucket = fail-closed).
// ---------------------------------------------------------------------------

// Wire type for natively mapped elements, or "" when the type is not native
// (hybrid / legend-backed / unknown). GRID folds into the linked map item.
std::string native_wire_type(const std::string& element_type);

bool is_hybrid_type(const std::string& element_type);
bool is_legend_backed_type(const std::string& element_type);

// Hard hybrid boundary, itemized: timescale, inset_map, stat_chart, profile,
// fault_symbols, lithology_legend.
const std::vector<std::string>& hybrid_type_names();

// ---------------------------------------------------------------------------
// Mirror description (the render snapshot shared by screen and export).
// Layer entries read {id, layer_type, style{renderer}}; a missing/empty
// field behaves like Python's `_layer_field(..., "")`.
// ---------------------------------------------------------------------------

struct MirrorLayer {
    std::string id;
    std::string layer_type;
    Json style;  // object payload (may be null/non-object)
};

// null → {} · array → itself · object with "layers" array → that array ·
// everything else → {} (D-04).
std::vector<MirrorLayer> normalize_mirror_layers(const Json& mirror_layers);

// COLORBAR needs a scalar_grid layer; FACIES_LEGEND polygon/facies or a
// categorized vector surface; WELL_LEGEND well_point/well.
bool mirror_proves(const std::string& element_type,
                   const std::vector<MirrorLayer>& mirror);

// The proven legend-backed element types (subset of
// {colorbar, facies_legend, well_legend}), Python sort order.
std::vector<std::string> legend_backed_types(
    const std::vector<MirrorLayer>& mirror);

// doc_id include list for a legend-backed element's filter_layers wire key
// (empty = no filtering = list every layer of the linked map).
std::vector<std::string> legend_filter_doc_ids(
    const std::string& element_type, const std::vector<MirrorLayer>& mirror);

// ---------------------------------------------------------------------------
// Spec building (build_layout_spec).
// ---------------------------------------------------------------------------

struct BuildSpecInput {
    std::array<double, 4> map_extent{0.0, 0.0, 0.0, 0.0};  // xmin,ymin,xmax,ymax
    std::string crs;  // "" = project CRS (Python crs=None)
    Json mirror_layers;  // see normalize_mirror_layers
};

// Visible (visible=true) elements in stable z_index order.
std::vector<const ComposerElement*> visible_elements(const Composition& doc);

// Sorted distinct element_type values of visible elements with no native
// counterpart under the mirror description (unproven legend-backed types
// count). This is the report's hybrid_items list.
std::vector<std::string> hybrid_element_types(
    const Composition& doc, const Json& mirror_layers);

// Throws std::invalid_argument with the Python message when a visible
// element cannot map natively, has a non-positive extent, or an IMAGE has
// no image_path. Warnings (when the pointer is non-null) receive the exact
// Python warning strings. Returns {"page":{width_mm,height_mm},"items":[..]}.
Json build_layout_spec(const Composition& doc, const BuildSpecInput& input,
                       std::vector<std::string>* warnings);

// ---------------------------------------------------------------------------
// Export pixel budget (layout_export.py MAX_EXPORT_PIXELS contract).
// ---------------------------------------------------------------------------

constexpr double kMaxExportPixels = 200000000.0;  // ~A0 @ 600 dpi x 0.5

// Throws std::invalid_argument (exact Python message, %g formatting)
// when page_mm / 25.4 * dpi exceeds the budget. A budget breach is a caller
// error, never an engine fallback.
void check_pixel_budget(const Composition& doc, double dpi);

// ---------------------------------------------------------------------------
// Report (LayoutExportReport — key-for-key parity + C++ superset).
// ---------------------------------------------------------------------------

struct LayoutExportReport {
    std::string engine;  // "qgis_layout" | "composer_fallback" (Python shapes)
    std::string path;
    std::string format;
    double dpi = 0.0;
    bool ok = false;
    std::vector<std::string> warnings;
    std::vector<std::string> unmapped_elements;  // hybrid element ids
    long long items = 0;
    std::vector<std::string> hybrid_items;  // hybrid element TYPES
    // C++ superset (27-decisions.md D-06): failure diagnostics + page
    // dimensions; empty/0 when not applicable.
    std::string failure;
    long long width_px = 0;
    long long height_px = 0;
    // doc_id include lists actually emitted for legend items, by legend title.
    Json filter_layers;  // object title → array

    Json to_dict() const;
};

// ---------------------------------------------------------------------------
// Orchestration (export_composition_reported).
// ---------------------------------------------------------------------------

struct ExportRequest {
    std::string format = "pdf";  // pdf|svg|png
    double dpi = 300.0;
    bool geo_pdf = false;
    // C++ executor extension: force vector output for pdf/svg (no raster
    // fallback layers). Emitted as the spec root key "force_vector".
    bool force_vector = false;
    bool has_map_extent = false;
    std::array<double, 4> map_extent{0.0, 0.0, 0.0, 0.0};
    std::string crs;
    Json mirror_layers;
};

// The native layout executor: consumes the spec JSON and writes the file.
// Returns the bridge report JSON {ok,path,format,dpi,items,...}; throws on
// failure (the bridge contract — partial files are removed by the executor).
using LayoutExecutor = std::function<Json(
    const std::string& spec_json, const std::string& output_path,
    const std::string& format, double dpi)>;

// Python-faithful flow with the documented D-03 deviations: pixel budget
// first (throws — caller error), hybrid boundary itemized up front, spec
// build, executor call. Every path that Python would route to the composer
// SVG renderer returns ok=false with the SAME warnings text plus a `failure`
// reason — never a second engine, never a partial product.
LayoutExportReport export_composition_reported(
    const Composition& doc, const std::filesystem::path& output_path,
    const ExportRequest& request, const LayoutExecutor* executor);

// ---------------------------------------------------------------------------
// Screen/export parity (27-decisions.md D-07).
// State shape (both sides): {"extent":[xmin,ymin,xmax,ymax], "crs": str,
//   "layers":[{"id":str,"visible":bool}...],   // top-first
//   "grid":{"enabled":bool,"interval_x":num,"interval_y":num}, "legend":bool}
// Aspects compared: extent, crs, layer order (visible ids), visibility,
// grid, legend. Style/annotation rendering is by construction (shared
// QgsProject layer instances) and disclosed in the result.
// ---------------------------------------------------------------------------

struct ParityAspect {
    bool equal = true;
    std::string detail;
};

struct ParityReport {
    bool equal = true;
    ParityAspect extent;
    ParityAspect crs;
    ParityAspect layer_order;
    ParityAspect visibility;
    ParityAspect grid;
    ParityAspect legend;
    std::vector<std::string> diffs;

    Json to_dict() const;
};

// Tolerances: exact for strings/bools/orders; 1e-9 absolute + 1e-9 relative
// for extent/interval doubles.
ParityReport screen_export_parity(const Json& canvas_state,
                                  const Json& export_state);

// Materialises the built-in north indicator SVG (needle + N) into the
// machine temp dir (pwb_north_arrow.svg), byte-identical to the Python
// literal. Returns "" when the filesystem refuses (same as Python).
std::string north_arrow_svg_path();

}  // namespace pwb::layout_export
