// Domain models for the joint well–seismic scene (VIZ-C / plan V4).
// Faithful port of geoviz_well_seismic_3d/models.py @ 08851951 (frozen
// behavior source; the Python module stays as the legacy reference and
// oracle generator). Qt-free; NumPy arrays become std::vector<double> and
// validation errors are std::invalid_argument (Python ValueError parity).
#pragma once

#include <array>
#include <cmath>
#include <cstdint>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace pwb::geo3d_viz::joint {

// JointWellId is a stable source identity string (NewType in Python).
using JointWellId = std::string;

inline constexpr std::size_t kMaxTimeSlices = 8;  // MAX_TIME_SLICES

enum class VerticalDomain { Time, Depth };

inline constexpr const char* to_string(VerticalDomain domain) {
    return domain == VerticalDomain::Depth ? "depth" : "time";
}

// Well surface/bottom location in Local Rectangular XY (metres).
struct WellHead {
    std::string name;
    double x = 0.0;
    double y = 0.0;
    double bottom_x = 0.0;
    double bottom_y = 0.0;
    double total_depth_m = 0.0;
    double kb_m = 0.0;
    JointWellId id;  // required non-empty (set_wells refuses otherwise)
};

// TIME (ms) ↔ MD (m) pairs for one well (SMI-style TD). md_to_time_ms is
// NaN outside the calibrated range — callers truncate, never clamp (V6 §8).
class TimeDepthTable {
public:
    TimeDepthTable(std::string well_name, std::vector<double> time_ms,
                   std::vector<double> md_m);

    const std::string& well_name() const { return well_name_; }
    std::size_t size() const { return time_ms_.size(); }
    const std::vector<double>& time_ms() const { return time_ms_; }
    const std::vector<double>& md_m() const { return md_m_; }

    // Calibrated MD extent (interpolation is valid ONLY inside it).
    std::pair<double, double> md_range() const {
        return {md_m_.front(), md_m_.back()};
    }

    // Interpolate MD → TWT (ms). NaN outside the calibrated range.
    double md_to_time_ms(double md) const;
    // Interpolate TWT (ms) → MD. NaN outside the calibrated range.
    double time_ms_to_md(double twt) const;
    std::vector<double> md_to_time_ms(const std::vector<double>& md) const;
    std::vector<double> time_ms_to_md(const std::vector<double>& twt) const;

private:
    // xp strictly increasing, both axes (validated in the constructor).
    double interp(const std::vector<double>& xp, const std::vector<double>& fp,
                  double x) const;

    std::string well_name_;
    std::vector<double> time_ms_;
    std::vector<double> md_m_;
};

// Well path in scene coordinates (x, y, z) for the active vertical domain.
struct WellTrajectory3D {
    std::string name;
    std::vector<std::array<double, 3>> points;
    bool has_td = false;
    std::optional<std::string> warning;
};

// Well path samples paired with GR values for color rendering.
struct WellGrTrajectory {
    JointWellId id;
    std::string name;
    std::string display_name;
    std::vector<std::array<double, 3>> points;
    std::vector<double> gr_values;
};

// Well trajectory intersection with the ActiveTimeSlice (survey XY + TWT).
struct WellPierce {
    JointWellId well_id;
    std::string name;
    std::string display_name;
    double x = 0.0;
    double y = 0.0;
    double z = 0.0;
};

// Project-persisted color scales and shared well trajectory width.
struct JointDisplaySettings {
    std::string seismic_color_scale = "blue-white-red";
    std::string gr_color_scale = "viridis";
    int well_width_px = 5;

    JointDisplaySettings() = default;
    JointDisplaySettings(std::string seismic, std::string gr, int width_px)
        : seismic_color_scale(std::move(seismic)),
          gr_color_scale(std::move(gr)),
          well_width_px(width_px) {
        if (well_width_px < 2 || well_width_px > 10) {
            throw std::invalid_argument(
                "well_width_px must be between 2 and 10");
        }
    }
};

// One persisted horizontal seismic slice in TWT milliseconds.
struct TimeSliceState {
    double time_ms = 0.0;
    bool visible = true;

    TimeSliceState() = default;
    TimeSliceState(double ms, bool vis = true) : time_ms(ms), visible(vis) {
        if (!std::isfinite(time_ms)) {
            throw std::invalid_argument("time_ms must be finite");
        }
    }
};

// Joint-scene state for one IL, one XL and a Time slice stack.
struct OrthogonalSliceState {
    std::optional<std::int64_t> inline_index;
    std::optional<std::int64_t> crossline_index;
    std::vector<TimeSliceState> time_slices;
    std::optional<double> active_time_ms;
    double time_opacity = 0.8;

    OrthogonalSliceState() = default;
    OrthogonalSliceState(std::optional<std::int64_t> il,
                         std::optional<std::int64_t> xl,
                         std::vector<TimeSliceState> slices,
                         std::optional<double> active_ms, double opacity);
};

}  // namespace pwb::geo3d_viz::joint
