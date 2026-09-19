#pragma once

// UI-09 — WellMapQgisSurface: the QGIS-backed IWellMapSurface.
//
// Owns an isolated pwb::qgis::MapSession (its own QgsProject +
// QgsMapCanvas — the DisplayMapCanvas role from ui_map) and mirrors each
// WellMapScene into memory vector layers: boundary/survey/reference
// lines below ok/flagged/selected point layers plus the cross-view
// spatial-cursor marker. Hover/click hit-testing matches the QPainter
// fallback exactly (nearest point within 8 px; series "wells" probed
// before "wells_flagged").
//
// When the QGIS runtime is not initialized the surface degrades to an
// explicit placeholder — the unavailable state stays visible (never a
// silent empty pane), matching the ui_map canvas contract.

#include <memory>
#include <optional>
#include <string>

#include <QPointF>
#include <QString>
#include <QWidget>

#include <pwb/ui_wellseis/qt/well_map_canvas.hpp>

class QLabel;
class QgsMapCanvas;
class QgsMapToolPan;
class QgsVectorLayer;

namespace pwb::qgis {
class MapSession;
}

namespace pwb::ui_wellseis::qgis {

class WellMapQgisSurface : public QWidget, public qt::IWellMapSurface {
    Q_OBJECT
public:
    explicit WellMapQgisSurface(QWidget* parent = nullptr);
    ~WellMapQgisSurface() override;

    QWidget* widget() override { return this; }
    void set_scene(const qt::WellMapScene& scene) override;
    void autofit() override;
    void reset_view() override;
    void set_view_bounds(double xmin, double xmax, double ymin,
                         double ymax) override;
    void focus_point(double x, double y, double zoom_factor) override;

    // Diagnostics for tests/host chrome.
    [[nodiscard]] QString backend_status() const;
    [[nodiscard]] bool qgis_active() const { return canvas_ != nullptr; }

    // Ordered teardown (canvas → session); idempotent. The destructor
    // calls it — explicit early shutdown is also safe.
    void shutdown();

protected:
    bool eventFilter(QObject* watched, QEvent* event) override;
    void closeEvent(QCloseEvent* event) override;

private:
    void rebuild_layers();
    [[nodiscard]] bool hit_test(const QPointF& pos, std::string* series,
                                int* index,
                                qt::WellMapPoint* point) const;
    [[nodiscard]] std::optional<qt::WellMapPoint> screen_to_map(
        const QPointF& pos) const;
    [[nodiscard]] std::optional<QPointF> map_to_screen(double x,
                                                       double y) const;

    std::unique_ptr<pwb::qgis::MapSession> session_;
    QgsMapCanvas* canvas_ = nullptr;  // tracked by session_ (QPointer)
    QgsMapToolPan* pan_tool_ = nullptr;
    QLabel* placeholder_ = nullptr;

    qt::WellMapScene scene_;
    double fit_extent_[4] = {0.0, 0.0, 0.0, 0.0};  // xmin ymin xmax ymax
    bool fit_extent_valid_ = false;
    bool pressed_ = false;
    QPointF press_pos_;
    bool shutdown_done_ = false;
};

}  // namespace pwb::ui_wellseis::qgis
