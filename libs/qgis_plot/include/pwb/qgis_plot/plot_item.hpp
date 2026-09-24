// QGIS-plot convergence — the scene host for a Qgs2DPlot.
//
// QgsPlotCanvas deliberately ships no setPlot()/data model: the upstream
// pattern (QgsElevationProfilePlotItem) is a QgsPlotCanvasItem that *is* or
// *holds* the plot. PwbPlotItem holds any Qgs2DPlot (stock line/bar/pie or a
// Paleo renderContent subclass) plus its QgsPlotData, and supplies the
// canvas<->data coordinate mapping, image-cached painting and axis titles
// that Qgs2DPlot itself does not provide.
#pragma once

#include <array>
#include <memory>
#include <optional>
#include <utility>

#include <QRectF>
#include <QString>
#include <QVector>

#include <qgsplotcanvasitem.h>
#include <qgsrange.h>

class QPainter;

class Qgs2DPlot;
class Qgs2DXyPlot;
class QgsPlotData;

namespace pwb::qgis_plot {

class PwbPlotItem : public QgsPlotCanvasItem {
public:
    // The plot is owned by the item; ownership transfers. `fraction` is the
    // horizontal slice of the canvas this item occupies (0..1); the canvas
    // assigns scene rects from cumulative fractions — one item = full width.
    PwbPlotItem(QgsPlotCanvas* canvas, std::unique_ptr<Qgs2DPlot> plot);
    ~PwbPlotItem() override = default;

    void setPlot(std::unique_ptr<Qgs2DPlot> plot);
    Qgs2DPlot* plot() const { return plot_.get(); }
    // nullptr for non-XY plots (pie).
    Qgs2DXyPlot* xyPlot() const;

    void setPlotData(QgsPlotData data);
    const QgsPlotData& plotData() const;

    // Scene rect assignment (called by PwbPlotCanvas layout).
    void setSceneRect(const QRectF& rect);
    QRectF sceneRect() const { return scene_rect_; }
    QRectF boundingRect() const override;

    // Interior (axis-inset) plot area in canvas coordinates; empty until laid
    // out/rendered once.
    QRectF plotArea();

    // Coordinate mapping — XY plots only; canvas (scene) coords <-> data.
    bool canvasToPlot(QPointF canvas_pos, double& x, double& y) const;
    QPointF plotToCanvas(double x, double y) const;
    bool hasXyMapping() const { return xyPlot() != nullptr; }

    QgsDoubleRange xRange() const;
    QgsDoubleRange yRange() const;
    void setXRange(double lo, double hi);
    void setYRange(double lo, double hi);
    // Finite data extent of the XY series; false when no finite pairs.
    bool dataExtent(double& xmin, double& xmax, double& ymin,
                    double& ymax) const;
    // Explicit full extent for content drawn outside QgsPlotData (e.g.
    // PwbIntervalStripPlot bands): zoomFull prefers this over series data.
    void setFullExtent(double xmin, double xmax, double ymin, double ymax);
    // full extent when set, else series dataExtent.
    bool extent(double& xmin, double& xmax, double& ymin,
                double& ymax) const;

    // Axis titles (QgsPlotAxis has none): drawn inside the plot margins.
    void setAxisTitles(QString x_title, QString y_title);
    // Column header drawn centred in the top margin (track name/unit).
    void setTopTitle(QString title);

    // Axis participation in canvas-level pan/zoom (multi-track linking).
    void setShareX(bool on) { share_x_ = on; }
    void setShareY(bool on) { share_y_ = on; }
    bool shareX() const { return share_x_; }
    bool shareY() const { return share_y_; }

    void updatePlot();   // invalidate cached render

    void paint(QPainter* painter) override;

    // Vectorial render into `target` rect on `painter` — export path; does
    // not use or invalidate the screen image cache.
    void renderToPainter(QPainter* painter, const QRectF& target);

    // Hit testing over QgsXyPlotSeries data (linear scan, pixel space).
    // Returns (series_index, point_index).
    std::optional<std::pair<int, int>> nearestSeriesPoint(
        QPointF canvas_pos, double radius_px) const;
    // All (series, point) pairs whose mapped canvas point falls in rect.
    QList<std::pair<int, int>> pointsInRect(const QRectF& canvas_rect) const;

private:
    // `local_area` is the interior plot area in item-local coords.
    void drawAxisTitles(QPainter* painter, const QRectF& local_area);
    void updateMargins();

    std::unique_ptr<Qgs2DPlot> plot_;
    std::unique_ptr<QgsPlotData> data_;
    std::optional<std::array<double, 4>> full_extent_;
    QRectF scene_rect_;               // canvas coords
    QRectF plot_area_;                // canvas coords, cached
    QImage image_;                    // paint cache (local coords)
    QString x_title_, y_title_, top_title_;
    bool share_x_ = true;
    bool share_y_ = true;
};

}  // namespace pwb::qgis_plot
