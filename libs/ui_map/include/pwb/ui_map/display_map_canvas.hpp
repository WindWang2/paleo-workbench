#pragma once

// UI-05 — DisplayMapCanvas: the read-only display canvas that owns an
// isolated pwb::qgis::MapSession (its own QgsProject + QgsMapCanvas), the
// C++ counterpart of qgis_stack/display_canvas.py's QgisDisplayCanvas.
//
// Contract parity:
//   * QgisRuntime must already be acquired by the host (MapSession
//     construction throws otherwise — caught into the unavailable surface);
//   * extent history seeds (0,0,1,1), coalesce/100-cap, programmatic
//     extents do not re-record;
//   * set_layer_snapshot mirrors the immutable MapRenderSnapshot Json into
//     the session project (full-rebuild variant of the Python incremental
//     mirror — display snapshots are immutable, so rebuild == reconcile);
//   * mirror failures surface via backend_status() = "qgis: degraded
//     (N mirror failures)" (#1164 parity);
//   * left-click press+release under 6px Manhattan emits map_clicked in
//     map coordinates;
//   * the overlay widget paints selected-feature rings + map chrome
//     through map_chrome_painter (dark_chrome = true, matching the
//     light frame backgrounds the renderers produce);
//   * shutdown() is idempotent and releases the session before teardown.

#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include <QPointer>
#include <QWidget>

#include <pwb/ui_map/map_chrome_core.hpp>

class QgsMapCanvas;
class QgsMapTool;
class QLabel;

namespace pwb::qgis {
class MapSession;
}

namespace pwb::ui_map {

class DisplayMapCanvas : public QWidget {
    Q_OBJECT
public:
    explicit DisplayMapCanvas(QWidget* parent = nullptr);
    ~DisplayMapCanvas() override;

    // Idempotent: drop the session (ordered teardown) before the widget is
    // destroyed by the host. Hosts call this on project switch/teardown.
    void shutdown();

    bool backend_available() const { return canvas_ != nullptr; }
    // "qgis" | "qgis: degraded (N mirror failures)" | "unavailable".
    QString backend_status() const;
    std::vector<std::string> mirror_failures() const {
        return mirror_failures_;
    }

    // Immutable MapRenderSnapshot Json: {"project_crs","layers":[{...}]}.
    void set_layer_snapshot(const Json& snapshot);
    const Json& snapshot() const { return snapshot_; }

    // Extent navigation (display_canvas.py parity — the live canvas extent
    // is authoritative; history is the fallback).
    Extent view_extent() const;
    void set_extent(const Extent& extent, bool record_history = true,
                    bool coalesce_history = false);
    // factor must be positive; std::invalid_argument otherwise (Python
    // ValueError parity).
    void zoom_by(
        double factor,
        std::optional<std::pair<double, double>> center = std::nullopt,
        bool coalesce_history = false);
    bool can_previous_extent() const { return history_.can_previous(); }
    bool can_next_extent() const { return history_.can_next(); }
    bool previous_extent();
    bool next_extent();

    // map → device px through the canvas transform; nullopt when the
    // transform is degenerate (Python's ArithmeticError catch — #1166).
    std::optional<QPointF> map_to_screen(double x, double y) const;
    std::pair<double, double> screen_to_map(const QPointF& point) const;
    double map_units_per_pixel() const;
    std::vector<std::string> snapshot_source_version_ids() const;

    // Overlay payload provider — called inside the overlay's paintEvent.
    // Must never throw; empty/non-object → decorations cleared.
    // Provider returns a widget-owned cached state — invoked per paint,
    // so callers must not rebuild the tree per call (#1392).
    void set_overlay_provider(std::function<const Json&()> provider);

    QgsMapCanvas* qgs_canvas() const { return canvas_; }
    pwb::qgis::MapSession* session() const { return session_.get(); }

    // Mirror a single vector layer's visible flag through the layer tree
    // (the canvas bridge follows — no second authority).
    void set_layer_visible(const std::string& layer_id, bool visible);

signals:
    void extent_changed(const pwb::ui_map::Extent& extent);
    void map_position_changed(double x, double y);
    void backend_status_changed(const QString& status);
    void map_clicked(double x, double y);
    void tool_operation(bool edits_data);

protected:
    bool eventFilter(QObject* watched, QEvent* event) override;
    void resizeEvent(QResizeEvent* event) override;
    void showEvent(QShowEvent* event) override;
    void closeEvent(QCloseEvent* event) override;

private:
    // The transparent overlay widget paints through the provider and the
    // canvas transform (anonymous-namespace class in the .cpp).
    friend class CanvasOverlay;

    void on_canvas_extents_changed();
    void install_overlay_geometry();
    void emit_click(const QPointF& pos);

    std::unique_ptr<pwb::qgis::MapSession> session_;
    QgsMapCanvas* canvas_ = nullptr;   // child widget (Qt-owned)
    QgsMapTool* pan_tool_ = nullptr;   // owned by canvas after setMapTool
    QLabel* placeholder_ = nullptr;    // unavailable surface
    QWidget* overlay_ = nullptr;       // transparent decoration layer
    std::function<const Json&()> overlay_provider_;
    Json snapshot_ = Json::object();
    ExtentHistory history_;
    std::vector<std::string> mirror_failures_;
    bool shutdown_done_ = false;
    bool pending_programmatic_ = false;
    bool pressed_ = false;
    QPointF press_pos_;
};

}  // namespace pwb::ui_map
