// UI-15 — native Qt map canvas (native_map_canvas.py parity): cached
// scalar images + contour/point overlays + pointer pan/zoom. The scene is
// the composition authority; this widget only renders it.
#pragma once

#include <array>
#include <map>
#include <memory>
#include <optional>
#include <set>
#include <string>
#include <utility>

#include <QImage>
#include <QPointF>
#include <QWidget>

#include <pwb/ui_canvas/layer_scene.hpp>
#include <pwb/ui_canvas/qt/native_raster_controller.hpp>

class QMouseEvent;
class QWheelEvent;
class QCloseEvent;

namespace pwb::ui_canvas {

class NativeMapCanvas : public QWidget {
    Q_OBJECT
public:
    explicit NativeMapCanvas(NativeMapScene* scene = nullptr,
                             QWidget* parent = nullptr);
    ~NativeMapCanvas() override;

    // The composition authority; nullptr clears the canvas. The scene is
    // NOT owned (Python holds a ref; C++ uses an observer pointer — hosts
    // must outlive the canvas or call clear_scene() first).
    NativeMapScene* scene() const { return scene_; }
    void set_scene(NativeMapScene* scene);
    void clear_scene() { set_scene(nullptr); }

    std::array<double, 4> view_extent() const { return view_extent_; }
    void set_view_extent(const std::array<double, 4>& extent);
    void zoom_to_extent(const std::array<double, 4>& extent) {
        set_view_extent(extent);
    }
    void zoom_by(double factor,
                 std::optional<std::pair<double, double>> center =
                     std::nullopt);
    void pan_by_pixels(double dx, double dy);
    void fit_to_scene();

    // Synchronously populate any missing images before an explicit PNG
    // export (interactive paints stay asynchronous; a user-initiated export
    // waits for the native cache — Python prepare_for_export parity).
    void prepare_for_export();

    // The raster controller's boolean shutdown/join report (#1042 parity).
    bool shutdown(int wait_ms = 3000);

    // Test/self-check visibility.
    const QImage& cached_image(const std::string& layer_id) const;
    std::size_t image_cache_size() const { return image_cache_.size(); }
    std::string last_raster_error() const { return last_raster_error_; }
    NativeRasterRequestController* raster_controller() {
        return &raster_controller_;
    }

protected:
    void paintEvent(QPaintEvent* event) override;
    void wheelEvent(QWheelEvent* event) override;
    void mousePressEvent(QMouseEvent* event) override;
    void mouseMoveEvent(QMouseEvent* event) override;
    void mouseReleaseEvent(QMouseEvent* event) override;
    void closeEvent(QCloseEvent* event) override;

private:
    QPointF world_to_screen(double x, double y) const;
    std::pair<double, double> screen_to_world(const QPointF& point) const;
    // Returns the cached image for `layer_id` or queues its rasterization
    // (null image while in flight — Python _image_for parity).
    QImage image_for(const std::string& layer_id);
    static QImage image_from_rgba(const RasterImage& raster);

    void on_raster_ready(const NativeRasterRequest& request,
                         const RasterImage& image);
    void on_raster_failed(const NativeRasterRequest& request,
                          const QString& message);

    NativeMapScene* scene_ = nullptr;  // observer
    std::size_t scene_listener_token_ = 0;
    std::uint64_t scene_epoch_ = 0;
    std::array<double, 4> view_extent_{0.0, 0.0, 1.0, 1.0};
    // layer_id -> (raster_key, image) — keyed by (data, style) revisions.
    std::map<std::string, std::pair<RasterKey, QImage>> image_cache_;
    std::optional<QPointF> last_drag_pos_;
    NativeRasterRequestController raster_controller_;
    std::string last_raster_error_;
    // _logged_raster_errors parity — per-instance dedupe of raster-failure
    // warnings (#897).
    std::set<std::pair<std::string, RasterKey>> logged_raster_errors_;
};

}  // namespace pwb::ui_canvas
