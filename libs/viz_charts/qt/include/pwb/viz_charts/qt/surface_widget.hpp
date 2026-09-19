// 1:1 port of geoviz_plots/surface/surface_widget.py (frozen behavior
// source @0885195): QPainter vector filled-contour + isoline spatial map
// on the light slate workbench palette, with mid-line rotated labels cut
// out of long isolines, a hover crosshair bubble, contour-extraction
// caching (Issue #59), and SVG/PDF exports.
//
// Port notes (all mirror the frozen Python exactly):
//   * Control points / fault polylines / selected_contour_level /
//     selected_cp_idx / is_dragging_cp are stored (and announced via
//     signals) but never rendered — the frozen render_surface does not
//     draw them either.
//   * grid_updated is declared but never emitted (Python parity).
//   * autofit fits the exact grid min/max with no padding.
//   * The extraction cache replicates the Python dict: entries keyed by
//     grid identity + levels + colormap, whole cache cleared once it
//     holds 4 entries before inserting a new one.
//   * Task-mandated guard beyond Python: set_grid_data with < 2 rows or
//     < 2 columns (or a z size that does not match rows×cols) clears the
//     state instead of binding an unrenderable grid.
#pragma once

#include <QColor>
#include <QPointF>
#include <QPolygonF>
#include <QString>
#include <QVector>
#include <QWidget>

#include <cstddef>
#include <optional>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

#include "pwb/viz_charts/marching_squares.hpp"

class QEvent;
class QMouseEvent;
class QPaintEvent;
class QPainter;
class QResizeEvent;
class QWheelEvent;

namespace pwb::viz_charts::qt {

// Python control point dict {"id": str, "x": float, "y": float, "z": float}.
struct ControlPoint {
    QString id;
    double x = 0.0;
    double y = 0.0;
    double z = 0.0;
};

class SurfaceWidget : public QWidget {
    Q_OBJECT
public:
    explicit SurfaceWidget(QWidget* parent = nullptr);

    void set_control_points(const QVector<ControlPoint>& points);
    // point_id empty ↔ Python None → auto "cp_{count+1}". Emits
    // control_points_changed with the full list.
    void add_control_point(double x, double y, double z,
                           const QString& point_id = QString());
    void set_fault_polylines(const QVector<QPolygonF>& polylines);
    void select_contour_level(double level);

    // grid_z is row-major with shape (len(grid_y), len(grid_x)); levels are
    // sorted ascending on bind; unknown colormaps fall back to viridis.
    void set_grid_data(std::vector<double> grid_x, std::vector<double> grid_y,
                       std::vector<double> grid_z, std::vector<double> levels,
                       const QString& colormap = QStringLiteral("viridis"));

    void clear();
    void autofit();

    QColor get_color(double val) const;

    std::tuple<double, double, double, double> get_plot_rect(int width,
                                                             int height) const;
    std::pair<double, double> data_to_pixel(double x, double y) const;
    std::pair<double, double> pixel_to_data(double px, double py) const;
    void pan(double dpx, double dpy);
    void zoom(double factor, double cx, double cy);

    void export_svg(const QString& filepath);
    void export_pdf(const QString& filepath);
    void render_surface(QPainter* painter, int width, int height);

signals:
    void view_changed(double xmin, double xmax, double ymin, double ymax);
    void contour_selected(double level);
    void control_points_changed(const QVector<ControlPoint>& points);
    void grid_updated(const std::vector<double>& grid_x,
                      const std::vector<double>& grid_y,
                      const std::vector<double>& grid_z);

protected:
    void paintEvent(QPaintEvent* event) override;
    void mousePressEvent(QMouseEvent* event) override;
    void mouseMoveEvent(QMouseEvent* event) override;
    void mouseReleaseEvent(QMouseEvent* event) override;
    void wheelEvent(QWheelEvent* event) override;
    void mouseDoubleClickEvent(QMouseEvent* event) override;

private:
    // Issue #59 extraction cache.
    struct ExtractionResult {
        std::optional<std::vector<BandedFill>> bands;
        std::optional<std::vector<std::pair<double, std::vector<Polyline>>>>
            lines;
    };
    // Python key: array identity + shape + content checksum + levels +
    // colormap. Grids are stored by value (identity = data pointers) and
    // the cache is cleared on every set_grid_data, so pointer/size/levels/
    // colormap equality is the exact invalidation surface.
    struct CacheKey {
        const double* gx = nullptr;
        const double* gy = nullptr;
        const double* gz = nullptr;
        std::size_t nx = 0;
        std::size_t ny = 0;
        std::size_t nz = 0;
        std::vector<double> levels;
        std::string colormap;

        bool operator==(const CacheKey& other) const = default;
    };

    // Lazy contour extraction (Python _ensure contours inside
    // render_surface): returns the cached result, extracting on miss.
    const ExtractionResult& ensure_contours(const CacheKey& key);

    std::vector<double> grid_x_;  // empty ↔ Python None
    std::vector<double> grid_y_;
    std::vector<double> grid_z_;
    std::vector<double> levels_;
    QString colormap_name_ = QStringLiteral("viridis");

    // Control points & fault barriers.
    QVector<ControlPoint> control_points_;
    QVector<QPolygonF> fault_polylines_;
    std::optional<std::size_t> selected_cp_idx_;
    std::optional<double> selected_contour_level_;
    bool is_dragging_cp_ = false;

    // Viewport boundaries.
    double view_xmin_ = 0.0;
    double view_xmax_ = 1.0;
    double view_ymin_ = 0.0;
    double view_ymax_ = 1.0;

    // Light slate workbench palette (Python defaults).
    QColor bg_color_{QColor(QStringLiteral("#f1f5f9"))};
    QColor plot_bg_color_{QColor(QStringLiteral("#ffffff"))};
    QColor grid_color_{203, 213, 225, 200};  // Python theme member (unused
                                             // by the frozen renderer)
    QColor axis_color_{QColor(QStringLiteral("#475569"))};
    QColor text_color_{QColor(QStringLiteral("#0f172a"))};
    QColor contour_line_color_{51, 65, 85, 180};

    // Margins.
    int margin_left_ = 65;
    int margin_right_ = 25;
    int margin_top_ = 25;
    int margin_bottom_ = 50;

    // Interaction states.
    std::optional<QPointF> last_mouse_pos_;
    std::optional<QPointF> hover_pos_;

    // (key, result) pairs; Python dict insert order preserved, cleared
    // wholesale at 4 entries.
    std::vector<std::pair<CacheKey, ExtractionResult>> contour_cache_;
};

}  // namespace pwb::viz_charts::qt
