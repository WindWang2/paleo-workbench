// 1:1 port of geoviz_plots/chart/plot_widget.py (frozen behavior source
// @0885195) — see plot_widget.hpp for the Python→C++ mapping notes.

#include "pwb/viz_charts/qt/plot_widget.hpp"

#include <QApplication>
#include <QBrush>
#include <QFont>
#include <QFontMetrics>
#include <QMouseEvent>
#include <QPageSize>
#include <QPaintEvent>
#include <QPainter>
#include <QPen>
#include <QPolygonF>
#include <QPrinter>
#include <QResizeEvent>
#include <QSvgGenerator>
#include <QWheelEvent>

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <utility>

#include "pwb/viz_charts/axes.hpp"
#include "pwb/viz_charts/series.hpp"

namespace pwb::viz_charts::qt {

PlotWidget::PlotWidget(QWidget* parent) : QWidget(parent) {
    setMouseTracking(true);
    setFocusPolicy(Qt::StrongFocus);
}

// -- series management -------------------------------------------------------

void PlotWidget::add_series(std::unique_ptr<SeriesData> series) {
    series_list_.push_back(std::move(series));
    update();
}

void PlotWidget::clear() {
    invalidate_hover();
    clear_last_click();
    last_mouse_pos_.reset();
    press_pos_.reset();
    dragged_since_press_ = false;
    series_list_.clear();
    highlighted_points_.clear();
    selected_point_.reset();
    selected_label_.clear();
    autofit_bounds_.reset();
    full_view_bounds_.reset();
    update();
}

// -- viewport ------------------------------------------------------------------

void PlotWidget::set_equal_aspect(bool enabled) {
    equal_aspect_ = enabled;
    if (!equal_aspect_) {
        return;
    }
    if (autofit_bounds_.has_value()) {
        full_view_bounds_ = equalized_bounds(*autofit_bounds_);
    }
    apply_view(equalized_bounds(current_view()));
}

void PlotWidget::autofit() {
    if (series_list_.empty()) {
        autofit_bounds_ = View{0.0, 1.0, 0.0, 1.0};
        full_view_bounds_ = view_for_current_aspect(*autofit_bounds_);
        apply_view(*full_view_bounds_);
        return;
    }

    double g_xmin = std::numeric_limits<double>::infinity();
    double g_xmax = -std::numeric_limits<double>::infinity();
    double g_ymin = std::numeric_limits<double>::infinity();
    double g_ymax = -std::numeric_limits<double>::infinity();

    bool has_data = false;
    for (const auto& s : series_list_) {
        if (!s->visible) {
            continue;
        }
        const Bounds b = series_bounds(s->x, s->y);
        if (b.xmin == 0.0 && b.xmax == 0.0 && b.ymin == 0.0 && b.ymax == 0.0 &&
            s->x.empty()) {
            continue;
        }
        has_data = true;
        g_xmin = std::min(g_xmin, b.xmin);
        g_xmax = std::max(g_xmax, b.xmax);
        g_ymin = std::min(g_ymin, b.ymin);
        g_ymax = std::max(g_ymax, b.ymax);
    }

    if (!has_data) {
        autofit_bounds_ = View{0.0, 1.0, 0.0, 1.0};
        full_view_bounds_ = view_for_current_aspect(*autofit_bounds_);
        apply_view(*full_view_bounds_);
        return;
    }

    // Add 5% padding.
    double dx = g_xmax - g_xmin;
    double dy = g_ymax - g_ymin;
    if (dx == 0.0) {
        dx = (g_xmin != 0.0) ? std::abs(g_xmin) * 0.1 : 1.0;
    }
    if (dy == 0.0) {
        dy = (g_ymin != 0.0) ? std::abs(g_ymin) * 0.1 : 1.0;
    }

    autofit_bounds_ = View{g_xmin - 0.05 * dx, g_xmax + 0.05 * dx,
                           g_ymin - 0.05 * dy, g_ymax + 0.05 * dy};
    full_view_bounds_ = view_for_current_aspect(*autofit_bounds_);
    apply_view(*full_view_bounds_);
}

void PlotWidget::focus_point(double x, double y, double zoom_factor) {
    // Python raises ValueError for zoom_factor <= 0.
    if (zoom_factor <= 0.0) {
        throw std::invalid_argument("zoom_factor must be positive");
    }
    if (!full_view_bounds_.has_value()) {
        autofit();
    }
    const auto [full_xmin, full_xmax, full_ymin, full_ymax] = *full_view_bounds_;
    const double half_width = (full_xmax - full_xmin) / (2.0 * zoom_factor);
    const double half_height = (full_ymax - full_ymin) / (2.0 * zoom_factor);
    apply_view(View{x - half_width, x + half_width, y - half_height,
                    y + half_height});
}

void PlotWidget::reset_view() {
    if (!full_view_bounds_.has_value()) {
        autofit();
        return;
    }
    apply_view(*full_view_bounds_);
}

std::tuple<double, double, double, double> PlotWidget::view_bounds() const {
    const View v = current_view();
    return {v[0], v[1], v[2], v[3]};
}

void PlotWidget::set_view_bounds(double xmin, double xmax, double ymin,
                                 double ymax) {
    const double values[4] = {xmin, xmax, ymin, ymax};
    for (const double value : values) {
        if (!std::isfinite(value)) {
            throw std::invalid_argument(
                "view bounds must be finite increasing ranges");
        }
    }
    if (values[0] >= values[1] || values[2] >= values[3]) {
        throw std::invalid_argument(
            "view bounds must be finite increasing ranges");
    }
    apply_view(View{values[0], values[1], values[2], values[3]});
}

void PlotWidget::set_axis_labels(const QString& x_label,
                                 const QString& y_label) {
    x_axis_label_ = x_label;
    y_axis_label_ = y_label;
    update();
}

std::pair<QString, QString> PlotWidget::axis_labels() const {
    return {x_axis_label_, y_axis_label_};
}

PlotWidget::View PlotWidget::current_view() const {
    return View{view_xmin_, view_xmax_, view_ymin_, view_ymax_};
}

PlotWidget::View PlotWidget::view_for_current_aspect(const View& bounds) const {
    if (!equal_aspect_) {
        return bounds;
    }
    return equalized_bounds(bounds);
}

PlotWidget::View PlotWidget::equalized_bounds(const View& bounds) const {
    const auto [xmin, xmax, ymin, ymax] = bounds;
    const auto [left, right, top, bottom] = get_plot_rect(width(), height());
    const double plot_width = std::max(1.0, right - left);
    const double plot_height = std::max(1.0, bottom - top);
    const double units_per_pixel =
        std::max((xmax - xmin) / plot_width, (ymax - ymin) / plot_height);
    const double center_x = (xmin + xmax) / 2.0;
    const double center_y = (ymin + ymax) / 2.0;
    const double half_width = units_per_pixel * plot_width / 2.0;
    const double half_height = units_per_pixel * plot_height / 2.0;
    return View{center_x - half_width, center_x + half_width,
                center_y - half_height, center_y + half_height};
}

void PlotWidget::apply_view(const View& bounds) {
    invalidate_hover();
    std::tie(view_xmin_, view_xmax_, view_ymin_, view_ymax_) =
        std::make_tuple(bounds[0], bounds[1], bounds[2], bounds[3]);
    emit view_changed(view_xmin_, view_xmax_, view_ymin_, view_ymax_);
    update();
}

std::tuple<double, double, double, double> PlotWidget::get_plot_rect(
    int width, int height) const {
    return {static_cast<double>(margin_left_), width - static_cast<double>(margin_right_),
            static_cast<double>(margin_top_), height - static_cast<double>(margin_bottom_)};
}

std::pair<double, double> PlotWidget::data_to_pixel(double x, double y) const {
    const auto [left, right, top, bottom] = get_plot_rect(width(), height());
    const double plot_w = right - left;
    const double plot_h = bottom - top;

    double x_range = view_xmax_ - view_xmin_;
    double y_range = view_ymax_ - view_ymin_;
    if (x_range == 0.0) {
        x_range = 1.0;
    }
    if (y_range == 0.0) {
        y_range = 1.0;
    }

    const double px = left + (x - view_xmin_) / x_range * plot_w;
    const double py = bottom - (y - view_ymin_) / y_range * plot_h;
    return {px, py};
}

std::pair<double, double> PlotWidget::pixel_to_data(double px, double py) const {
    const auto [left, right, top, bottom] = get_plot_rect(width(), height());
    double plot_w = right - left;
    double plot_h = bottom - top;

    const double x_range = view_xmax_ - view_xmin_;
    const double y_range = view_ymax_ - view_ymin_;

    if (plot_w == 0.0) {
        plot_w = 1.0;
    }
    if (plot_h == 0.0) {
        plot_h = 1.0;
    }

    const double x = view_xmin_ + (px - left) / plot_w * x_range;
    const double y = view_ymin_ + (bottom - py) / plot_h * y_range;
    return {x, y};
}

void PlotWidget::pan(double dpx, double dpy) {
    const auto [left, right, top, bottom] = get_plot_rect(width(), height());
    const double plot_w = right - left;
    const double plot_h = bottom - top;

    if (plot_w <= 0.0 || plot_h <= 0.0) {
        return;
    }

    const double x_range = view_xmax_ - view_xmin_;
    const double y_range = view_ymax_ - view_ymin_;

    const double dx = (dpx / plot_w) * x_range;
    const double dy = -(dpy / plot_h) * y_range;

    invalidate_hover();
    view_xmin_ -= dx;
    view_xmax_ -= dx;
    view_ymin_ -= dy;
    view_ymax_ -= dy;

    emit view_changed(view_xmin_, view_xmax_, view_ymin_, view_ymax_);
    update();
}

void PlotWidget::zoom(double factor, double cx, double cy) {
    if (factor <= 0.0) {
        return;
    }

    invalidate_hover();
    view_xmin_ = cx - (cx - view_xmin_) / factor;
    view_xmax_ = cx + (view_xmax_ - cx) / factor;
    view_ymin_ = cy - (cy - view_ymin_) / factor;
    view_ymax_ = cy + (view_ymax_ - cy) / factor;

    emit view_changed(view_xmin_, view_xmax_, view_ymin_, view_ymax_);
    update();
}

// -- inter-page data linking ----------------------------------------------------

void PlotWidget::set_selected_point(const QString& series_name, int index,
                                    const QString& label) {
    const auto it = std::find_if(series_list_.begin(), series_list_.end(),
                                 [&](const std::unique_ptr<SeriesData>& s) {
                                     return s->name == series_name;
                                 });
    if (it == series_list_.end()) {
        throw std::invalid_argument("unknown series: " +
                                    series_name.toStdString());
    }
    if (index < 0 || static_cast<std::size_t>(index) >= (*it)->x.size()) {
        throw std::out_of_range("point index out of range: " +
                                std::to_string(index));
    }
    selected_point_ = PointRef{series_name, index};
    selected_label_ = label;
    update();
}

void PlotWidget::clear_selected_point() {
    selected_point_.reset();
    selected_label_.clear();
    update();
}

void PlotWidget::highlight_point(const QString& series_name, int index) {
    highlighted_points_[series_name].insert(index);
    update();
}

void PlotWidget::clear_highlights() {
    highlighted_points_.clear();
    update();
}

// -- interaction events ---------------------------------------------------------

void PlotWidget::mousePressEvent(QMouseEvent* event) {
    if (event->button() == Qt::LeftButton || event->button() == Qt::MiddleButton) {
        last_mouse_pos_ = event->position();
        press_pos_ = event->position();
        dragged_since_press_ = false;
    }
}

void PlotWidget::mouseMoveEvent(QMouseEvent* event) {
    const QPointF curr_pos = event->position();
    const auto [left, right, top, bottom] = get_plot_rect(width(), height());

    // Panning (Python compares the full button mask for exact equality).
    const Qt::MouseButtons buttons = event->buttons();
    if ((buttons == Qt::LeftButton || buttons == Qt::MiddleButton) &&
        last_mouse_pos_.has_value()) {
        if (press_pos_.has_value()) {
            const double drag_distance =
                std::abs(curr_pos.x() - press_pos_->x()) +
                std::abs(curr_pos.y() - press_pos_->y());
            if (drag_distance >= 4.0) {
                dragged_since_press_ = true;
            }
        }
        const double dpx = curr_pos.x() - last_mouse_pos_->x();
        const double dpy = curr_pos.y() - last_mouse_pos_->y();
        pan(dpx, dpy);
        last_mouse_pos_ = curr_pos;
        return;
    }

    // Hover / tracking.
    if (left <= curr_pos.x() && curr_pos.x() <= right && top <= curr_pos.y() &&
        curr_pos.y() <= bottom) {
        hover_pos_ = curr_pos;
        check_nearest_point(curr_pos);
    } else {
        hover_pos_.reset();
        clear_hovered_point();
    }

    update();
}

void PlotWidget::mouseReleaseEvent(QMouseEvent* event) {
    if (event->button() == Qt::LeftButton) {
        if (!dragged_since_press_) {
            const auto hit = check_nearest_point(event->position());
            last_click_pos_ = event->position();
            last_click_hit_ = hit;
            last_click_time_ = std::chrono::steady_clock::now();
            if (hit.has_value()) {
                emit point_clicked(hit->series_name, hit->index, hit->x,
                                   hit->y);
            }
        } else {
            clear_last_click();
        }
    }
    last_mouse_pos_.reset();
    press_pos_.reset();
    dragged_since_press_ = false;
}

void PlotWidget::wheelEvent(QWheelEvent* event) {
    const QPointF curr_pos = event->position();
    const auto [left, right, top, bottom] = get_plot_rect(width(), height());
    if (!(left <= curr_pos.x() && curr_pos.x() <= right &&
          top <= curr_pos.y() && curr_pos.y() <= bottom)) {
        return;
    }

    const auto [cx, cy] = pixel_to_data(curr_pos.x(), curr_pos.y());
    const int angle = event->angleDelta().y();
    const double factor = angle > 0 ? 1.15 : 1.0 / 1.15;
    zoom(factor, cx, cy);
}

void PlotWidget::mouseDoubleClickEvent(QMouseEvent* event) {
    if (event->button() != Qt::LeftButton) {
        return;
    }
    const auto hit = check_nearest_point(event->position());
    const bool previous_point_hit =
        double_click_started_on_point(event->position());
    clear_last_click();
    if (!hit.has_value() && !previous_point_hit) {
        reset_view();
        emit reset_requested();
    }
}

bool PlotWidget::double_click_started_on_point(const QPointF& position) const {
    if (!last_click_hit_.has_value() || !last_click_pos_.has_value()) {
        return false;
    }
    QApplication* application =
        qobject_cast<QApplication*>(QCoreApplication::instance());
    const double interval_seconds =
        application != nullptr
            ? static_cast<double>(application->doubleClickInterval()) / 1000.0
            : 0.5;
    const double elapsed =
        std::chrono::duration<double>(std::chrono::steady_clock::now() -
                                      last_click_time_)
            .count();
    const double distance =
        std::hypot(position.x() - last_click_pos_->x(),
                   position.y() - last_click_pos_->y());
    return elapsed <= interval_seconds && distance < 4.0;
}

void PlotWidget::clear_last_click() {
    last_click_pos_.reset();
    last_click_hit_.reset();
    last_click_time_ = {};
}

void PlotWidget::leaveEvent(QEvent* event) {
    invalidate_hover();
    QWidget::leaveEvent(event);
}

void PlotWidget::resizeEvent(QResizeEvent* event) {
    if (equal_aspect_ && autofit_bounds_.has_value()) {
        const View current = current_view();
        const std::optional<View> previous_full_view = full_view_bounds_;
        full_view_bounds_ = equalized_bounds(*autofit_bounds_);
        if (!previous_full_view.has_value()) {
            apply_view(*full_view_bounds_);
        } else {
            const double current_width = current[1] - current[0];
            const double current_height = current[3] - current[2];
            const double zoom_factor =
                std::max((previous_full_view->at(1) - previous_full_view->at(0)) /
                             std::max(current_width,
                                      std::numeric_limits<double>::epsilon()),
                         (previous_full_view->at(3) - previous_full_view->at(2)) /
                             std::max(current_height,
                                      std::numeric_limits<double>::epsilon()));
            const double center_x = (current[0] + current[1]) / 2.0;
            const double center_y = (current[2] + current[3]) / 2.0;
            const double half_width =
                (full_view_bounds_->at(1) - full_view_bounds_->at(0)) /
                (2.0 * zoom_factor);
            const double half_height =
                (full_view_bounds_->at(3) - full_view_bounds_->at(2)) /
                (2.0 * zoom_factor);
            apply_view(View{center_x - half_width, center_x + half_width,
                            center_y - half_height, center_y + half_height});
        }
    }
    QWidget::resizeEvent(event);
}

// -- hover snapping ----------------------------------------------------------------

std::optional<PlotWidget::PointHit> PlotWidget::check_nearest_point(
    const QPointF& mouse_pos) {
    // Activation radius in pixels. Linear pixel-space scan — identical to
    // the Python no-scipy numpy fallback (strict <, first point wins ties).
    double closest_dist = 15.0;
    std::optional<PointHit> closest_pt;

    const auto [left, right, top, bottom] = get_plot_rect(width(), height());
    const double plot_w = std::max(right - left, 1.0);
    const double plot_h = std::max(bottom - top, 1.0);
    double x_range = view_xmax_ - view_xmin_;
    double y_range = view_ymax_ - view_ymin_;
    if (x_range == 0.0) {
        x_range = 1.0;
    }
    if (y_range == 0.0) {
        y_range = 1.0;
    }
    const double mx = mouse_pos.x();
    const double my = mouse_pos.y();

    for (const auto& s : series_list_) {
        if (!s->visible || s->x.empty()) {
            continue;
        }
        const std::size_t n = std::min(s->x.size(), s->y.size());
        for (std::size_t i = 0; i < n; ++i) {
            const double xv = s->x[i];
            const double yv = s->y[i];
            if (std::isnan(xv) || std::isnan(yv)) {
                continue;
            }
            const double px = left + (xv - view_xmin_) / x_range * plot_w;
            const double py = bottom - (yv - view_ymin_) / y_range * plot_h;
            const double dist = std::hypot(mx - px, my - py);
            if (dist < closest_dist) {
                closest_dist = dist;
                closest_pt = PointHit{s->name, static_cast<int>(i), xv, yv};
            }
        }
    }

    if (closest_pt.has_value()) {
        if (!hovered_point_.has_value() ||
            hovered_point_->first != closest_pt->series_name ||
            hovered_point_->second != closest_pt->index) {
            hovered_point_ = PointRef{closest_pt->series_name,
                                      closest_pt->index};
            emit point_hovered(closest_pt->series_name, closest_pt->index,
                               closest_pt->x, closest_pt->y);
        }
    } else {
        clear_hovered_point();
    }
    return closest_pt;
}

void PlotWidget::clear_hovered_point() {
    if (!hovered_point_.has_value()) {
        return;
    }
    hovered_point_.reset();
    emit point_hover_cleared();
}

void PlotWidget::invalidate_hover() {
    hover_pos_.reset();
    clear_hovered_point();
}

std::optional<std::pair<double, double>> PlotWidget::resolve_point(
    const std::optional<PointRef>& reference) const {
    if (!reference.has_value()) {
        return std::nullopt;
    }
    const auto& [series_name, index] = *reference;
    const auto it = std::find_if(series_list_.begin(), series_list_.end(),
                                 [&](const std::unique_ptr<SeriesData>& s) {
                                     return s->name == series_name;
                                 });
    if (it == series_list_.end() ||
        static_cast<std::size_t>(index) >= (*it)->x.size() || index < 0) {
        return std::nullopt;
    }
    return std::make_pair((*it)->x[static_cast<std::size_t>(index)],
                          (*it)->y[static_cast<std::size_t>(index)]);
}

void PlotWidget::draw_point_indicator(
    QPainter* painter, const std::function<QPointF(double, double)>& to_pixel,
    const std::optional<PointRef>& reference, const QPen& pen,
    const QBrush& brush, const std::vector<double>& radii,
    const QString& label) {
    const auto point = resolve_point(reference);
    if (!point.has_value()) {
        return;
    }
    const QPointF p = to_pixel(point->first, point->second);
    painter->save();
    painter->setPen(pen);
    painter->setBrush(brush);
    for (const double radius : radii) {
        painter->drawEllipse(p, radius, radius);
    }
    if (!label.isEmpty()) {
        painter->setFont(QFont("Arial", 9, QFont::Bold));
        painter->setPen(highlight_color_);
        painter->drawText(QPointF(p.x() + 16.0, p.y() - 12.0), label);
    }
    painter->restore();
}

// -- vector export ------------------------------------------------------------------

void PlotWidget::export_svg(const QString& filepath) {
    export_svg(filepath, size());
}

void PlotWidget::export_pdf(const QString& filepath) {
    QPrinter printer(QPrinter::HighResolution);
    printer.setOutputFormat(QPrinter::PdfFormat);
    printer.setOutputFileName(filepath);
    printer.setPageSize(QPageSize(QPageSize::A4));

    // Use full page dimensions.
    const QRectF page_rect = printer.pageRect(QPrinter::DevicePixel);

    QPainter painter(&printer);
    painter.setRenderHint(QPainter::Antialiasing);
    render_plot(&painter, static_cast<int>(page_rect.width()),
                static_cast<int>(page_rect.height()));
    painter.end();
}

void PlotWidget::export_svg(const QString& filepath, QSize canvas) {
    if (canvas.isEmpty()) {
        canvas = QSize(900, 600);  // never-laid-out host: degenerate canvas guard
    }
    QSvgGenerator generator;
    generator.setFileName(filepath);
    generator.setSize(canvas);
    generator.setViewBox(QRect(QPoint(0, 0), canvas));
    generator.setTitle(QStringLiteral("GeoViz Plot - ") + windowTitle());
    generator.setDescription(
        QStringLiteral("Generated by GeoViz Engine QPainter plotting core."));

    QPainter painter(&generator);
    painter.setRenderHint(QPainter::Antialiasing);
    render_plot(&painter, canvas.width(), canvas.height());
    painter.end();
}

void PlotWidget::export_pdf(const QString& filepath, QSize canvas) {
    Q_UNUSED(canvas);  // PDF always renders the full A4 page (Python parity)
    export_pdf(filepath);
}

// -- core paint & rendering core ------------------------------------------------------

void PlotWidget::paintEvent(QPaintEvent* event) {
    Q_UNUSED(event);
    QPainter painter(this);
    painter.setRenderHint(QPainter::Antialiasing);
    render_plot(&painter, width(), height());
}

void PlotWidget::render_plot(QPainter* painter, int width_v, int height_v) {
    // 1. Fill entire widget background.
    painter->fillRect(0, 0, width_v, height_v, bg_color_);

    const auto [left, right, top, bottom] = get_plot_rect(width_v, height_v);
    const double plot_w = right - left;
    const double plot_h = bottom - top;

    if (plot_w <= 0.0 || plot_h <= 0.0) {
        return;
    }

    // 2. Draw interior plot background.
    painter->fillRect(QRectF(left, top, plot_w, plot_h), plot_bg_color_);

    // Calculate nice ticks for X and Y.
    const auto [x_ticks, x_step] = calculate_ticks(view_xmin_, view_xmax_, 6);
    const auto [y_ticks, y_step] = calculate_ticks(view_ymin_, view_ymax_, 6);

    // Helper converting data coordinates inside the render engine size.
    const auto to_p = [&](double x_val, double y_val) -> QPointF {
        double x_r = view_xmax_ - view_xmin_;
        double y_r = view_ymax_ - view_ymin_;
        if (x_r == 0.0) {
            x_r = 1.0;
        }
        if (y_r == 0.0) {
            y_r = 1.0;
        }
        return QPointF(left + (x_val - view_xmin_) / x_r * plot_w,
                       bottom - (y_val - view_ymin_) / y_r * plot_h);
    };

    // 3. Draw grid lines (only ticks inside the current view).
    const QPen grid_pen(grid_color_, 1, Qt::DashLine);
    painter->setPen(grid_pen);

    for (const double xt : x_ticks) {
        if (view_xmin_ <= xt && xt <= view_xmax_) {
            const QPointF p = to_p(xt, view_ymin_);
            painter->drawLine(QLineF(p.x(), top, p.x(), bottom));
        }
    }

    for (const double yt : y_ticks) {
        if (view_ymin_ <= yt && yt <= view_ymax_) {
            const QPointF p = to_p(view_xmin_, yt);
            painter->drawLine(QLineF(left, p.y(), right, p.y()));
        }
    }

    // 4. Render series data (clipped so off-view strokes stay in frame).
    painter->save();
    painter->setClipRect(QRectF(left, top, plot_w, plot_h));
    for (const auto& s : series_list_) {
        if (!s->visible || s->x.empty()) {
            continue;
        }

        // LTTB downsampling for huge series protects the UI from lockups.
        bool downsampled = false;
        const std::vector<double>* sx = &s->x;
        const std::vector<double>* sy = &s->y;
        std::vector<double> ds_x;
        std::vector<double> ds_y;
        if (static_cast<int>(s->x.size()) > downsample_threshold) {
            DownsampleResult ds =
                lttb_downsample(s->x, s->y, downsample_threshold);
            ds_x = std::move(ds.x);
            ds_y = std::move(ds.y);
            sx = &ds_x;
            sy = &ds_y;
            downsampled = true;
        }

        // Break paths when encountering NaN values.
        if (const auto* line = dynamic_cast<const LineSeriesData*>(s.get())) {
            const QPen line_pen(line->color, line->width, line->style);
            painter->setPen(line_pen);

            QPolygonF poly;
            const std::size_t n = std::min(sx->size(), sy->size());
            for (std::size_t i = 0; i < n; ++i) {
                const double x_val = (*sx)[i];
                const double y_val = (*sy)[i];
                if (std::isnan(x_val) || std::isnan(y_val)) {
                    if (poly.size() > 1) {
                        painter->drawPolyline(poly);
                    }
                    poly.clear();
                    continue;
                }
                poly.append(to_p(x_val, y_val));
            }
            if (poly.size() > 1) {
                painter->drawPolyline(poly);
            }

            // Draw markers for LineSeries if specified.
            if (line->marker_size > 0.0 && line->marker_style != QLatin1String("none")) {
                draw_markers(painter, *sx, *sy, line->marker_style,
                             line->marker_size, line->color, to_p);
            }
        } else if (const auto* scatter =
                       dynamic_cast<const ScatterSeriesData*>(s.get())) {
            draw_markers(painter, *sx, *sy, scatter->marker_style,
                         scatter->size, scatter->color, to_p);
            // Per-point labels (well names etc.): only while the series is
            // not downsampled, so labels stay aligned with points.
            if (!scatter->labels.empty() && !downsampled) {
                draw_labels(painter, *sx, *sy, scatter->labels, scatter->size,
                            to_p);
            }
        }
    }
    painter->restore();

    // 5. Draw interactive hover crosshair & highlight selection.
    if (hover_pos_.has_value()) {
        painter->save();
        const QPen cross_pen(crosshair_color_, 1, Qt::DashLine);
        painter->setPen(cross_pen);

        // Vertical & horizontal crosshair lines.
        painter->drawLine(
            QLineF(hover_pos_->x(), top, hover_pos_->x(), bottom));
        painter->drawLine(
            QLineF(left, hover_pos_->y(), right, hover_pos_->y()));

        // Hover coordinate text label near the mouse.
        const auto [dx, dy] =
            pixel_to_data(hover_pos_->x(), hover_pos_->y());
        const QString lbl_txt =
            QStringLiteral("X: ") +
            QString::fromStdString(format_tick(dx, x_step)) +
            QStringLiteral("\nY: ") +
            QString::fromStdString(format_tick(dy, y_step));

        painter->setFont(QFont("Monospace", 8));
        painter->setPen(text_color_);
        painter->drawText(
            QPointF(hover_pos_->x() + 10.0, hover_pos_->y() - 10.0), lbl_txt);
        painter->restore();
    }

    // Draw nearest hover point highlight ring.
    draw_point_indicator(painter, to_p, hovered_point_,
                         QPen(highlight_color_, 2, Qt::SolidLine),
                         QBrush(Qt::NoBrush), {9.0}, QString());

    // Draw caller-owned selected point and its label independently of hover.
    draw_point_indicator(painter, to_p, selected_point_,
                         QPen(axis_color_, 3, Qt::SolidLine),
                         QBrush(highlight_color_), {12.0}, selected_label_);

    // Draw external highlighted/linked points.
    for (const auto& [series_name, indices] : highlighted_points_) {
        for (const int idx : indices) {
            draw_point_indicator(
                painter, to_p, PointRef{series_name, idx},
                QPen(highlight_color_, 1.5, Qt::SolidLine),
                QBrush(Qt::NoBrush), {6.0, 10.0}, QString());
        }
    }

    // 6. Draw axis borders & tick labels (above plot data overlay).
    painter->save();
    const QPen axis_pen(axis_color_, 1.5, Qt::SolidLine);
    painter->setPen(axis_pen);
    painter->setFont(QFont("Arial", 9));

    // Border.
    painter->drawRect(QRectF(left, top, plot_w, plot_h));

    // Tick labels.
    const QFontMetrics font_metrics(painter->font());

    // X ticks.
    for (const double xt : x_ticks) {
        if (view_xmin_ <= xt && xt <= view_xmax_) {
            const QPointF p = to_p(xt, view_ymin_);
            painter->drawLine(QLineF(p.x(), bottom, p.x(), bottom + 5.0));

            // Center label horizontally.
            const QString label =
                QString::fromStdString(format_tick(xt, x_step));
            const double lbl_w = font_metrics.horizontalAdvance(label);
            painter->setPen(text_color_);
            painter->drawText(QPointF(p.x() - lbl_w / 2.0, bottom + 20.0),
                              label);
            painter->setPen(axis_pen);
        }
    }

    // Y ticks.
    for (const double yt : y_ticks) {
        if (view_ymin_ <= yt && yt <= view_ymax_) {
            const QPointF p = to_p(view_xmin_, yt);
            painter->drawLine(QLineF(left - 5.0, p.y(), left, p.y()));

            // Right-align label on the Y axis.
            const QString label =
                QString::fromStdString(format_tick(yt, y_step));
            const double lbl_w = font_metrics.horizontalAdvance(label);
            painter->setPen(text_color_);
            painter->drawText(
                QPointF(left - lbl_w - 10.0,
                        p.y() + static_cast<double>(font_metrics.height()) / 4.0),
                label);
            painter->setPen(axis_pen);
        }
    }

    if (!x_axis_label_.isEmpty()) {
        painter->setPen(text_color_);
        const double label_width = font_metrics.horizontalAdvance(x_axis_label_);
        painter->drawText(
            QPointF(left + (plot_w - label_width) / 2.0, bottom + 42.0),
            x_axis_label_);
    }
    if (!y_axis_label_.isEmpty()) {
        painter->save();
        painter->setPen(text_color_);
        const double label_width = font_metrics.horizontalAdvance(y_axis_label_);
        painter->translate(16.0, top + (plot_h + label_width) / 2.0);
        painter->rotate(-90.0);
        painter->drawText(QPointF(0.0, 0.0), y_axis_label_);
        painter->restore();
    }

    painter->restore();
}

void PlotWidget::draw_markers(
    QPainter* painter, const std::vector<double>& sx,
    const std::vector<double>& sy, const QString& style, double size,
    const QColor& color,
    const std::function<QPointF(double, double)>& to_p) {
    painter->save();
    painter->setPen(QPen(color, 1.0, Qt::SolidLine));
    painter->setBrush(QBrush(color));

    const double half = size / 2.0;

    const std::size_t n = std::min(sx.size(), sy.size());
    for (std::size_t i = 0; i < n; ++i) {
        const double x_val = sx[i];
        const double y_val = sy[i];
        if (std::isnan(x_val) || std::isnan(y_val)) {
            continue;
        }

        const QPointF p = to_p(x_val, y_val);

        if (style == QLatin1String("circle")) {
            painter->drawEllipse(p, half, half);
        } else if (style == QLatin1String("square")) {
            painter->drawRect(QRectF(p.x() - half, p.y() - half, size, size));
        } else if (style == QLatin1String("triangle")) {
            QPolygonF poly;
            poly.append(QPointF(p.x(), p.y() - half));
            poly.append(QPointF(p.x() - half, p.y() + half));
            poly.append(QPointF(p.x() + half, p.y() + half));
            painter->drawPolygon(poly);
        } else if (style == QLatin1String("cross")) {
            painter->drawLine(QLineF(p.x() - half, p.y(), p.x() + half, p.y()));
            painter->drawLine(QLineF(p.x(), p.y() - half, p.x(), p.y() + half));
        }
    }
    painter->restore();
}

void PlotWidget::draw_labels(
    QPainter* painter, const std::vector<double>& sx,
    const std::vector<double>& sy, const std::vector<QString>& labels,
    double size, const std::function<QPointF(double, double)>& to_p) {
    painter->save();
    painter->setFont(QFont("Arial", 8));
    painter->setPen(QPen(text_color_, 1.0, Qt::SolidLine));
    painter->setBrush(QBrush(Qt::NoBrush));
    const double offset = size / 2.0 + 3.0;
    const std::size_t count =
        std::min({labels.size(), sx.size(), sy.size()});
    for (std::size_t i = 0; i < count; ++i) {
        const double x_val = sx[i];
        const double y_val = sy[i];
        if (std::isnan(x_val) || std::isnan(y_val)) {
            continue;
        }
        const QString& text = labels[i];
        if (text.isEmpty()) {
            continue;
        }
        const QPointF p = to_p(x_val, y_val);
        painter->drawText(QPointF(p.x() + offset, p.y() - offset), text);
    }
    painter->restore();
}

}  // namespace pwb::viz_charts::qt
