// Shared colormap tables and sampling — port of
// geoviz_plots/surface/colormaps.py. Colors are carried as (r, g, b) bytes
// (0-255); the Qt layer converts to QColor without recomputation.
#pragma once

#include <array>
#include <string_view>
#include <vector>

namespace pwb::viz_charts {

struct Rgb {
    int r = 0;
    int g = 0;
    int b = 0;
};

struct ColorStop {
    double fraction;
    Rgb color;
};

// viridis / cnpc_strat / cnpc_fluid / thermal control points (fractions
// monotonic in [0, 1]); unknown names resolve to viridis.
const std::vector<ColorStop>& colormap(std::string_view name);

// Linear interpolation between adjacent control points after clamping val
// into [vmin, vmax]. vmin == vmax → first stop's color. Channel rounding is
// int() truncation of c1 + w*(c2-c1), exactly like the Python QColor ctor.
Rgb sample_colormap(std::string_view name, double val, double vmin, double vmax);

}  // namespace pwb::viz_charts
