// Well curve processing kernels (L3 toolbox) — Qt-free, QGIS-free port of
// paleo_workbench/workflow/curve_operations.py plus the three pure numeric
// kernels of curve_interpretation.py (depth_shift / despike / baseline_shift).
//
// Every kernel is NaN-aware: missing samples ride along as NaN and never
// silently become zeros. Units go through an explicit whitelist; unknown
// pairs raise instead of guessing. Error message texts are frozen against
// the Python modules.
#pragma once

#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace pwb::well_science {

// ---------------------------------------------------------------------------
// Smoothing / filtering
// ---------------------------------------------------------------------------

// Centered moving average over `window` samples (NaN-aware). Window counts
// samples, not metres. A NaN position STAYS NaN; the window averages only its
// finite samples; a window wider than the curve averages the whole curve.
// Convolution offsets replicate numpy 'same' mode (even windows trail by one).
std::vector<double> moving_average(const std::vector<double>& values, int window = 5);

// Rolling median over `window` samples (odd, NaN positions preserved). The
// boundary extension replicates scipy median_filter mode="reflect"
// (= symmetric mirror about the edge samples). Non-finite positions are
// filled with the global finite median for their neighbours' windows and
// restored to NaN in the output.
std::vector<double> median_filter_curve(const std::vector<double>& values, int window = 5);

// ---------------------------------------------------------------------------
// Normalization / outlier handling
// ---------------------------------------------------------------------------

// Normalize finite samples to z-scores ("zscore", std ddof=0; constant curve
// → zeros) or the [0,1] range ("minmax"; constant curve → 0.5). Unknown
// method raises CurveOpError with the frozen text.
std::vector<double> normalize_curve(const std::vector<double>& values,
                                    const std::string& method = "zscore");

// Clip finite samples to explicit bounds or a symmetric percentile band
// (np.percentile linear interpolation). NaN survives untouched. Raises on
// percentile outside (0,50) and when no clipping was requested. An all-NaN
// input returns unchanged BEFORE any validation (Python parity).
std::vector<double> clip_outliers(const std::vector<double>& values,
                                  std::optional<double> lower = std::nullopt,
                                  std::optional<double> upper = std::nullopt,
                                  std::optional<double> percentile = std::nullopt);

// ---------------------------------------------------------------------------
// Unit conversion (explicit whitelist — never a guessed factor)
// ---------------------------------------------------------------------------

// Canonical unit key for a LAS header unit string (nullopt if unmatched).
std::optional<std::string> normalize_unit_name(std::optional<std::string> unit);

// Exact factor for a whitelisted (from, to) pair; identity → 1.0; raises
// CurveOpError with the frozen text otherwise.
double conversion_factor(std::optional<std::string> from_unit,
                         std::optional<std::string> to_unit);

// Convert curve values between whitelisted units (NaN preserved).
std::vector<double> convert_values(const std::vector<double>& values,
                                   std::optional<std::string> from_unit,
                                   std::optional<std::string> to_unit);

// ---------------------------------------------------------------------------
// Resampling
// ---------------------------------------------------------------------------

// New regular depth axis spanning the input range at `step`. Positive step
// required; non-descending axis required; a partial trailing interval is
// dropped, not rounded up. Fewer than 2 input samples pass through unchanged.
std::vector<double> resample_axis(const std::vector<double>& depth, double step);

// Linear interpolation that keeps NaN holes bridged (DEPRECATED display-only
// semantics, kept for parity): NaN samples are dropped from the interpolant,
// so an interior gap is silently bridged. Scientific paths must use
// interp_gap_preserving. Outside the finite samples' hull → NaN; duplicate
// depths keep the first sample (stable).
std::vector<double> interp_nan_aware(const std::vector<double>& new_x,
                                     const std::vector<double>& x,
                                     const std::vector<double>& y);

// Linear interpolation that never bridges an interior gap (V6 §4): output is
// NaN inside an interior NaN span and outside each contiguous finite run;
// interpolation happens only within runs. Duplicate depths within a run keep
// the first sample. A non-descending finite-x axis is required.
std::vector<double> interp_gap_preserving(const std::vector<double>& new_x,
                                          const std::vector<double>& x,
                                          const std::vector<double>& y);

// ---------------------------------------------------------------------------
// Missing-interval diagnostics (read-only)
// ---------------------------------------------------------------------------

struct MissingIntervalReport {
    // Gaps strictly INSIDE the surveyed range (edges are not gaps), as
    // (first_missing_depth, last_missing_depth) pairs in axis order.
    std::vector<std::pair<double, double>> intervals;
    long total_samples = 0;    // size of the values axis (NaNs included)
    long missing_samples = 0;  // count of non-finite VALUES

    double missing_fraction() const {
        return total_samples != 0
                   ? static_cast<double>(missing_samples) / static_cast<double>(total_samples)
                   : 0.0;
    }
    // Python parity: max() over the spans folds left-to-right and is
    // order-dependent around NaN (max([nan]) is nan; max([nan, 1]) stays nan;
    // max([1, nan]) is 1). Empty → 0.0.
    double largest_gap() const {
        if (intervals.empty()) return 0.0;
        double best = intervals.front().second - intervals.front().first;
        for (std::size_t i = 1; i < intervals.size(); ++i) {
            const double span = intervals[i].second - intervals[i].first;
            if (span > best) best = span;
        }
        return best;
    }
};

MissingIntervalReport missing_interval_report(const std::vector<double>& depth,
                                              const std::vector<double>& values);

// ---------------------------------------------------------------------------
// curve_interpretation.py pure kernels
// ---------------------------------------------------------------------------

// Shift the measured-depth axis by delta_m metres (positive = deeper). The
// delta is defined in METRES; a foot axis converts it first. Unknown axis
// unit (nullopt or unclassifiable) raises UnknownDepthUnitError.
std::vector<double> depth_shift(const std::vector<double>& depths, double delta_m,
                                std::optional<std::string> axis_unit = std::string("m"));

// Replace samples deviating > threshold_sigma from a rolling median with the
// baseline (interpretation correction, not smoothing): MAD-based residual
// scale floored at 1% of the curve's own range. NaN positions stay NaN.
std::vector<double> despike(const std::vector<double>& values,
                            double threshold_sigma = 3.0, int window = 3);

// Add a constant environmental correction to the curve values.
std::vector<double> baseline_shift(const std::vector<double>& values, double delta);

// ---------------------------------------------------------------------------
// Operation registry metadata (curve_interpretation CURVE_OPERATIONS table)
// ---------------------------------------------------------------------------

struct CurveOperationInfo {
    std::string_view name;
    std::vector<std::string_view> required_params;
    std::string_view scope;  // depth_axis | curve | file | derive
};

// The 11 registered interpretation operations, in Python dict insertion order.
const std::vector<CurveOperationInfo>& curve_operations();

}  // namespace pwb::well_science
