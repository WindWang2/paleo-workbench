#pragma once

// pwb::seismic_io — bounded sub-volume (tile) reads.
//
// A "window" is a half-open index-space box [origin, origin+extent) over the
// (inline, crossline, sample) grid. Window reads are the only sample-access
// primitive of this module: they gather exactly the requested box (per-trace
// seeks for SEG-Y, per-row seeks for PWBVOL1) and never materialise the
// whole volume. This is the parity surface for the Python reader contract
// (geoviz_seismic.chunked VolumeReader.read_voxel_window: half-open
// base-index bounds, one batched read, no point-wise loops).
//
// Output layout: C-order over (inline, crossline, sample) restricted to the
// window — i.e. out[(i-o0)*e1*e2 + (j-o1)*e2 + (t-o2)] holds sample
// volume[il=i][xl=j][t]. `out.size()` must equal extent[0]*extent[1]*extent[2].
//
// Cancellation: the cancel flag is checked once per trace (SEG-Y) / per row
// (PWBVOL1). On cancellation the read stops immediately, returns 0 and sets
// *error to "cancelled"; the contents of `out` are then unspecified and the
// caller must discard them.
//
// PWBVOL1 is the repo's own little-endian float32 verification payload
// (magic "PWBVOL1\0" + u32 LE header size + JSON header + C-order f32
// samples — same bytes `pwb::application::write_volume_payload` emits). Its
// inspector reads and validates the header JSON only.

#include <array>
#include <cstdint>
#include <filesystem>
#include <optional>
#include <span>
#include <string>
#include <vector>

#include <pwb/seismic_io/segy_layout.hpp>
#include <pwb/seismic_io/volume_descriptor.hpp>

namespace pwb::seismic_io {

struct WindowSpec {
    std::array<std::int64_t, 3> origin{0, 0, 0};
    std::array<std::int64_t, 3> extent{0, 0, 0};

    [[nodiscard]] std::int64_t elements() const noexcept {
        // D5: checked multiplication — extreme extents from a hostile
        // window must refuse with 0 (an invalid elements count), never
        // signed-overflow-UB before the bounds check can run.
        std::int64_t n = extent[0];
        for (int k = 1; k < 3; ++k) {
            if (n == 0) return 0;
            if (extent[k] != 0 &&
                std::abs(extent[k]) > (std::numeric_limits<std::int64_t>::max() /
                                       std::abs(n))) {
                return 0;
            }
            n *= extent[k];
        }
        return n;
    }
};

// Validates bounds against the descriptor (out-of-range or empty windows are
// refused, never clamped) without touching I/O.
[[nodiscard]] bool window_in_bounds(const VolumeDescriptor& descriptor,
                                    const WindowSpec& window);

// Gathers the window from a SEG-Y file previously described by
// inspect_segy. Returns the number of elements written (== window.elements()
// on success); 0 + *error on any failure (including cancellation).
std::size_t read_segy_window(const SegyLayout& layout,
                             const WindowSpec& window, std::span<float> out,
                             const CancelFlag& cancel, std::string* error);

// Header-only inspection of a PWBVOL1 payload file.
struct PwbvolLayout {
    VolumeDescriptor descriptor;
};

std::optional<PwbvolLayout> inspect_pwbvol(const std::filesystem::path& file,
                                           std::string* error);

// Gathers the window from a PWBVOL1 file (each row along the sample axis is
// contiguous; one seek + one read per inline/crossline row).
std::size_t read_pwbvol_window(const PwbvolLayout& layout,
                               const WindowSpec& window, std::span<float> out,
                               const CancelFlag& cancel, std::string* error);

}  // namespace pwb::seismic_io
