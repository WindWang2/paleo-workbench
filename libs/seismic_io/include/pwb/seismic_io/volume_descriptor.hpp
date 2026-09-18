#pragma once

// pwb::seismic_io — volume descriptor and shared IO vocabulary (Qt-free,
// Python-free). This is the metadata-first surface every consumer (tile
// reader, tiled ISeismicVolume backend, service, host app) shares:
//
//   * `VolumeDescriptor` describes ONE regular post-stack 3-D volume with
//     its source format, dtype/endian, physical axes (inline/crossline and
//     a sample axis that may be time OR depth), and an optional bin-grid
//     calibration. It never carries sample data.
//   * `BinGridGeometry` is the frozen port of the geoviz oracle's
//     geoviz_seismic.models.BinGridGeometry: inline/crossline <-> world
//     (x, y) with azimuth measured CLOCKWISE FROM NORTH (+Y). A missing
//     bin grid means "not geographically calibrated" — consumers must
//     surface that instead of fabricating coordinates.
//   * `CancelFlag` is the one cancellation vocabulary for every potentially
//     long IO loop (checked between traces / rows; never mid-sample).

#include <array>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <limits>
#include <memory>
#include <optional>
#include <string>
#include <utility>

namespace pwb::seismic_io {

// SEG-Y sample format codes this module supports (the repo's real data):
// 1 = IBM System/360 float, big-endian; 5 = IEEE float32, big-endian.
// Everything else is refused honestly by the inspector.
enum class SampleFormat : std::uint16_t {
    ibm_f32_be = 1,
    ieee_f32_be = 5,
};

// Physical meaning of the sample axis. Derived from the declared unit —
// never guessed. "unknown" units stay unknown (the viewer treats them as
// not_convertible; nothing silently reinterprets m as ms or vice versa).
enum class SampleDomain : std::uint8_t { time, depth, unknown };

[[nodiscard]] inline SampleDomain domain_from_unit(std::string_view unit) {
    if (unit == "ms" || unit == "s") {
        return SampleDomain::time;
    }
    if (unit == "m" || unit == "ft") {
        return SampleDomain::depth;
    }
    return SampleDomain::unknown;
}

// Inline/crossline <-> world coordinates. Formulas are symbol-for-symbol the
// oracle's (geoviz_seismic/models.py BinGridGeometry, geo-viz-engine):
// azimuth is clockwise from north (+Y); spacings may be negative; a zero
// spacing makes the conversion undefined and the inspector refuses such a
// grid instead of emitting it.
struct BinGridGeometry {
    double x_origin = 0.0;
    double y_origin = 0.0;
    double il_azimuth_deg = 0.0;
    double il_spacing_m = 1.0;
    double xl_spacing_m = 1.0;

    // World (x, y) -> fractional (inline, crossline) indices.
    [[nodiscard]] std::pair<double, double> xy_to_il_xl(double x,
                                                        double y) const {
        const double dx = x - x_origin;
        const double dy = y - y_origin;
        const double az = il_azimuth_deg * 0.017453292519943295; // degrees->rad
        const double cos_a = std::cos(az);
        const double sin_a = std::sin(az);
        return {(-dx * sin_a + dy * cos_a) / il_spacing_m,
                (dx * cos_a + dy * sin_a) / xl_spacing_m};
    }

    // Fractional (inline, crossline) indices -> world (x, y).
    [[nodiscard]] std::pair<double, double> il_xl_to_xy(double il_frac,
                                                        double xl_frac) const {
        const double az = il_azimuth_deg * 0.017453292519943295;
        const double cos_a = std::cos(az);
        const double sin_a = std::sin(az);
        const double x = x_origin - il_frac * il_spacing_m * sin_a
                         + xl_frac * xl_spacing_m * cos_a;
        const double y = y_origin + il_frac * il_spacing_m * cos_a
                         + xl_frac * xl_spacing_m * sin_a;
        return {x, y};
    }

    // World (x, y) -> nearest integer (inline, crossline) index pair.
    [[nodiscard]] std::pair<std::int64_t, std::int64_t> nearest_il_xl(
        double x, double y) const {
        const auto [il_frac, xl_frac] = xy_to_il_xl(x, y);
        return {std::llround(il_frac), std::llround(xl_frac)};
    }
};

// Self-describing metadata for one volume. No sample data. Valid values are
// produced only by the inspectors (inspect_segy / inspect_pwbvol); default
// construction yields an empty descriptor that describes nothing.
struct VolumeDescriptor {
    std::filesystem::path source;
    std::string storage;          // "seg-y" | "pwbvol1"
    std::int64_t ni = 0;          // inline count
    std::int64_t nc = 0;          // crossline count
    std::int64_t ns = 0;          // samples per trace
    double iline_start = 1.0;     // physical (minimum) inline number
    double xline_start = 1.0;
    double iline_step = 1.0;      // positive; the file's own numbering order
    double xline_step = 1.0;      // is captured by the trace index, not here
    double sample_start = 0.0;    // t0 (ms) or z0 (m)
    double sample_step = 1.0;     // dt (ms) or dz (m/ft)
    std::string sample_unit = "ms";
    SampleDomain sample_domain = SampleDomain::time;
    SampleFormat format = SampleFormat::ieee_f32_be;  // seg-y only
    std::endian byte_order = std::endian::big;        // pwbvol1 is little
    float missing_value = std::numeric_limits<float>::quiet_NaN();
    // Metadata only: nothing in this module ever rewrites samples that
    // compare equal to missing_value (the Python transcode copied floats
    // verbatim; invalid-sample semantics stay "non-finite is invalid" in the
    // rendering layer).
    std::optional<BinGridGeometry> bin_grid;
    std::string geometry_source;  // e.g. "trace-headers-188-192", "pwbvol1-header"
    std::uint64_t payload_offset_bytes = 0;  // sample data start in the file
    std::uint64_t file_size_bytes = 0;

    [[nodiscard]] std::int64_t elements() const noexcept {
        return ni * nc * ns;
    }
};

// Cooperative cancellation. `cancelled()` is checked between traces / rows
// in every window-read loop; the flag is single-shot (set once, never
// cleared) so reads observe a stable decision.
class CancelFlag {
public:
    CancelFlag() = default;

    static CancelFlag make() {
        CancelFlag flag;
        flag.state_ = std::make_shared<std::atomic<bool>>(false);
        return flag;
    }

    void cancel() {
        if (state_ != nullptr) {
            state_->store(true, std::memory_order_relaxed);
        }
    }

    [[nodiscard]] bool cancelled() const {
        return state_ != nullptr && state_->load(std::memory_order_relaxed);
    }

private:
    std::shared_ptr<std::atomic<bool>> state_;
};

}  // namespace pwb::seismic_io
