// 1:1 port of geoviz_plots/chart/colorbar.py (frozen behavior source
// @0885195): vertical colorbar with a continuous colormap gradient mode and
// a discrete lithology-swatch legend mode. Fixed width 65px; gradient stops
// come from the C++ colormap tables (pwb/viz_charts/colormaps.hpp), which
// carry the same fractions/colors as the Python COLORMAPS dict.
#pragma once

#include <QColor>
#include <QPair>
#include <QString>
#include <QVector>
#include <QWidget>

class QPaintEvent;

namespace pwb::viz_charts::qt {

class ColorbarWidget : public QWidget {
    Q_OBJECT
public:
    explicit ColorbarWidget(QWidget* parent = nullptr);

    // Continuous mode: unknown colormap names fall back to viridis
    // (Python `colormap_name if colormap_name in COLORMAPS else "viridis"`).
    void set_continuous_range(double vmin, double vmax,
                              const QString& colormap_name =
                                  QStringLiteral("viridis"));

    // Discrete mode: (name, color) legend rows.
    void set_discrete_swatches(const QVector<QPair<QString, QColor>>& swatches);

protected:
    void paintEvent(QPaintEvent* event) override;

private:
    QString mode_ = QStringLiteral("continuous");  // "continuous" | "discrete"
    double vmin_ = 0.0;
    double vmax_ = 1.0;
    QString colormap_name_ = QStringLiteral("viridis");
    QVector<QPair<QString, QColor>> swatches_;
};

}  // namespace pwb::viz_charts::qt
