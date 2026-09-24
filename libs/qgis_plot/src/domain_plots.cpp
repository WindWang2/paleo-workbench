#include "pwb/qgis_plot/domain_plots.hpp"

#include <cmath>

#include <QPainter>

#include <qgsplot.h>
#include <qgsrendercontext.h>
// Qgs2DPlot/Qgs2DXyPlot live in qgsplot.h (QGIS 4.2).

namespace pwb::qgis_plot {

namespace {

QColor rampColor(const QVector<QColor>& stops, double t) {
    if (stops.isEmpty())
        return QColor(70, 70, 70);
    if (stops.size() == 1)
        return stops.first();
    t = std::clamp(t, 0.0, 1.0);
    const double pos = t * (stops.size() - 1);
    const int i = static_cast<int>(pos);
    if (i >= stops.size() - 1)
        return stops.last();
    const double f = pos - i;
    const QColor& a = stops[i];
    const QColor& b = stops[i + 1];
    return QColor::fromRgbF(a.redF() + (b.redF() - a.redF()) * f,
                            a.greenF() + (b.greenF() - a.greenF()) * f,
                            a.blueF() + (b.blueF() - a.blueF()) * f);
}

// Shared data->painter mapping, mirroring QgsLineChartPlot::renderContent.
// Returns false when the point is non-finite or out of categories.
inline bool mapPoint(const Qgs2DXyPlot& plot, const QRectF& plot_area,
                     double px, double py, QPointF& out) {
    const double min_x = plot.xMinimum(), max_x = plot.xMaximum();
    const double min_y = plot.yMinimum(), max_y = plot.yMaximum();
    if (!std::isfinite(px) || !std::isfinite(py) || max_x == min_x ||
        max_y == min_y)
        return false;
    const double fx = (px - min_x) / (max_x - min_x);
    const double fy = (py - min_y) / (max_y - min_y);
    if (plot.flipAxes())
        out = {plot_area.x() + fy * plot_area.width(),
               plot_area.bottom() - fx * plot_area.height()};
    else
        out = {plot_area.x() + fx * plot_area.width(),
               plot_area.y() + plot_area.height() - fy * plot_area.height()};
    return true;
}

}  // namespace

void PwbScatterPlot::setSeriesColors(const QList<QColor>& colors) {
    series_colors_ = colors;
}

void PwbScatterPlot::setSeriesZValues(int series_index,
                                      const QVector<double>& z, double zmin,
                                      double zmax, const QVector<QColor>& stops) {
    if (z.isEmpty()) {
        z_ramps_.remove(series_index);
        return;
    }
    ZRamp ramp;
    ramp.z = z;
    ramp.zmin = zmin;
    ramp.zmax = zmax > zmin ? zmax : zmin + 1.0;
    ramp.stops = stops;
    z_ramps_[series_index] = ramp;
}

void PwbScatterPlot::clearSeriesZValues(int series_index) {
    z_ramps_.remove(series_index);
}

void PwbScatterPlot::setPointLabels(int series_index,
                                    const QStringList& labels) {
    if (labels.isEmpty())
        labels_.remove(series_index);
    else
        labels_[series_index] = labels;
}

void PwbScatterPlot::setSeriesLine(int series_index, bool on,
                                   double width_px) {
    if (on)
        lines_[series_index] = {true, width_px};
    else
        lines_.remove(series_index);
}

void PwbScatterPlot::setSeriesMarkers(int series_index, bool on) {
    if (on)
        markers_off_.remove(series_index);
    else
        markers_off_[series_index] = true;
}

QColor PwbScatterPlot::colorFor(int series_index, int point_index) const {
    const auto ramp = z_ramps_.constFind(series_index);
    if (ramp != z_ramps_.constEnd() && point_index < ramp->z.size()) {
        const double z = ramp->z[point_index];
        if (std::isfinite(z))
            return rampColor(ramp->stops,
                             (z - ramp->zmin) / (ramp->zmax - ramp->zmin));
        return QColor(160, 160, 160);
    }
    if (series_index < series_colors_.size())
        return series_colors_[series_index];
    return QColor(70, 70, 70);
}

void PwbScatterPlot::renderContent(QgsRenderContext& rc,
                                   QgsPlotRenderContext&,
                                   const QRectF& plot_area,
                                   const QgsPlotData& plot_data) {
    const QList<QgsAbstractPlotSeries*> series = plot_data.series();
    if (series.isEmpty())
        return;
    QPainter* painter = rc.painter();
    if (!painter)
        return;
    painter->save();
    painter->setClipRect(plot_area);
    painter->setRenderHint(QPainter::Antialiasing);
    const double r = marker_px_ * 0.5;
    for (int i = 0; i < series.size(); ++i) {
        const auto* xy = dynamic_cast<const QgsXyPlotSeries*>(series[i]);
        if (!xy)
            continue;
        const auto data = xy->data();
        const QStringList* labels = nullptr;
        const auto lit = labels_.constFind(i);
        if (lit != labels_.constEnd())
            labels = &lit.value();
        const bool draw_markers = !markers_off_.value(i, false);
        const auto line_it = lines_.constFind(i);
        if (line_it != lines_.constEnd() && line_it->enabled) {
            const QColor c = i < series_colors_.size()
                                 ? series_colors_[i]
                                 : QColor(70, 70, 70);
            painter->setPen(QPen(c, line_it->width_px));
            painter->setBrush(Qt::NoBrush);
            QPolygonF segment;
            for (int j = 0; j < data.size(); ++j) {
                QPointF pt;
                if (!mapPoint(*this, plot_area, data[j].first,
                              data[j].second, pt)) {
                    if (segment.size() > 1)
                        painter->drawPolyline(segment);
                    segment.clear();
                    continue;
                }
                segment << pt;
            }
            if (segment.size() > 1)
                painter->drawPolyline(segment);
        }
        if (!draw_markers && !labels)
            continue;
        for (int j = 0; j < data.size(); ++j) {
            QPointF pt;
            if (!mapPoint(*this, plot_area, data[j].first, data[j].second, pt))
                continue;
            if (draw_markers) {
                painter->setPen(Qt::NoPen);
                painter->setBrush(colorFor(i, j));
                painter->drawEllipse(pt, r, r);
            }
            if (labels && j < labels->size() && !labels->at(j).isEmpty()) {
                painter->setPen(QColor(60, 60, 60));
                painter->drawText(pt + QPointF(r + 3, -r),
                                  labels->at(j));
            }
        }
    }
    painter->restore();
}

void PwbRangeBandPlot::renderContent(QgsRenderContext& rc,
                                     QgsPlotRenderContext&,
                                     const QRectF& plot_area,
                                     const QgsPlotData& plot_data) {
    const QList<QgsAbstractPlotSeries*> series = plot_data.series();
    if (series.size() < 2)
        return;
    QPainter* painter = rc.painter();
    if (!painter)
        return;
    painter->save();
    painter->setClipRect(plot_area);
    painter->setRenderHint(QPainter::Antialiasing);
    // Pairwise: series 2k = lower bound, series 2k+1 = upper bound. A
    // non-finite pair on either side breaks the band (missing-section gap).
    for (int i = 0; i + 1 < series.size(); i += 2) {
        const auto* lo = dynamic_cast<const QgsXyPlotSeries*>(series[i]);
        const auto* hi = dynamic_cast<const QgsXyPlotSeries*>(series[i + 1]);
        if (!lo || !hi)
            continue;
        const auto lo_data = lo->data();
        const auto hi_data = hi->data();
        const int n = std::min(lo_data.size(), hi_data.size());
        QPolygonF lo_pts, hi_pts;
        auto flush = [&] {
            const QPolygonF band = lo_pts + hi_pts;
            if (band.size() >= 3) {
                QColor fill = color_;
                fill.setAlpha(60);
                painter->setPen(Qt::NoPen);
                painter->setBrush(fill);
                painter->drawPolygon(band);
            }
            painter->setPen(QPen(color_, 1.0));
            painter->setBrush(Qt::NoBrush);
            if (lo_pts.size() > 1)
                painter->drawPolyline(lo_pts);
            if (hi_pts.size() > 1)
                painter->drawPolyline(hi_pts);
            lo_pts.clear();
            hi_pts.clear();
        };
        for (int j = 0; j < n; ++j) {
            QPointF plo, phi;
            const bool ok =
                mapPoint(*this, plot_area, lo_data[j].first,
                         lo_data[j].second, plo) &&
                mapPoint(*this, plot_area, hi_data[j].first,
                         hi_data[j].second, phi);
            if (!ok) {
                flush();
                continue;
            }
            lo_pts << plo;
            hi_pts.prepend(phi);  // upper edge walks back down x
        }
        flush();
    }
    painter->restore();
}

}  // namespace pwb::qgis_plot

