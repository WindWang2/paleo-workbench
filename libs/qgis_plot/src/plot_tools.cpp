#include "pwb/qgis_plot/plot_tools.hpp"

#include <QGraphicsPolygonItem>

#include <qgsplotmouseevent.h>
#include <qgsplotrubberband.h>

#include "pwb/qgis_plot/plot_canvas.hpp"

namespace pwb::qgis_plot {

// ---------------------------------------------------------------------------
// X-axis marquee zoom

PwbPlotToolXAxisZoom::PwbPlotToolXAxisZoom(PwbPlotCanvas* canvas)
    : QgsPlotToolZoom(canvas) {
    setCursor(Qt::CrossCursor);
}

QRectF PwbPlotToolXAxisZoom::constrainBounds(
    const QRectF& scene_bounds) const {
    const QRectF area = pwb_canvas()->unionPlotArea();
    if (area.isEmpty())
        return scene_bounds;
    return QRectF(scene_bounds.left(), area.top(), scene_bounds.width(),
                  area.height());
}

PwbPlotCanvas* PwbPlotToolXAxisZoom::pwb_canvas() const {
    return static_cast<PwbPlotCanvas*>(canvas());
}

// ---------------------------------------------------------------------------
// Identify (click pick + rectangle)

PwbPlotToolIdentify::PwbPlotToolIdentify(PwbPlotCanvas* canvas)
    : QgsPlotTool(canvas, tr("Identify")), pwb_canvas_(canvas) {
    setCursor(Qt::CrossCursor);
    rubber_band_ = new QgsPlotRectangularRubberBand(canvas);
}

PwbPlotToolIdentify::~PwbPlotToolIdentify() = default;

Qgis::PlotToolFlags PwbPlotToolIdentify::flags() const {
    return Qgis::PlotToolFlag::ShowContextMenu;
}

void PwbPlotToolIdentify::plotPressEvent(QgsPlotMouseEvent* event) {
    if (event->button() != Qt::LeftButton)
        return;
    press_pos_ = event->pos();
    dragging_ = false;
    rubber_band_->start(event->pos(), Qt::KeyboardModifiers());
}

void PwbPlotToolIdentify::plotMoveEvent(QgsPlotMouseEvent* event) {
    if (!(event->buttons() & Qt::LeftButton))
        return;
    if (!dragging_ && isClickAndDrag(press_pos_, event->pos()))
        dragging_ = true;
    if (dragging_)
        rubber_band_->update(event->pos(), Qt::KeyboardModifiers());
}

void PwbPlotToolIdentify::plotReleaseEvent(QgsPlotMouseEvent* event) {
    if (event->button() != Qt::LeftButton)
        return;
    if (dragging_) {
        const QRectF rect = rubber_band_->finish(event->pos());
        emit identified(pwb_canvas_->identifyRect(rect));
    } else {
        rubber_band_->finish();
        if (const auto hit = pwb_canvas_->nearestPoint(QPointF(event->pos())))
            emit pointPicked(*hit);
        else
            emit identified({});
    }
    dragging_ = false;
}

void PwbPlotToolIdentify::deactivate() {
    QgsPlotTool::deactivate();
    rubber_band_->finish();
    dragging_ = false;
}

// ---------------------------------------------------------------------------
// Freehand lasso

PwbPlotToolLasso::PwbPlotToolLasso(PwbPlotCanvas* canvas)
    : QgsPlotTool(canvas, tr("Lasso")), pwb_canvas_(canvas) {
    setCursor(Qt::CrossCursor);
}

PwbPlotToolLasso::~PwbPlotToolLasso() = default;

Qgis::PlotToolFlags PwbPlotToolLasso::flags() const {
    return Qgis::PlotToolFlag::ShowContextMenu;
}

void PwbPlotToolLasso::plotPressEvent(QgsPlotMouseEvent* event) {
    if (event->button() != Qt::LeftButton)
        return;
    polygon_.clear();
    polygon_ << QPointF(event->pos());
    if (!polygon_item_) {
        polygon_item_ = new QGraphicsPolygonItem();
        polygon_item_->setPen(QPen(QColor(30, 90, 200), 1.0, Qt::DashLine));
        polygon_item_->setBrush(QColor(30, 90, 200, 40));
        polygon_item_->setZValue(90.0);
        canvas()->scene()->addItem(polygon_item_);
    }
    polygon_item_->setPolygon(polygon_);
    polygon_item_->show();
    active_ = true;
}

void PwbPlotToolLasso::plotMoveEvent(QgsPlotMouseEvent* event) {
    if (!active_ || !(event->buttons() & Qt::LeftButton))
        return;
    const QPointF pos(event->pos());
    if (polygon_.isEmpty() ||
        QLineF(polygon_.last(), pos).length() >= 2.0) {
        polygon_ << pos;
        polygon_item_->setPolygon(polygon_);
    }
}

void PwbPlotToolLasso::plotReleaseEvent(QgsPlotMouseEvent* event) {
    if (!active_ || event->button() != Qt::LeftButton)
        return;
    active_ = false;
    if (polygon_item_)
        polygon_item_->hide();
    const bool cancelled = polygon_.size() < 3;
    emit lassoFinished(cancelled ? QPolygonF() : polygon_);
    polygon_.clear();
}

void PwbPlotToolLasso::deactivate() {
    QgsPlotTool::deactivate();
    if (polygon_item_)
        polygon_item_->hide();
    polygon_.clear();
    active_ = false;
}

}  // namespace pwb::qgis_plot
