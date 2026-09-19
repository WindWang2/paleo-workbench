// Line/scatter series data + Largest-Triangle-Three-Buckets downsampling —
// port of geoviz_plots/chart/series.py (Qt-free half; the QColor field of
// the Python model lives in the Qt layer).
#pragma once

#include <cstddef>
#include <string>
#include <vector>

namespace pwb::viz_charts {

struct SeriesSample {
    double x = 0.0;
    double y = 0.0;
};

// (x, y) keep/drop semantics follow the Python NaN filter exactly: pairs
// where either side is non-finite are dropped BEFORE bucketing, and the
// returned arrays are the filtered originals when no downsampling fires.
struct DownsampleResult {
    std::vector<double> x;
    std::vector<double> y;
};

// LTTB downsample to `threshold` points. threshold >= n or <= 2 returns the
// filtered input verbatim (Python early-return).
DownsampleResult lttb_downsample(const std::vector<double>& x,
                                 const std::vector<double>& y, int threshold);

// (xmin, xmax, ymin, ymax) over finite pairs; empty/all-non-finite → zeros
// (Series.get_bounds).
struct Bounds {
    double xmin = 0.0;
    double xmax = 0.0;
    double ymin = 0.0;
    double ymax = 0.0;
};
Bounds series_bounds(const std::vector<double>& x, const std::vector<double>& y);

}  // namespace pwb::viz_charts
