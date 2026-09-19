// Line/scatter series models, Qt half — 1:1 port of the QColor-bearing
// fields of geoviz_plots/chart/series.py (frozen behavior source @0885195).
// The Qt-free kernel half (LTTB downsampling, finite bounds) already lives
// in pwb/viz_charts/series.hpp and is reused, not reimplemented.
//
// Python mapping:
//   Series.x / Series.y          → SeriesData::x / SeriesData::y
//   Series.name / visible        → SeriesData::name / visible
//   Series.color (None → blue)   → SeriesData::color (invalid QColor → blue)
//   LineSeries.width/style/marker_size/marker_style
//   ScatterSeries.size/marker_style/labels
// marker_style keeps the Python string set ("none"/"circle"/"square"/
// "triangle"/"cross"); unrecognized strings draw nothing, exactly like the
// Python elif chain.
#pragma once

#include <QColor>
#include <QPen>
#include <QString>

#include <utility>
#include <vector>

namespace pwb::viz_charts::qt {

// Python Series base: plain data + a default "sleek blue" color.
struct SeriesData {
    QString name;
    QColor color{64, 156, 255};
    bool visible = true;
    std::vector<double> x;
    std::vector<double> y;

    SeriesData() = default;
    // color == invalid QColor mirrors color=None → QColor(64, 156, 255).
    SeriesData(std::vector<double> x_, std::vector<double> y_, QString name_,
               const QColor& color_)
        : name(std::move(name_)),
          color(color_.isValid() ? color_ : QColor(64, 156, 255)),
          x(std::move(x_)),
          y(std::move(y_)) {}

    virtual ~SeriesData() = default;

    SeriesData(const SeriesData&) = default;
    SeriesData& operator=(const SeriesData&) = default;
    SeriesData(SeriesData&&) = default;
    SeriesData& operator=(SeriesData&&) = default;
};

// Python LineSeries(x, y, name, color, width=1.5, style=SolidLine,
//                   marker_size=0.0, marker_style="none").
struct LineSeriesData : SeriesData {
    double width = 1.5;
    Qt::PenStyle style = Qt::SolidLine;
    double marker_size = 0.0;
    QString marker_style = QStringLiteral("none");

    LineSeriesData() = default;
    explicit LineSeriesData(std::vector<double> x_, std::vector<double> y_,
                            QString name_ = QString(),
                            QColor color_ = QColor(), double width_ = 1.5,
                            Qt::PenStyle style_ = Qt::SolidLine,
                            double marker_size_ = 0.0,
                            QString marker_style_ = QStringLiteral("none"))
        : SeriesData(std::move(x_), std::move(y_), std::move(name_), color_),
          width(width_),
          style(style_),
          marker_size(marker_size_),
          marker_style(std::move(marker_style_)) {}
};

// Python ScatterSeries(x, y, name, color, size=6.0, marker_style="circle",
//                      visible, labels=None). Per-point labels are rendered
// only while the series is not downsampled (plot_widget parity).
struct ScatterSeriesData : SeriesData {
    double size = 6.0;
    QString marker_style = QStringLiteral("circle");
    std::vector<QString> labels;

    ScatterSeriesData() = default;
    explicit ScatterSeriesData(std::vector<double> x_, std::vector<double> y_,
                               QString name_ = QString(),
                               QColor color_ = QColor(), double size_ = 6.0,
                               QString marker_style_ = QStringLiteral("circle"))
        : SeriesData(std::move(x_), std::move(y_), std::move(name_), color_),
          size(size_),
          marker_style(std::move(marker_style_)) {}
};

}  // namespace pwb::viz_charts::qt
