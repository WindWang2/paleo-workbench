// QGIS-plot convergence — domain binding layer.
//
// The canvas/items are generic 2-D plot infrastructure over QgsPlotCanvas;
// *what a rendered point means* lives here: every series may carry a
// SeriesBinding recording which domain objects it was built from, and every
// point may resolve to a domain id. Nothing in this header knows about
// widgets — it is plain data (QtCore types only).
#pragma once

#include <QString>
#include <QStringList>
#include <QVector>

namespace pwb::qgis_plot {

// Who a rendered series *is* in product terms. Fields are optional — fill
// what the producer knows; empty means "unbound" rather than "unknown".
struct SeriesBinding {
    QString series_id;        // stable id inside the owning panel
    QString name;             // display name (mirrors series->name())
    QString domain_object_id; // umbrella object (e.g. preview/result id)
    QString well_id;
    QString curve_id;
    QString layer_id;         // QgsMapLayer id when layer-derived
    QString version_id;
    QString run_id;
    QString track_id;         // multi-track grouping (well-log columns)
    QString unit;
    QString axis_role;        // quantity bound to the axes — "xy" |
                              // "time-depth" | "value" | "depth"
    QString style_role;       // "line" | "scatter" | "band" | "bar" | "probe"
    QVector<QString> point_domain_ids;  // optional, index-aligned to series data
};

// A resolved hit on a rendered point.
struct PointHit {
    int item_index = -1;    // which PwbPlotItem on the canvas
    int series_index = -1;  // series index inside that item's QgsPlotData
    int point_index = -1;   // index into the series' data list
    double plot_x = 0.0;
    double plot_y = 0.0;    // data coordinates (pre-mapping, as fed)
    QString series_id;      // resolved via binding (empty when unbound)
    QString domain_id;      // point_domain_ids[point_index] when present
    bool valid() const { return item_index >= 0 && series_index >= 0 && point_index >= 0; }
};

}  // namespace pwb::qgis_plot
