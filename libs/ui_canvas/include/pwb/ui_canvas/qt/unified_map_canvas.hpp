// UI-15 — primary renderer-neutral map canvas with GIS navigation and
// edit overlays (unified_map_canvas.py UnifiedMapCanvas parity).
//
// One host widget consuming frames from a MapRenderBackend. Feature
// editing overlays are intentionally painted above this widget; mouse
// navigation only changes viewport state and never rebuilds layer data.
#pragma once

#include <array>
#include <memory>
#include <optional>
#include <set>
#include <string>
#include <utility>
#include <vector>

#include <QImage>
#include <QPointF>
#include <QTimer>
#include <QTransform>
#include <QWidget>

#include <pwb/ui_canvas/map_render_backend.hpp>
#include <pwb/ui_map/map_chrome_core.hpp>

class QCloseEvent;
class QMouseEvent;
class QWheelEvent;
class QKeyEvent;
class QPainter;

namespace pwb::ui_canvas {

// Framework-neutral exclusive host map-tool controller — the canvas
// converts pointer coordinates and paints feedback but never becomes edit
// authority (Python _tool_controller duck parity). Hosts implement this
// over their tool system; the canvas calls the active tool's callbacks.
class MapToolController {
public:
    virtual ~MapToolController() = default;
    // controller.active_tool — nullptr semantics: no active tool.
    virtual bool has_active_tool() const = 0;
    // tool.tool_id ("" when none); "pan" is special-cased to drag-pan.
    virtual std::string active_tool_id() const = 0;
    // tool.edits_data — True only when the operation mutated document data.
    virtual bool active_tool_edits_data() const = 0;
    // tool.mouse_press(point, button=..., modifiers=...) -> handled.
    virtual bool tool_mouse_press(
        std::pair<double, double> map_point, const std::string& button,
        const std::set<std::string>& modifiers) = 0;
    virtual bool tool_mouse_move(
        std::pair<double, double> map_point,
        const std::set<std::string>& modifiers) = 0;
    virtual bool tool_mouse_release(
        std::pair<double, double> map_point, const std::string& button,
        const std::set<std::string>& modifiers) = 0;
    virtual bool tool_double_click(
        std::pair<double, double> map_point,
        const std::set<std::string>& modifiers) = 0;
    // controller.key_press(key_name) -> handled.
    virtual bool key_press(const std::string& key_name) = 0;
};

// Cheap overlay snapshot producer (selection/rubber band/snap mark/
// decorations). Returns a Json dict shaped like the Python overlay state:
//   {"selected_features": [{"geometry": {...}}, ...],
//    "capture_points": [[x, y], ...], "snap_point": [x, y] | null,
//    "decorations": {...}}
using OverlayProvider = std::function<Json()>;

// Optional backend capability for true vector export painting — the C++
// counterpart of Python's isinstance(backend, FallbackMapRenderBackend)
// check in _paint_export_vector. A backend that can paint its map body
// straight onto a QPainter implements this interface; the canvas discovers
// it via dynamic_cast (QPainter cannot appear in the Qt-free core header).
class VectorPaintCapableBackend {
public:
    virtual ~VectorPaintCapableBackend() = default;
    virtual bool render_to_painter(QPainter& painter, int width,
                                   int height, double dpi) = 0;
};

class UnifiedMapCanvas : public QWidget {
    Q_OBJECT
public:
    explicit UnifiedMapCanvas(
        std::shared_ptr<MapRenderBackend> backend = {},
        QWidget* parent = nullptr);
    ~UnifiedMapCanvas() override;

    MapRenderBackend* backend() const { return backend_.get(); }
    std::shared_ptr<MapRenderBackend> backend_shared() const {
        return backend_;
    }
    // "name: status" (Python backend_status property).
    QString backend_status() const;

    const std::optional<RenderFrame>& last_frame() const {
        return last_frame_;
    }
    Extent view_extent() const { return view_extent_; }
    // Whether the previous frame is being transformed pending a fresh
    // render (navigation_preview_active parity).
    bool navigation_preview_active() const {
        return !navigation_transform_.isIdentity();
    }

    // Local counters keeping navigation delivery observable
    // (frame_delivery_diagnostics parity).
    struct FrameDiagnostics {
        int render_requests = 0;
        int frames_delivered = 0;
        int frame_bytes_delivered = 0;
        int polls = 0;
        int empty_polls = 0;
    };
    FrameDiagnostics frame_delivery_diagnostics() const {
        return diagnostics_;
    }

    bool is_shutdown() const { return shutdown_done_; }

    void set_layer_snapshot(const MapRenderSnapshot& snapshot);
    // The signature dedup key (Python _snapshot_signature) — exposed for
    // tests and hosts.
    static std::string layer_snapshot_signature(
        const MapRenderSnapshot& snapshot) {
        return snapshot_signature(snapshot);
    }

    // Catalog DataVersion ids referenced by the current composition.
    std::vector<std::string> snapshot_source_version_ids() const;

    // V8/M1 duck parity with QgisCanvasShim: the fallback canvas has no
    // native QgsMapTool — always "" (honest).
    QString active_map_tool_id() const { return QString(); }

    void set_map_tool_controller(MapToolController* controller) {
        tool_controller_ = controller;
    }
    MapToolController* map_tool_controller() const {
        return tool_controller_;
    }

    void set_overlay_provider(OverlayProvider provider);
    const OverlayProvider& overlay_provider() const {
        return overlay_provider_;
    }

