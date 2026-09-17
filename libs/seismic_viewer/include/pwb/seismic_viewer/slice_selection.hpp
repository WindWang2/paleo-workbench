#pragma once

// Seismic slice selection events — D-line viewer contract (Qt-free).
// This header lives in pwb::seismic_viewer on purpose: richer slice-level
// events (axis/index/physical coordinates) stay in the viewer module and are
// NOT pushed into C's shared pwb::viz files. Depth-domain vocabulary is
// reused from pwb::viz::selection.hpp (published C interface).

#include <cstdint>
#include <optional>
#include <string>
#include <string_view>

#include <pwb/viz/selection.hpp>
#include <pwb/viz/seismic_volume.hpp>

namespace pwb::seismic_viewer {

// Domain identity of the displayed volume, mirroring A/B's volume versioning.
struct VolumeIdentity {
    std::string volume_id; // stable domain id; "" for anonymous test volumes
    std::uint64_t version{0};
};

// Result of a unit-domain crossing attempt. Time units (ms/s) never convert
// to length units (m/ft) implicitly: without an explicit time-depth relation
// the status is not_convertible — the viewer must not treat m as ms.
enum class ConversionStatus : std::uint8_t { native, converted, not_convertible };

enum class UnitKind : std::uint8_t { time, length, unknown };

[[nodiscard]] inline UnitKind unit_kind(std::string_view unit) {
    if (unit == "ms" || unit == "s") {
        return UnitKind::time;
    }
    if (unit == "m" || unit == "ft") {
        return UnitKind::length;
    }
    return UnitKind::unknown;
}

// Explicit linear time-depth relation for well-log linkage. The host must
// supply measured parameters; the viewer never guesses a velocity.
// time_ms = origin_ms + depth_m * ms_per_m
struct LinearTimeDepth {
    double origin_ms{0.0};
    double ms_per_m{1.0};
};

// Emitted on user pick/drag and on programmatic selection (not on echoes of
// apply_selection — see the feedback-loop rule in v3-contracts.md).
struct SliceSelectionEvent {
    std::string origin;        // emitting viewer identity; rebroadcasts skip it
    std::string document_id;   // VolumeIdentity.volume_id at emission time
    std::uint64_t revision{0}; // volume revision counter set via set_volume

    pwb::viz::VolumeAxis axis{pwb::viz::VolumeAxis::inline_};
    std::int64_t index{0};             // slice index in [0, shape[axis])
    double axis_coordinate{0.0};       // geometry.origin + index * step
    std::string axis_unit;             // sample axis -> geometry.unit; inline/
                                       // crossline are unitless line numbers

    // Single-point pick (click without drag).
    bool has_point{false};
    double row_coordinate{0.0}; // physical value of the plane's row axis
    double col_coordinate{0.0}; // physical value of the plane's column axis
    std::string row_unit;
    std::string col_unit;

    // Dragged time interval on section views (inline/crossline planes,
    // vertical drag): sample-axis physical range, time_top <= time_bottom.
    bool has_time_range{false};
    double time_top{0.0};
    double time_bottom{0.0};
    std::string time_unit; // geometry.unit of the sample axis

    // Well-log linkage fields. domain is the volume's sample-domain kind;
    // conversion reports what happened when a LinearTimeDepth relation was
    // applied to time_top/time_bottom (converted_* are valid iff converted).
    pwb::viz::DepthDomainKind domain{pwb::viz::DepthDomainKind::time};
    ConversionStatus conversion{ConversionStatus::native};
    double converted_top{0.0};
    double converted_bottom{0.0};
    std::string converted_unit;
};

} // namespace pwb::seismic_viewer
