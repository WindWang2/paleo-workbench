// 1:1 port of geoviz_plots/chart/cross_plot_widget.py (frozen behavior
// source @0885195): interactive 2D scatter cross-plot with polygon-lasso
// cluster selection (point-in-polygon + convex hull via the C++ kernels)
// and viridis z-coloring. Clouds above _SCATTER_ELLIPSE_LIMIT (4000) are
// stamped into a full-widget QImage with a 3×3 neighbourhood instead of
// per-point QPainter ellipses.
//
// Port notes (behavior-preserving):
//   * The Python widget declares mouse tracking but ships no hover
//     crosshair/bubble in its frozen paintEvent — only the lasso API, the
//     QColor(50,50,50) dashed grid inside _draw_axes, and the z colorbar
//     exist. This port matches that exactly.
//   * points_selected payload (indices, (xmin, xmax, ymin, ymax)) is
//     flattened to QVector<int> + four doubles.
#pragma once

#include <QColor>
#include <QPointF>
#include <QString>
#include <QVector>
#include <QWidget>

#include <array>
#include <cstddef>
#include <optional>
#include <utility>
#include <vector>

#include "pwb/viz_charts/convex_hull.hpp"

class QPainter;
class QPaintEvent;
class QRectF;

namespace pwb::viz_charts::qt {

class CrossPlotWidget : public QWidget {
    Q_OBJECT
public:
    explicit CrossPlotWidget(QWidget* parent = nullptr);

    // set_scatter_data(x, y, z=None, ...): z stays uncolored (flat
    // QColor(90,175,255)) when nullopt. A single non-finite sample must not
    // poison the view bounds (#553 parity): bounds come from the finite
    // mask only, and only when at least one finite pair exists.
    void set_scatter_data(std::vector<double> x, std::vector<double> y,
                          std::optional<std::vector<double>> z = std::nullopt,
                          QString x_label = QStringLiteral("X Axis"),
                          QString y_label = QStringLiteral("Y Axis"),
                          QString z_label = QStringLiteral("Z Axis"));

    // Select points inside the lasso polygon (data coordinates), stash the
    // cluster hull, and emit points_selected when anything was caught.
    void apply_lasso_polygon(const QVector<QPointF>& lasso_data_pts);

signals:
    void points_selected(const QVector<int>& indices, double xmin, double xmax,
                         double ymin, double ymax);

protected:
    void paintEvent(QPaintEvent* event) override;

private:
    // {"name", "hull", "indices", "color"} — Python cluster dict.
    struct Cluster {
        QString name;
        std::vector<Point2> hull;
        QVector<int> indices;
        QColor color{31, 102, 212, 50};
    };

    void draw_axes(QPainter* painter, const QRectF& plot_rect);
    void draw_z_colorbar(QPainter* painter, const QRectF& plot_rect,
                         double vmin, double vmax);
    // (vmin, vmax) over finite z samples; empty → (0, 1).
    std::pair<double, double> z_range(const std::vector<double>& z) const;
    std::vector<std::array<unsigned char, 4>> z_rgba_lut(
        const std::vector<double>& z, double vmin, double vmax) const;
    void blit_scatter_points(QPainter* painter,
                             const std::vector<double>& px,
                             const std::vector<double>& py, int width,
                             int height,
                             const std::vector<std::array<unsigned char, 4>>*
                                 rgba);

    std::vector<double> x_data_;  // empty ↔ Python None
    std::vector<double> y_data_;
    std::optional<std::vector<double>> z_data_;

    QString x_label_ = QStringLiteral("X Axis");
    QString y_label_ = QStringLiteral("Y Axis");
    QString z_label_ = QStringLiteral("Z Axis");

    int margin_left_ = 65;
    int margin_right_ = 75;
    int margin_top_ = 25;
    int margin_bottom_ = 50;

    // Viewport boundaries.
    double view_xmin_ = 0.0;
    double view_xmax_ = 1.0;
    double view_ymin_ = 0.0;
    double view_ymax_ = 1.0;

    // Lasso & clusters (Python state; current_lasso_pts_/lasso_active_ are
    // kept for parity, the frozen renderer never draws them).
    bool lasso_active_ = false;
    QVector<QPointF> current_lasso_pts_;
    std::vector<Cluster> clusters_;
};

}  // namespace pwb::viz_charts::qt
