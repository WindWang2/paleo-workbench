#pragma once

// LayoutExportService — the single product export path for persistent
// layouts (docs/development/qgis-native-layout-convergence/01 §07).
//
// PDF / SVG / PNG / preview / atlas all render the *same* QgsPrintLayout
// through QgsLayoutExporter. There is no composer-SVG fallback on this
// path and no transient layout reconstruction — the layout being exported
// is the document the editor shows.

#include <pwb/domain/json.hpp>

#include <QImage>
#include <QString>

#include <string>
#include <vector>

class QgsPrintLayout;
class QgsVectorLayer;

namespace pwb::qgis {

// Same product-wide guard the retired kernel enforced (layout_export
// kMaxExportPixels): a page whose rasterisation exceeds the budget is a
// caller error, not an engine degradation.
inline constexpr double kMaxExportPixels = 2.0e8;
inline constexpr double kDefaultExportDpi = 300.0;

struct LayoutExportRequest {
    std::string output_path;
    std::string format;  // "" → derive from extension; pdf|svg|png
    double dpi = kDefaultExportDpi;
    bool force_vector = false;   // pdf/svg: no rasterised fallback layers
    bool geo_pdf = false;        // pdf: opt-in GeoPDF
};

struct LayoutExportReport {
    bool ok = false;
    std::string error;
    std::string engine = "qgis_layout";
    std::string path;
    std::string format;
    double dpi = kDefaultExportDpi;
    int pages = 1;
    long long width_px = 0;
    long long height_px = 0;
    domain::Json to_json() const;
};

// Exports `layout` (all pages for pdf/svg; page 1 for png). A failed
// export never leaves a partial file behind (never-fake contract).
LayoutExportReport export_layout(QgsPrintLayout& layout,
                                 const LayoutExportRequest& request);

// Screen-DPI preview of page 0 rendered from the same layout (preview and
// export are the same document, same engine).
QImage render_layout_preview(QgsPrintLayout& layout, double dpi = 96.0);

// ---- Atlas / batch cartography (Phase 7) ---------------------------------

struct AtlasExportRequest {
    // Coverage layer features drive the pages. When null the layout's own
    // atlas configuration is used as-is.
    QgsVectorLayer* coverage_layer = nullptr;
    std::string filter_expression;   // QgsExpression filter ("" = all)
    std::string filename_expression; // evaluated per feature ("" = index)
    std::string output_base;         // "<base>_001.pdf" style suffixed files
    std::string format = "pdf";
    double dpi = kDefaultExportDpi;
    bool hide_coverage = true;
};

struct AtlasExportReport {
    bool ok = false;
    std::string error;
    std::string engine = "qgis_layout_atlas";
    int pages = 0;
    std::vector<std::string> files;
    domain::Json to_json() const;
};

AtlasExportReport export_atlas(QgsPrintLayout& layout,
                               const AtlasExportRequest& request);

// Pixel-budget guard: page w/h (mm) at dpi must stay under kMaxExportPixels.
// Returns an error message, or "" when the budget holds.
std::string check_export_pixel_budget(double page_w_mm, double page_h_mm,
                                      double dpi);

}  // namespace pwb::qgis
