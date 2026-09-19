// Qt-free scalar/factor layer styling spec + classification (CONV-27).
//
// Port of paleo_workbench/mapping/scalar_style.py (host half): the
// declarative ScalarStyleSpec and the deterministic classification kernels.
// numpy semantics are reproduced bit-exactly (see numpy_math.hpp):
//   * equal_interval = np.linspace (i*step + start, forced endpoint);
//   * quantile = np.quantile 'linear' incl. the two-branch _lerp;
//   * natural_breaks = Fisher-Jenks DP over numpy pairwise sums, with the
//     deterministic default_rng(0).choice(..., replace=False) sample draw
//     for inputs larger than the sample cap;
//   * labels use Python f"{v:.{d}f}" formatting (NaN -> "nan").
// The renderer XML itself stays authored by QGIS through the vendored
// qgis_render_bridge (build_scalar_renderer_xml) — this module produces the
// exact payload dict that C++ entry point consumes (see qgis_adapter.hpp).
#pragma once

#include <pwb/cartography/color_ramps.hpp>
#include <pwb/domain/json.hpp>

#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace pwb::cartography {

using Json = pwb::domain::Json;

struct ScalarStyleSpec {
    std::string ramp_name = "viridis";
    std::string mode = "continuous";            // continuous | classified
    std::string classification = "equal_interval";  // equal_interval |
                                                    // quantile |
                                                    // natural_breaks |
                                                    // explicit
    long long n_classes = 5;                    // [2, 256]
    std::optional<std::vector<double>> explicit_breaks;
    std::optional<std::pair<double, double>> manual_range;
    bool reverse = false;
    double opacity = 1.0;
    bool nodata_transparent = true;
    std::string unit_label;
    std::string colorbar_title;
    int colorbar_decimals = 2;

    // Python __post_init__: throws std::invalid_argument with the exact
    // Python ValueError messages on any violation.
    void validate() const;

    Json to_dict() const;
    // Python from_dict: missing keys take the defaults; explicit/manual
    // keys only materialize when truthy.
    static ScalarStyleSpec from_dict(const Json& data);
};

// Python f"{v:.{decimals}f}"; NaN -> "nan", +/-inf -> "+/-inf".
std::string format_fixed(double value, int decimals);

// The (breaks, labels) pair produced by every classification entry point.
struct ClassifiedBreaks {
    std::vector<double> breaks;
    std::vector<std::string> labels;
};

ClassifiedBreaks equal_interval_breaks(double vmin, double vmax, long long n,
                                       int decimals);
// numpy quantile over the finite values (order preserved); throws
// std::invalid_argument("quantile classification needs at least one finite
// value") when nothing finite remains.
ClassifiedBreaks quantile_breaks(const std::vector<double>& values,
                                 long long n, int decimals);
// Fisher-Jenks with the seeded deterministic sample draw (numpy stream
// contract, see numpy_math.hpp).
ClassifiedBreaks natural_breaks(const std::vector<double>& values,
                                long long n, long long sample,
                                long long seed, int decimals);
// Jenks over an explicitly provided sample (already the finite values; the
// function sorts internally). Exposed for reproducibility seams.
ClassifiedBreaks natural_breaks_from_values(const std::vector<double>& finite,
                                            long long n, int decimals);

// Dispatch per spec; manual_range overrides the span for equal_interval.
ClassifiedBreaks classify_breaks(const ScalarStyleSpec& spec,
                                 const std::vector<double>& values,
                                 double vmin, double vmax,
                                 std::optional<long long> n = std::nullopt);

// Shader items {"value", "color", "label"}: continuous -> 17 stops across
// the span; classified -> one item per break (step ramp, colors flipped
// end-for-end under reverse). Throws std::invalid_argument on degenerate
// spans / missing breaks with the Python messages.
std::vector<Json> ramp_items_for_spec(const ScalarStyleSpec& spec,
                                      const ColorRamp& ramp, double vmin,
                                      double vmax, const std::string& mode,
                                      const std::vector<double>& breaks = {});

// Finite-only copy of the values (numpy isfinite filter, order preserved).
std::vector<double> finite_values(const std::vector<double>& values);

}  // namespace pwb::cartography
