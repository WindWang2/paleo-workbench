// 1:1 port of geoviz_plots/surface/surface_widget.py (frozen behavior
// source @0885195) — see surface_widget.hpp for the port notes.

#include "pwb/viz_charts/qt/surface_widget.hpp"

#include <QBrush>
#include <QFont>
#include <QFontMetrics>
#include <QMouseEvent>
#include <QPageSize>
#include <QPaintEvent>
#include <QPainter>
#include <QPainterPath>
#include <QPen>
#include <QPolygonF>
#include <QPrinter>
#include <QSvgGenerator>
#include <QWheelEvent>

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <limits>
#include <numbers>
#include <string_view>
#include <utility>

#include "pwb/viz_charts/axes.hpp"
#include "pwb/viz_charts/colormaps.hpp"

namespace pwb::viz_charts::qt {
namespace {

bool colormap_known(const QString& name) {
    const std::string_view raw = name.toStdString();
    return raw == "viridis" || raw == "cnpc_strat" ||
           raw == "cnpc_fluid" || raw == "thermal";
}

// np.searchsorted(a, v, side="left") → first index with a[i] >= v.
std::ptrdiff_t searchsorted_left(const std::vector<double>& a, double v) {
    return static_cast<std::ptrdiff_t>(
        std::lower_bound(a.begin(), a.end(), v) - a.begin());
}

}  // namespace

SurfaceWidget::SurfaceWidget(QWidget* parent) : QWidget(parent) {
    setMouseTracking(true);
    setFocusPolicy(Qt::StrongFocus);
}

// -- control points & faults ---------------------------------------------------

void SurfaceWidget::set_control_points(const QVector<ControlPoint>& points) {
    control_points_ = points;
    update();
}

void SurfaceWidget::add_control_point(double x, double y, double z,
                                      const QString& point_id) {
    ControlPoint cp;
    cp.id = point_id.isEmpty()
                ? QStringLiteral("cp_%1").arg(control_points_.size() + 1)
                : point_id;
    cp.x = x;
    cp.y = y;
    cp.z = z;
    control_points_.push_back(cp);
    emit control_points_changed(control_points_);
    update();
}

void SurfaceWidget::set_fault_polylines(const QVector<QPolygonF>& polylines) {
    fault_polylines_ = polylines;
    update();
}

void SurfaceWidget::select_contour_level(double level) {
    selected_contour_level_ = level;
    emit contour_selected(selected_contour_level_.value());
    update();
}

// -- grid binding -----------------------------------------------------------------

void SurfaceWidget::set_grid_data(std::vector<double> grid_x,
                                  std::vector<double> grid_y,
                                  std::vector<double> grid_z,
                                  std::vector<double> levels,
                                  const QString& colormap) {
    // Task-mandated guard: marching squares needs >= 2 nodes per axis and a
    // matching z matrix; anything else clears the widget state.
    if (grid_y.size() < 2 || grid_x.size() < 2 ||
        grid_z.size() != grid_x.size() * grid_y.size()) {
        clear();
        return;
    }
    grid_x_ = std::move(grid_x);
    grid_y_ = std::move(grid_y);
    grid_z_ = std::move(grid_z);
    std::sort(levels.begin(), levels.end());
    levels_ = std::move(levels);
    colormap_name_ = colormap_known(colormap)
                         ? colormap
                         : QStringLiteral("viridis");
    contour_cache_.clear();
    update();
}

void SurfaceWidget::clear() {
    grid_x_.clear();
    grid_y_.clear();
    grid_z_.clear();
    levels_.clear();
    control_points_.clear();
    fault_polylines_.clear();
    selected_contour_level_.reset();
    view_xmin_ = 0.0;
    view_xmax_ = 1.0;
    view_ymin_ = 0.0;
    view_ymax_ = 1.0;
    contour_cache_.clear();
    update();
}

void SurfaceWidget::autofit() {
    if (grid_x_.empty() || grid_y_.empty()) {
        view_xmin_ = 0.0;
        view_xmax_ = 1.0;
        view_ymin_ = 0.0;
        view_ymax_ = 1.0;
        update();
        return;
    }

    view_xmin_ = *std::min_element(grid_x_.begin(), grid_x_.end());
    view_xmax_ = *std::max_element(grid_x_.begin(), grid_x_.end());
    view_ymin_ = *std::min_element(grid_y_.begin(), grid_y_.end());
    view_ymax_ = *std::max_element(grid_y_.begin(), grid_y_.end());

    emit view_changed(view_xmin_, view_xmax_, view_ymin_, view_ymax_);
    update();
}

// -- viewport helpers ----------------------------------------------------------------

std::tuple<double, double, double, double> SurfaceWidget::get_plot_rect(
    int width, int height) const {
    return {static_cast<double>(margin_left_),
            width - static_cast<double>(margin_right_),
            static_cast<double>(margin_top_),
            height - static_cast<double>(margin_bottom_)};
}

std::pair<double, double> SurfaceWidget::data_to_pixel(double x,
                                                       double y) const {
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

std::pair<double, double> SurfaceWidget::pixel_to_data(double px,
                                                       double py) const {
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

void SurfaceWidget::pan(double dpx, double dpy) {
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

    view_xmin_ -= dx;
    view_xmax_ -= dx;
    view_ymin_ -= dy;
    view_ymax_ -= dy;

    emit view_changed(view_xmin_, view_xmax_, view_ymin_, view_ymax_);
    update();
}

void SurfaceWidget::zoom(double factor, double cx, double cy) {
    if (factor <= 0.0) {
        return;
    }

    view_xmin_ = cx - (cx - view_xmin_) / factor;
    view_xmax_ = cx + (view_xmax_ - cx) / factor;
    view_ymin_ = cy - (cy - view_ymin_) / factor;
    view_ymax_ = cy + (view_ymax_ - cy) / factor;

    emit view_changed(view_xmin_, view_xmax_, view_ymin_, view_ymax_);
    update();
}

// -- interaction events -----------------------------------------------------------------

void SurfaceWidget::mousePressEvent(QMouseEvent* event) {
    if (event->button() == Qt::LeftButton ||
        event->button() == Qt::MiddleButton) {
        last_mouse_pos_ = event->position();
    }
}

void SurfaceWidget::mouseMoveEvent(QMouseEvent* event) {
    const QPointF curr_pos = event->position();
    const auto [left, right, top, bottom] = get_plot_rect(width(), height());

    // Panning (Python compares the full button mask for exact equality).
    const Qt::MouseButtons buttons = event->buttons();
    if ((buttons == Qt::LeftButton || buttons == Qt::MiddleButton) &&
        last_mouse_pos_.has_value()) {
        const double dpx = curr_pos.x() - last_mouse_pos_->x();
        const double dpy = curr_pos.y() - last_mouse_pos_->y();
        pan(dpx, dpy);
        last_mouse_pos_ = curr_pos;
        return;
    }

    // Hover coordinate tracing.
    if (left <= curr_pos.x() && curr_pos.x() <= right &&
        top <= curr_pos.y() && curr_pos.y() <= bottom) {
        hover_pos_ = curr_pos;
    } else {
        hover_pos_.reset();
    }

    update();
}

void SurfaceWidget::mouseReleaseEvent(QMouseEvent* event) {
    Q_UNUSED(event);
    last_mouse_pos_.reset();
}

void SurfaceWidget::wheelEvent(QWheelEvent* event) {
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

void SurfaceWidget::mouseDoubleClickEvent(QMouseEvent* event) {
    if (event->button() == Qt::LeftButton) {
        autofit();
    }
}

// -- color interpolation ------------------------------------------------------------

QColor SurfaceWidget::get_color(double val) const {
    if (levels_.empty()) {
        return QColor(100, 100, 100);
    }
    const Rgb rgb = sample_colormap(colormap_name_.toStdString(), val,
                                    levels_.front(), levels_.back());
    return QColor(rgb.r, rgb.g, rgb.b);
}

// -- vector exports ---------------------------------------------------------------------

void SurfaceWidget::export_svg(const QString& filepath) {
    export_svg(filepath, size());
}

void SurfaceWidget::export_svg(const QString& filepath, QSize canvas) {
    if (canvas.isEmpty()) {
        canvas = QSize(900, 600);  // never-laid-out host: degenerate canvas guard
    }
    QSvgGenerator generator;
    generator.setFileName(filepath);
    generator.setSize(canvas);
    generator.setViewBox(QRect(QPoint(0, 0), canvas));
    generator.setTitle(QStringLiteral("GeoViz Surface Map - ") + windowTitle());
    generator.setDescription(
        QStringLiteral("Generated by GeoViz Engine QPainter Surface core."));

    QPainter painter(&generator);
    painter.setRenderHint(QPainter::Antialiasing);
    render_surface(&painter, canvas.width(), canvas.height());
    painter.end();
}

void SurfaceWidget::export_pdf(const QString& filepath) {
    QPrinter printer(QPrinter::HighResolution);
    printer.setOutputFormat(QPrinter::PdfFormat);
    printer.setOutputFileName(filepath);
    printer.setPageSize(QPageSize(QPageSize::A4));

    const QRectF page_rect = printer.pageRect(QPrinter::DevicePixel);

    QPainter painter(&printer);
    painter.setRenderHint(QPainter::Antialiasing);
    render_surface(&painter, static_cast<int>(page_rect.width()),
                   static_cast<int>(page_rect.height()));
    painter.end();
}

void SurfaceWidget::export_pdf(const QString& filepath, QSize canvas) {
    Q_UNUSED(canvas);  // PDF always renders the full A4 page (Python parity)
    export_pdf(filepath);
}

// -- core paint ---------------------------------------------------------------------------

void SurfaceWidget::paintEvent(QPaintEvent* event) {
    Q_UNUSED(event);
    QPainter painter(this);
    painter.setRenderHint(QPainter::Antialiasing);
    render_surface(&painter, width(), height());
}

const SurfaceWidget::ExtractionResult& SurfaceWidget::ensure_contours(
    const CacheKey& key) {
    // Issue #59 cache: hover repaints and pan/zoom hit the cache instead of
    // re-running extraction. Python clears the whole dict once it holds 4
    // entries before inserting the new one.
    for (auto& entry : contour_cache_) {
        if (entry.first == key) {
            return entry.second;
        }
    }
    ExtractionResult result;
    result.bands = extract_filled_contours(grid_x_, grid_y_, grid_z_, levels_,
                                           colormap_name_.toStdString());
    result.lines =
        extract_contour_lines(grid_x_, grid_y_, grid_z_, levels_);
    if (contour_cache_.size() >= 4) {
        contour_cache_.clear();
    }
    contour_cache_.emplace_back(key, std::move(result));
    return contour_cache_.back().second;
}

void SurfaceWidget::render_surface(QPainter* painter, int width_v,
                                   int height_v) {
    // 1. Fill entire widget background.
    painter->fillRect(0, 0, width_v, height_v, bg_color_);

    const auto [left, right, top, bottom] = get_plot_rect(width_v, height_v);
    const double plot_w = right - left;
    const double plot_h = bottom - top;

    if (plot_w <= 0.0 || plot_h <= 0.0) {
        return;
    }

    // 2. Draw interior background.
    painter->fillRect(QRectF(left, top, plot_w, plot_h), plot_bg_color_);

    if (grid_x_.empty() || grid_y_.empty() || grid_z_.empty() ||
        levels_.empty()) {
        return;
    }

    // Coordinate mapping inside the render boundary.
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

    // Batch transform factors (Issue #59 vectorized to_p_np equivalent).
    double x_r = view_xmax_ - view_xmin_;
    double y_r = view_ymax_ - view_ymin_;
    if (x_r == 0.0) {
        x_r = 1.0;
    }
    if (y_r == 0.0) {
        y_r = 1.0;
    }
    const double sx = plot_w / x_r;
    const double sy = plot_h / y_r;
    const auto to_p_np = [&](double x_val, double y_val) -> QPointF {
        return QPointF(left + (x_val - view_xmin_) * sx,
                       bottom - (y_val - view_ymin_) * sy);
    };

    // Clip painter to the plotting rectangle so rendering stays in frame.
    painter->save();
    painter->setClipRect(QRectF(left, top, plot_w, plot_h));

    // 3. Draw filled contours (color blocks), extracted once per
    // (grid, levels, colormap) and cached.
    const CacheKey key{grid_x_.data(),  grid_y_.data(), grid_z_.data(),
                       grid_x_.size(),  grid_y_.size(), grid_z_.size(),
                       levels_,         colormap_name_.toStdString()};
    const ExtractionResult& extracted = ensure_contours(key);

    if (extracted.bands.has_value()) {
        for (const BandedFill& band : *extracted.bands) {
            QColor color(band.color_r, band.color_g, band.color_b);
            color.setAlpha(180);  // Standard clean alpha transparency.

            painter->setBrush(QBrush(color));
            painter->setPen(Qt::NoPen);

            const std::size_t n_polys =
                std::min(band.rings.points.size(), band.rings.offsets.size());
            for (std::size_t pi = 0; pi < n_polys; ++pi) {
                const Polyline& poly = band.rings.points[pi];
                const std::vector<std::size_t>& offset_arr =
                    band.rings.offsets[pi];
                if (poly.xs.size() < 3) {
                    continue;
                }

                QPainterPath path;
                path.setFillRule(Qt::OddEvenFill);

                for (std::size_t j = 0; j + 1 < offset_arr.size(); ++j) {
                    const std::size_t start_idx = offset_arr[j];
                    const std::size_t end_idx = offset_arr[j + 1];
                    if (end_idx - start_idx < 3) {
                        continue;
                    }
                    QPolygonF ring;
                    ring.reserve(static_cast<int>(end_idx - start_idx));
                    for (std::size_t k = start_idx; k < end_idx; ++k) {
                        ring.append(to_p_np(poly.xs[k], poly.ys[k]));
                    }
                    // addPolygon builds one closed subpath per ring.
                    path.addPolygon(ring);
                }

                painter->drawPath(path);
            }
        }
    }

    // 4. Draw vector contour isolines & labels (text cut-outs).
    if (extracted.lines.has_value()) {
        painter->setFont(QFont("Arial", 8, QFont::Bold));
        const QFontMetrics font_metrics(painter->font());

        // sorted(lines_dict.keys()) without copying the cached polylines.
        std::vector<const std::pair<double, std::vector<Polyline>>*>
            sorted_levels;
        sorted_levels.reserve(extracted.lines->size());
        for (const auto& entry : *extracted.lines) {
            sorted_levels.push_back(&entry);
        }
        std::sort(sorted_levels.begin(), sorted_levels.end(),
                  [](const auto* a, const auto* b) { return a->first < b->first; });
        const std::size_t major_every = 5;  // every 5th level is major
        for (std::size_t level_index = 0; level_index < sorted_levels.size();
             ++level_index) {
            const double lv = sorted_levels[level_index]->first;
            const std::vector<Polyline>& lines =
                sorted_levels[level_index]->second;
            const bool is_major = level_index % major_every == 0;
            const QPen line_pen(contour_line_color_,
                                is_major ? 1.2 : 0.6, Qt::SolidLine);
            painter->setPen(line_pen);
            painter->setBrush(QBrush(Qt::NoBrush));

            const QString label_txt = QString::asprintf("%.1f", lv);
            const double txt_w = font_metrics.horizontalAdvance(label_txt);
            const double txt_h = font_metrics.height();

            for (const Polyline& line : lines) {
                if (line.xs.size() < 2) {
                    continue;
                }
                const std::size_t n_pts = line.xs.size();

                // Pixel transform + cumulative path length.
                std::vector<QPointF> pts;
                pts.reserve(n_pts);
                for (std::size_t k = 0; k < n_pts; ++k) {
                    pts.push_back(to_p_np(line.xs[k], line.ys[k]));
                }
                std::vector<double> seg_lens;
                seg_lens.reserve(n_pts - 1);
                double total_len = 0.0;
                for (std::size_t k = 0; k + 1 < n_pts; ++k) {
                    const double seg = std::hypot(pts[k + 1].x() - pts[k].x(),
                                                  pts[k + 1].y() - pts[k].y());
                    seg_lens.push_back(seg);
                    total_len += seg;
                }

                // Draw a text cut-out label when the line is long enough
                // (> 130 pixels).
                if (total_len > 130.0) {
                    const double half_len = total_len / 2.0;
                    std::vector<double> dists;
                    dists.reserve(n_pts);
                    dists.push_back(0.0);
                    for (const double seg : seg_lens) {
                        dists.push_back(dists.back() + seg);
                    }

                    // Find the midpoint segment by pixel length.
                    std::ptrdiff_t mid_idx =
                        searchsorted_left(dists, half_len) - 1;
                    mid_idx = std::max<std::ptrdiff_t>(
                        0, std::min(mid_idx,
                                    static_cast<std::ptrdiff_t>(n_pts) - 2));

                    const QPointF pt_mid =
                        pts[static_cast<std::size_t>(mid_idx)];
                    const QPointF pt_next =
                        pts[static_cast<std::size_t>(mid_idx) + 1];

                    // Direction angle of the path segment.
                    const double dx = pt_next.x() - pt_mid.x();
                    const double dy = pt_next.y() - pt_mid.y();
                    double angle = std::atan2(dy, dx);
                    if (dx < 0.0) {
                        angle += std::numbers::pi;  // keep text upright
                    }

                    // Cut-out gap of text_width + 10px padding.
                    const double gap_pixels = txt_w + 10.0;
                    const double half_gap = gap_pixels / 2.0;
                    const double entry_target = half_len - half_gap;
                    const double exit_target = half_len + half_gap;

                    std::ptrdiff_t entry_i =
                        searchsorted_left(dists, entry_target);
                    entry_i = std::max<std::ptrdiff_t>(
                        1, std::min(entry_i,
                                    static_cast<std::ptrdiff_t>(n_pts) - 1));
                    std::ptrdiff_t exit_i =
                        searchsorted_left(dists, exit_target);
                    exit_i = std::max<std::ptrdiff_t>(
                        entry_i, std::min(exit_i,
                                          static_cast<std::ptrdiff_t>(n_pts) -
                                              1));

                    const double seg_entry =
                        seg_lens[static_cast<std::size_t>(entry_i - 1)];
                    const double w_entry =
                        seg_entry > 0.0
                            ? (entry_target -
                               dists[static_cast<std::size_t>(entry_i - 1)]) /
                                  seg_entry
                            : 0.0;
                    const QPointF gap_entry(
                        pts[static_cast<std::size_t>(entry_i - 1)].x() +
                            w_entry *
                                (pts[static_cast<std::size_t>(entry_i)].x() -
                                 pts[static_cast<std::size_t>(entry_i - 1)]
                                     .x()),
                        pts[static_cast<std::size_t>(entry_i - 1)].y() +
                            w_entry *
                                (pts[static_cast<std::size_t>(entry_i)].y() -
                                 pts[static_cast<std::size_t>(entry_i - 1)]
                                     .y()));

                    // Split drawing at the gap entrance/exit.
                    QPainterPath path_start;
                    QPainterPath path_end;

                    path_start.moveTo(pts[0]);
                    for (std::size_t i = 1;
                         i < static_cast<std::size_t>(entry_i); ++i) {
                        path_start.lineTo(pts[i]);
                    }
                    path_start.lineTo(gap_entry);

                    if (exit_target < total_len) {
                        const double seg_exit =
                            seg_lens[static_cast<std::size_t>(exit_i - 1)];
                        const double w_exit =
                            seg_exit > 0.0
                                ? (exit_target -
                                   dists[static_cast<std::size_t>(
                                       exit_i - 1)]) /
                                      seg_exit
                                : 0.0;
                        const QPointF gap_exit(
                            pts[static_cast<std::size_t>(exit_i - 1)].x() +
                                w_exit *
                                    (pts[static_cast<std::size_t>(exit_i)]
                                         .x() -
                                     pts[static_cast<std::size_t>(exit_i - 1)]
                                         .x()),
                            pts[static_cast<std::size_t>(exit_i - 1)].y() +
                                w_exit *
                                    (pts[static_cast<std::size_t>(exit_i)]
                                         .y() -
                                     pts[static_cast<std::size_t>(exit_i - 1)]
                                         .y()));
                        path_end.moveTo(gap_exit);
                        for (std::size_t i = static_cast<std::size_t>(exit_i);
                             i < n_pts; ++i) {
                            path_end.lineTo(pts[i]);
                        }
                    }

                    painter->drawPath(path_start);
                    painter->drawPath(path_end);

                    // Render rotated text cleanly in the gap.
                    painter->save();
                    painter->translate(pt_mid.x(), pt_mid.y());
                    painter->rotate(angle * 180.0 / std::numbers::pi);

                    painter->setPen(text_color_);
                    painter->drawText(QPointF(-txt_w / 2.0, txt_h / 4.0),
                                      label_txt);
                    painter->restore();

                    // Restore active isoline pen.
                    painter->setPen(line_pen);
                } else {
                    // Draw the entire line without a label cut-out.
                    QPainterPath path;
                    path.moveTo(pts[0]);
                    for (std::size_t k = 1; k < n_pts; ++k) {
                        path.lineTo(pts[k]);
                    }
                    painter->drawPath(path);
                }
            }
        }
    }

    painter->restore();  // End clip rect.

    const auto [x_ticks, x_step] = calculate_ticks(view_xmin_, view_xmax_, 6);
    const auto [y_ticks, y_step] = calculate_ticks(view_ymin_, view_ymax_, 6);

    // 5. Draw interactive coordinates hover.
    if (hover_pos_.has_value()) {
        painter->save();
        const QPen cross_pen(QColor(255, 165, 0, 150), 1, Qt::DashLine);
        painter->setPen(cross_pen);
        painter->drawLine(
            QLineF(hover_pos_->x(), top, hover_pos_->x(), bottom));
        painter->drawLine(
            QLineF(left, hover_pos_->y(), right, hover_pos_->y()));

        // Text coordinates bubble.
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

    // 6. Draw axis borders & tick labels (above plot data overlay).
    painter->save();
    const QPen axis_pen(axis_color_, 1.5, Qt::SolidLine);
    painter->setPen(axis_pen);
    painter->setFont(QFont("Arial", 9));

    // Border box.
    painter->drawRect(QRectF(left, top, plot_w, plot_h));

    const QFontMetrics font_metrics(painter->font());

    // X ticks.
    for (const double xt : x_ticks) {
        if (view_xmin_ <= xt && xt <= view_xmax_) {
            const QPointF p = to_p(xt, view_ymin_);
            painter->drawLine(QLineF(p.x(), bottom, p.x(), bottom + 5.0));

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

            const QString label =
                QString::fromStdString(format_tick(yt, y_step));
            const double lbl_w = font_metrics.horizontalAdvance(label);
            painter->setPen(text_color_);
            painter->drawText(
                QPointF(left - lbl_w - 10.0,
                        p.y() +
                            static_cast<double>(font_metrics.height()) / 4.0),
                label);
            painter->setPen(axis_pen);
        }
    }

    painter->restore();
}

}  // namespace pwb::viz_charts::qt
