// Coordinate axes ticks and nice number calculations — 1:1 port of
// geoviz_plots/chart/axes.py (frozen behavior source @0885195).
#pragma once

#include <string>
#include <utility>
#include <vector>

namespace pwb::viz_charts {

// Heckbert nice number: round_flag=true rounds to the nearest of
// {1, 2, 5, 10}×10^k; false ceils to the next. value 0 → 0.
double nice_number(double value, bool round_flag);

// (ticks, step) for [vmin, vmax] with at most max_ticks labels. Degenerate
// inputs follow the Python branches: max_ticks<=1 → [vmin]/1.0;
// non-finite → []/1.0; vmin==vmax==0 → [0]/1.0; vmin==vmax → [vmin]/step.
std::pair<std::vector<double>, double> calculate_ticks(double vmin, double vmax,
                                                       int max_ticks);

// Label formatting: decimals = min(12, max(0, -floor(log10(step))));
// non-finite value → Python str() spelling ("nan"/"inf"/"-inf").
std::string format_tick(double value, double step);

}  // namespace pwb::viz_charts
