#include <pwb/ui_wellseis/qt/well_map_canvas.hpp>

#include <algorithm>
#include <cmath>
#include <limits>

#include <QMouseEvent>
#include <QPainter>
#include <QPainterPath>
#include <QWheelEvent>

namespace pwb::ui_wellseis::qt {

namespace {

// Palette mirrors the Python series colors (tokens.PRIMARY / WARNING /
// ACCENT / TEXT_SECONDARY / TEAL / CANVAS_CURSOR).
const QColor kColorOk(0x2f, 0x6f, 0xd8);
const QColor kColorFlagged(0xb4, 0x6a, 0x00);
const QColor kColorSelected(0x7a, 0x3e, 0xd8);
const QColor kColorBoundary(0x6b, 0x6f, 0x76);
const QColor kColorSurvey(0x12, 0x8c, 0x7e);
const QColor kColorSpatialCursor(0xd4, 0x46, 0x7c);
constexpr double kHitTolerancePx = 8.0;
constexpr double kMinScale = 1e-9;

void draw_ring(QPainter& painter, const WellMapRing& ring,
               const std::function<QPointF(const WellMapPoint&)>& to_widget,
               const QPen& pen) {
    if (ring.size() < 2) {
        return;
    }
    painter.setPen(pen);
    QPointF previous = to_widget(ring.front());
    for (std::size_t i = 1; i < ring.size(); ++i) {
        const WellMapPoint& point = ring[i];
        if (std::isnan(point.first) || std::isnan(point.second)) {
            // NaN separates multi-ring payloads (Python np.nan parity).
            if (i + 1 < ring.size()) {
                previous = to_widget(ring[i + 1]);
                ++i;
            }
            continue;
        }
        const QPointF current = to_widget(point);
        painter.drawLine(previous, current);
        previous = current;
    }
}

}  // namespace

WellMapCanvas::WellMapCanvas(QWidget* parent) : QWidget(parent) {
    setObjectName(QStringLiteral("WellMapCanvas"));
    setMinimumSize(240, 180);
    setMouseTracking(true);
    setFocusPolicy(Qt::StrongFocus);
}

void WellMapCanvas::set_scene(const WellMapScene& scene) {
    scene_ = scene;
    update();
}

WellMapCanvas::ViewTransform WellMapCanvas::fit_transform() const {
    double xmin = std::numeric_limits<double>::max();
    double ymin = std::numeric_limits<double>::max();
    double xmax = std::numeric_limits<double>::lowest();
    double ymax = std::numeric_limits<double>::lowest();
    const auto extend = [&](const std::vector<WellMapPoint>& points) {
        for (const auto& [x, y] : points) {
            if (std::isnan(x) || std::isnan(y)) {
                continue;
            }
            xmin = std::min(xmin, x);
            xmax = std::max(xmax, x);
            ymin = std::min(ymin, y);
            ymax = std::max(ymax, y);
        }
    };
    extend(scene_.ok_points);
    extend(scene_.flagged_points);
    extend(scene_.boundary);
    for (const auto& ring : scene_.survey_rings) {
        extend(ring);
    }
    for (const auto& ring : scene_.reference_rings) {
        extend(ring);
    }
    ViewTransform out;
    if (xmin > xmax || ymin > ymax) {
        return out;  // empty scene → identity
    }
    const double dx = std::max(xmax - xmin, std::abs(xmin) * 1e-3 + 1e-6);
    const double dy = std::max(ymax - ymin, std::abs(ymin) * 1e-3 + 1e-6);
    const double margin = 1.15;
    const double sx = width() / (dx * margin);
    const double sy = height() / (dy * margin);
    out.scale = std::max(std::min(sx, sy), kMinScale);
    out.cx = (xmin + xmax) / 2.0;
    out.cy = (ymin + ymax) / 2.0;
    return out;
}

WellMapPoint WellMapCanvas::to_world(const QPointF& pos) const {
    const double cx = width() / 2.0;
    const double cy = height() / 2.0;
    return {view_.cx + (pos.x() - cx) / view_.scale,
            view_.cy - (pos.y() - cy) / view_.scale};
}

QPointF WellMapCanvas::to_widget(const WellMapPoint& world) const {
    const double cx = width() / 2.0;
    const double cy = height() / 2.0;
    return {cx + (world.first - view_.cx) * view_.scale,
            cy - (world.second - view_.cy) * view_.scale};
}

void WellMapCanvas::autofit() {
    view_ = fit_transform();
    view_initialized_ = true;
    update();
}

void WellMapCanvas::reset_view() {
    autofit();
}

void WellMapCanvas::set_view_bounds(double xmin, double xmax, double ymin,
                                    double ymax) {
    const double dx = std::max(xmax - xmin, 1e-9);
    const double dy = std::max(ymax - ymin, 1e-9);
    view_.scale =
        std::max(std::min(width() / dx, height() / dy), kMinScale);
    view_.cx = (xmin + xmax) / 2.0;
    view_.cy = (ymin + ymax) / 2.0;
    view_initialized_ = true;
    update();
}

void WellMapCanvas::focus_point(double x, double y, double zoom_factor) {
    // Python plot.focus_point: center on the point at the base-fit scale
    // multiplied by zoom_factor.
    const ViewTransform fit = fit_transform();
    view_.cx = x;
    view_.cy = y;
    view_.scale = fit.scale * std::max(zoom_factor, 1e-6);
    view_initialized_ = true;
    update();
}

bool WellMapCanvas::hit_test(const QPointF& pos, std::string* series,
                             int* index, WellMapPoint* point) const {
    double best = kHitTolerancePx;
    bool found = false;
    const auto probe = [&](const std::vector<WellMapPoint>& points,
                           const std::string& name) {
        for (std::size_t i = 0; i < points.size(); ++i) {
            const QPointF widget = to_widget(points[i]);
            const double distance =
                std::hypot(widget.x() - pos.x(), widget.y() - pos.y());
            if (distance <= best) {
                best = distance;
                *series = name;
                *index = static_cast<int>(i);
                *point = points[i];
                found = true;
            }
        }
    };
    probe(scene_.ok_points, "wells");
    probe(scene_.flagged_points, "wells_flagged");
    return found;
}

void WellMapCanvas::paintEvent(QPaintEvent*) {
    QPainter painter(this);
    painter.setRenderHint(QPainter::Antialiasing);
    painter.fillRect(rect(), QColor(0xfb, 0xfc, 0xfe));
    if (!view_initialized_) {
        // First paint: fit inline (no update() recursion through autofit).
        view_ = fit_transform();
        view_initialized_ = true;
    }
    const auto to = [this](const WellMapPoint& p) { return to_widget(p); };

    draw_ring(painter, scene_.boundary, to,
              QPen(kColorBoundary, 1.2, Qt::DashLine));
    for (const auto& ring : scene_.survey_rings) {
        draw_ring(painter, ring, to, QPen(kColorSurvey, 1.0, Qt::DotLine));
    }
    for (const auto& ring : scene_.reference_rings) {
        draw_ring(painter, ring, to, QPen(kColorBoundary, 0.8));
    }

    const auto draw_points = [&](const std::vector<WellMapPoint>& points,
                                 const QColor& color, double radius) {
        painter.setPen(Qt::NoPen);
        painter.setBrush(color);
        for (const auto& point : points) {
            if (std::isnan(point.first) || std::isnan(point.second)) {
                continue;
            }
            painter.drawEllipse(to_widget(point), radius, radius);
        }
    };
    draw_points(scene_.ok_points, kColorOk, 3.0);
    draw_points(scene_.flagged_points, kColorFlagged, 3.0);
    draw_points(scene_.selected_points, kColorSelected, 5.0);

    if (scene_.show_labels) {
        painter.setPen(QColor(0x40, 0x44, 0x4c));
        QFont font = painter.font();
        font.setPointSizeF(8.0);
        painter.setFont(font);
        const auto draw_labels =
            [&](const std::vector<WellMapPoint>& points,
                const std::vector<std::string>& labels) {
                for (std::size_t i = 0;
                     i < points.size() && i < labels.size(); ++i) {
                    const QPointF pos = to_widget(points[i]);
                    painter.drawText(pos + QPointF(5, -4),
                                     QString::fromStdString(labels[i]));
                }
            };
        draw_labels(scene_.ok_points, scene_.ok_labels);
        draw_labels(scene_.flagged_points, scene_.flagged_labels);
    }

    if (scene_.spatial_cursor.has_value()) {
        painter.setPen(QPen(kColorSpatialCursor, 1.6));
        painter.setBrush(Qt::NoBrush);
        const QPointF pos = to_widget(*scene_.spatial_cursor);
        painter.drawEllipse(pos, 6.0, 6.0);
        painter.drawLine(pos + QPointF(-9, 0), pos + QPointF(9, 0));
        painter.drawLine(pos + QPointF(0, -9), pos + QPointF(0, 9));
    }
}

void WellMapCanvas::wheelEvent(QWheelEvent* event) {
    const double factor =
        event->angleDelta().y() > 0 ? 1.15 : 1.0 / 1.15;
    const WellMapPoint anchor_world = to_world(event->position());
    view_.scale = std::max(view_.scale * factor, kMinScale);
    // Keep the cursor-anchored world point fixed.
    const QPointF anchor_widget = to_widget(anchor_world);
    const QPointF delta = anchor_widget - event->position();
    const WellMapPoint widget_center_world =
        to_world(QPointF(width() / 2.0, height() / 2.0) - delta);
    view_.cx = widget_center_world.first;
    view_.cy = widget_center_world.second;
    update();
    event->accept();
}

void WellMapCanvas::mousePressEvent(QMouseEvent* event) {
    if (event->button() == Qt::LeftButton) {
        std::string series;
        int index = -1;
        WellMapPoint point{0.0, 0.0};
        if (hit_test(event->pos(), &series, &index, &point)) {
            if (on_point_clicked) {
                on_point_clicked(series, index, point.first, point.second);
            }
        } else {
            panning_ = true;
            pan_anchor_ = event->pos();
            setCursor(Qt::ClosedHandCursor);
        }
        event->accept();
        return;
    }
    QWidget::mousePressEvent(event);
}

void WellMapCanvas::mouseMoveEvent(QMouseEvent* event) {
    if (panning_ && (event->buttons() & Qt::LeftButton)) {
        const QPointF delta = event->pos() - pan_anchor_;
        pan_anchor_ = event->pos();
        view_.cx -= delta.x() / view_.scale;
        view_.cy += delta.y() / view_.scale;
        update();
        return;
    }
    std::string series;
    int index = -1;
    WellMapPoint point{0.0, 0.0};
    if (hit_test(event->pos(), &series, &index, &point)) {
        if (on_point_hovered) {
            on_point_hovered(series, index, point.first, point.second);
        }
    }
    QWidget::mouseMoveEvent(event);
}

void WellMapCanvas::mouseReleaseEvent(QMouseEvent* event) {
    if (panning_ && event->button() == Qt::LeftButton) {
        panning_ = false;
        unsetCursor();
    }
    QWidget::mouseReleaseEvent(event);
}

void WellMapCanvas::resizeEvent(QResizeEvent* event) {
    if (!view_initialized_) {
        autofit();
    }
    QWidget::resizeEvent(event);
}

}  // namespace pwb::ui_wellseis::qt
