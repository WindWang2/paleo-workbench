// UI-15 — primary renderer-neutral map canvas (unified_map_canvas.py
// UnifiedMapCanvas parity).

#include <pwb/ui_canvas/qt/fallback_map_backend.hpp>
#include <pwb/ui_canvas/qt/unified_map_canvas.hpp>

#include <pwb/ui_canvas/qt/qt_meta.hpp>

#include <algorithm>
#include <cmath>
#include <stdexcept>

#include <QCloseEvent>
#include <QKeyEvent>
#include <QMetaEnum>
#include <QMouseEvent>
#include <QPageSize>
#include <QPainter>
#include <QPainterPath>
#include <QPdfWriter>
#include <QPolygonF>
#include <QSvgGenerator>
#include <QSvgRenderer>
#include <QTemporaryFile>
#include <QVariantMap>
#include <QWheelEvent>

#include <pwb/ui_widgets/map_chrome.hpp>
#include <pwb/ui_widgets/ui_context.hpp>

#include "json_variant.hpp"

namespace pwb::ui_canvas {

using qt::detail::json_to_variant_map;

namespace {

// RenderContext.device_px_per_logical_px(dpi): physical device px per
// logical px — dpi / 96 for exports (Python parity).
double device_px_per_logical_px(double dpi) {
    return dpi > 0.0 ? dpi / 96.0 : 1.0;
}

QPointF to_qpoint(std::pair<double, double> point) {
    return QPointF(point.first, point.second);
}

// Python create_map_render_backend() has the fallback built in; the C++
// registry needs the factory installed before selection (idempotent).
std::shared_ptr<MapRenderBackend> default_backend() {
    qt::install_fallback_backend_factory();
    return create_map_render_backend();
}

}  // namespace

UnifiedMapCanvas::UnifiedMapCanvas(
    std::shared_ptr<MapRenderBackend> backend, QWidget* parent)
    : QWidget(parent),
      backend_(backend ? std::move(backend) : default_backend()) {
    setObjectName(QStringLiteral("UnifiedMapCanvas"));
    setMinimumSize(240, 180);
    setMouseTracking(true);
    backend_->initialize();
    extent_history_.record(view_extent_);
    // The seeded (0,0,1,1) entry is already recorded by ExtentHistory's
    // constructor — record() skips the duplicate tail (Python parity:
    // history starts at [view_extent]).
    poll_timer_.setSingleShot(true);
    connect(&poll_timer_, &QTimer::timeout, this,
            &UnifiedMapCanvas::take_completed_frame);
    navigation_render_timer_.setSingleShot(true);
    navigation_render_timer_.setInterval(24);
    connect(&navigation_render_timer_, &QTimer::timeout, this,
            &UnifiedMapCanvas::request_render);
    publish_backend_status();
}

UnifiedMapCanvas::~UnifiedMapCanvas() { shutdown(); }

QString UnifiedMapCanvas::backend_status() const {
    return QStringLiteral("%1: %2")
        .arg(QString::fromStdString(backend_->backend_name()),
             QString::fromStdString(backend_->status()));
}

void UnifiedMapCanvas::set_layer_snapshot(
    const MapRenderSnapshot& snapshot) {
    if (shutdown_done_) {
        // A late publish after teardown must not restart render polling
        // (review 二轮 #4).
        return;
    }
    const std::string signature = snapshot_signature(snapshot);
    if (signature == last_snapshot_signature_) {
        // Host refreshes can fire many times per interaction; identical
        // revisions/visibility must not enqueue another render pass.
        return;
    }
    last_snapshot_signature_ = signature;
    navigation_render_timer_.stop();
    backend_->set_layer_snapshot(snapshot);
    request_render();
}

std::vector<std::string>
UnifiedMapCanvas::snapshot_source_version_ids() const {
    return ui_canvas::snapshot_source_version_ids(backend_->snapshot());
}

void UnifiedMapCanvas::set_overlay_provider(OverlayProvider provider) {
    overlay_provider_ = std::move(provider);
    update();
}

bool UnifiedMapCanvas::active_tool_edits_data() const {
    return tool_controller_ != nullptr &&
           tool_controller_->active_tool_edits_data();
}

void UnifiedMapCanvas::emit_tool_operation() {
    emit tool_operation(active_tool_edits_data());
}

Extent UnifiedMapCanvas::fitted_extent() const {
    return fit_extent_to_aspect(view_extent_, width(), height());
}

double UnifiedMapCanvas::map_units_per_pixel() const {
    const Extent fitted = fitted_extent();
    // Uniform after letterboxing; keep max() as a degenerate guard.
    return std::max((fitted[2] - fitted[0]) / std::max(1, width()),
                    (fitted[3] - fitted[1]) / std::max(1, height()));
}

std::pair<double, double>
UnifiedMapCanvas::screen_to_map(const QPointF& point) const {
    const Extent fitted = fitted_extent();
    return {fitted[0] + point.x() * (fitted[2] - fitted[0]) /
                          std::max(1, width()),
            fitted[3] - point.y() * (fitted[3] - fitted[1]) /
                          std::max(1, height())};
}

QPointF UnifiedMapCanvas::map_to_screen(
    std::pair<double, double> map_point) const {
    const Extent fitted = fitted_extent();
    const double dx = fitted[2] - fitted[0];
    const double dy = fitted[3] - fitted[1];
    if (dx == 0.0 || dy == 0.0 ||
        !(std::isfinite(dx) && std::isfinite(dy))) {
        // #1166: degenerate extent — center the point instead of a
        // division fault (paint paths must never crash).
        return QPointF(width() / 2.0, height() / 2.0);
    }
    return QPointF((map_point.first - fitted[0]) * width() / dx,
                   (fitted[3] - map_point.second) * height() / dy);
}

void UnifiedMapCanvas::set_extent(const Extent& extent,
                                  bool record_history,
                                  bool coalesce_history) {
    const Extent sanitized = sanitize_extent(extent);
    backend_->set_extent(sanitized);
    view_extent_ = sanitized;
    if (record_history) {
        extent_history_.record(view_extent_, coalesce_history);
    }
    emit extent_changed(view_extent_);
    if (coalesce_history) {
        request_navigation_render();
    } else {
        navigation_render_timer_.stop();
        request_render();
    }
}

void UnifiedMapCanvas::zoom_by(
    double factor, std::optional<std::pair<double, double>> center,
    bool coalesce_history) {
    if (!std::isfinite(factor) || factor <= 0.0) {
        throw std::invalid_argument(
            "zoom factor must be finite and positive");
    }
    const double xmin = view_extent_[0], ymin = view_extent_[1];
    const double xmax = view_extent_[2], ymax = view_extent_[3];
    const auto [cx, cy] =
        center.value_or(
            std::make_pair((xmin + xmax) / 2.0, (ymin + ymax) / 2.0));
    if (!image_.isNull()) {
        const QPointF screen = map_to_screen({cx, cy});
        navigation_transform_.translate(screen.x(), screen.y());
        navigation_transform_.scale(1.0 / factor, 1.0 / factor);
        navigation_transform_.translate(-screen.x(), -screen.y());
        update();
    }
    set_extent({cx + (xmin - cx) * factor, cy + (ymin - cy) * factor,
                cx + (xmax - cx) * factor, cy + (ymax - cy) * factor},
               true, coalesce_history);
}

void UnifiedMapCanvas::pan_by_pixels(double dx, double dy) {
    // Pixel→world conversion uses the letterboxed (fitted) span — the same
    // mapping the content is drawn through (#522/#831).
    const Extent fitted = fitted_extent();
    const double w = std::max(1, width());
    const double h = std::max(1, height());
    const double world_dx = -dx * (fitted[2] - fitted[0]) / w;
    const double world_dy = dy * (fitted[3] - fitted[1]) / h;
    if (!image_.isNull()) {
        navigation_transform_.translate(dx, dy);
        update();
    }
    set_extent({fitted[0] + world_dx, fitted[1] + world_dy,
                fitted[2] + world_dx, fitted[3] + world_dy},
               true, /*coalesce_history=*/true);
}

bool UnifiedMapCanvas::can_previous_extent() const {
    return extent_history_.can_previous();
}

bool UnifiedMapCanvas::can_next_extent() const {
    return extent_history_.can_next();
}

bool UnifiedMapCanvas::previous_extent() {
    const std::optional<Extent> previous = extent_history_.previous();
    if (!previous.has_value()) {
        return false;
    }
    set_extent(*previous, /*record_history=*/false);
    return true;
}

bool UnifiedMapCanvas::next_extent() {
    const std::optional<Extent> next = extent_history_.next();
    if (!next.has_value()) {
        return false;
    }
    set_extent(*next, /*record_history=*/false);
    return true;
}

double UnifiedMapCanvas::screen_pixel_ratio() const {
    const double ratio = devicePixelRatioF();
    return ratio > 0.0 ? ratio : 1.0;
}

void UnifiedMapCanvas::request_render() {
    const double ratio = screen_pixel_ratio();
    const int w = std::max(1, static_cast<int>(
                                  std::lround(width() * ratio)));
    const int h = std::max(1, static_cast<int>(
                                  std::lround(height() * ratio)));
    backend_->set_output_size(w, h);
    backend_->set_dpi(96.0 * ratio);
    backend_->request_render();
    ++diagnostics_.render_requests;
    schedule_frame_poll(0);
}

void UnifiedMapCanvas::request_navigation_render() {
    // Coalesce motion events while the previous frame remains responsive.
    navigation_render_timer_.start();
}

void UnifiedMapCanvas::schedule_frame_poll(int interval_ms) {
    poll_interval_ms_ = std::max(0, interval_ms);
    poll_timer_.start(poll_interval_ms_);
}

void UnifiedMapCanvas::take_completed_frame() {
    ++diagnostics_.polls;
    std::optional<RenderFrame> frame = backend_->take_completed_frame();
    if (!frame.has_value()) {
        if (backend_->render_active()) {
            ++diagnostics_.empty_polls;
            const int interval =
                poll_interval_ms_ <= 0
                    ? 8
                    : std::min(poll_interval_ms_ * 2, 32);
            schedule_frame_poll(interval);
        }
        return;
    }
    last_frame_ = *frame;
    image_buffer_ = frame->rgba;
    image_ = QImage(image_buffer_.data(), frame->width, frame->height,
                    frame->stride, QImage::Format_RGBA8888);
    image_.setDevicePixelRatio(screen_pixel_ratio());
    navigation_transform_ = QTransform();
    ++diagnostics_.frames_delivered;
    diagnostics_.frame_bytes_delivered +=
        static_cast<int>(frame->rgba.size());
    emit frame_ready(*frame);
    update();
}

void UnifiedMapCanvas::publish_backend_status() {
    emit backend_status_changed(backend_status());
}

void UnifiedMapCanvas::resizeEvent(QResizeEvent* event) {
    QWidget::resizeEvent(event);
    if (width() > 0 && height() > 0) {
        navigation_render_timer_.stop();
        request_render();
    }
}

void UnifiedMapCanvas::paintEvent(QPaintEvent* /*event*/) {
    QPainter painter(this);
    painter.fillRect(rect(),
                     QColor(pwb::ui_widgets::palette_token("BG_SEARCH")));
    if (!image_.isNull()) {
        painter.save();
        painter.setTransform(navigation_transform_);
        painter.drawImage(rect(), image_);
        painter.restore();
    }
    paint_overlay(painter);
}

void UnifiedMapCanvas::paint_overlay(QPainter& painter) {
    if (overlay_provider_ == nullptr) {
        return;
    }
    const Json state = overlay_provider_();
    const auto selected = state.value("selected_features", Json::array());
    if (selected.is_array() && !selected.empty()) {
        painter.save();
        painter.setRenderHint(QPainter::Antialiasing, true);
        painter.setPen(
            QPen(QColor(pwb::ui_widgets::palette_token("CANVAS_SELECTION")),
                 2.0));
        painter.setBrush(Qt::NoBrush);
        for (const Json& feature : selected) {
            const Json* geometry = nullptr;
            if (feature.is_object()) {
                const auto it = feature.find("geometry");
                if (it != feature.end()) {
                    geometry = &*it;
                }
            }
            paint_geometry_outline(
                painter, geometry != nullptr ? *geometry : Json());
        }
        painter.restore();
    }
    const Json points_json = state.value("capture_points", Json::array());
    std::vector<std::pair<double, double>> points;
    if (points_json.is_array()) {
        for (const Json& entry : points_json) {
            if (entry.is_array() && entry.size() >= 2) {
                points.emplace_back(entry.at(0).get<double>(),
                                    entry.at(1).get<double>());
            }
        }
    }
    if (!points.empty()) {
        painter.save();
        painter.setRenderHint(QPainter::Antialiasing, true);
        painter.setPen(
            QPen(QColor(pwb::ui_widgets::palette_token("CANVAS_SNAP")),
                 1.5, Qt::DashLine));
        std::vector<std::pair<double, double>> preview = points;
        if (cursor_map_.has_value()) {
            preview.push_back(*cursor_map_);
        }
        QPolygonF screen_points;
        for (const auto& point : preview) {
            screen_points.append(map_to_screen(point));
        }
        if (screen_points.size() >= 2) {
            painter.drawPolyline(screen_points);
        }
        painter.setBrush(
            QColor(pwb::ui_widgets::palette_token("CANVAS_SNAP")));
        for (std::size_t i = 0; i < points.size(); ++i) {
            painter.drawEllipse(screen_points.at(static_cast<int>(i)),
                                3.5, 3.5);
        }
        painter.restore();
    }
    const auto snap_it = state.find("snap_point");
    if (snap_it != state.end() && !snap_it->is_null()) {
        // Python `except (TypeError, ValueError, IndexError): return`
        // parity — a malformed snap point aborts the overlay INCLUDING
        // decorations; it never escapes paintEvent.
        QPointF center;
        try {
            center = map_to_screen({snap_it->at(0).get<double>(),
                                    snap_it->at(1).get<double>()});
        } catch (...) {
            return;
        }
        painter.save();
        painter.setPen(
            QPen(QColor(pwb::ui_widgets::palette_token("CANVAS_EDIT")),
                 1.5));
        painter.setBrush(Qt::NoBrush);
        painter.drawEllipse(center, 6.0, 6.0);
        painter.drawLine(center + QPointF(-8, 0),
                         center + QPointF(8, 0));
        painter.drawLine(center + QPointF(0, -8),
                         center + QPointF(0, 8));
        painter.restore();
    }
    // Screen chrome measures the letterboxed extent actually drawn
    // (#522/#831).
    paint_decorations(painter,
                      state.value("decorations", Json::object()), width(),
                      height(), 1.0, fitted_extent());
}

void UnifiedMapCanvas::paint_decorations(QPainter& painter,
                                         const Json& decorations,
                                         int width, int height,
                                         double scale,
                                         const Extent& extent) {
    // Frame background selects the chrome ink: light frames (all built-in
    // backends) use dark ink — otherwise text vanishes into the body.
    std::array<double, 4> ext{extent[0], extent[1], extent[2], extent[3]};
    pwb::ui_widgets::paint_map_decorations(
        painter, json_to_variant_map(decorations), width, height, ext,
        scale, backend_->light_frame_background());
}

void UnifiedMapCanvas::paint_geometry_outline(QPainter& painter,
                                              const Json& geometry) {
    if (!geometry.is_object()) {
        return;
    }
    const std::string type = geometry.value("type", "");
    const auto coords_it = geometry.find("coordinates");
    auto point_at = [this, &painter](const Json& coords) {
        if (!coords.is_array() || coords.size() < 2) {
            return;
        }
        // Python try/except (TypeError, ValueError, IndexError) parity —
        // malformed coordinates skip the mark, never abort painting.
        try {
            painter.drawEllipse(
                map_to_screen({coords.at(0).get<double>(),
                               coords.at(1).get<double>()}),
                6.0, 6.0);
        } catch (...) {
        }
    };
    if (type == "Point") {
        if (coords_it != geometry.end()) {
            point_at(*coords_it);
        }
        return;
    }
    if (type == "MultiPoint" && coords_it != geometry.end() &&
        coords_it->is_array()) {
        for (const Json& point : *coords_it) {
            paint_geometry_outline(
                painter, Json{{"type", "Point"}, {"coordinates", point}});
        }
        return;
    }
    if ((type == "LineString" || type == "Polygon") &&
        coords_it != geometry.end() && coords_it->is_array()) {
        const Json& lines =
            type == "Polygon" ? *coords_it : Json::array({*coords_it});
        for (const Json& line : lines) {
            if (!line.is_array()) {
                continue;
            }
            QPolygonF pts;
            for (const Json& point : line) {
                if (!point.is_array() || point.size() < 2) {
                    continue;
                }
                try {
                    pts.append(map_to_screen({point.at(0).get<double>(),
                                              point.at(1).get<double>()}));
                } catch (...) {
                    continue;
                }
            }
            if (pts.size() >= 2) {
                painter.drawPolyline(pts);
            }
        }
        return;
    }
    if ((type == "MultiLineString" || type == "MultiPolygon") &&
        coords_it != geometry.end() && coords_it->is_array()) {
        const std::string child_type =
            type == "MultiLineString" ? "LineString" : "Polygon";
        for (const Json& child : *coords_it) {
            paint_geometry_outline(
                painter,
                Json{{"type", child_type}, {"coordinates", child}});
        }
    }
}

void UnifiedMapCanvas::wheelEvent(QWheelEvent* event) {
    const int delta = event->angleDelta().y();
    if (delta != 0) {
        // Anchor the zoom at the world point under the cursor.
        zoom_by(delta > 0 ? 0.8 : 1.25, screen_to_map(event->position()),
                /*coalesce_history=*/true);
        event->accept();
        return;
    }
    event->ignore();
}

void UnifiedMapCanvas::keyPressEvent(QKeyEvent* event) {
    if (event->key() == Qt::Key_Space) {
        space_pan_ = true;
        event->accept();
        return;
    }
    const int key = event->key();
    std::string key_name;
    if (key == Qt::Key_Escape) {
        key_name = "escape";
    } else {
        const QString text = event->text();
        // Python Qt.Key(key).name.lower() — the enum member name
        // ("Key_Up" → "key_up"), NOT QKeySequence text ("Up" → "up").
        key_name = !text.isEmpty()
                       ? text.toStdString()
                       : QString::fromLatin1(
                             QMetaEnum::fromType<Qt::Key>().valueToKey(key))
                             .toLower()
                             .toStdString();
    }
    if (tool_controller_ != nullptr &&
        tool_controller_->key_press(key_name)) {
        emit_tool_operation();
        update();
        event->accept();
        return;
    }
    QWidget::keyPressEvent(event);
}

void UnifiedMapCanvas::keyReleaseEvent(QKeyEvent* event) {
    if (event->key() == Qt::Key_Space) {
        space_pan_ = false;
        event->accept();
        return;
    }
    QWidget::keyReleaseEvent(event);
}

void UnifiedMapCanvas::mousePressEvent(QMouseEvent* event) {
    if (event->button() == Qt::LeftButton) {
        press_pos_ = event->position();
    }
    if (event->button() == Qt::MiddleButton ||
        (space_pan_ && event->button() == Qt::LeftButton)) {
        drag_pos_ = event->position();
        setCursor(Qt::ClosedHandCursor);
        event->accept();
        return;
    }
    if (tool_controller_ != nullptr && tool_controller_->has_active_tool()) {
        if (tool_controller_->active_tool_id() == "pan" &&
            event->button() == Qt::LeftButton) {
            drag_pos_ = event->position();
            setCursor(Qt::ClosedHandCursor);
            event->accept();
            return;
        }
        const auto point = screen_to_map(event->position());
        if (tool_controller_->tool_mouse_press(
                point, button_name(event->button()),
                modifier_names(event->modifiers()))) {
            emit_tool_operation();
            update();
            event->accept();
            return;
        }
    }
    QWidget::mousePressEvent(event);
}

void UnifiedMapCanvas::mouseMoveEvent(QMouseEvent* event) {
    if (drag_pos_.has_value()) {
        const QPointF delta = event->position() - *drag_pos_;
        pan_by_pixels(delta.x(), delta.y());
        drag_pos_ = event->position();
        event->accept();
        return;
    }
    cursor_map_ = screen_to_map(event->position());
    emit map_position_changed(*cursor_map_);
    if (tool_controller_ != nullptr && tool_controller_->has_active_tool()) {
        if (tool_controller_->tool_mouse_move(
                *cursor_map_, modifier_names(event->modifiers()))) {
            emit_tool_operation();
            // Only tools paint cursor-relative feedback; a bare hover over
            // the canvas must not schedule full repaints per mouse-move.
            update();
        }
    }
    QWidget::mouseMoveEvent(event);
}

void UnifiedMapCanvas::mouseReleaseEvent(QMouseEvent* event) {
    if (drag_pos_.has_value() &&
        (event->button() == Qt::MiddleButton ||
         event->button() == Qt::LeftButton)) {
        drag_pos_.reset();
        unsetCursor();
        event->accept();
        return;
    }
    if (tool_controller_ != nullptr && tool_controller_->has_active_tool()) {
        const auto point = screen_to_map(event->position());
        if (tool_controller_->tool_mouse_release(
                point, button_name(event->button()),
                modifier_names(event->modifiers()))) {
            emit_tool_operation();
            update();
            event->accept();
            return;
        }
    }
    // A bare left-click (no drag, no tool claim) is a map click.
    if (event->button() == Qt::LeftButton && press_pos_.has_value()) {
        const QPointF press = *press_pos_;
        press_pos_.reset();
        if ((event->position() - press).manhattanLength() <
            kMapClickTolerancePx) {
            emit map_clicked(screen_to_map(event->position()));
            event->accept();
            return;
        }
    }
    QWidget::mouseReleaseEvent(event);
}

void UnifiedMapCanvas::mouseDoubleClickEvent(QMouseEvent* event) {
    if (tool_controller_ != nullptr && tool_controller_->has_active_tool()) {
        if (tool_controller_->tool_double_click(
                screen_to_map(event->position()),
                modifier_names(event->modifiers()))) {
            emit_tool_operation();
            update();
            event->accept();
            return;
        }
    }
    QWidget::mouseDoubleClickEvent(event);
}

std::string UnifiedMapCanvas::button_name(Qt::MouseButton button) {
    switch (button) {
        case Qt::LeftButton: return "left";
        case Qt::RightButton: return "right";
        case Qt::MiddleButton: return "middle";
        default: return "other";
    }
}

std::set<std::string>
UnifiedMapCanvas::modifier_names(Qt::KeyboardModifiers modifiers) {
    std::set<std::string> names;
    if (modifiers & Qt::ControlModifier) names.insert("ctrl");
    if (modifiers & Qt::ShiftModifier) names.insert("shift");
    if (modifiers & Qt::AltModifier) names.insert("alt");
    return names;
}

// ---------------------------------------------------------------------------
// Export paths (export_png / export_svg / export_pdf parity)
// ---------------------------------------------------------------------------

int UnifiedMapCanvas::default_export_height(int width) const {
    return ui_canvas::default_export_height(view_extent_, width);
}

QImage UnifiedMapCanvas::render_export_image(int width, int height,
                                             double dpi,
                                             bool preserve_aspect) {
    if (width < 1 || height < 1) {
        throw std::invalid_argument("export size must be positive");
    }
    if (backend_->render_active()) {
        backend_->cancel_render();
    }
    const auto previous_size = backend_->output_size();
    const double previous_dpi = backend_->dpi();
    const Extent previous_extent = backend_->extent();
    const auto restore = [this, previous_size, previous_dpi,
                          previous_extent]() {
        backend_->set_output_size(previous_size.first,
                                  previous_size.second);
        backend_->set_dpi(previous_dpi);
        backend_->set_extent(previous_extent);
    };
    try {
        backend_->set_output_size(width, height);
        backend_->set_dpi(dpi);
        if (preserve_aspect) {
            backend_->set_extent(
                letterboxed_extent(view_extent_, width, height));
        }
        const RenderFrame frame = backend_->render_sync();
        QImage image(frame.rgba.data(), frame.width, frame.height,
                     frame.stride, QImage::Format_RGBA8888);
        image = image.copy();
        QPainter painter(&image);
        painter.setRenderHint(QPainter::Antialiasing, true);
        const Json state = overlay_provider_ != nullptr
                               ? overlay_provider_()
                               : Json::object();
        paint_decorations(
            painter, state.value("decorations", Json::object()), width,
            height, device_px_per_logical_px(dpi),
            preserve_aspect
                ? letterboxed_extent(view_extent_, width, height)
                : view_extent_);
        painter.end();
        restore();
        return image;
    } catch (...) {
        restore();
        throw;
    }
}

void UnifiedMapCanvas::export_png(const std::string& path, int width,
                                  std::optional<int> height, double dpi) {
    const int resolved_height =
        height.has_value() ? *height : default_export_height(width);
    QImage image = render_export_image(width, resolved_height, dpi);
    // Persist the physical resolution so printed sizes match the export DPI.
    const int dots_per_meter = static_cast<int>(std::lround(dpi / 0.0254));
    image.setDotsPerMeterX(dots_per_meter);
    image.setDotsPerMeterY(dots_per_meter);
    if (!image.save(QString::fromStdString(path), "PNG")) {
        throw std::runtime_error("could not save unified map PNG");
    }
}

bool UnifiedMapCanvas::export_via_backend(const std::string& path,
                                          const std::string& format,
                                          int width, int height,
                                          double dpi) {
    // Produce the map body through the backend's own vector exporter.
    if (backend_->render_active()) {
        backend_->cancel_render();
    }
    const auto previous_size = backend_->output_size();
    const double previous_dpi = backend_->dpi();
    const Extent previous_extent = backend_->extent();
    const auto restore = [this, previous_size, previous_dpi,
                          previous_extent]() {
        backend_->set_output_size(previous_size.first,
                                  previous_size.second);
        backend_->set_dpi(previous_dpi);
        backend_->set_extent(previous_extent);
    };
    try {
        backend_->set_output_size(width, height);
        backend_->set_dpi(dpi);
        backend_->set_extent(
            letterboxed_extent(view_extent_, width, height));
        const bool ok = backend_->export_map_body(path, format, width,
                                                  height, dpi);
        restore();
        return ok;
    } catch (...) {
        restore();
        return false;
    }
}

bool UnifiedMapCanvas::paint_native_map_body(QPainter& painter, int width,
                                             int height, double dpi) {
    // The native backend writes a map-only SVG to a temp file, replayed
    // through QSvgRenderer so SVG and PDF exports keep vector geometry
    // from the same renderer configuration as the screen.
    QTemporaryFile temp(QStringLiteral("paleo-map-body-XXXXXX.svg"));
    if (!temp.open()) {
        return false;
    }
    const std::string temp_path = temp.fileName().toStdString();
    temp.close();
    try {
        if (!export_via_backend(temp_path, "svg", width, height, dpi)) {
            return false;
        }
        QSvgRenderer renderer(QString::fromStdString(temp_path));
        if (!renderer.isValid()) {
            return false;
        }
        renderer.render(&painter,
                        QRectF(0, 0, double(width), double(height)));
        return true;
    } catch (...) {
        return false;
    }
}

void UnifiedMapCanvas::export_svg(const std::string& path, int width,
                                  std::optional<int> height, double dpi) {
    const int resolved_height =
        height.has_value() ? *height : default_export_height(width);
    QSvgGenerator generator;
    generator.setFileName(QString::fromStdString(path));
    generator.setSize(QSize(width, resolved_height));
    generator.setViewBox(QRect(0, 0, width, resolved_height));
    generator.setResolution(static_cast<int>(std::lround(dpi)));
    generator.setTitle(export_title());
    QPainter painter;
    if (!painter.begin(&generator)) {
        throw std::runtime_error("could not begin unified map SVG export");
    }
    painter.setRenderHint(QPainter::Antialiasing, true);
    if (paint_native_map_body(painter, width, resolved_height, dpi)) {
        paint_export_decorations(painter, width, resolved_height, dpi);
        painter.end();
        return;
    }
    paint_export_vector(painter, width, resolved_height, dpi);
    painter.end();
}

void UnifiedMapCanvas::export_pdf(const std::string& path, int width,
                                  std::optional<int> height, double dpi) {
    const int resolved_height =
        height.has_value() ? *height : default_export_height(width);
    QPdfWriter writer(QString::fromStdString(path));
    writer.setResolution(static_cast<int>(std::lround(dpi)));
    const QSizeF page_mm(width / dpi * 25.4, resolved_height / dpi * 25.4);
    writer.setPageSize(QPageSize(page_mm, QPageSize::Millimeter));
    writer.setPageMargins(QMarginsF(0, 0, 0, 0));
    QPainter painter;
    if (!painter.begin(&writer)) {
        throw std::runtime_error("could not begin unified map PDF export");
    }
    painter.setRenderHint(QPainter::Antialiasing, true);
    const QRectF page_rect =
        writer.pageLayout().paintRectPixels(writer.resolution());
    if (paint_native_map_body(painter, static_cast<int>(page_rect.width()),
                              static_cast<int>(page_rect.height()), dpi)) {
        paint_export_decorations(
            painter, static_cast<int>(page_rect.width()),
            static_cast<int>(page_rect.height()), dpi,
            letterboxed_extent(view_extent_, width, resolved_height));
        painter.end();
        return;
    }
    paint_export_vector(painter, static_cast<int>(page_rect.width()),
                        static_cast<int>(page_rect.height()), dpi);
    painter.end();
}

void UnifiedMapCanvas::paint_export_decorations(
    QPainter& painter, int width, int height, double dpi,
    std::optional<Extent> extent) {
    const Json state = overlay_provider_ != nullptr ? overlay_provider_()
                                                    : Json::object();
    const Extent export_extent =
        extent.has_value() ? *extent
                           : letterboxed_extent(view_extent_, width, height);
    paint_decorations(painter, state.value("decorations", Json::object()),
                      width, height, device_px_per_logical_px(dpi),
                      export_extent);
}

void UnifiedMapCanvas::paint_export_vector(QPainter& painter, int width,
                                           int height, double dpi) {
    // The backend's vector/raster pipeline plus chrome at export
    // resolution — _paint_export_vector parity.
    if (backend_->render_active()) {
        // An in-flight screen render must not complete against the mutated
        // export viewport and later surface on screen.
        backend_->cancel_render();
    }
    const auto previous_size = backend_->output_size();
    const double previous_dpi = backend_->dpi();
    const Extent previous_extent = backend_->extent();
    const Extent export_extent =
        letterboxed_extent(view_extent_, width, height);
    const auto restore = [this, previous_size, previous_dpi,
                          previous_extent]() {
        backend_->set_output_size(previous_size.first,
                                  previous_size.second);
        backend_->set_dpi(previous_dpi);
        backend_->set_extent(previous_extent);
    };
    try {
        backend_->set_output_size(width, height);
        backend_->set_dpi(dpi);
        backend_->set_extent(export_extent);
        // FallbackMapRenderBackend's render_to_painter path is a
        // backend-specific vector hook; other backends rasterise a frame
        // at export resolution (Python parity: isinstance check →
        // VectorPaintCapableBackend RTTI).
        if (auto* vector_backend =
                dynamic_cast<VectorPaintCapableBackend*>(backend_.get());
            vector_backend != nullptr &&
            vector_backend->render_to_painter(painter, width, height,
                                              dpi)) {
            // Vector body painted natively.
        } else {
            const RenderFrame frame = backend_->render_sync();
            QImage image(frame.rgba.data(), frame.width, frame.height,
                         frame.stride, QImage::Format_RGBA8888);
            painter.drawImage(QRectF(0, 0, width, height), image);
        }
        const Json state = overlay_provider_ != nullptr
                               ? overlay_provider_()
                               : Json::object();
        paint_decorations(painter,
                          state.value("decorations", Json::object()),
                          width, height, device_px_per_logical_px(dpi),
                          export_extent);
        restore();
    } catch (...) {
        restore();
        throw;
    }
}

QString UnifiedMapCanvas::export_title() const {
    const Json state = overlay_provider_ != nullptr ? overlay_provider_()
                                                    : Json::object();
    const auto decorations = state.find("decorations");
    if (decorations != state.end() && decorations->is_object()) {
        const auto title = decorations->find("title");
        if (title != decorations->end() && title->is_string() &&
            !title->get<std::string>().empty()) {
            return QString::fromStdString(title->get<std::string>());
        }
    }
    return QStringLiteral("Paleogeographic map");
}

void UnifiedMapCanvas::shutdown() {
    if (shutdown_done_) {
        return;
    }
    shutdown_done_ = true;
    poll_timer_.stop();
    navigation_render_timer_.stop();
    image_ = QImage();
    image_buffer_.clear();
    backend_->shutdown();
}

void UnifiedMapCanvas::closeEvent(QCloseEvent* event) {
    shutdown();
    QWidget::closeEvent(event);
}

}  // namespace pwb::ui_canvas
