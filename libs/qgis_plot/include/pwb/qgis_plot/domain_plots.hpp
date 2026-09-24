// QGIS-plot convergence — Paleo-specific Qgs2DPlot content renderers.
//
// These are domain content plots: they reuse every stock Qgs2DXyPlot
// capability (axes, grid, border, intervals, extent math, export render) and
// only override renderContent() where stock Qgs*Plot classes cannot express
// the requirement:
//   * PwbScatterPlot — marker-only scatter with per-point z-ramp colouring
//     and optional per-point labels (cross-plot needs both; stock
//     QgsLineChartPlot colours per-series only).
//
// If upstream grows equivalent items, these classes shrink or go away.
#pragma once

#include <QColor>
#include <QRectF>
#include <QStringList>
#include <QVector>

#include <qgsplot.h>

class QgsPlotRenderContext;
class QgsRenderContext;

namespace pwb::qgis_plot {

class PwbScatterPlot : public Qgs2DXyPlot {
public:
    // Flat marker colour per series (fallback when no z values bound).
    void setSeriesColors(const QList<QColor>& colors);
    // Per-point scalar colouring for one series: z values are index-aligned
    // with the series' data; colours come from a linear ramp over `stops`
    // spanning [zmin, zmax]. Pass empty z to clear.
    void setSeriesZValues(int series_index, const QVector<double>& z,
                          double zmin, double zmax,
                          const QVector<QColor>& stops);
    void clearSeriesZValues(int series_index);
    // Optional label drawn beside each point (index-aligned). Empty clears.
    void setPointLabels(int series_index, const QStringList& labels);
    void setMarkerSizePx(double px) { marker_px_ = px; }
    // Per-series geometry: markers default ON, connecting line default OFF.
    // Line segments break at non-finite pairs.
    void setSeriesLine(int series_index, bool on, double width_px = 1.4);
    void setSeriesMarkers(int series_index, bool on);

    // Scatter semantics: points never connect, so NaN gaps are meaningless.
    void renderContent(QgsRenderContext& rc, QgsPlotRenderContext& context,
                       const QRectF& plot_area,
                       const QgsPlotData& plot_data) override;

private:
    QColor colorFor(int series_index, int point_index) const;
    struct ZRamp {
        QVector<double> z;
        double zmin = 0.0, zmax = 1.0;
        QVector<QColor> stops;
    };
    struct LineStyle {
        bool enabled = false;
        double width_px = 1.4;
    };
    QList<QColor> series_colors_;
    QHash<int, ZRamp> z_ramps_;
    QHash<int, QStringList> labels_;
    QHash<int, LineStyle> lines_;
    QHash<int, bool> markers_off_;
    double marker_px_ = 4.0;
};

// Min-max range band: series come in pairs (lower, upper); the filled band
// between them plus outline is drawn (well-log per-column value envelopes).
class PwbRangeBandPlot : public Qgs2DXyPlot {
public:
    void setBandColor(const QColor& color) { color_ = color; }

    void renderContent(QgsRenderContext& rc, QgsPlotRenderContext& context,
                       const QRectF& plot_area,
                       const QgsPlotData& plot_data) override;

private:
    QColor color_ = QColor(0x1d, 0x4e, 0xd8);
};

// Depth-interval strip: labelled coloured bands spanning [top,bottom] along
// a (negated) depth axis — the stratigraphic/QC column primitive. Feed the
// plot data coords as y = -depth so increasing depth renders downward.
class PwbIntervalStripPlot : public Qgs2DXyPlot {
public:
    struct IntervalBand {
        double top = 0.0;     // depth, shallow edge
        double bottom = 0.0;  // depth, deep edge
        QString label;
        QColor color;
        int alpha = 140;      // fill alpha (border uses opaque color)
    };

    void setBands(QVector<IntervalBand> bands);

    void renderContent(QgsRenderContext& rc, QgsPlotRenderContext& context,
                       const QRectF& plot_area,
                       const QgsPlotData& plot_data) override;

private:
    QVector<IntervalBand> bands_;
};

}  // namespace pwb::qgis_plot
