// resample_bounds.hpp — exact integer block boundaries for stride-block
// decimation (#1463), extracted from fast_resample_volume_3d so the
// boundary math can be unit-tested without allocating volumes.
//
// Contract (peak-preserving stride-block decimation): target cell i owns
// the half-open source block [lo(i), lo(i+1)) on each axis, with the last
// target forced to end at s (the source edge). Expressed closed for the
// consumer's inclusive loops: block i = [lo[i], hi[i]] where
//   lo[i] = floor(i * s / t)          (exact, no float rounding)
//   hi[i] = (i + 1 == t) ? s - 1 : lo[i + 1] - 1, clamped up to lo[i]
// Blocks are contiguous, cover every source index exactly once, and never
// exceed s - 1. The previous float32 form (lo[i] = trunc(i * (float)s /
// (float)t)) rounded i*step past s - 1 once axes exceeded 2^24 — float32
// cannot represent those integers — and read past the source buffer.
//
// The recurrence below keeps everything in uint64 without one i*s product:
//   lo[0] = 0, r[0] = 0
//   lo[i+1] = lo[i] + (r[i] + s) / t   (integer division)
//   r[i+1]  = (r[i] + s) % t
// r stays < t <= 2^63-1 and s <= 2^63-1, so r + s cannot wrap uint64.

#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

namespace pwb::seismic_core {

// Computes lo/hi for one axis. Returns false when t == 0 (no target cells
// — callers reject that earlier, the guard keeps the helper total).
inline bool resample_block_bounds(std::uint64_t s, std::uint64_t t,
                                  std::vector<std::size_t>& lo,
                                  std::vector<std::size_t>& hi) {
    if (t == 0) return false;
    lo.assign(static_cast<std::size_t>(t), 0);
    hi.assign(static_cast<std::size_t>(t), 0);
    std::uint64_t current = 0;  // lo[i]
    std::uint64_t rem = 0;      // (i * s) mod t
    for (std::uint64_t i = 0; i < t; ++i) {
        lo[static_cast<std::size_t>(i)] =
            static_cast<std::size_t>(current);
        const std::uint64_t next = current + (rem + s) / t;
        rem = (rem + s) % t;
        std::uint64_t top;
        if (i + 1 == t) {
            if (s == 0) return false;  // empty source; caller rejects earlier
            top = s - 1;
        } else {
            top = next > 0 ? next - 1 : 0;
        }
        if (top < current) top = current;  // upsampling: single sample
        hi[static_cast<std::size_t>(i)] = static_cast<std::size_t>(top);
        current = next;
    }
    return true;
}

}  // namespace pwb::seismic_core
