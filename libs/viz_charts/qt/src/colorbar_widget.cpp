// 1:1 port of geoviz_plots/chart/colorbar.py (frozen behavior source
// @0885195) — see colorbar_widget.hpp.

#include "pwb/viz_charts/qt/colorbar_widget.hpp"

#include <QBrush>
#include <QFont>
#include <QLinearGradient>
#include <QPaintEvent>
#include <QPainter>
#include <QPen>
#include <QRectF>

#include <algorithm>
#include <cstdio>
#include <string>
#include <string_view>

#include "pwb/viz_charts/colormaps.hpp"

namespace pwb::viz_charts::qt {
namespace {

// Python `colormap_name if colormap_name in COLORMAPS else "viridis"`.
bool colormap_known(const QString& name) {
    const std::string_view raw = name.toStdString();
    return raw == "viridis" || raw == "cnpc_strat" ||
           raw == "cnpc_fluid" || raw == "thermal";
}

// Python f"{val:.1f}".
QString format_1f(double val) {
    char buf[48];
    std::snprintf(buf, sizeof(buf), "%.1f", val);
    return QString::fromStdString(buf);
}

}  // namespace

ColorbarWidget::ColorbarWidget(QWidget* parent) : QWidget(parent) {
    setFixedWidth(65);
}

void ColorbarWidget::set_continuous_range(double vmin, double vmax,
                                          const QString& colormap_name) {
    mode_ = QStringLiteral("continuous");
    vmin_ = vmin;
    vmax_ = vmax;
    colormap_name_ =
        colormap_known(colormap_name) ? colormap_name
                                      : QStringLiteral("viridis");
    update();
}

void ColorbarWidget::set_discrete_swatches(
    const QVector<QPair<QString, QColor>>& swatches) {
    mode_ = QStringLiteral("discrete");
    swatches_ = swatches;
    update();
}

void ColorbarWidget::paintEvent(QPaintEvent* event) {
    Q_UNUSED(event);
    QPainter painter(this);
    painter.setRenderHint(QPainter::Antialiasing);

    const int w = width();
    const int h = height();
    const double margin_top = 20.0;
    const double margin_bottom = 30.0;
    const double bar_w = 20.0;
    const double bar_x = 10.0;
    const double bar_h = std::max(10.0, h - margin_top - margin_bottom);

    if (mode_ == QLatin1String("continuous")) {
        // Draw gradient bar.
        const QRectF bar_rect(bar_x, margin_top, bar_w, bar_h);
        // Gradient runs from the bar bottom to the top (vmin → vmax).
        QLinearGradient grad(bar_x, margin_top + bar_h, bar_x, margin_top);

        const auto& stops =
            colormap(colormap_name_.toStdString());
        for (const auto& [pos, rgb] : stops) {
            grad.setColorAt(pos, QColor(rgb.r, rgb.g, rgb.b));
        }

        painter.setBrush(QBrush(grad));
        painter.setPen(QPen(QColor(88, 104, 120), 1));
        painter.drawRect(bar_rect);

        // Draw tick labels.
        painter.setPen(QColor(210, 210, 210));
        painter.setFont(QFont("SansSerif", 8));

        // np.linspace(vmin, vmax, 5): interior points via the exact step,
        // endpoint pinned to vmax.
        const double step = (vmax_ - vmin_) / 4.0;
        for (int i = 0; i < 5; ++i) {
            const double val = (i == 4) ? vmax_ : vmin_ + i * step;
            const double norm_y =
                (val - vmin_) / std::max(1e-6, vmax_ - vmin_);
            const double py = margin_top + bar_h * (1.0 - norm_y);
            // Python truncates the tick line endpoints with int().
            painter.drawLine(QLineF(static_cast<int>(bar_x + bar_w),
                                     static_cast<int>(py),
                                     static_cast<int>(bar_x + bar_w + 4.0),
                                     static_cast<int>(py)));
            painter.drawText(
                QRectF(bar_x + bar_w + 6.0, py - 8.0, 30.0, 16.0),
                Qt::AlignLeft | Qt::AlignVCenter, format_1f(val));
        }
    } else {
        // Draw discrete swatches.
        if (swatches_.isEmpty()) {
            return;
        }
        const int n = swatches_.size();
        const double row_h = std::min(24.0, bar_h / n);
        painter.setFont(QFont("SansSerif", 8));

        for (int i = 0; i < n; ++i) {
            const auto& [name, color] = swatches_.at(i);
            const double py = margin_top + i * row_h;
            const QRectF swatch_rect(bar_x, py + 2.0, 14.0, row_h - 4.0);
            painter.setBrush(QBrush(color));
            painter.setPen(QPen(QColor(88, 104, 120), 1));
            painter.drawRect(swatch_rect);

            painter.setPen(QColor(210, 210, 210));
            painter.drawText(
                QRectF(bar_x + 18.0, py, w - bar_x - 18.0, row_h),
                Qt::AlignLeft | Qt::AlignVCenter, name);
        }
    }
}

}  // namespace pwb::viz_charts::qt
