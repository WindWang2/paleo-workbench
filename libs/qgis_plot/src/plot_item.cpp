#include "pwb/qgis_plot/plot_item.hpp"

#include <cmath>

#include <QGraphicsView>
#include <QPainter>

#include <qgsplot.h>
#include <qgsplotcanvas.h>
#include <qgsrendercontext.h>

namespace pwb::qgis_plot {

namespace {

// Margins in mm (converted to px by the render context scale factor).
// Left/bottom carry axis labels; widened when axis titles are present.
constexpr double kMarginLeftMm = 12.0;
constexpr double kMarginTopMm = 4.0;
constexpr double kMarginRightMm = 3.0;
constexpr double kMarginBottomMm = 7.0;
constexpr double kTitleExtraMm = 5.0;

}  // namespace

PwbPlotItem::PwbPlotItem(QgsPlotCanvas* canvas, std::unique_ptr<Qgs2DPlot> plot)
    : QgsPlotCanvasItem(canvas),
      plot_(std::move(plot)),
      data_(std::make_unique<QgsPlotData>()) {
    updateMargins();
}

void PwbPlotItem::updatePlot() {
    image_ = QImage();
    plot_area_ = QRectF();
    update();
}

void PwbPlotItem::setPlot(std::unique_ptr<Qgs2DPlot> plot) {
    plot_ = std::move(plot);
    updateMargins();
    updatePlot();
}

Qgs2DXyPlot* PwbPlotItem::xyPlot() const {
    return dynamic_cast<Qgs2DXyPlot*>(plot_.get());
}

void PwbPlotItem::setPlotData(QgsPlotData data) {
    *data_ = std::move(data);
    updatePlot();
}

const QgsPlotData& PwbPlotItem::plotData() const {
    return *data_;
}

void PwbPlotItem::setSceneRect(const QRectF& rect) {
    if (scene_rect_ == rect)
        return;
    prepareGeometryChange();
    scene_rect_ = rect;
    setPos(rect.topLeft());
    if (plot_)
        plot_->setSize(rect.size());
    updatePlot();
}

QRectF PwbPlotItem::boundingRect() const {
    return QRectF(QPointF(0, 0), scene_rect_.size());
}

void PwbPlotItem::updateMargins() {
    if (!plot_)
        return;
    const double left = kMarginLeftMm + (y_title_.isEmpty() ? 0.0 : kTitleExtraMm);
    const double top =
        kMarginTopMm + (top_title_.isEmpty() ? 0.0 : kTitleExtraMm);
    const double bottom =
        kMarginBottomMm + (x_title_.isEmpty() ? 0.0 : kTitleExtraMm);
    plot_->setMargins(QgsMargins(left, top, kMarginRightMm, bottom));
}

void PwbPlotItem::setAxisTitles(QString x_title, QString y_title) {
    x_title_ = std::move(x_title);
    y_title_ = std::move(y_title);
    updateMargins();
    updatePlot();
}

void PwbPlotItem::setTopTitle(QString title) {
    top_title_ = std::move(title);
    updateMargins();
    updatePlot();
}

QRectF PwbPlotItem::plotArea() {
    if (plot_area_.isNull() && plot_ && !scene_rect_.isEmpty()) {
        // Compute the interior area without forcing a repaint: a plain render
        // context at screen dpi gives the same margin math as paint().
        QgsRenderContext rc;
        rc.setScaleFactor(mCanvas->logicalDpiX() / 25.4);
        QgsPlotRenderContext plot_ctx;
        if (auto* xy = xyPlot())
            xy->calculateOptimisedIntervals(rc, plot_ctx);
        plot_area_ =
            plot_->interiorPlotArea(rc, plot_ctx, *data_).translated(pos());
    }
    return plot_area_;
}

bool PwbPlotItem::canvasToPlot(QPointF canvas_pos, double& x, double& y) const {
    const auto* xy = xyPlot();
    const QRectF area = const_cast<PwbPlotItem*>(this)->plotArea();
    if (!xy || area.isEmpty() || !area.contains(canvas_pos))
        return false;
    const double fx = (canvas_pos.x() - area.left()) / area.width();
    const double fy = (area.bottom() - canvas_pos.y()) / area.height();
    if (xy->flipAxes()) {
        // Flipped: data-x runs along canvas Y (top-down), data-y along X.
        x = xy->xMinimum() + fy * (xy->xMaximum() - xy->xMinimum());
        y = xy->yMinimum() + fx * (xy->yMaximum() - xy->yMinimum());
    } else {
        x = xy->xMinimum() + fx * (xy->xMaximum() - xy->xMinimum());
        y = xy->yMinimum() + fy * (xy->yMaximum() - xy->yMinimum());
    }
    return true;
}

QPointF PwbPlotItem::plotToCanvas(double x, double y) const {
    const auto* xy = xyPlot();
    const QRectF area = const_cast<PwbPlotItem*>(this)->plotArea();
    if (!xy || area.isEmpty())
        return {};
    const double fx = (x - xy->xMinimum()) / (xy->xMaximum() - xy->xMinimum());
    const double fy = (y - xy->yMinimum()) / (xy->yMaximum() - xy->yMinimum());
    if (xy->flipAxes())
        return {area.left() + fy * area.width(),
                area.bottom() - fx * area.height()};
    return {area.left() + fx * area.width(), area.bottom() - fy * area.height()};
}

QgsDoubleRange PwbPlotItem::xRange() const {
    const auto* xy = xyPlot();
    return xy ? QgsDoubleRange(xy->xMinimum(), xy->xMaximum())
              : QgsDoubleRange();
}

QgsDoubleRange PwbPlotItem::yRange() const {
    const auto* xy = xyPlot();
    return xy ? QgsDoubleRange(xy->yMinimum(), xy->yMaximum())
              : QgsDoubleRange();
}

void PwbPlotItem::setXRange(double lo, double hi) {
    if (auto* xy = xyPlot()) {
        xy->setXMinimum(lo);
        xy->setXMaximum(hi);
        updatePlot();
    }
}

void PwbPlotItem::setYRange(double lo, double hi) {
    if (auto* xy = xyPlot()) {
        xy->setYMinimum(lo);
        xy->setYMaximum(hi);
        updatePlot();
    }
}

void PwbPlotItem::setFullExtent(double xmin, double xmax, double ymin,
                                double ymax) {
    full_extent_ = std::array{xmin, xmax, ymin, ymax};
}

bool PwbPlotItem::extent(double& xmin, double& xmax, double& ymin,
                         double& ymax) const {
    if (full_extent_) {
        xmin = (*full_extent_)[0];
        xmax = (*full_extent_)[1];
        ymin = (*full_extent_)[2];
        ymax = (*full_extent_)[3];
        return true;
    }
    return dataExtent(xmin, xmax, ymin, ymax);
}

bool PwbPlotItem::dataExtent(double& xmin, double& xmax, double& ymin,
                             double& ymax) const {
    xmin = std::numeric_limits<double>::max();
    ymin = std::numeric_limits<double>::max();
    xmax = std::numeric_limits<double>::lowest();
    ymax = std::numeric_limits<double>::lowest();
    bool any = false;
    for (const QgsAbstractPlotSeries* s : data_->series()) {
        const auto* xy = dynamic_cast<const QgsXyPlotSeries*>(s);
        if (!xy)
            continue;
        for (const auto& [x, y] : xy->data()) {
            if (!std::isfinite(x) || !std::isfinite(y))
                continue;
            xmin = std::min(xmin, x);
            xmax = std::max(xmax, x);
            ymin = std::min(ymin, y);
            ymax = std::max(ymax, y);
            any = true;
        }
    }
    return any;
}

void PwbPlotItem::drawAxisTitles(QPainter* painter, const QRectF& area) {
    if (x_title_.isEmpty() && y_title_.isEmpty() && top_title_.isEmpty())
        return;
    if (area.isEmpty())
        return;
    const QRectF bounds = boundingRect();
    painter->save();
    QFont f = painter->font();
    f.setPointSizeF(f.pointSizeF() * 0.85);
    painter->setFont(f);
    painter->setPen(QColor(60, 60, 60));
    if (!top_title_.isEmpty()) {
        const QRectF r(area.left(), bounds.top(), area.width(), area.top());
        painter->drawText(r, Qt::AlignHCenter | Qt::AlignVCenter, top_title_);
    }
    if (!x_title_.isEmpty()) {
        const QRectF r(area.left(), area.bottom(), area.width(),
                       bounds.bottom() - area.bottom());
        painter->drawText(r, Qt::AlignHCenter | Qt::AlignVCenter, x_title_);
    }
    if (!y_title_.isEmpty()) {
        painter->save();
        painter->translate(area.left(), area.center().y());
        painter->rotate(-90.0);
        const QRectF r(-area.height() / 2.0, -area.left(), area.height(),
                       area.left());
        painter->drawText(r, Qt::AlignHCenter | Qt::AlignVCenter, y_title_);
        painter->restore();
    }
    painter->restore();
}

void PwbPlotItem::paint(QPainter* painter) {
    if (!plot_)
        return;
    if (image_.isNull() && !scene_rect_.isEmpty()) {
        const qreal pixel_ratio = mCanvas->devicePixelRatioF();
        image_ = QImage(scene_rect_.size().toSize() * pixel_ratio,
                        QImage::Format_ARGB32_Premultiplied);
        image_.setDevicePixelRatio(pixel_ratio);
        image_.fill(Qt::transparent);

        QPainter image_painter(&image_);
        image_painter.setRenderHint(QPainter::Antialiasing);
        QgsRenderContext rc = QgsRenderContext::fromQPainter(&image_painter);
        QgsPlotRenderContext plot_ctx;
        if (auto* xy = xyPlot())
            xy->calculateOptimisedIntervals(rc, plot_ctx);
        plot_->render(rc, plot_ctx, *data_);
        const QRectF local_area =
            plot_->interiorPlotArea(rc, plot_ctx, *data_);
        plot_area_ = local_area.translated(pos());
        drawAxisTitles(&image_painter, local_area);
        image_painter.end();
    }
    painter->drawImage(0, 0, image_);
}

void PwbPlotItem::renderToPainter(QPainter* painter, const QRectF& target) {
    if (!plot_)
        return;
    painter->save();
    painter->translate(target.topLeft());
    const QSizeF screen_size = scene_rect_.size();
    plot_->setSize(target.size());
    QgsRenderContext rc = QgsRenderContext::fromQPainter(painter);
    QgsPlotRenderContext plot_ctx;
    if (auto* xy = xyPlot()) {
        // Interval optimisation measures label text; some output devices
        // (notably QPdfWriter) report metrics that make the upstream loop
        // never converge. Compute on a scratch image painter — intervals
        // persist on the axis objects for the real render below.
        QImage scratch(64, 64, QImage::Format_ARGB32);
        QPainter scratch_painter(&scratch);
        QgsRenderContext scratch_rc =
            QgsRenderContext::fromQPainter(&scratch_painter);
        xy->calculateOptimisedIntervals(scratch_rc, plot_ctx);
        scratch_painter.end();
    }
    plot_->render(rc, plot_ctx, *data_);
    drawAxisTitles(painter, plot_->interiorPlotArea(rc, plot_ctx, *data_));
    plot_->setSize(screen_size);
    painter->restore();
}

std::optional<std::pair<int, int>> PwbPlotItem::nearestSeriesPoint(
    QPointF canvas_pos, double radius_px) const {
    const auto* xy = xyPlot();
    if (!xy)
        return std::nullopt;
    const double r2 = radius_px * radius_px;
    double best = r2;
    std::pair<int, int> hit{-1, -1};
    const QList<QgsAbstractPlotSeries*> series = data_->series();
    for (int i = 0; i < series.size(); ++i) {
        const auto* xy_series = dynamic_cast<const QgsXyPlotSeries*>(series[i]);
        if (!xy_series)
            continue;
        const auto data = xy_series->data();
        for (int j = 0; j < data.size(); ++j) {
            if (!std::isfinite(data[j].first) || !std::isfinite(data[j].second))
                continue;
            const QPointF pt = plotToCanvas(data[j].first, data[j].second);
            const double d2 = QPointF::dotProduct(pt - canvas_pos, pt - canvas_pos);
            if (d2 <= best) {
                best = d2;
                hit = {i, j};
            }
        }
    }
    if (hit.first < 0)
        return std::nullopt;
    return hit;
}

QList<std::pair<int, int>> PwbPlotItem::pointsInRect(
    const QRectF& canvas_rect) const {
    QList<std::pair<int, int>> out;
    if (!xyPlot())
        return out;
    const QList<QgsAbstractPlotSeries*> series = data_->series();
    for (int i = 0; i < series.size(); ++i) {
        const auto* xy_series = dynamic_cast<const QgsXyPlotSeries*>(series[i]);
        if (!xy_series)
            continue;
        const auto data = xy_series->data();
        for (int j = 0; j < data.size(); ++j) {
            if (!std::isfinite(data[j].first) || !std::isfinite(data[j].second))
                continue;
            if (canvas_rect.contains(plotToCanvas(data[j].first, data[j].second)))
                out.append({i, j});
        }
    }
    return out;
}

}  // namespace pwb::qgis_plot
