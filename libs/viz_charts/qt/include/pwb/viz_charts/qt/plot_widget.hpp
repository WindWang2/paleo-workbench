// 1:1 port of geoviz_plots/chart/plot_widget.py (frozen behavior source
// @0885195): premium dark-theme QPainter 2D line/scatter widget with
// Heckbert ticks, pan/zoom/at-cursor wheel zoom, autofit with 5% padding,
// equal-aspect locking, hover snapping + crosshair, caller-owned selected /
// highlighted points, LTTB downsampling above `downsample_threshold`, and
// SVG/PDF vector exports.
//
// Deviations from the Python (documented, all behavior-preserving):
//   * scipy cKDTree snap index is NOT ported — nearest-point lookup always
//     uses the linear pixel-space scan, which is exactly the Python
//     no-scipy numpy fallback branch (same first-wins strict-< semantics).
//   * The deprecated `point_selected` signal exists in Python but is never
//     emitted there; it is not declared in this port.
#pragma once

#include <QColor>
#include <QPointF>
#include <QString>
#include <QWidget>

#include <array>
#include <chrono>
#include <cstddef>
#include <functional>
#include <map>
#include <memory>
#include <optional>
#include <set>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

#include "pwb/viz_charts/qt/series.hpp"

class QPainter;
class QMouseEvent;
class QPaintEvent;
class QResizeEvent;
class QWheelEvent;
class QEvent;

namespace pwb::viz_charts::qt {

class PlotWidget : public QWidget {
    Q_OBJECT
public:
    explicit PlotWidget(QWidget* parent = nullptr);

    // -- series management -------------------------------------------------
    // add_series(series): takes ownership of the Python-passed series object.
    void add_series(std::unique_ptr<SeriesData> series);
    void clear();

    // -- viewport ----------------------------------------------------------
    void autofit();
    void set_equal_aspect(bool enabled);
    void focus_point(double x, double y, double zoom_factor = 4.0);
    void reset_view();
    // Python view_bounds() tuple (xmin, xmax, ymin, ymax).
    std::tuple<double, double, double, double> view_bounds() const;
    // Python set_view_bounds: non-finite or non-increasing ranges throw
    // std::invalid_argument (Python ValueError).
    void set_view_bounds(double xmin, double xmax, double ymin, double ymax);

    void set_axis_labels(const QString& x_label, const QString& y_label);
    std::pair<QString, QString> axis_labels() const;

    // (left, right, top, bottom) of the plot canvas for a widget size.
    std::tuple<double, double, double, double> get_plot_rect(int width,
                                                             int height) const;
    std::pair<double, double> data_to_pixel(double x, double y) const;
    std::pair<double, double> pixel_to_data(double px, double py) const;
    void pan(double dpx, double dpy);
    void zoom(double factor, double cx, double cy);

    // -- inter-page data linking --------------------------------------------
    // Unknown series → std::invalid_argument; index out of range →
    // std::out_of_range (Python ValueError / IndexError).
    void set_selected_point(const QString& series_name, int index,
                            const QString& label = QString());
    void clear_selected_point();
    void highlight_point(const QString& series_name, int index);
    void clear_highlights();

    // -- export / direct painting -------------------------------------------
    void export_svg(const QString& filepath);
    void export_pdf(const QString& filepath);
    // Explicit-canvas variants for hosts whose widget never became
    // visible (hidden stack pages / headless export): render at `canvas`
    // instead of the live widget size.
    void export_svg(const QString& filepath, QSize canvas);
    void export_pdf(const QString& filepath, QSize canvas);
    void render_plot(QPainter* painter, int width, int height);

    // -- hover snapping -------------------------------------------------------
    // Python check_nearest_point: nearest visible finite point within the
    // 15px activation radius (pixel space); emits point_hovered /
    // point_hover_cleared only when the hovered point changes.
    struct PointHit {
        QString series_name;
        int index = -1;
        double x = 0.0;
        double y = 0.0;
    };
    std::optional<PointHit> check_nearest_point(const QPointF& mouse_pos);

