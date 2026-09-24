#include "pwb/qgis_plot/plot_canvas.hpp"

#include <cmath>

#include <QMouseEvent>
#include <QPainter>
#include <QPdfWriter>
#include <QResizeEvent>
#include <QSvgGenerator>
#include <QWheelEvent>

#include <qgsplot.h>
#include <qgsplotcanvasitem.h>

#include "pwb/qgis_plot/plot_item.hpp"

namespace pwb::qgis_plot {

// Crosshair overlay: draws the hovered/snap point as a dashed cross through
// the owning item's plot area plus a value readout. Pure presentation — the
// canvas feeds it canvas-space positions.
class PwbCrosshairItem : public QgsPlotCanvasItem {
public:
    explicit PwbCrosshairItem(QgsPlotCanvas* canvas)
        : QgsPlotCanvasItem(canvas) {
        setZValue(100.0);
    }

    void setCanvasRect(const QRectF& rect) {
        prepareGeometryChange();
        rect_ = rect;
    }

    void setPoint(const QPointF& canvas_pos, const QString& label,
                  const QRectF& clip_area) {
        point_ = canvas_pos;
        label_ = label;
        clip_area_ = clip_area;
        update();
    }

    void clear() {
        if (point_.isNull() && label_.isEmpty())
            return;
        point_ = QPointF();
        label_.clear();
        update();
    }

    QRectF boundingRect() const override { return rect_; }

    void paint(QPainter* painter) override {
        if (point_.isNull())
            return;
        painter->save();
        painter->setRenderHint(QPainter::Antialiasing);
        const QPointF local = point_ - rect_.topLeft();
        QPen pen(QColor(30, 30, 30), 1.0, Qt::DashLine);
        pen.setCosmetic(true);
        painter->setPen(pen);
        const QRectF area =
            clip_area_.isNull() ? rect_ : clip_area_.translated(-rect_.topLeft());
        painter->setClipRect(area);
        painter->drawLine(QPointF(local.x(), area.top()),
                          QPointF(local.x(), area.bottom()));
        painter->drawLine(QPointF(area.left(), local.y()),
                          QPointF(area.right(), local.y()));
        painter->setClipping(false);
        painter->setBrush(QColor(30, 30, 30));
        painter->drawEllipse(local, 3.5, 3.5);
        if (!label_.isEmpty()) {
            painter->setPen(QColor(30, 30, 30));
            painter->drawText(local + QPointF(8, -8), label_);
        }
        painter->restore();
    }

private:
    QRectF rect_;
    QRectF clip_area_;
    QPointF point_;
    QString label_;
};

// Horizontal guide: a dashed line across the union plot area at a data-y
// mapped through the first shareY item (depth-cursor linkage).
class PwbHGuideItem : public QgsPlotCanvasItem {
public:
    explicit PwbHGuideItem(QgsPlotCanvas* canvas)
        : QgsPlotCanvasItem(canvas) {
        setZValue(95.0);
    }

    void setCanvasRect(const QRectF& rect) {
        prepareGeometryChange();
        rect_ = rect;
    }

    void setLine(double canvas_y, const QRectF& clip_area) {
        y_ = canvas_y;
        clip_area_ = clip_area;
        update();
    }

    void clear() {
        y_ = std::nullopt;
        update();
    }

    QRectF boundingRect() const override { return rect_; }

