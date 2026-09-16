#pragma once

// Seismic volume data-source contract (C3). The interface is deliberately
// shaped so a chunked-store backend (geo-viz-engine #148 secondary layout)
// can be added later: explicit axis order, index-space shape, element
// strides, physical origin/step with units, missing value, byte order and an
// ownership/lifetime guard. A backend must never copy the whole volume to
// serve a slice.

#include <array>
#include <bit>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <optional>
#include <span>
#include <string>
#include <utility>
#include <vector>

namespace pwb::viz {

enum class VolumeAxis : std::uint8_t { inline_, crossline, sample };

[[nodiscard]] inline std::size_t axis_index(VolumeAxis axis) noexcept {
    return axis == VolumeAxis::inline_ ? 0 : (axis == VolumeAxis::crossline ? 1 : 2);
}

enum class VolumeOwnership : std::uint8_t { none, owning, mmap };

// One chunk of a (future) chunked store: element-space offset and extent of a
// contiguous chunk plus its layout tag. In-memory volumes report no chunks.
struct ChunkInfo {
    std::array<std::int64_t, 3> offset{0, 0, 0};
    std::array<std::int64_t, 3> extent{0, 0, 0};
    std::string layout; // "main" | secondary layout tag from #148
};

struct VolumeGeometryV1 {
    std::array<std::int64_t, 3> shape{0, 0, 0};  // (n_inline, n_crossline, n_sample) index space
    std::array<std::int64_t, 3> strides{0, 0, 0}; // element strides; permuted layouts allowed
    std::array<double, 3> origin{0.0, 0.0, 0.0};  // physical first value per axis
    std::array<double, 3> step{1.0, 1.0, 1.0};    // physical step (may be negative)
    std::string unit;                             // sample-axis unit, e.g. "ms"
    float missing_value{-999.25f};
    std::endian byte_order{std::endian::native};
    VolumeOwnership ownership{VolumeOwnership::none};

    [[nodiscard]] double axis_value(VolumeAxis axis, std::int64_t index) const noexcept {
        const std::size_t a = axis_index(axis);
        return origin[a] + static_cast<double>(index) * step[a];
    }
    // Physical axis coordinate range for [first, last] index, first < last.
    [[nodiscard]] std::pair<double, double> axis_extent(VolumeAxis axis) const noexcept {
        const std::size_t a = axis_index(axis);
        const double first = axis_value(axis, 0);
        const double last = axis_value(axis, shape[a] - 1);
        return first <= last ? std::make_pair(first, last) : std::make_pair(last, first);
    }
    [[nodiscard]] std::array<std::int64_t, 3> effective_strides() const noexcept {
        if (strides[0] != 0 || strides[1] != 0 || strides[2] != 0) {
            return strides;
        }
        return {shape[1] * shape[2], shape[2], 1};
    }
};

class ISeismicVolume {
public:
    virtual ~ISeismicVolume() = default;

    [[nodiscard]] virtual const VolumeGeometryV1& geometry() const = 0;

    // Reads one full plane perpendicular to `axis` at `index` into `out`.
    // The output order is the canonical row-major order of the two remaining
    // axes in their declared order (e.g. axis=inline -> rows over crossline,
    // columns over sample). `out.size()` must equal the product of the two
    // remaining extents. Returns the number of elements written; 0 on an
    // out-of-bounds index or a mismatched span (no partial writes, no
    // exceptions across this boundary). Implementations must not cache
    // copies of slice data between calls.
    virtual std::size_t read_slice(VolumeAxis axis, std::int64_t index,
                                   std::span<float> out) = 0;

    // Chunk metadata for chunked backends; empty for in-memory volumes.
    [[nodiscard]] virtual std::vector<ChunkInfo> chunk_plan() const { return {}; }

    // Lifetime guard: keeps the backing storage alive while slices are read.
    [[nodiscard]] virtual std::shared_ptr<const void> lifetime() const = 0;
};

// Builds an in-memory reference backend over caller-owned storage.
// `data` must stay valid as long as `lifetime` is alive; geometry.strides may
// describe any permuted layout. Ownership stays with the caller.
[[nodiscard]] std::unique_ptr<ISeismicVolume> make_in_memory_volume(
    VolumeGeometryV1 geometry, const float* data, std::shared_ptr<const void> lifetime);

// Convenience: fully owning C-order volume (packed strides).
[[nodiscard]] std::unique_ptr<ISeismicVolume> make_owning_volume(VolumeGeometryV1 geometry,
                                                                 std::vector<float> data);

// Canonical slice extent (product of the two non-sliced axes) for a geometry.
[[nodiscard]] inline std::int64_t slice_extent(const VolumeGeometryV1& geometry,
                                               VolumeAxis axis) noexcept {
    const std::size_t a = axis_index(axis);
    std::int64_t product = 1;
    for (std::size_t i = 0; i < 3; ++i) {
        if (i != a) {
            product *= geometry.shape[i];
        }
    }
    return product;
}

// ---------------------------------------------------------------------------
// Slice post-processing: 8-bit indexed color mapping with per-slice stretch.
// Semantics frozen against paleo_workbench/native_backend.py
// _py_fast_slice_to_indexed8 (the numeric oracle):
//   - non-finite samples are excluded from the min/max stretch and render 0;
//   - an explicit value_range overrides the stretch;
//   - degenerate ranges (constant, all-invalid, non-finite bounds) produce an
//     all-zero plane and report (0.0, 0.0);
//   - quantization truncates toward zero after float32 arithmetic.
// ---------------------------------------------------------------------------

struct IndexedSlice {
    std::vector<std::uint8_t> pixels; // slice.size() entries
    double value_min{0.0};
    double value_max{0.0};
    bool degenerate{false};
};

[[nodiscard]] IndexedSlice map_slice_to_indexed8(
    std::span<const float> slice,
    const std::optional<std::pair<double, double>>& value_range = std::nullopt);

} // namespace pwb::viz
