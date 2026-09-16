#pragma once

// LayoutService — layout export (PNG/PDF/SVG) from the session's live
// layer tree (same QgsProject as canvas/legend; no second map document).
// Honest failure: missing capability or export error returns a reason and
// removes partial files; no faked success.

#include <filesystem>
#include <string>
#include <vector>

namespace pwb::qgis {

class MapSession;

struct LayoutMapSpec {
    double x_mm = 0.0, y_mm = 0.0, w_mm = 200.0, h_mm = 150.0;
    std::string crs;                    // "" = project CRS
    double extent[4] = {0, 0, 0, 0};    // xmin,ymin,xmax,ymax; all zero = auto
};

struct LayoutSpec {
    double page_width_mm = 297.0;
    double page_height_mm = 210.0;
    std::string background = "#ffffff";
    LayoutMapSpec map;
    bool include_legend = true;
    double legend_x_mm = 10.0;
    double legend_y_mm = 10.0;
};

class LayoutService {
public:
    explicit LayoutService(MapSession& session);

    // format: "png"|"pdf"|"svg". Returns "" on success (file exists and is
    // non-empty), else the reason.
    std::string export_layout(const LayoutSpec& spec,
                              const std::filesystem::path& output_path,
                              const std::string& format, double dpi);

private:
    MapSession& session_;
};

}  // namespace pwb::qgis
