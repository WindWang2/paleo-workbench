// VIZ-A — robust display-range scaling for well-log tracks. Port of
// geoviz_well_log/robust_scale.py::compute_robust_display_range
// (geo-viz-engine 08851951, behavior-frozen): P2–P98 general bounds with
// preset overrides for GR/density/neutron families, inverted-preset
// fallback (#113), finite-only masking (legal negatives kept), and
// null-sentinel exclusion at atol=1e-3. Frozen against
// tools/oracle/generate_viz_a_scale_fixtures.py (real Python run).

#pragma once

#include <optional>
#include <string>
#include <vector>

namespace pwb::viz {

struct DisplayRange {
    double vmin = 0.0;
    double vmax = 100.0;
};

DisplayRange compute_robust_display_range(
    const std::vector<double>& values, const std::string& curve_name = {},
    std::optional<double> null_value = std::nullopt);

}  // namespace pwb::viz
