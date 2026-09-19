#pragma once

// VIZ-B — well tie report export.
// Port of geoviz_well_tie/report_export.py: single-page A4-landscape
// PDF/SVG, title "油田井震精细标定与相关性分析报告", three-column title
// block (well/block/horizon | wavelet/R/lag | org/date/scale), "—" for
// empty values.

#include <limits>
#include <QString>

namespace pwb::viz::well_tie::qt {

struct WellTieReportInputs {
    QString well_name;
    QString block;
    QString horizon;
    QString wavelet;   // e.g. "Ricker 30 Hz"
    QString org;
    QString date_str;  // ISO; empty -> today
    // Numeric summary; NaN -> rendered as "—".
    double r_score = std::numeric_limits<double>::quiet_NaN();
    double lag_ms = std::numeric_limits<double>::quiet_NaN();
};

// Export pdf (default) or svg (by suffix). Returns false on device
// failure.
bool export_well_tie_report(const WellTieReportInputs& inputs,
                            const QString& output_path);

}  // namespace pwb::viz::well_tie::qt
