#pragma once

// UI-02 — read-only QgsMapCanvas with its own session project (home /
// workspace / preview maps), ported from
// paleo_workbench/ui/qgis_stack/display_canvas.py.
//
// Session-owned QgsProject (guidance: display canvases NEVER touch the
// shared project state). The widget keeps the Python contract: pan-only
// interaction, click hit-test, decorations overlay, extent history,
// mirror publish with honest failure surfacing, orderly shutdown.

#include <QPointer>
#include <QWidget>

#include <array>
#include <functional>
#include <memory>
#include <vector>

class QgsMapCanvas;
class QgsVectorLayer;

namespace pwb::qgis {
class MapSession;
}

namespace pwb::ui_widgets::qgis {

class StackEvents;
class QgisCanvasHost;
struct MirrorSnapshot;
struct MirrorOptions;
class MirrorLedger;
struct MirrorResult;

// Backend descriptor parity (_DisplayBackend): the display canvas is
// always a real QGIS backend in the native build.
struct DisplayBackend {
    QString backend_name = QStringLiteral("qgis");
    QString status = QStringLiteral("ready");
};

class QgisDisplayCanvas : public QWidget {
    Q_OBJECT
public:
    explicit QgisDisplayCanvas(QWidget* parent = nullptr);
    ~QgisDisplayCanvas() override;

    // --- Python property surface -----------------------------------
    std::array<double, 4> view_extent() const;
    void set_extent(const std::array<double, 4>& extent,
                    bool record_history = true,
                    bool coalesce_history = false);
    void zoom_by(double factor,
                 std::pair<double, double> center = {0, 0},
                 bool has_center = false,
                 bool coalesce_history = false);

    bool can_previous_extent() const { return extent_history_index_ > 0; }
    bool can_next_extent() const {
        return extent_history_index_ + 1 < int(extent_history_.size());
    }
    bool previous_extent();
    bool next_extent();

    QPointF map_to_screen(std::pair<double, double> point) const;
    std::pair<double, double> screen_to_map(
        std::pair<double, double> point) const;
    double map_units_per_pixel() const;

    // Decorations provider (the Python _overlay_provider): returns the
    // decorations QVariantMap painted by the overlay (basic chrome is
    // injected when elements is empty).
    void set_overlay_provider(
        std::function<QVariantMap()> provider);

    // Mirror publish (set_layer_snapshot parity): failures surface into
    // backend_status + backend_status_changed, never swallowed (#1164).
    void set_layer_snapshot(const MirrorSnapshot& snapshot);
    QString backend_status() const;
    const DisplayBackend& backend() const { return backend_; }

    // snapshot_source_version_ids parity: unique source_version_id
    // values declared by the last snapshot's layers (metadata key).
    QStringList snapshot_source_version_ids() const;

    QgsMapCanvas* canvas() const { return canvas_; }
    quintptr canvas_address() const {
        return reinterpret_cast<quintptr>(canvas_);
    }

    // Orderly teardown (host calls before destroying the widget tree —
    // same contract as Python's shutdown(); Qt-destruction bookkeeping
    // is handled internally via _mark_disposed semantics).
    void shutdown();

    // Internal surfaces used by the click filter / overlay (public for
    // the same reason the Python helpers are reachable).
    void emit_map_click(const QPointF& pos);
    QVariantMap overlay_state() const;

signals:
    void extent_changed(std::array<double, 4> extent);
    void map_position_changed(std::pair<double, double> position);
    void backend_status_changed(const QString& status);
    void map_clicked(std::pair<double, double> map_point);
    void tool_operation(bool mutated);

protected:
    void resizeEvent(QResizeEvent* event) override;
    void showEvent(QShowEvent* event) override;
    void closeEvent(QCloseEvent* event) override;

private:
    void record_extent(const std::array<double, 4>& tup, bool coalesce);
    void install_chrome_overlay();
    void on_stack_extent(double xmin, double ymin, double xmax,
                         double ymax);
    void mark_disposed();

    std::unique_ptr<pwb::qgis::MapSession> session_;
    QgisCanvasHost* host_ = nullptr;
    QgsMapCanvas* canvas_ = nullptr;
    StackEvents* events_ = nullptr;
    QWidget* overlay_ = nullptr;
    QObject* click_filter_ = nullptr;
    std::function<QVariantMap()> overlay_provider_;
    std::unique_ptr<MirrorLedger> ledger_;
    QStringList mirror_failures_;
    bool shutdown_done_ = false;
    std::vector<std::array<double, 4>> extent_history_{{0, 0, 1, 1}};
    int extent_history_index_ = 0;
    bool pending_programmatic_ = false;
    QStringList snapshot_version_ids_;
    DisplayBackend backend_;
};

}  // namespace pwb::ui_widgets::qgis