    // Coordinate transforms on the letterboxed (fitted) extent.
    Extent fitted_extent() const;
    double map_units_per_pixel() const;
    std::pair<double, double> screen_to_map(const QPointF& point) const;
    // Degenerate fitted extent → canvas center (#1166 parity).
    QPointF map_to_screen(std::pair<double, double> map_point) const;

    // Navigation.
    void set_extent(const Extent& extent, bool record_history = true,
                    bool coalesce_history = false);
    void zoom_by(double factor,
                 std::optional<std::pair<double, double>> center =
                     std::nullopt,
                 bool coalesce_history = false);
    void pan_by_pixels(double dx, double dy);
    bool can_previous_extent() const;
    bool can_next_extent() const;
    bool previous_extent();
    bool next_extent();

    // Synchronously render the same backend/composition at export
    // resolution (render_export_image parity).
    QImage render_export_image(int width, int height, double dpi = 300.0,
                               bool preserve_aspect = true);

    // Exports (export_png/export_svg/export_pdf parity).
    void export_png(const std::string& path, int width = 2400,
                    std::optional<int> height = std::nullopt,
                    double dpi = 300.0);
    void export_svg(const std::string& path, int width = 2400,
                    std::optional<int> height = std::nullopt,
                    double dpi = 300.0);
    void export_pdf(const std::string& path, int width = 2400,
                    std::optional<int> height = std::nullopt,
                    double dpi = 300.0);

    int default_export_height(int width) const;
    Extent letterboxed_export_extent(int width, int height) const {
        return letterboxed_extent(view_extent_, width, height);
    }

    // Idempotent teardown: stops polling and releases the backend.
    // Hosts call this on project switch / app exit — close() must not be
    // relied on for hidden widgets.
    void shutdown();

signals:
    void backend_status_changed(const QString& status);
    void frame_ready(const pwb::ui_canvas::RenderFrame& frame);
    void extent_changed(const pwb::ui_canvas::Extent& extent);
    void map_position_changed(const std::pair<double, double>& map_point);
    // V8/M1 signal-surface parity with QgisCanvasShim — the fallback
    // canvas never emits it (native tool activation failure is a
    // native-path concept; hosts connect by duck typing).
    void native_tool_activation_failed(const QString& tool_id,
                                       const QString& reason);
    // Left-click (press+release without drag) in map coordinates — for
    // hosts without a tool controller to hit-test features.
    void map_clicked(const std::pair<double, double>& map_point);
    // True only when the operation mutated document data (composition
    // must resync); pointer/selection feedback emits False.
    void tool_operation(bool edits_data);

protected:
    void resizeEvent(QResizeEvent* event) override;
    void paintEvent(QPaintEvent* event) override;
    void wheelEvent(QWheelEvent* event) override;
    void keyPressEvent(QKeyEvent* event) override;
    void keyReleaseEvent(QKeyEvent* event) override;
    void mousePressEvent(QMouseEvent* event) override;
    void mouseMoveEvent(QMouseEvent* event) override;
    void mouseReleaseEvent(QMouseEvent* event) override;
    void mouseDoubleClickEvent(QMouseEvent* event) override;
    void closeEvent(QCloseEvent* event) override;

private:
    void request_render();
    void request_navigation_render();
    void schedule_frame_poll(int interval_ms);
    void take_completed_frame();
    void publish_backend_status();
    void paint_overlay(QPainter& painter);
    void paint_decorations(QPainter& painter, const Json& decorations,
                           int width, int height, double scale,
                           const Extent& extent);
    void paint_geometry_outline(QPainter& painter, const Json& geometry);
    void paint_export_decorations(QPainter& painter, int width,
                                  int height, double dpi,
                                  std::optional<Extent> extent =
                                      std::nullopt);
    void paint_export_vector(QPainter& painter, int width, int height,
                             double dpi);
    bool paint_native_map_body(QPainter& painter, int width, int height,
                               double dpi);
    bool export_via_backend(const std::string& path,
                            const std::string& format, int width,
                            int height, double dpi);
    QString export_title() const;
    double screen_pixel_ratio() const;
    bool active_tool_edits_data() const;
    void emit_tool_operation();

    static std::string button_name(Qt::MouseButton button);
    static std::set<std::string> modifier_names(
        Qt::KeyboardModifiers modifiers);

    std::shared_ptr<MapRenderBackend> backend_;
    Extent view_extent_{0.0, 0.0, 1.0, 1.0};
    pwb::ui_map::ExtentHistory extent_history_;
    std::optional<RenderFrame> last_frame_;
    QImage image_;
    // QImage below borrows this immutable payload; retaining it keeps the
    // native pixels valid until the next delivered frame (Python
    // _image_buffer parity).
    std::vector<std::uint8_t> image_buffer_;
    QTransform navigation_transform_;
    std::optional<QPointF> drag_pos_;
    std::optional<QPointF> press_pos_;
    bool space_pan_ = false;
    MapToolController* tool_controller_ = nullptr;  // observer
    OverlayProvider overlay_provider_;
    std::optional<std::pair<double, double>> cursor_map_;
    QTimer poll_timer_;
    QTimer navigation_render_timer_;
    int poll_interval_ms_ = 0;
    bool shutdown_done_ = false;
    std::string last_snapshot_signature_;
    FrameDiagnostics diagnostics_;
};

}  // namespace pwb::ui_canvas