    // Python public attribute: LTTB guard for huge series.
    int downsample_threshold = 2000;

signals:
    void point_hovered(const QString& series_name, int index, double x,
                       double y);
    void point_hover_cleared();
    void point_clicked(const QString& series_name, int index, double x,
                       double y);
    void reset_requested();
    void view_changed(double xmin, double xmax, double ymin, double ymax);

protected:
    void paintEvent(QPaintEvent* event) override;
    void resizeEvent(QResizeEvent* event) override;
    void leaveEvent(QEvent* event) override;
    void mousePressEvent(QMouseEvent* event) override;
    void mouseMoveEvent(QMouseEvent* event) override;
    void mouseReleaseEvent(QMouseEvent* event) override;
    void wheelEvent(QWheelEvent* event) override;
    void mouseDoubleClickEvent(QMouseEvent* event) override;

private:
    using View = std::array<double, 4>;  // (xmin, xmax, ymin, ymax)
    using PointRef = std::pair<QString, int>;

    View current_view() const;
    View view_for_current_aspect(const View& bounds) const;
    View equalized_bounds(const View& bounds) const;
    void apply_view(const View& bounds);

    void clear_hovered_point();
    void invalidate_hover();
    void clear_last_click();
    bool double_click_started_on_point(const QPointF& position) const;

    std::optional<std::pair<double, double>> resolve_point(
        const std::optional<PointRef>& reference) const;
    void draw_point_indicator(QPainter* painter,
                              const std::function<QPointF(double, double)>& to_pixel,
                              const std::optional<PointRef>& reference,
                              const QPen& pen, const QBrush& brush,
                              const std::vector<double>& radii,
                              const QString& label);
    void draw_markers(QPainter* painter, const std::vector<double>& sx,
                      const std::vector<double>& sy, const QString& style,
                      double size, const QColor& color,
                      const std::function<QPointF(double, double)>& to_pixel);
    void draw_labels(QPainter* painter, const std::vector<double>& sx,
                     const std::vector<double>& sy,
                     const std::vector<QString>& labels, double size,
                     const std::function<QPointF(double, double)>& to_pixel);

    std::vector<std::unique_ptr<SeriesData>> series_list_;

    // Viewport boundaries in data coordinates.
    double view_xmin_ = 0.0;
    double view_xmax_ = 1.0;
    double view_ymin_ = 0.0;
    double view_ymax_ = 1.0;
    bool equal_aspect_ = false;
    std::optional<View> autofit_bounds_;
    std::optional<View> full_view_bounds_;

    // Premium Elegant Dark Theme (Python defaults).
    QColor bg_color_{25, 25, 25};
    QColor plot_bg_color_{15, 15, 15};
    QColor grid_color_{45, 45, 45, 200};
    QColor axis_color_{200, 200, 200};
    QColor text_color_{210, 210, 210};
    QColor crosshair_color_{255, 165, 0, 120};
    QColor highlight_color_{255, 69, 0};

    // Margins around the plotting canvas (left/right/top/bottom).
    int margin_left_ = 65;
    int margin_right_ = 25;
    int margin_top_ = 25;
    int margin_bottom_ = 50;
    QString x_axis_label_;
    QString y_axis_label_;

    // Interaction states.
    std::optional<QPointF> last_mouse_pos_;
    std::optional<QPointF> press_pos_;
    bool dragged_since_press_ = false;
    std::optional<QPointF> last_click_pos_;
    std::optional<PointHit> last_click_hit_;
    // Python time.monotonic(); only consulted while last_click_hit_ is set.
    std::chrono::steady_clock::time_point last_click_time_{};
    std::optional<QPointF> hover_pos_;
    std::optional<PointRef> hovered_point_;
    std::optional<PointRef> selected_point_;
    QString selected_label_;
    std::map<QString, std::set<int>> highlighted_points_;
};

}  // namespace pwb::viz_charts::qt
