#pragma once

// pwb::seismic_io — SEG-Y metadata inspection.
//
// `inspect_segy` performs the header pass ONLY (binary header + every trace
// header): grid discovery, dedup/uniform/completeness validation, dt, and
// the frozen bin-grid inference from three corner traces. It never reads
// sample bytes, so a host can show survey metadata before deciding to read
// anything. The returned `SegyLayout` carries everything `read_segy_window`
// needs to gather arbitrary sub-volumes without re-scanning.
//
// Error-string semantics are the frozen `read_segy` ones (same strings, same
// precedence: open -> size -> binary header -> ns -> trace body -> trace
// header -> duplicate -> uniform grid -> complete grid -> format code), and
// `read_segy` composes inspect + one full-extent window read, so its
// observable behavior is unchanged.

#include <cstdint>
#include <filesystem>
#include <optional>
#include <string>
#include <vector>

#include <pwb/seismic_io/volume_descriptor.hpp>

namespace pwb::seismic_io {

// One trace's file position. `inline_index`/`crossline_index` are grid
// indices in [0, ni) x [0, nc); `byte_offset` points at the trace's 240-byte
// header (samples follow at +240).
struct SegyTracePos {
    std::int64_t inline_index = 0;
    std::int64_t crossline_index = 0;
    std::uint64_t byte_offset = 0;
};

// Result of a successful inspection: the descriptor plus the trace→file
// map in canonical grid order (row-major inline-major; index =
// il*nc + xl). Exactly ni*nc entries — the grid is complete by contract.
struct SegyLayout {
    VolumeDescriptor descriptor;
    std::vector<SegyTracePos> traces;

    [[nodiscard]] std::uint64_t trace_offset(std::int64_t il,
                                             std::int64_t xl) const {
        return traces[static_cast<std::size_t>(il * descriptor.nc + xl)]
            .byte_offset;
    }
};

// Header-only pass. Returns nullopt + *error on any structural violation.
std::optional<SegyLayout> inspect_segy(const std::filesystem::path& file,
                                       std::string* error);

}  // namespace pwb::seismic_io
