#pragma once

// VIZ-D crossplot core — Qt-free data preparation for the two geoviz
// seismic crossplots (geo-viz-engine@08851951):
//
//   * analyze_lithology_crossplot (geoviz_seismic/crossplot.py): GR vs
//     acoustic-impedance samples grouped by lithology label with per-cluster
//     population mean/std ("Unknown" fallback for short label lists);
//   * attribute crossplot (geoviz_seismic/dialogs/crossplot.py):
//     instantaneous frequency (x) vs envelope (y) of a 2-D slice, computed
//     by REUSING the frozen single-trace attribute kernels from
//     libs/seismic_attributes (seismic.envelope /
//     seismic.instantaneous_frequency) through the pwb::science SDK — never
//     reimplemented here — then subsampled with step = max(1, size // 5000)
//     exactly like the Python worker, plus the CrossplotCanvas P1/P99 axis
//     limits with the hi = lo + 1 degenerate guard.

#include <cstdint>
#include <span>
#include <string>
#include <vector>

namespace pwb::seismic_viewer::crossplot {

// --- lithology crossplot (headless stats) -----------------------------------

struct LithologyPoint {
    double gr{0.0};
    double ai{0.0};
    std::string lithology;
};

struct LithologyCluster {
    std::int64_t count{0};
    double mean_gr{0.0};
    double mean_ai{0.0};
    double std_gr{0.0}; // population std (numpy std, ddof = 0)
    double std_ai{0.0};
};

struct LithologyCrossplot {
    std::vector<LithologyPoint> points;
    std::vector<std::pair<std::string, LithologyCluster>> clusters; // insertion order
};

// Parity of analyze_lithology_crossplot: shorter label lists fall back to
// "Unknown"; clusters appear in first-seen order; NaN inputs propagate into
// the means (numpy semantics), they are not dropped.
[[nodiscard]] LithologyCrossplot
analyze_lithology_crossplot(std::span<const double> gr, std::span<const double> ai,
                            const std::vector<std::string>& lithology);

// --- attribute crossplot (frequency vs envelope) -----------------------------

struct AxisLimits {
    double lo{0.0};
    double hi{1.0};
};

struct AttributeCrossplotData {
    std::vector<float> frequency_hz; // x, subsampled
    std::vector<float> envelope;     // y, subsampled (aligned with x)
    AxisLimits x_limits;             // P1/P99 over frequency_hz
    AxisLimits y_limits;             // P1/P99 over envelope
    std::string diagnostic;          // non-empty on kernel failure
    bool ok{false};
};

// `plane` is the (n_samples, n_traces) slice in canonical row-major order;
// `sample_interval_s` is the sample interval in SECONDS (the kernel
// contract). The plane is wrapped as a (n_traces, 1, n_samples) volume for
// the kernels; results are re-flattened to the numpy (sample-major) order
// before the stride-subsample so the selected sample set matches the Python
// worker bit-for-bit.
[[nodiscard]] AttributeCrossplotData
prepare_attribute_crossplot(std::span<const float> plane, std::int64_t n_samples,
                            std::int64_t n_traces, double sample_interval_s);

// nanpercentile(1) / nanpercentile(99) limits with the CrossplotCanvas
// degenerate guard (hi = lo + 1 when collapsed/empty).
[[nodiscard]] AxisLimits percentile_axis_limits(std::span<const float> values);

} // namespace pwb::seismic_viewer::crossplot