    void paint(QPainter* painter) override {
        if (!y_)
            return;
        painter->save();
        const QRectF area =
            clip_area_.isNull() ? rect_ : clip_area_.translated(-rect_.topLeft());
        painter->setClipRect(area);
        QPen pen(QColor(0x00, 0x78, 0xd4), 1.0, Qt::DashLine);
        pen.setCosmetic(true);
        painter->setPen(pen);
        const double y = *y_ - rect_.top();
        painter->drawLine(QPointF(area.left(), y),
                          QPointF(area.right(), y));
        painter->restore();
    }

private:
    QRectF rect_;
    QRectF clip_area_;
    std::optional<double> y_;
};

namespace {

constexpr double kMinSpan = 1e-9;

// Pad [lo,hi] by `fraction` of span; degenerate ranges get a sane fallback.
// Degenerate padding matches the retired PlotWidget (0.05 * (10% of |v| or 1)).
void padRange(double& lo, double& hi, double fraction) {
    double span = hi - lo;
    if (span < kMinSpan) {
        const double base =
            (std::fabs(lo) > kMinSpan) ? std::fabs(lo) * 0.1 : 1.0;
        const double pad = base * fraction;
        lo -= pad;
        hi += pad;
        return;
    }
    lo -= span * fraction;
    hi += span * fraction;
}

}  // namespace

PwbPlotCanvas::PwbPlotCanvas(QWidget* parent) : QgsPlotCanvas(parent) {
    setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    setVerticalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    setFrameShape(QFrame::NoFrame);
    setMinimumHeight(120);
    crosshair_ = new PwbCrosshairItem(this);
    hguide_ = new PwbHGuideItem(this);
}

PwbPlotCanvas::~PwbPlotCanvas() = default;

PwbPlotItem* PwbPlotCanvas::addPlot(std::unique_ptr<Qgs2DPlot> plot) {
    auto* item = new PwbPlotItem(this, std::move(plot));
    items_.append(item);
    layoutItems();
    return item;
}

void PwbPlotCanvas::clearPlots() {
    qDeleteAll(items_);
    items_.clear();
    bindings_.clear();
    crosshair_->clear();
    hguide_->clear();
    last_hover_ = std::nullopt;
    has_view_ = false;
}

void PwbPlotCanvas::setHorizontalGuide(std::optional<double> plot_y) {
    if (!plot_y) {
        hguide_->clear();
        return;
    }
    for (auto* item : items_) {
        if (!item->shareY())
            continue;
        const QPointF pt = item->plotToCanvas(item->xRange().lower(), *plot_y);
        hguide_->setLine(pt.y(), unionPlotArea());
        return;
    }
    hguide_->clear();
}

void PwbPlotCanvas::setColumnGutter(int px) {
    column_gutter_ = px;
    layoutItems();
}

void PwbPlotCanvas::setSeriesBindings(
    int item_index, const QList<SeriesBinding>& bindings) {
    bindings_[item_index] = bindings;
}

const SeriesBinding* PwbPlotCanvas::bindingFor(int item_index,
                                               int series_index) const {
    const auto it = bindings_.constFind(item_index);
    if (it == bindings_.constEnd() || series_index < 0 ||
        series_index >= it->size())
        return nullptr;
    return &it->at(series_index);
}

void PwbPlotCanvas::layoutItems() {
    const QRectF r(QPointF(0, 0), rect().size());
    scene()->setSceneRect(r);
    crosshair_->setCanvasRect(r);
    hguide_->setCanvasRect(r);
    if (items_.isEmpty())
        return;

    const double gutters =
        column_gutter_ * std::max(0, static_cast<int>(items_.size()) - 1);
    const double w =
        std::max(0.0, r.width() - gutters) / items_.size();
    double x = r.left();
    for (auto* item : items_) {
        item->setSceneRect(QRectF(x, r.top(), w, r.height()));
        x += w + column_gutter_;
    }
}

void PwbPlotCanvas::resizeEvent(QResizeEvent* e) {
    QgsPlotCanvas::resizeEvent(e);
    layoutItems();
    // First-time convenience: if data exists but no view was ever set, fit.
    if (!has_view_) {
        for (auto* item : items_) {
            double a, b, c, d;
            if (item->extent(a, b, c, d)) {
                zoomFull();
                break;
            }
        }
    } else if (equal_aspect_) {
        // plotArea() changed with the widget — re-equalize the current view
        // (retired PlotWidget::resizeEvent kept the lock too).
        for (auto* item : items_) {
            if (!item->xyPlot())
                continue;
            const auto xr = item->xRange();
            const auto yr = item->yRange();
            double xmin = xr.lower(), xmax = xr.upper();
            double ymin = yr.lower(), ymax = yr.upper();
            applyEqualAspect(item, xmin, xmax, ymin, ymax);
            item->setXRange(xmin, xmax);
            item->setYRange(ymin, ymax);
            break;
        }
    }
    emit plotAreaChanged();
}

void PwbPlotCanvas::refresh() {
    for (auto* item : items_)
        item->updatePlot();
    viewport()->update();
}

void PwbPlotCanvas::cancelJobs() {}

// ---------------------------------------------------------------------------
// Navigation — the QgsPlotCanvas virtuals QGIS tools call into.
// Math mirrors QgsElevationProfileCanvas (upstream reference implementation,
// QGIS 4.2.0): ranges are dragged "with the paper", zoom is centred on the
// cursor, and axes participate per-item via shareX()/shareY().

void PwbPlotCanvas::panContentsBy(double dx, double dy) {
    // Linked-axis rule: all shareX items receive the SAME data-space dx (the
    // drag's data displacement measured against the first shareX item's plot
    // area), otherwise differing y-label insets would let tracks drift apart.
    bool have_dx = false;
    double dxp = 0.0;
    for (auto* item : items_) {
        if (!item->shareX())
            continue;
        const QRectF area = item->plotArea();
        if (area.isEmpty())
            continue;
        if (!have_dx) {
            dxp = -dx / area.width() *
                  (item->xRange().upper() - item->xRange().lower());
            have_dx = true;
        }
        item->setXRange(item->xRange().lower() + dxp,
                        item->xRange().upper() + dxp);
    }
    for (auto* item : items_) {
        if (!item->shareY())
            continue;
        const QRectF area = item->plotArea();
        if (area.isEmpty())
            continue;
        const double dyp =
            dy / area.height() * (item->yRange().upper() - item->yRange().lower());
        item->setYRange(item->yRange().lower() + dyp,
                        item->yRange().upper() + dyp);
    }
    emitViewChanged();
    emit plotAreaChanged();
}

void PwbPlotCanvas::centerPlotOn(double x, double y) {
    // Linked rule: the data-space translation is measured on the first item
    // containing the point, then applied uniformly so tracks stay locked.
    bool have_dx = false, have_dy = false;
    double dxp = 0.0, dyp = 0.0;
    for (auto* item : items_) {
        const QRectF area = item->plotArea();
        if (area.isEmpty() || !area.contains(QPointF(x, y)))
            continue;
        double px, py;
        if (!item->canvasToPlot(QPointF(x, y), px, py))
            continue;
        const auto xr = item->xRange();
        const auto yr = item->yRange();
        if (item->shareX() && !have_dx) {
            dxp = px - (xr.lower() + xr.upper()) * 0.5;
            have_dx = true;
        }
        if (item->shareY() && !have_dy) {
            dyp = py - (yr.lower() + yr.upper()) * 0.5;
            have_dy = true;
        }
    }
    for (auto* item : items_) {
        if (item->shareX() && have_dx)
            item->setXRange(item->xRange().lower() + dxp,
                            item->xRange().upper() + dxp);
        if (item->shareY() && have_dy)
            item->setYRange(item->yRange().lower() + dyp,
                            item->yRange().upper() + dyp);
    }
    emitViewChanged();
    emit plotAreaChanged();
}

void PwbPlotCanvas::scalePlot(double x_factor, double y_factor) {
    for (auto* item : items_) {
        const auto xr = item->xRange();
        const auto yr = item->yRange();
        double xmin = xr.lower(), xmax = xr.upper();
        double ymin = yr.lower(), ymax = yr.upper();
        if (item->shareX()) {
            const double cx = (xmin + xmax) * 0.5;
            const double w = (xmax - xmin) / x_factor;
            xmin = cx - w * 0.5;
            xmax = cx + w * 0.5;
        }
        if (item->shareY()) {
            const double cy = (ymin + ymax) * 0.5;
            const double h = (ymax - ymin) / y_factor;
            ymin = cy - h * 0.5;
            ymax = cy + h * 0.5;
        }
        if (equal_aspect_)
            applyEqualAspect(item, xmin, xmax, ymin, ymax);
        item->setXRange(xmin, xmax);
        item->setYRange(ymin, ymax);
    }
    emitViewChanged();
    emit plotAreaChanged();
}

void PwbPlotCanvas::scalePlot(double factor) {
    scalePlot(factor, factor);
}

void PwbPlotCanvas::zoomToRect(const QRectF& rect) {
    // Pass 1: linked-X items all adopt the x-range mapped on the FIRST
    // shareX item the rect intersects — linked tracks cannot drift.
    bool have_linked_x = false;
    double linked_xmin = 0.0, linked_xmax = 0.0;
    for (auto* item : items_) {
        if (!item->shareX())
            continue;
        const QRectF area = item->plotArea();
        const QRectF clipped = rect.intersected(area);
        if (area.isEmpty() || clipped.isEmpty())
            continue;
        const auto xr = item->xRange();
        linked_xmin =
            xr.lower() + (clipped.left() - area.left()) / area.width() *
                             (xr.upper() - xr.lower());
        linked_xmax =
            xr.lower() + (clipped.right() - area.left()) / area.width() *
                             (xr.upper() - xr.lower());
        have_linked_x = true;
        break;
    }

    for (auto* item : items_) {
        const QRectF area = item->plotArea();
        if (area.isEmpty())
            continue;
        const QRectF clipped = rect.intersected(area);
        const auto xr = item->xRange();
        const auto yr = item->yRange();
        double xmin = xr.lower(), xmax = xr.upper();
        double ymin = yr.lower(), ymax = yr.upper();
        if (item->shareX() && have_linked_x) {
            xmin = linked_xmin;
            xmax = linked_xmax;
        }
        if (item->shareY() && !clipped.isEmpty()) {
            ymin = yr.lower() +
                   (area.bottom() - clipped.bottom()) / area.height() *
                       (yr.upper() - yr.lower());
            ymax = yr.lower() +
                   (area.bottom() - clipped.top()) / area.height() *
                       (yr.upper() - yr.lower());
        }
        if (equal_aspect_)
            applyEqualAspect(item, xmin, xmax, ymin, ymax);
        item->setXRange(xmin, xmax);
        item->setYRange(ymin, ymax);
    }
    emitViewChanged();
    emit plotAreaChanged();
}

void PwbPlotCanvas::wheelZoom(QWheelEvent* e) {
    // 1.25^steps in/out; Ctrl refines x4 (upstream scales by settings; the
    // fixed factor keeps tests deterministic and matches QGIS defaults).
    double factor = std::pow(1.25, e->angleDelta().y() / 120.0);
    if (e->modifiers() & Qt::ControlModifier)
        factor = 1.0 + (factor - 1.0) / 4.0;
    if (factor <= 0.0)
        return;

    const QPointF pos = e->position();
    // Data-space pivot under the cursor, resolved on the first item that
    // contains it; linked-X items share that pivot so tracks stay locked.
    bool have_pivot_x = false, have_pivot_y = false;
    double pivot_x = 0.0, pivot_y = 0.0;
    for (auto* item : items_) {
        double px, py;
        if (!item->canvasToPlot(pos, px, py))
            continue;
        if (item->shareX() && !have_pivot_x) {
            pivot_x = px;
            have_pivot_x = true;
        }
        if (item->shareY() && !have_pivot_y) {
            pivot_y = py;
            have_pivot_y = true;
        }
    }

    for (auto* item : items_) {
        const auto xr = item->xRange();
        const auto yr = item->yRange();
        const double cx = (item->shareX() && have_pivot_x)
                              ? pivot_x
                              : (xr.lower() + xr.upper()) * 0.5;
        const double cy = (item->shareY() && have_pivot_y)
                              ? pivot_y
                              : (yr.lower() + yr.upper()) * 0.5;
        double xmin = cx + (xr.lower() - cx) / factor;
        double xmax = cx + (xr.upper() - cx) / factor;
        double ymin = cy + (yr.lower() - cy) / factor;
        double ymax = cy + (yr.upper() - cy) / factor;
        if (!item->shareX()) {
            xmin = xr.lower();
            xmax = xr.upper();
        }
        if (!item->shareY()) {
            ymin = yr.lower();
            ymax = yr.upper();
        }
        if (equal_aspect_)
            applyEqualAspect(item, xmin, xmax, ymin, ymax);
        item->setXRange(xmin, xmax);
        item->setYRange(ymin, ymax);
    }
    emitViewChanged();
    emit plotAreaChanged();
}

void PwbPlotCanvas::zoomFull() {
    // Union X across all shareX items so linked tracks share one extent.
    double uxmin = std::numeric_limits<double>::max();
    double uxmax = std::numeric_limits<double>::lowest();
    bool shared_x = false;
    for (auto* item : items_) {
        if (!item->shareX())
            continue;
        double a, b, c, d;
        if (item->extent(a, b, c, d)) {
            uxmin = std::min(uxmin, a);
            uxmax = std::max(uxmax, b);
            shared_x = true;
        }
    }
    if (shared_x)
        padRange(uxmin, uxmax, autofit_padding_);

    for (auto* item : items_) {
        double xmin, xmax, ymin, ymax;
        if (!item->extent(xmin, xmax, ymin, ymax))
            continue;
        padRange(ymin, ymax, autofit_padding_);
        if (item->shareX() && shared_x) {
            xmin = uxmin;
            xmax = uxmax;
        } else {
            padRange(xmin, xmax, autofit_padding_);
        }
        if (equal_aspect_)
            applyEqualAspect(item, xmin, xmax, ymin, ymax);
        item->setXRange(xmin, xmax);
        item->setYRange(ymin, ymax);
    }
    has_view_ = true;
    emitViewChanged();
    emit plotAreaChanged();
}

void PwbPlotCanvas::applyEqualAspect(PwbPlotItem* item, double& xmin,
                                     double& xmax, double& ymin,
                                     double& ymax) const {
    const QRectF area = const_cast<PwbPlotItem*>(item)->plotArea();
    if (area.isEmpty())
        return;
    const double x_span = xmax - xmin;
    const double y_span = ymax - ymin;
    if (x_span <= 0.0 || y_span <= 0.0)
        return;
    const double x_per_px = x_span / area.width();
    const double y_per_px = y_span / area.height();
    if (x_per_px > y_per_px) {
        // Y too dense — expand Y to match X scale.
        const double want = x_per_px * area.height();
        const double cy = (ymin + ymax) * 0.5;
        ymin = cy - want * 0.5;
        ymax = cy + want * 0.5;
    } else {
        const double want = y_per_px * area.width();
        const double cx = (xmin + xmax) * 0.5;
        xmin = cx - want * 0.5;
        xmax = cx + want * 0.5;
    }
}

void PwbPlotCanvas::setEqualAspect(bool on) {
    equal_aspect_ = on;
}

void PwbPlotCanvas::setViewBounds(double xmin, double xmax, double ymin,
                                  double ymax) {
    for (auto* item : items_) {
        if (item->shareX())
            item->setXRange(xmin, xmax);
        if (item->shareY())
            item->setYRange(ymin, ymax);
    }
    has_view_ = true;
    emitViewChanged();
    emit plotAreaChanged();
}

std::tuple<double, double, double, double> PwbPlotCanvas::viewBounds() const {
    double xmin = std::numeric_limits<double>::max();
    double xmax = std::numeric_limits<double>::lowest();
    double ymin = std::numeric_limits<double>::max();
    double ymax = std::numeric_limits<double>::lowest();
    bool any = false;
    for (auto* item : items_) {
        if (!item->xyPlot())
            continue;
        const auto xr = item->xRange();
        const auto yr = item->yRange();
        xmin = std::min(xmin, xr.lower());
        xmax = std::max(xmax, xr.upper());
        ymin = std::min(ymin, yr.lower());
        ymax = std::max(ymax, yr.upper());
        any = true;
    }
    if (!any)
        return {0.0, 0.0, 0.0, 0.0};
    return {xmin, xmax, ymin, ymax};
}

QRectF PwbPlotCanvas::unionPlotArea() const {
    QRectF out;
    for (auto* item : items_)
        out = out.united(const_cast<PwbPlotItem*>(item)->plotArea());
    return out;
}

// ---------------------------------------------------------------------------
// Picking / hover

PointHit PwbPlotCanvas::makeHit(int item_index, int series_index,
                                int point_index) const {
    PointHit hit;
    hit.item_index = item_index;
    hit.series_index = series_index;
    hit.point_index = point_index;
    const auto* item = items_.at(item_index);
    const auto series = item->plotData().series();
    if (series_index < series.size()) {
        if (const auto* xy =
                dynamic_cast<const QgsXyPlotSeries*>(series[series_index])) {
            const auto d = xy->data();
            if (point_index < d.size()) {
                hit.plot_x = d[point_index].first;
                hit.plot_y = d[point_index].second;
            }
        }
    }
    if (const auto* b = bindingFor(item_index, series_index)) {
        hit.series_id = b->series_id;
        if (point_index < b->point_domain_ids.size())
            hit.domain_id = b->point_domain_ids[point_index];
    }
    return hit;
}

std::optional<PointHit> PwbPlotCanvas::nearestPoint(QPointF canvas_pos,
                                                    double radius_px) const {
    std::optional<PointHit> best;
    double best_d2 = radius_px * radius_px;
    for (int i = 0; i < items_.size(); ++i) {
        const auto found = items_[i]->nearestSeriesPoint(canvas_pos, radius_px);
        if (!found)
            continue;
        const auto series = items_[i]->plotData().series();
        const auto* xy = dynamic_cast<const QgsXyPlotSeries*>(
            series.value(found->first));
        if (!xy)
            continue;
        const auto d = xy->data();
        if (found->second >= d.size())
            continue;
        const QPointF pt = items_[i]->plotToCanvas(d[found->second].first,
                                                   d[found->second].second);
        const double d2 =
            QPointF::dotProduct(pt - canvas_pos, pt - canvas_pos);
        if (d2 <= best_d2) {
            best_d2 = d2;
            best = makeHit(i, found->first, found->second);
        }
    }
    return best;
}

QList<PointHit> PwbPlotCanvas::identifyRect(const QRectF& canvas_rect) const {
    QList<PointHit> out;
    for (int i = 0; i < items_.size(); ++i) {
        for (const auto& [s, p] : items_[i]->pointsInRect(canvas_rect))
            out.append(makeHit(i, s, p));
    }
    return out;
}

QgsPointXY PwbPlotCanvas::snapToPlot(QPoint point) {
    const auto hit = nearestPoint(QPointF(point), 12.0);
    if (!hit)
        return QgsPointXY(point.x(), point.y());
    return items_[hit->item_index]->plotToCanvas(hit->plot_x, hit->plot_y);
}

QgsPoint PwbPlotCanvas::toMapCoordinates(const QgsPointXY& point) const {
    for (auto* item : items_) {
        double x, y;
        if (item->canvasToPlot(QPointF(point.x(), point.y()), x, y))
            return QgsPoint(x, y);
    }
    return QgsPoint();
}

QgsPointXY PwbPlotCanvas::toCanvasCoordinates(const QgsPoint& point) const {
    // Multi-track canvases are ambiguous — convention: the first shared-X
    // item's mapping wins (upstream elevation canvas is single-plot).
    for (auto* item : items_) {
        if (item->xyPlot() && item->shareX())
            return item->plotToCanvas(point.x(), point.y());
    }
    return QgsPointXY(point.x(), point.y());
}

void PwbPlotCanvas::updateHover(const QPointF& canvas_pos) {
    const auto hit = nearestPoint(canvas_pos, 15.0);
    const bool changed =
        (hit.has_value() != last_hover_.has_value()) ||
        (hit && last_hover_ &&
         (hit->item_index != last_hover_->item_index ||
          hit->series_index != last_hover_->series_index ||
          hit->point_index != last_hover_->point_index));
    if (!changed)
        return;
    last_hover_ = hit;
    if (hit) {
        const QPointF pt =
            items_[hit->item_index]->plotToCanvas(hit->plot_x, hit->plot_y);
        crosshair_->setPoint(
            pt, QStringLiteral("%1, %2").arg(hit->plot_x).arg(hit->plot_y),
            items_[hit->item_index]->plotArea());
        emit pointHovered(*hit);
    } else {
        crosshair_->clear();
        emit pointHoverCleared();
    }
}

void PwbPlotCanvas::mouseMoveEvent(QMouseEvent* e) {
    QgsPlotCanvas::mouseMoveEvent(e);
    updateHover(e->pos());
    double x = 0.0, y = 0.0;
    bool valid = false;
    for (auto* item : items_) {
        if (item->canvasToPlot(QPointF(e->pos()), x, y)) {
            valid = true;
            break;
        }
    }
    emit canvasPointMoved(QPointF(e->pos()), QPointF(x, y), valid);
}

void PwbPlotCanvas::mouseReleaseEvent(QMouseEvent* e) {
    QgsPlotCanvas::mouseReleaseEvent(e);
    if (e->button() == Qt::LeftButton && !tool() && last_hover_)
        emit pointClicked(*last_hover_);
}

void PwbPlotCanvas::leaveEvent(QEvent* e) {
    QgsPlotCanvas::leaveEvent(e);
    if (last_hover_) {
        last_hover_ = std::nullopt;
        crosshair_->clear();
        emit pointHoverCleared();
    }
}

void PwbPlotCanvas::emitViewChanged() {
    const auto [xmin, xmax, ymin, ymax] = viewBounds();
    emit viewChanged(xmin, xmax, ymin, ymax);
}

// ---------------------------------------------------------------------------
// Export

void PwbPlotCanvas::renderToPainter(QPainter* painter, const QSize& size_px) {
    const double gutters =
        column_gutter_ * std::max(0, static_cast<int>(items_.size()) - 1);
    const double w =
        std::max(0.0, size_px.width() - gutters) / items_.size();
    double x = 0.0;
    for (auto* item : items_) {
        item->renderToPainter(
            painter, QRectF(x, 0.0, w, size_px.height()));
        x += w + column_gutter_;
    }
}

bool PwbPlotCanvas::exportTo(const QString& path, QSize size_px) {
    if (size_px.isEmpty())
        size_px = viewport()->size();
    if (size_px.isEmpty() || items_.isEmpty())
        return false;

    const QString suffix = path.section(QLatin1Char('.'), -1).toLower();
    if (suffix == QLatin1String("svg")) {
        QSvgGenerator gen;
        gen.setFileName(path);
        gen.setSize(size_px);
        gen.setViewBox(QRect(0, 0, size_px.width(), size_px.height()));
        QPainter painter(&gen);
        renderToPainter(&painter, size_px);
        return painter.isActive();
    }
    if (suffix == QLatin1String("pdf")) {
        QPdfWriter writer(path);
        // Full A4 page (parity with the retired PlotWidget / Python oracle).
        writer.setPageSize(QPageSize(QPageSize::A4));
        // Keep device dpi at 96 so the render-context scale factor matches
        // the screen path (QPdfWriter at other resolutions can leave
        // QPaintDevice metrics inconsistent for the interval calculation).
        writer.setResolution(96);
        const QSizeF page_px =
            writer.pageLayout().paintRectPixels(writer.resolution()).size();
        QPainter painter(&writer);
        renderToPainter(&painter, page_px.toSize());
        return painter.isActive();
    }
    QImage image(size_px, QImage::Format_ARGB32);
    image.fill(Qt::white);
    QPainter painter(&image);
    renderToPainter(&painter, size_px);
    painter.end();
    return image.save(path);
}

}  // namespace pwb::qgis_plot
