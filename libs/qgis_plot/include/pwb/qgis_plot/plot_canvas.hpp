// QGIS-plot convergence — the single 2-D scientific plot canvas.
//
// PwbPlotCanvas is THE QgsPlotCanvas subclass for interactive 2-D plots in
// pwb-platform. It supplies the coordinate mapping / navigation that
// QgsPlotCanvas leaves virtual (the same contract QgsElevationProfileCanvas
// implements upstream), hosts N PwbPlotItems in a column layout (well-log
// tracks), drives an ambient crosshair/hover overlay, resolves domain hits
// through SeriesBinding, and exports vectorially via Qgs2DPlot::render.
//
// It is generic infrastructure — it never knows what a series *means*;
// meaning arrives via setSeriesBindings and leaves via PointHit signals.
#pragma once

#include <memory>
#include <optional>
#include <tuple>

#include <QList>
#include <QPointF>
#include <QRectF>

#include <qgsplotcanvas.h>

#include "pwb/qgis_plot/series_binding.hpp"

class Qgs2DPlot;
class QgsPointXY;
class QMouseEvent;
class QPainter;
class QResizeEvent;
class QWheelEvent;

namespace pwb::qgis_plot {

class PwbCrosshairItem;
class PwbHGuideItem;
class PwbPlotItem;

class PwbPlotCanvas : public QgsPlotCanvas {
    Q_OBJECT
public:
    explicit PwbPlotCanvas(QWidget* parent = nullptr);
    ~PwbPlotCanvas() override;

    // ---- items ------------------------------------------------------------
    // Appends an item hosting `plot` and reflows the column layout.
    PwbPlotItem* addPlot(std::unique_ptr<Qgs2DPlot> plot);
    void clearPlots();
    QList<PwbPlotItem*> plotItems() const { return items_; }
    // Inter-column gutter in canvas px (default 4).
    void setColumnGutter(int px);

    // ---- domain binding ----------------------------------------------------
    // bindings[i] describes items_[item_index]'s series i.
    void setSeriesBindings(int item_index, const QList<SeriesBinding>& bindings);
    const SeriesBinding* bindingFor(int item_index, int series_index) const;

    // ---- view --------------------------------------------------------------
    void zoomFull();                       // autofit all items to data extent
    void setAutofitPadding(double f);      // fraction, default 0.05
    // Equal aspect (data units/px identical on both axes) — single-XY-item
    // canvases only; ignored for multi-track layouts.
    void setEqualAspect(bool on);
    bool equalAspect() const { return equal_aspect_; }
    // (xmin, xmax, ymin, ymax) union over linked items — same shape as the
    // retired PlotWidget::view_bounds().
    std::tuple<double, double, double, double> viewBounds() const;
    void setViewBounds(double xmin, double xmax, double ymin, double ymax);

    // ---- picking / hover -----------------------------------------------------
    // Nearest series vertex within radius_px of canvas_pos (linear scan per
    // item — same asymptotics as the retired PlotWidget).
    std::optional<PointHit> nearestPoint(QPointF canvas_pos,
                                         double radius_px = 15.0) const;
    // All hits whose mapped point lies inside the canvas rect.
    QList<PointHit> identifyRect(const QRectF& canvas_rect) const;

    // ---- export --------------------------------------------------------------
    // Vectorial export (svg/pdf) or raster (png); dispatches on suffix.
    // `size_px` is the output logical size (default: current viewport size).
    bool exportTo(const QString& path, QSize size_px = QSize());
    void renderToPainter(QPainter* painter, const QSize& size_px);

    // ---- QgsPlotCanvas contract ---------------------------------------------
    void cancelJobs() override;
    void panContentsBy(double dx, double dy) override;
    void centerPlotOn(double x, double y) override;
    void scalePlot(double factor) override;
    void scalePlot(double x_factor, double y_factor);
    void zoomToRect(const QRectF& rect) override;
    QgsPointXY snapToPlot(QPoint point) override;
    void refresh() override;
    QgsPoint toMapCoordinates(const QgsPointXY& point) const override;
    QgsPointXY toCanvasCoordinates(const QgsPoint& point) const override;

    // Union of linked items' interior plot areas (canvas coords) — used by
    // axis-constrained tools.
    QRectF unionPlotArea() const;

    // Horizontal guide line at data-y on the reference item (default: first
    // shareY item) — depth-cursor linkage. nullopt hides it.
    void setHorizontalGuide(std::optional<double> plot_y);

Q_SIGNALS:
    void pointHovered(const pwb::qgis_plot::PointHit& hit);
    void pointHoverCleared();
    void pointClicked(const pwb::qgis_plot::PointHit& hit);
    // Generic cursor readout (canvas pos + plot pos of first XY item).
    void canvasPointMoved(QPointF canvas_pos, QPointF plot_pos, bool valid);
    void viewChanged(double xmin, double xmax, double ymin, double ymax);

protected:
    void mouseMoveEvent(QMouseEvent* e) override;
    void mouseReleaseEvent(QMouseEvent* e) override;
    void leaveEvent(QEvent* e) override;
    void resizeEvent(QResizeEvent* e) override;
    void wheelZoom(QWheelEvent* e) override;

private:
    void layoutItems();
    void emitViewChanged();
    void applyEqualAspect(PwbPlotItem* item, double& xmin, double& xmax,
                          double& ymin, double& ymax) const;
    void updateHover(const QPointF& canvas_pos);
    PointHit makeHit(int item_index, int series_index, int point_index) const;

    QList<PwbPlotItem*> items_;
    int column_gutter_ = 4;
    QHash<int, QList<SeriesBinding>> bindings_;
    PwbCrosshairItem* crosshair_ = nullptr;
    PwbHGuideItem* hguide_ = nullptr;
    double autofit_padding_ = 0.05;
    bool equal_aspect_ = false;
    std::optional<PointHit> last_hover_;
    bool has_view_ = false;
};

}  // namespace pwb::qgis_plot
