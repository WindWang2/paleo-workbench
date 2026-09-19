#pragma once

// UI-09 — the well-map drawing surface + injection seam.
//
// IWellMapSurface is the narrow contract ProjectWellMapPage needs — the
// geo-viz XY_SCATTER engine port (Python _create_plot). WellMapCanvas is
// the built-in fallback implementation (the UnifiedMapCanvas role); a
// QGIS DisplayMapCanvas adapter can implement the same interface later
// without touching the page.

#include <functional>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include <QWidget>

namespace pwb::ui_wellseis::qt {

using WellMapPoint = std::pair<double, double>;
using WellMapRing = std::vector<WellMapPoint>;

struct WellMapScene {
    // Scatter blocks (stable layout: OK block first, then flagged).
    std::vector<WellMapPoint> ok_points;
    std::vector<WellMapPoint> flagged_points;
    std::vector<WellMapPoint> selected_points;
    std::vector<std::string> ok_labels;
    std::vector<std::string> flagged_labels;
    bool show_labels = true;
    // Line overlays (project CRS).
    WellMapRing boundary;
    std::vector<WellMapRing> survey_rings;
    std::vector<WellMapRing> reference_rings;
    // Cross-view spatial cursor marker (scenario B).
    std::optional<WellMapPoint> spatial_cursor;
};

class IWellMapSurface {
public:
    virtual ~IWellMapSurface() = default;
    virtual QWidget* widget() = 0;
    virtual void set_scene(const WellMapScene& scene) = 0;
    virtual void autofit() = 0;
    virtual void reset_view() = 0;
    virtual void set_view_bounds(double xmin, double xmax, double ymin,
                                 double ymax) = 0;
    virtual void focus_point(double x, double y, double zoom_factor) = 0;

    // series_name: "wells" | "wells_flagged"; index is inside that series.
    std::function<void(const std::string& series, int index, double x,
                       double y)>
        on_point_hovered;
    std::function<void(const std::string& series, int index, double x,
                       double y)>
        on_point_clicked;
};

// Built-in QPainter surface — equal aspect, wheel zoom, drag pan,
// nearest-point hover/click within a pixel tolerance.
class WellMapCanvas : public QWidget, public IWellMapSurface {
    Q_OBJECT
public:
    explicit WellMapCanvas(QWidget* parent = nullptr);

    QWidget* widget() override { return this; }
    void set_scene(const WellMapScene& scene) override;
    void autofit() override;
    void reset_view() override;
    void set_view_bounds(double xmin, double xmax, double ymin,
                         double ymax) override;
    void focus_point(double x, double y, double zoom_factor) override;

protected:
    void paintEvent(QPaintEvent* event) override;
    void wheelEvent(QWheelEvent* event) override;
    void mousePressEvent(QMouseEvent* event) override;
    void mouseMoveEvent(QMouseEvent* event) override;
    void mouseReleaseEvent(QMouseEvent* event) override;
    void resizeEvent(QResizeEvent* event) override;

private:
    struct ViewTransform {
        double scale = 1.0;
        double cx = 0.0;  // world coords at widget center
        double cy = 0.0;
    };

    [[nodiscard]] WellMapPoint to_world(const QPointF& pos) const;
    [[nodiscard]] QPointF to_widget(const WellMapPoint& world) const;
    [[nodiscard]] ViewTransform fit_transform() const;
    // Nearest scatter hit within tolerance px; reports series + index.
    [[nodiscard]] bool hit_test(const QPointF& pos, std::string* series,
                                int* index, WellMapPoint* point) const;

    WellMapScene scene_;
    ViewTransform view_;
    bool view_initialized_ = false;
    bool panning_ = false;
    QPoint pan_anchor_;
};

}  // namespace pwb::ui_wellseis::qt
