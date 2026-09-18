#pragma once

// pwb::seismic_io — minimal post-stack 3-D SEG-Y reader (Qt-free,
// Python-free, dependency-free). Reads the classic layout — 3200-byte
// text header, 400-byte binary header, then fixed-length traces of
// (240-byte header + ns samples) — into a regular (inline, crossline,
// sample) C-order volume.
//
// Semantics frozen against the geoviz oracle loader (tiny.sgy case):
//   * sample formats 5 (IEEE float32, big-endian) and 1 (IBM float) are
//     supported; anything else is refused honestly.
//   * trace ordering is discovered from the trace headers (inline at
//     bytes 189-192, crossline at 193-196, big-endian int32) — no
//     assumption that the file is already sorted.
//   * the (inline, crossline) pairs must form a COMPLETE regular grid
//     (uniform steps, no gaps, no duplicates); irregular surveys are
//     refused, never silently reshaped.
//   * dt comes from the binary header (microseconds); the unit stays
//     "ms" (time domain) — depth-domain files need explicit conversion
//     later and are out of scope.

#include <cstdint>
#include <filesystem>
#include <optional>
#include <string>
#include <vector>

#include <pwb/seismic_io/volume_descriptor.hpp>

namespace pwb::seismic_io {

struct SegyVolume {
    std::int64_t ni = 0;             // inline count
    std::int64_t nc = 0;             // crossline count
    std::int64_t ns = 0;             // samples per trace
    double iline_start = 0.0;
    double xline_start = 0.0;
    double iline_step = 1.0;
    double xline_step = 1.0;
    double dt_ms = 1.0;              // from the binary header
    std::string unit = "ms";
    std::vector<float> samples;      // (ni, nc, ns) C-order, inline-major
};

// Reads one post-stack SEG-Y file. Returns nullopt + a user-readable
// reason on any structural/semantic violation (never a guessed volume).
std::optional<SegyVolume> read_segy(const std::filesystem::path& file,
                                    std::string* error);

// Same read with cooperative cancellation: `cancel` is polled between
// traces; on cancellation returns nullopt with *error == "cancelled" and
// the partial volume is discarded.
std::optional<SegyVolume> read_segy(const std::filesystem::path& file,
                                    std::string* error,
                                    const CancelFlag& cancel);

}  // namespace pwb::seismic_io
