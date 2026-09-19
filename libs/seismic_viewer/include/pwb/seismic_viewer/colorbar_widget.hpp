#pragma once

// VIZ-D ColorbarWidget — vertical colour-bar legend for the seismic slice
// viewer, ported from geoviz colorbar_widget.py (@08851951): fixed 60 px
// width, one gradient stop per LUT entry from bottom (min) to top (max),
// gray min/mid/max labels formatted "%.1f" to the right of the bar.

#include <QWidget>

#include <pwb/seismic_viewer/color_maps.hpp>

namespace pwb::seismic_viewer {

class ColorbarWidget final : public QWidget {
public:
    explicit ColorbarWidget(QWidget* parent = nullptr);

    void set_colormap(std::string_view name); // unknown name: keeps the current
    void set_range(double min_value, double max_value);

    [[nodiscard]] std::string colormap() const { return name_; }
    [[nodiscard]] double min_value() const { return min_; }
    [[nodiscard]] double max_value() const { return max_; }

protected:
    void paintEvent(QPaintEvent* event) override;

private:
    std::string name_{"seismic"};
    ColorLut lut_;
    double min_{-1.0};
    double max_{1.0};
};

} // namespace pwb::seismic_viewer
