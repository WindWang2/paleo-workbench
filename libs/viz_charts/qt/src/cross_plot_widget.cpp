// 1:1 port of geoviz_plots/chart/cross_plot_widget.py (frozen behavior
// source @0885195) — see cross_plot_widget.hpp.

#include "pwb/viz_charts/qt/cross_plot_widget.hpp"

#include <QBrush>
#include <QFont>
#include <QImage>
#include <QLinearGradient>
#include <QPaintEvent>
#include <QPainter>
#include <QPen>
#include <QPolygonF>
#include <QRectF>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <limits>
#include <utility>

#include "pwb/viz_charts/axes.hpp"
#include "pwb/viz_charts/colormaps.hpp"

namespace pwb::viz_charts::qt {
namespace {

// Per-point QPainter ellipses stay readable for small clouds; larger sets
// are stamped into a QImage so paint stays O(N) (Python constants).
constexpr int kScatterEllipseLimit = 4000;
constexpr QRgb kScatterRgba = qRgba(90, 175, 255, 255);

// np.rint semantics (round half to even under the default FP rounding mode).
int np_rint(double v) {
    return static_cast<int>(std::nearbyint(v));
}

QString format_1f(double val) {
    char buf[48];
    std::snprintf(buf, sizeof(buf), "%.1f", val);
    return QString::fromStdString(buf);
}

}  // namespace

CrossPlotWidget::CrossPlotWidget(QWidget* parent) : QWidget(parent) {
    setMouseTracking(true);
    setFocusPolicy(Qt::StrongFocus);
}

void CrossPlotWidget::set_scatter_data(
    std::vector<double> x, std::vector<double> y,
    std::optional<std::vector<double>> z, QString x_label, QString y_label,
    QString z_label) {
    x_data_ = std::move(x);
    y_data_ = std::move(y);
    z_data_ = std::move(z);

    x_label_ = std::move(x_label);
    y_label_ = std::move(y_label);
    z_label_ = std::move(z_label);

    if (!x_data_.empty()) {
        // A single NaN sample must not poison the whole view bounds
        // (#553): mask non-finite samples like Series.get_bounds.
        double vmin = std::numeric_limits<double>::infinity();
        double vmax = -std::numeric_limits<double>::infinity();
        double ymin = std::numeric_limits<double>::infinity();
        double ymax = -std::numeric_limits<double>::infinity();
        bool any = false;
        const std::size_t n = std::min(x_data_.size(), y_data_.size());
        for (std::size_t i = 0; i < n; ++i) {
            if (!std::isfinite(x_data_[i]) || !std::isfinite(y_data_[i])) {
                continue;
            }
            any = true;
            vmin = std::min(vmin, x_data_[i]);
            vmax = std::max(vmax, x_data_[i]);
            ymin = std::min(ymin, y_data_[i]);
            ymax = std::max(ymax, y_data_[i]);
        }
        if (any) {
            view_xmin_ = vmin;
            view_xmax_ = vmax;
            view_ymin_ = ymin;
            view_ymax_ = ymax;
        }
    }

    clusters_.clear();
    update();
}

void CrossPlotWidget::apply_lasso_polygon(const QVector<QPointF>& lasso_data_pts) {
    if (x_data_.empty() || y_data_.empty()) {
        return;
    }

    std::vector<Point2> poly_verts;
    poly_verts.reserve(static_cast<std::size_t>(lasso_data_pts.size()));
    for (const QPointF& p : lasso_data_pts) {
        poly_verts.push_back(Point2{p.x(), p.y()});
    }
    const std::vector<bool> mask =
        point_in_polygon_mask(x_data_, y_data_, poly_verts);
    QVector<int> indices;
    for (std::size_t i = 0; i < mask.size(); ++i) {
        if (mask[i]) {
            indices.push_back(static_cast<int>(i));
        }
    }

    if (!indices.isEmpty()) {
        std::vector<double> sel_x;
        std::vector<double> sel_y;
        sel_x.reserve(static_cast<std::size_t>(indices.size()));
        sel_y.reserve(static_cast<std::size_t>(indices.size()));
        for (const int idx : indices) {
            sel_x.push_back(x_data_[static_cast<std::size_t>(idx)]);
            sel_y.push_back(y_data_[static_cast<std::size_t>(idx)]);
        }
        const std::vector<Point2> hull_pts =
            compute_convex_hull(sel_x, sel_y);

        Cluster cluster;
        cluster.name = QStringLiteral("Cluster_%1").arg(clusters_.size() + 1);
        cluster.hull = std::move(hull_pts);
        cluster.indices = indices;
        cluster.color = QColor(31, 102, 212, 50);
        clusters_.push_back(std::move(cluster));

        const auto [xmin, xmax] = std::minmax_element(sel_x.begin(), sel_x.end());
        const auto [ymin, ymax] = std::minmax_element(sel_y.begin(), sel_y.end());
        emit points_selected(indices, *xmin, *xmax, *ymin, *ymax);
    }

    update();
}

std::pair<double, double> CrossPlotWidget::z_range(
    const std::vector<double>& z) const {
    double vmin = std::numeric_limits<double>::infinity();
    double vmax = -std::numeric_limits<double>::infinity();
    bool any = false;
    for (const double v : z) {
        if (!std::isfinite(v)) {
            continue;
        }
        any = true;
        vmin = std::min(vmin, v);
        vmax = std::max(vmax, v);
    }
    if (!any) {
        return {0.0, 1.0};
    }
    return {vmin, vmax};
}

std::vector<std::array<unsigned char, 4>> CrossPlotWidget::z_rgba_lut(
    const std::vector<double>& z, double vmin, double vmax) const {
    std::vector<std::array<unsigned char, 4>> rgba;
    rgba.reserve(z.size());

    // 256-entry LUT sampled over [vmin, vmax].
    std::array<std::array<unsigned char, 4>, 256> lut{};
    for (int i = 0; i < 256; ++i) {
        const Rgb c = sample_colormap(
            "viridis", vmin + (vmax - vmin) * (static_cast<double>(i) / 255.0),
            vmin, vmax);
        lut[static_cast<std::size_t>(i)] = {
            static_cast<unsigned char>(c.r),
            static_cast<unsigned char>(c.g),
            static_cast<unsigned char>(c.b),
            static_cast<unsigned char>(255)};
    }
    const double span = std::max(vmax - vmin, 1e-12);
    for (const double v : z) {
        double t = (v - vmin) / span;
        t = std::max(0.0, std::min(1.0, t));
        if (!std::isfinite(v)) {
            t = 0.0;  // np.where(np.isfinite(z), t, 0.0)
        }
        const int idx = np_rint(t * 255.0);
        rgba.push_back(lut[static_cast<std::size_t>(idx)]);
    }
    return rgba;
}

void CrossPlotWidget::blit_scatter_points(
    QPainter* painter, const std::vector<double>& px,
    const std::vector<double>& py, int width, int height,
    const std::vector<std::array<unsigned char, 4>>* rgba) {
    // Stamp in-view samples into one QImage (3×3 neighbourhood).
    QImage image(width, height, QImage::Format_RGBA8888);
    image.fill(Qt::transparent);
    const std::size_t n = std::min(px.size(), py.size());
    for (std::size_t j = 0; j < n; ++j) {
        const int ix = np_rint(px[j]);
        const int iy = np_rint(py[j]);
        const QRgb color =
            rgba != nullptr
                ? qRgba((*rgba)[j][0], (*rgba)[j][1], (*rgba)[j][2], 255)
                : kScatterRgba;
        for (int dx = -1; dx <= 1; ++dx) {
            for (int dy = -1; dy <= 1; ++dy) {
                const int xx = ix + dx;
                const int yy = iy + dy;
                if (xx >= 0 && xx < width && yy >= 0 && yy < height) {
                    image.setPixel(xx, yy, color);
                }
            }
        }
    }
    painter->drawImage(0, 0, image);
}

void CrossPlotWidget::draw_axes(QPainter* painter, const QRectF& plot_rect) {
    const auto [x_ticks, x_step] = calculate_ticks(view_xmin_, view_xmax_, 6);
    const auto [y_ticks, y_step] = calculate_ticks(view_ymin_, view_ymax_, 6);
    const double x_span = std::max(1e-6, view_xmax_ - view_xmin_);
    const double y_span = std::max(1e-6, view_ymax_ - view_ymin_);

    const auto to_p = [&](double x_val, double y_val) -> QPointF {
        const double px =
            plot_rect.left() +
            (x_val - view_xmin_) / x_span * plot_rect.width();
        const double py =
            plot_rect.bottom() -
            (y_val - view_ymin_) / y_span * plot_rect.height();
        return QPointF(px, py);
    };

    const QPen axis_pen(QColor(180, 180, 180), 1);
    const QPen grid_pen(QColor(50, 50, 50), 1, Qt::DashLine);
    painter->setFont(QFont("SansSerif", 8));
    const QFontMetrics metrics = painter->fontMetrics();
    const QColor text_color(210, 210, 210);

    painter->setPen(grid_pen);
    for (const double xt : x_ticks) {
        if (view_xmin_ <= xt && xt <= view_xmax_) {
            const QPointF p = to_p(xt, view_ymin_);
            painter->drawLine(
                QLineF(p.x(), plot_rect.top(), p.x(), plot_rect.bottom()));
        }
    }
    for (const double yt : y_ticks) {
        if (view_ymin_ <= yt && yt <= view_ymax_) {
            const QPointF p = to_p(view_xmin_, yt);
            painter->drawLine(
                QLineF(plot_rect.left(), p.y(), plot_rect.right(), p.y()));
        }
    }

    painter->setPen(axis_pen);
    for (const double xt : x_ticks) {
        if (view_xmin_ <= xt && xt <= view_xmax_) {
            const QPointF p = to_p(xt, view_ymin_);
            painter->drawLine(QLineF(p.x(), plot_rect.bottom(), p.x(),
                                     plot_rect.bottom() + 4.0));
            const QString label =
                QString::fromStdString(format_tick(xt, x_step));
            painter->setPen(text_color);
            painter->drawText(
                QPointF(p.x() -
                            static_cast<double>(
                                metrics.horizontalAdvance(label)) / 2.0,
                        plot_rect.bottom() + 16.0),
                label);
            painter->setPen(axis_pen);
        }
    }
    for (const double yt : y_ticks) {
        if (view_ymin_ <= yt && yt <= view_ymax_) {
            const QPointF p = to_p(view_xmin_, yt);
            painter->drawLine(
                QLineF(plot_rect.left() - 4.0, p.y(), plot_rect.left(), p.y()));
            const QString label =
                QString::fromStdString(format_tick(yt, y_step));
            painter->setPen(text_color);
            painter->drawText(
                QPointF(plot_rect.left() -
                            static_cast<double>(
                                metrics.horizontalAdvance(label)) -
                            8.0,
                        p.y() + 4.0),
                label);
            painter->setPen(axis_pen);
        }
    }

    painter->setPen(text_color);
    if (!x_label_.isEmpty()) {
        const double lw = static_cast<double>(metrics.horizontalAdvance(x_label_));
        painter->drawText(
            QPointF(plot_rect.center().x() - lw / 2.0, plot_rect.bottom() + 34.0),
            x_label_);
    }
    if (!y_label_.isEmpty()) {
        painter->save();
        painter->translate(
            14.0, plot_rect.center().y() +
                      static_cast<double>(metrics.horizontalAdvance(y_label_)) /
                          2.0);
        painter->rotate(-90.0);
        painter->drawText(QPointF(0.0, 0.0), y_label_);
        painter->restore();
    }
}

void CrossPlotWidget::draw_z_colorbar(QPainter* painter,
                                      const QRectF& plot_rect, double vmin,
                                      double vmax) {
    const QRectF bar(plot_rect.right() + 10.0, plot_rect.top(), 12.0,
                     plot_rect.height());
    QLinearGradient grad(bar.left(), bar.bottom(), bar.left(), bar.top());
    for (const auto& [pos, rgb] : colormap("viridis")) {
        grad.setColorAt(pos, QColor(rgb.r, rgb.g, rgb.b));
    }
    painter->setBrush(QBrush(grad));
    painter->setPen(QPen(QColor(88, 104, 120), 1));
    painter->drawRect(bar);
    painter->setPen(QColor(210, 210, 210));
    painter->setFont(QFont("SansSerif", 8));
    const QFontMetrics metrics = painter->fontMetrics();
    const std::pair<double, double> ends[2] = {{0.0, vmin}, {1.0, vmax}};
    for (const auto& [frac, val] : ends) {
        const double py = bar.bottom() - frac * bar.height();
        painter->drawText(
            QPointF(bar.right() + 4.0,
                    py + static_cast<double>(metrics.height()) / 4.0),
            format_1f(val));
    }
    if (!z_label_.isEmpty()) {
        painter->save();
        painter->translate(
            bar.right() + 28.0,
            plot_rect.center().y() +
                static_cast<double>(metrics.horizontalAdvance(z_label_)) / 2.0);
        painter->rotate(-90.0);
        painter->drawText(QPointF(0.0, 0.0), z_label_);
        painter->restore();
    }
}

void CrossPlotWidget::paintEvent(QPaintEvent* event) {
    Q_UNUSED(event);
    QPainter painter(this);
    painter.setRenderHint(QPainter::Antialiasing);

    const int w = width();
    const int h = height();
    painter.fillRect(0, 0, w, h, QColor(25, 25, 25));

    // Canvas bounds.
    const QRectF plot_rect(
        static_cast<double>(margin_left_), static_cast<double>(margin_top_),
        w - static_cast<double>(margin_left_) -
            static_cast<double>(margin_right_),
        h - static_cast<double>(margin_top_) -
            static_cast<double>(margin_bottom_));
    painter.fillRect(plot_rect, QColor(15, 15, 15));
    painter.setPen(QPen(QColor(88, 104, 120), 1));
    painter.drawRect(plot_rect);

    if (x_data_.empty()) {
        draw_axes(&painter, plot_rect);
        return;
    }

    const double x_span = std::max(1e-6, view_xmax_ - view_xmin_);
    const double y_span = std::max(1e-6, view_ymax_ - view_ymin_);

    // Map scatter points to pixels, keeping the pixel-finite subset (and
    // its z slice) like the numpy boolean masks.
    std::vector<double> px;
    std::vector<double> py;
    std::vector<double> z_view;
    const bool has_z =
        z_data_.has_value() && z_data_->size() == x_data_.size();
    {
        const std::size_t n = std::min(x_data_.size(), y_data_.size());
        px.reserve(n);
        py.reserve(n);
        if (has_z) {
            z_view.reserve(n);
        }
        for (std::size_t i = 0; i < n; ++i) {
            const double p_x =
                plot_rect.left() +
                (x_data_[i] - view_xmin_) / x_span * plot_rect.width();
            const double p_y =
                plot_rect.bottom() -
                (y_data_[i] - view_ymin_) / y_span * plot_rect.height();
            if (!std::isfinite(p_x) || !std::isfinite(p_y)) {
                continue;
            }
            px.push_back(p_x);
            py.push_back(p_y);
            if (has_z) {
                z_view.push_back((*z_data_)[i]);
            }
        }
    }

    // Keep only points inside the plot rectangle.
    std::vector<double> in_px;
    std::vector<double> in_py;
    std::vector<double> in_z;
    in_px.reserve(px.size());
    in_py.reserve(px.size());
    in_z.reserve(z_view.size());
    for (std::size_t i = 0; i < px.size(); ++i) {
        if (px[i] >= plot_rect.left() && px[i] <= plot_rect.right() &&
            py[i] >= plot_rect.top() && py[i] <= plot_rect.bottom()) {
            in_px.push_back(px[i]);
            in_py.push_back(py[i]);
            if (has_z) {
                in_z.push_back(z_view[i]);
            }
        }
    }

    bool has_z_view = false;
    double zmin = 0.0;
    double zmax = 1.0;
    std::vector<std::array<unsigned char, 4>> rgba;
    if (has_z && !in_z.empty()) {
        const auto [lo, hi] = z_range(in_z);
        zmin = lo;
        zmax = hi;
        has_z_view = true;
        rgba = z_rgba_lut(in_z, zmin, zmax);
    }

    if (static_cast<int>(in_px.size()) <= kScatterEllipseLimit) {
        painter.setPen(Qt::NoPen);
        if (!has_z_view) {
            painter.setBrush(QBrush(QColor(90, 175, 255)));
            for (std::size_t i = 0; i < in_px.size(); ++i) {
                painter.drawEllipse(QPointF(in_px[i], in_py[i]), 3.0, 3.0);
            }
        } else {
            for (std::size_t i = 0; i < in_px.size(); ++i) {
                painter.setBrush(QBrush(QColor(rgba[i][0], rgba[i][1],
                                                rgba[i][2])));
                painter.drawEllipse(QPointF(in_px[i], in_py[i]), 3.0, 3.0);
            }
        }
    } else {
        blit_scatter_points(&painter, in_px, in_py, w, h,
                            has_z_view ? &rgba : nullptr);
    }

    // Draw cluster convex hulls.
    for (const auto& c : clusters_) {
        if (c.hull.size() >= 3) {
            QPolygonF poly;
            poly.reserve(static_cast<int>(c.hull.size()));
            for (const Point2& pt : c.hull) {
                const double h_px =
                    plot_rect.left() +
                    (pt.x - view_xmin_) / x_span * plot_rect.width();
                const double h_py =
                    plot_rect.bottom() -
                    (pt.y - view_ymin_) / y_span * plot_rect.height();
                poly.append(QPointF(h_px, h_py));
            }
            painter.setPen(QPen(QColor(31, 102, 212), 2));
            painter.setBrush(QBrush(c.color));
            painter.drawPolygon(poly);
        }
    }

    draw_axes(&painter, plot_rect);
    if (has_z_view) {
        draw_z_colorbar(&painter, plot_rect, zmin, zmax);
    }
}

}  // namespace pwb::viz_charts::qt
