// UI-15 — native Qt map canvas (native_map_canvas.py parity).

#include <pwb/ui_canvas/qt/native_map_canvas.hpp>

#include <algorithm>
#include <cmath>
#include <set>
#include <stdexcept>

#include <QCloseEvent>
#include <QMouseEvent>
#include <QPainter>
#include <QPen>
#include <QWheelEvent>

#include <pwb/ui_widgets/ui_context.hpp>

namespace pwb::ui_canvas {

NativeMapCanvas::NativeMapCanvas(NativeMapScene* scene, QWidget* parent)
    : QWidget(parent) {
    setObjectName(QStringLiteral("NativeMapCanvas"));
    setMinimumSize(240, 180);
    setMouseTracking(true);
    connect(&raster_controller_,
            &NativeRasterRequestController::raster_ready, this,
            [this](const NativeRasterRequest& request,
                   const RasterImage& image) {
                on_raster_ready(request, image);
            });
    connect(&raster_controller_,
            &NativeRasterRequestController::raster_failed, this,
            [this](const NativeRasterRequest& request,
                   const QString& message) {
                on_raster_failed(request, message);
            });
    if (scene != nullptr) {
        set_scene(scene);
    }
}

NativeMapCanvas::~NativeMapCanvas() {
    if (scene_ != nullptr) {
        scene_->remove_change_listener(scene_listener_token_);
    }
}

void NativeMapCanvas::set_scene(NativeMapScene* scene) {
    if (scene_ != nullptr) {
        scene_->remove_change_listener(scene_listener_token_);
        scene_listener_token_ = 0;
    }
    scene_ = scene;
    ++scene_epoch_;
    raster_controller_.invalidate();
    if (scene_ != nullptr) {
        scene_listener_token_ = scene_->add_change_listener(
            [this]() { update(); });
    }
    image_cache_.clear();
    fit_to_scene();
    update();
}

void NativeMapCanvas::fit_to_scene() {
    if (scene_ == nullptr) {
        view_extent_ = {0.0, 0.0, 1.0, 1.0};
        return;
    }
    const std::array<double, 4> extent = scene_->extent();
    const double dx = extent[2] - extent[0];
    const double dy = extent[3] - extent[1];
    if (dx <= 0.0 || dy <= 0.0) {
        view_extent_ = {0.0, 0.0, 1.0, 1.0};
        return;
    }
    constexpr double margin = 0.04;
    view_extent_ = {extent[0] - dx * margin, extent[1] - dy * margin,
                    extent[2] + dx * margin, extent[3] + dy * margin};
}

void NativeMapCanvas::set_view_extent(
    const std::array<double, 4>& extent) {
    const double xmin = extent[0], ymin = extent[1];
    const double xmax = extent[2], ymax = extent[3];
    if (!(xmax > xmin && ymax > ymin)) {
        throw std::invalid_argument(
            "view extent must have positive width and height");
    }
    view_extent_ = {xmin, ymin, xmax, ymax};
    update();
}

void NativeMapCanvas::zoom_by(
    double factor, std::optional<std::pair<double, double>> center) {
    if (factor <= 0.0) {
        throw std::invalid_argument("zoom factor must be positive");
    }
    const double xmin = view_extent_[0], ymin = view_extent_[1];
    const double xmax = view_extent_[2], ymax = view_extent_[3];
    const auto [cx, cy] =
        center.value_or(
            std::make_pair((xmin + xmax) / 2.0, (ymin + ymax) / 2.0));
    set_view_extent({cx + (xmin - cx) * factor, cy + (ymin - cy) * factor,
                     cx + (xmax - cx) * factor, cy + (ymax - cy) * factor});
}

void NativeMapCanvas::pan_by_pixels(double dx, double dy) {
    const double xmin = view_extent_[0], ymin = view_extent_[1];
    const double xmax = view_extent_[2], ymax = view_extent_[3];
    const double width = std::max(1, this->width());
    const double height = std::max(1, this->height());
    const double world_dx = -dx * (xmax - xmin) / width;
    const double world_dy = dy * (ymax - ymin) / height;
    set_view_extent({xmin + world_dx, ymin + world_dy,
                     xmax + world_dx, ymax + world_dy});
}

QPointF NativeMapCanvas::world_to_screen(double x, double y) const {
    const double xmin = view_extent_[0], ymin = view_extent_[1];
    const double xmax = view_extent_[2], ymax = view_extent_[3];
    return QPointF((x - xmin) * width() / (xmax - xmin),
                   height() - (y - ymin) * height() / (ymax - ymin));
}

std::pair<double, double>
NativeMapCanvas::screen_to_world(const QPointF& point) const {
    const double xmin = view_extent_[0], ymin = view_extent_[1];
    const double xmax = view_extent_[2], ymax = view_extent_[3];
    const double w = std::max(1, width());
    const double h = std::max(1, height());
    return {xmin + point.x() * (xmax - xmin) / w,
            ymin + (height() - point.y()) * (ymax - ymin) / h};
}

QImage NativeMapCanvas::image_from_rgba(const RasterImage& raster) {
    // Copy — the QImage must own its pixels (RasterImage is transient).
    QImage image(raster.rgba.data(), raster.width, raster.height,
                 raster.stride, QImage::Format_RGBA8888);
    return image.copy();
}

QImage NativeMapCanvas::image_for(const std::string& layer_id) {
    Q_ASSERT(scene_ != nullptr);
    RasterKey key{0, 0};
    try {
        key = scene_->scalar_raster_key(layer_id);
    } catch (const std::out_of_range&) {
        return QImage();
    }
    const auto cached = image_cache_.find(layer_id);
    if (cached != image_cache_.end() && cached->second.first == key) {
        return cached->second.second;
    }
    ScalarRasterSourcePtr scalar = scene_->scalar_layer(layer_id);
    if (!scalar) {
        return QImage();
    }
    raster_controller_.request(scene_epoch_, layer_id, key,
                               std::move(scalar));
    return QImage();
}

void NativeMapCanvas::on_raster_ready(
    const NativeRasterRequest& request, const RasterImage& image) {
    if (scene_ == nullptr || request.scene_epoch != scene_epoch_) {
        return;
    }
    if (scene_->scalar_layer(request.layer_id) != request.scalar) {
        return;
    }
    try {
        if (scene_->scalar_raster_key(request.layer_id) !=
            request.raster_key) {
            return;
        }
    } catch (const std::out_of_range&) {
        return;
    }
    image_cache_[request.layer_id] =
        std::make_pair(request.raster_key, image_from_rgba(image));
    last_raster_error_.clear();
    update();
}

void NativeMapCanvas::on_raster_failed(
    const NativeRasterRequest& request, const QString& message) {
    const bool stale =
        scene_ != nullptr && request.scene_epoch != scene_epoch_;
    if (stale) {
        return;
    }
    if (scene_ != nullptr && request.scene_epoch == scene_epoch_) {
        last_raster_error_ = message.toStdString();
    }
    // The stored error previously had no consumer at all: a failed native
    // rasterization silently rendered as "no data" (#897). Log once per
    // layer+raster_key so repeated failures don't spam.
    const auto key =
        std::make_pair(request.layer_id, request.raster_key);
    if (logged_raster_errors_.insert(key).second) {
        qWarning("native scalar layer %s rasterization failed "
                 "(raster_key=(%llu,%llu)): %s",
                 request.layer_id.empty() ? "<unknown>"
                                          : request.layer_id.c_str(),
                 static_cast<unsigned long long>(request.raster_key.first),
                 static_cast<unsigned long long>(request.raster_key.second),
                 qUtf8Printable(message));
    }
}

void NativeMapCanvas::prepare_for_export() {
    if (scene_ == nullptr) {
        return;
    }
    for (const auto& layer : scene_->registry().layers()) {
        ScalarRasterSourcePtr scalar = scene_->scalar_layer(layer->id());
        if (!scalar) {
            continue;
        }
        RasterKey key{0, 0};
        try {
            key = scene_->scalar_raster_key(layer->id());
        } catch (const std::out_of_range&) {
            continue;
        }
        const auto cached = image_cache_.find(layer->id());
        if (cached != image_cache_.end() && cached->second.first == key) {
            continue;
        }
        image_cache_[layer->id()] = std::make_pair(
            key, image_from_rgba(scene_->raster_rgba(layer->id())));
    }
}

bool NativeMapCanvas::shutdown(int wait_ms) {
    return raster_controller_.shutdown(wait_ms);
}

const QImage& NativeMapCanvas::cached_image(
    const std::string& layer_id) const {
    static const QImage empty;
    const auto it = image_cache_.find(layer_id);
    return it == image_cache_.end() ? empty : it->second.second;
}

void NativeMapCanvas::paintEvent(QPaintEvent* /*event*/) {
    QPainter painter(this);
    painter.fillRect(rect(), QColor(pwb::ui_widgets::palette_token("BG_SEARCH")));
    if (scene_ == nullptr) {
        return;
    }
    for (const auto& layer : scene_->registry().layers()) {
        if (!scene_->registry().is_effectively_visible(layer->id(), 1.0)) {
            continue;
        }
        ScalarRasterSourcePtr scalar = scene_->scalar_layer(layer->id());
        painter.save();
        painter.setOpacity(layer->opacity());
        if (scalar) {
            const auto e = layer->extent();
            const QPointF lower_left = world_to_screen(e[0], e[1]);
            const QPointF upper_right = world_to_screen(e[2], e[3]);
            const QRectF target =
                QRectF(upper_right, lower_left).normalized();
            painter.drawImage(target, image_for(layer->id()));
        }
        if (const ContourGeometry* contour =
                scene_->contour_geometry(layer->id())) {
            painter.setPen(QPen(QColor(contour->color[0], contour->color[1],
                                       contour->color[2], contour->color[3]),
                                contour->width));
            for (const auto& path : contour->paths) {
                if (path.size() < 2) {
                    continue;
                }
                for (std::size_t i = 0; i + 1 < path.size(); ++i) {
                    painter.drawLine(world_to_screen(path[i].first,
                                                     path[i].second),
                                     world_to_screen(path[i + 1].first,
                                                     path[i + 1].second));
                }
            }
        }
        if (const PointGeometry* points =
                scene_->point_geometry(layer->id())) {
            painter.setPen(Qt::NoPen);
            painter.setBrush(QColor(points->color[0], points->color[1],
                                    points->color[2], points->color[3]));
            for (const auto& [x, y] : points->points) {
                painter.drawEllipse(world_to_screen(x, y), points->radius,
                                    points->radius);
            }
        }
        painter.restore();
    }
}

void NativeMapCanvas::wheelEvent(QWheelEvent* event) {
    const int delta = event->angleDelta().y();
    if (delta != 0) {
        const auto [wx, wy] = screen_to_world(event->position());
        zoom_by(delta > 0 ? 0.8 : 1.25, std::make_pair(wx, wy));
        event->accept();
        return;
    }
    event->ignore();
}

void NativeMapCanvas::mousePressEvent(QMouseEvent* event) {
    if (event->button() == Qt::LeftButton) {
        last_drag_pos_ = event->position();
        setCursor(Qt::ClosedHandCursor);
        event->accept();
        return;
    }
    QWidget::mousePressEvent(event);
}

void NativeMapCanvas::mouseMoveEvent(QMouseEvent* event) {
    if (last_drag_pos_.has_value() &&
        (event->buttons() & Qt::LeftButton)) {
        const QPointF delta = event->position() - *last_drag_pos_;
        pan_by_pixels(delta.x(), delta.y());
        last_drag_pos_ = event->position();
        event->accept();
        return;
    }
    QWidget::mouseMoveEvent(event);
}

void NativeMapCanvas::mouseReleaseEvent(QMouseEvent* event) {
    if (event->button() == Qt::LeftButton && last_drag_pos_.has_value()) {
        last_drag_pos_.reset();
        unsetCursor();
        event->accept();
        return;
    }
    QWidget::mouseReleaseEvent(event);
}

void NativeMapCanvas::closeEvent(QCloseEvent* event) {
    raster_controller_.shutdown();
    QWidget::closeEvent(event);
}

}  // namespace pwb::ui_canvas
