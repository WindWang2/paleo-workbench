#pragma once

// Minimal versioned result-volume payload (A-owned, v3-contracts.md §5).
//
// Purpose: serialize ONE algorithm result volume (float32) with a stable
// self-describing header (shape / axis semantics / units / layout) into a
// single staged file that B's publish transaction stores verbatim. This is
// a *verification format* with an explicit version and boundary — it is
// not SEG-Y, not Zarr, and never claims to be an industry format.
//
// Layout (little-endian, no external deps):
//   bytes  0..7    magic "PWBVOL1\0"
//   bytes  8..11   uint32 header_json_size
//   bytes 12..     header JSON (UTF-8), nlohmann round-trip
//   then           float32 payload, C-order (inline, crossline, sample)
//
// Header members (documented contract, validated on read):
//   version          = 1
//   shape            = [ni, nc, ns]
//   axes             = ["inline","crossline","sample"]
//   axis_starts      = [i0, c0, s0]       (physical first index per axis)
//   axis_steps       = [di, dc, ds]       (physical step per axis)
//   units            = {axis unit strings + value_unit}
//   value_unit       = e.g. "1" (dimensionless coherence)
//   layout           = "c-order-f32"
//   approximations   = free-form array of approximation flags
//   provenance       = {algorithm_id, algorithm_version, build, request_id}

#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>

namespace pwb::application {

struct VolumePayloadHeader {
    std::uint32_t ni = 0, nc = 0, ns = 0;
    double inline_start = 0, crossline_start = 0, sample_start = 0;
    double inline_step = 1, crossline_step = 1, sample_step = 1;
    std::string inline_unit;      // e.g. "" (index) or "m"
    std::string crossline_unit;
    std::string sample_unit;      // e.g. "ms" or "m"
    std::string value_unit;       // e.g. "1"
    std::string algorithm_id;
    std::string algorithm_version;
    std::string build_identity;
    std::string request_id;
    std::vector<std::string> approximations;
};

struct VolumePayload {
    VolumePayloadHeader header;
    std::vector<float> samples;   // ni*nc*ns, C-order (inline, crossline, sample)
};

// Serializes to path (atomic enough for staging: written then hashed by the
// caller). Returns "" on success.
std::string write_volume_payload(const VolumePayload& payload,
                                 const std::filesystem::path& path);

// Reads + validates (magic, version, shape, payload size). Returns "" on
// success; out is untouched on failure.
std::string read_volume_payload(const std::filesystem::path& path,
                                VolumePayload* out);

}  // namespace pwb::application
