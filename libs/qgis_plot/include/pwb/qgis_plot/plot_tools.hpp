// QGIS-plot convergence — interactive tools on top of QgsPlotTool.
//
// QgsPlotToolPan / QgsPlotToolZoom / the transient tools are stock QGIS and
// are used unmodified. This header only carries what upstream does not ship:
//   * PwbPlotToolXAxisZoom — QgsPlotToolZoom with full-height constrained
//     marquee (upstream QgsPlotToolXAxisZoom is hard-bound to
//     QgsElevationProfileCanvas and cannot be reused).
//   * PwbPlotToolIdentify — click pick + rectangle identify over series
//     points, resolved to PointHit domain references.
//   * PwbPlotToolLasso — freehand polygon selection (cross-plot brushing);
//     the polygon is reported in canvas coordinates, conversion to data
//     space is the canvas'/consumer's job.
#pragma once

#include <QList>
#include <QPolygonF>

#include <qgsplottool.h>
#include <qgsplottoolzoom.h>

#include "pwb/qgis_plot/series_binding.hpp"

class QGraphicsPolygonItem;

namespace pwb::qgis_plot {

class PwbPlotCanvas;

class PwbPlotToolXAxisZoom : public QgsPlotToolZoom {
    Q_OBJECT
public:
    explicit PwbPlotToolXAxisZoom(PwbPlotCanvas* canvas);

protected:
    // Stretch the marquee to the full plot height — X-only zoom.
    QRectF constrainBounds(const QRectF& scene_bounds) const override;

private:
    PwbPlotCanvas* pwb_canvas() const;
};

class PwbPlotToolIdentify : public QgsPlotTool {
    Q_OBJECT
public:
    explicit PwbPlotToolIdentify(PwbPlotCanvas* canvas);
    ~PwbPlotToolIdentify() override;

    Qgis::PlotToolFlags flags() const override;
    void plotPressEvent(QgsPlotMouseEvent* event) override;
    void plotMoveEvent(QgsPlotMouseEvent* event) override;
    void plotReleaseEvent(QgsPlotMouseEvent* event) override;
    void deactivate() override;

Q_SIGNALS:
    void pointPicked(const pwb::qgis_plot::PointHit& hit);
    void identified(const QList<pwb::qgis_plot::PointHit>& hits);

private:
    PwbPlotCanvas* pwb_canvas_;
    class QgsPlotRectangularRubberBand* rubber_band_ = nullptr;
    QPoint press_pos_;
    bool dragging_ = false;
};

class PwbPlotToolLasso : public QgsPlotTool {
    Q_OBJECT
public:
    explicit PwbPlotToolLasso(PwbPlotCanvas* canvas);
    ~PwbPlotToolLasso() override;

    Qgis::PlotToolFlags flags() const override;
    void plotPressEvent(QgsPlotMouseEvent* event) override;
    void plotMoveEvent(QgsPlotMouseEvent* event) override;
    void plotReleaseEvent(QgsPlotMouseEvent* event) override;
    void deactivate() override;

Q_SIGNALS:
    // Polygon in canvas coordinates; empty when the gesture was cancelled
    // (click without drag).
    void lassoFinished(const QPolygonF& canvas_polygon);

private:
    PwbPlotCanvas* pwb_canvas_;
    QGraphicsPolygonItem* polygon_item_ = nullptr;
    QPolygonF polygon_;
    bool active_ = false;
};

}  // namespace pwb::qgis_plot
