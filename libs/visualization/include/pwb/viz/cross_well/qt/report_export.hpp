#pragma once

// VIZ-B — publication report export for the cross-well section.
// Port of geoviz_cross_well/report_export.py: page-size table
// (A4/A3/A2 landscape default), 15 mm margins, 12 mm title block, 15 mm
// legend strip, 10%-tick grid frame, content = the section painted via
// the SAME paint_section entry the screen uses (no parallel renderer).

#include <QString>

#include <pwb/viz/cross_well/qt/section_canvas.hpp>

namespace pwb::viz::cross_well::qt {

struct CrossWellReportOptions {
    QString page_size = QStringLiteral("A4");  // A4 | A3 | A2
    bool portrait = false;
    int dpi = 300;
    bool include_legend = true;
    bool include_grid_frame = true;
    QString title = QStringLiteral("井间对比剖面图");
};

// Export the publication report (pdf via QPrinter, svg via QSvgGenerator,
// png via QImage). Returns false when no wells are in the scene or the
// device cannot be written. The painted content carries the data
// identity (well names, formation names, depths, TWT axis).
bool export_cross_well_report(const SectionScene& scene,
                              const QString& output_path,
                              const CrossWellReportOptions& options = {});

}  // namespace pwb::viz::cross_well::qt