namespace pwb::qgis_plot {

void PwbIntervalStripPlot::setBands(QVector<IntervalBand> bands) {
    bands_ = std::move(bands);
}

void PwbIntervalStripPlot::renderContent(QgsRenderContext& rc,
                                         QgsPlotRenderContext&,
                                         const QRectF& plot_area,
                                         const QgsPlotData&) {
    QPainter* painter = rc.painter();
    if (!painter)
        return;
    painter->save();
    painter->setClipRect(plot_area);
    const double y_min = yMinimum(), y_max = yMaximum();
    const double span = y_max - y_min;
    if (span == 0.0) {
        painter->restore();
        return;
    }
    // Data y = -depth: band [top,bottom] -> y in [-bottom,-top].
    auto y_of = [&](double depth) {
        return plot_area.y() + plot_area.height() *
               (1.0 - ((-depth) - y_min) / span);
    };
    for (const IntervalBand& band : bands_) {
        const double y0 = y_of(band.top);
        const double y1 = std::max(y0 + 2.0, y_of(band.bottom));
        const QRectF target(plot_area.left() + 2, y0,
                            plot_area.width() - 4, y1 - y0);
        QColor fill = band.color;
        fill.setAlpha(band.alpha);
        painter->fillRect(target, fill);
        painter->setPen(QPen(band.color.darker(120), 1.0));
        painter->setBrush(Qt::NoBrush);
        painter->drawRect(target);
        if (!band.label.isEmpty()) {
            painter->setPen(QColor(0x25, 0x31, 0x3d));
            painter->drawText(target, Qt::AlignHCenter | Qt::AlignVCenter,
                              band.label);
        }
    }
    painter->restore();
}

}  // namespace pwb::qgis_plot
