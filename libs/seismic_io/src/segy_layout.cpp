#include <pwb/seismic_io/segy_layout.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <fstream>
#include <map>
#include <set>

namespace pwb::seismic_io {
namespace {

constexpr std::size_t kTextHeaderBytes = 3200;
constexpr std::size_t kTraceHeaderBytes = 240;
constexpr std::size_t kBinaryHeaderOffset = kTextHeaderBytes;
constexpr std::size_t kHeaderTotal = kTextHeaderBytes + 400;

// Trace-header field byte offsets (SEG-Y rev0/rev1 standard positions the
// reader supports): inline 188-191, crossline 192-195 (BE int32); coordinate
// scalar 70-71 (BE int16); SourceX/Y 72-79; CDP_X/Y 180-187.
constexpr std::size_t kInlineOffset = 188;
constexpr std::size_t kCrosslineOffset = 192;
constexpr std::size_t kScalarOffset = 70;
constexpr std::size_t kSourceXOffset = 72;
constexpr std::size_t kCdpXOffset = 180;

std::uint16_t be_u16(const unsigned char* p) {
    return static_cast<std::uint16_t>((p[0] << 8) | p[1]);
}

std::int32_t be_i32(const unsigned char* p) {
    std::uint32_t v = (static_cast<std::uint32_t>(p[0]) << 24)
        | (static_cast<std::uint32_t>(p[1]) << 16)
        | (static_cast<std::uint32_t>(p[2]) << 8)
        | static_cast<std::uint32_t>(p[3]);
    std::int32_t out;
    std::memcpy(&out, &v, sizeof(out));
    return out;
}

std::int16_t be_i16(const unsigned char* p) {
    return static_cast<std::int16_t>(be_u16(p));
}

bool uniform_steps(const std::vector<std::int64_t>& sorted, std::int64_t* step) {
    if (sorted.size() < 2) {
        *step = 1;
        return true;
    }
    const std::int64_t first = sorted[1] - sorted[0];
    if (first == 0) return false;
    for (std::size_t i = 2; i < sorted.size(); ++i) {
        if (sorted[i] - sorted[i - 1] != first) return false;
    }
    *step = first;
    return true;
}

// THE canonical SourceGroupScalar application (frozen in the geoviz oracle,
// loader.py apply_source_group_scalar): >0 multiply, <0 divide by -scalar,
// 0 = identity ("already metres").
double apply_source_group_scalar(double value, std::int16_t scalar) {
    if (scalar > 0) return value * static_cast<double>(scalar);
    if (scalar < 0) return value / static_cast<double>(-scalar);
    return value;
}

// Frozen bin-grid inference (loader.py _infer_bin_grid): world coordinates
// of the three grid-corner traces (0,0), (1,0), (0,1) from CDP_X/Y — falling
// back to SourceX/Y — yield the inline azimuth (clockwise from north) and
// the (possibly signed) line spacings. Any degeneracy => no bin grid; the
// caller must surface "未标定" rather than fabricate a default grid.
std::optional<BinGridGeometry> infer_bin_grid(std::ifstream& input,
                                              const SegyLayout& partial,
                                              std::int64_t ni,
                                              std::int64_t nc) {
    if (ni < 2 || nc < 2) {
        return std::nullopt;
    }
    struct CornerXY {
        double x = 0.0;
        double y = 0.0;
        std::int16_t scalar = 0;
    };
    const std::array<std::pair<std::int64_t, std::int64_t>, 3> corner_grid = {
        std::make_pair(0, 0), std::make_pair(1, 0), std::make_pair(0, 1)};
    std::array<CornerXY, 3> corners{};
    for (std::size_t c = 0; c < corner_grid.size(); ++c) {
        std::array<unsigned char, kTraceHeaderBytes> header{};
        input.seekg(static_cast<std::streamoff>(partial.trace_offset(
                        corner_grid[c].first, corner_grid[c].second)),
                    std::ios::beg);
        input.read(reinterpret_cast<char*>(header.data()),
                   static_cast<std::streamsize>(kTraceHeaderBytes));
        if (!input.good()) {
            return std::nullopt;
        }
        corners[c].x = static_cast<double>(
            be_i32(&header[kCdpXOffset]));
        corners[c].y = static_cast<double>(
            be_i32(&header[kCdpXOffset + 4]));
        corners[c].scalar = be_i16(&header[kScalarOffset]);
    }
    bool cdp_present = false;
    for (const CornerXY& corner : corners) {
        if (corner.x != 0.0 || corner.y != 0.0) {
            cdp_present = true;
            break;
        }
    }
    if (!cdp_present) {
        // Fall back to SourceX/Y (bytes 72-79) — reread the same headers.
        for (std::size_t c = 0; c < corner_grid.size(); ++c) {
            std::array<unsigned char, kTraceHeaderBytes> header{};
            input.seekg(static_cast<std::streamoff>(partial.trace_offset(
                            corner_grid[c].first, corner_grid[c].second)),
                        std::ios::beg);
            input.read(reinterpret_cast<char*>(header.data()),
                       static_cast<std::streamsize>(kTraceHeaderBytes));
            if (!input.good()) {
                return std::nullopt;
            }
            corners[c].x = static_cast<double>(be_i32(&header[kSourceXOffset]));
            corners[c].y = static_cast<double>(
                be_i32(&header[kSourceXOffset + 4]));
            corners[c].scalar = be_i16(&header[kScalarOffset]);
        }
        bool source_present = false;
        for (const CornerXY& corner : corners) {
            if (corner.x != 0.0 || corner.y != 0.0) {
                source_present = true;
                break;
            }
        }
        if (!source_present) {
            return std::nullopt;
        }
    }
    for (CornerXY& corner : corners) {
        corner.x = apply_source_group_scalar(corner.x, corner.scalar);
        corner.y = apply_source_group_scalar(corner.y, corner.scalar);
    }
    const double il_dx = corners[1].x - corners[0].x;
    const double il_dy = corners[1].y - corners[0].y;
    const double xl_dx = corners[2].x - corners[0].x;
    const double xl_dy = corners[2].y - corners[0].y;
    double il_spacing = std::hypot(il_dx, il_dy);
    double xl_spacing = std::hypot(xl_dx, xl_dy);
    if (il_spacing <= 0.0 || xl_spacing <= 0.0) {
        return std::nullopt;
    }
    // Clockwise from north (+Y), matching BinGridGeometry.
    const double azimuth_deg =
        (il_dx != 0.0 || il_dy != 0.0)
            ? std::atan2(il_dx, il_dy) * 57.29577951308232  // rad->deg
            : 0.0;
    const double az_rad = azimuth_deg / 180.0 * 3.14159265358979323846;
    const double sin_a = std::sin(az_rad);
    const double cos_a = std::cos(az_rad);
    if (-sin_a * il_dx + cos_a * il_dy < 0) {
        il_spacing = -il_spacing;
    }
    if (cos_a * xl_dx + sin_a * xl_dy < 0) {
        xl_spacing = -xl_spacing;
    }
    BinGridGeometry grid;
    grid.x_origin = corners[0].x;
    grid.y_origin = corners[0].y;
    grid.il_azimuth_deg = azimuth_deg;
    grid.il_spacing_m = il_spacing;
    grid.xl_spacing_m = xl_spacing;
    return grid;
}

}  // namespace

std::optional<SegyLayout> inspect_segy(const std::filesystem::path& file,
                                       std::string* error) {
    std::ifstream input(file, std::ios::binary);
    if (!input.good()) {
        if (error != nullptr) *error = "cannot open file: " + file.string();
        return std::nullopt;
    }
    input.seekg(0, std::ios::end);
    const std::streamsize size = input.tellg();
    input.seekg(0, std::ios::beg);
    if (size < static_cast<std::streamsize>(kHeaderTotal)) {
        if (error != nullptr) {
            *error = "file smaller than the SEG-Y headers (" + std::to_string(size)
                + " bytes)";
        }
        return std::nullopt;
    }
    std::array<unsigned char, 400> binary_header{};
    input.seekg(static_cast<std::streamoff>(kBinaryHeaderOffset), std::ios::beg);
    input.read(reinterpret_cast<char*>(binary_header.data()), 400);
    if (!input.good()) {
        if (error != nullptr) *error = "binary header unreadable";
        return std::nullopt;
    }

    const std::uint16_t format_code = be_u16(&binary_header[24]);
    const std::uint16_t ns_raw = be_u16(&binary_header[20]);
    const std::uint16_t dt_us = be_u16(&binary_header[16]);
    if (ns_raw == 0) {
        if (error != nullptr) *error = "binary header declares 0 samples/trace";
        return std::nullopt;
    }
    const std::int64_t ns = ns_raw;
    const std::size_t bytes_per_sample = 4;  // formats 1/5 both 4-byte
    const std::size_t trace_bytes = kTraceHeaderBytes
        + static_cast<std::size_t>(ns) * bytes_per_sample;
    const std::streamsize body = size - static_cast<std::streamsize>(kHeaderTotal);
    if (body <= 0
        || static_cast<std::streamsize>(body / trace_bytes)
                * static_cast<std::streamsize>(trace_bytes)
            != body) {
        if (error != nullptr) {
            *error = "trace body size " + std::to_string(body)
                + " is not a whole multiple of the declared trace size "
                + std::to_string(trace_bytes);
        }
        return std::nullopt;
    }
    const std::size_t trace_count = static_cast<std::size_t>(body
        / static_cast<std::streamsize>(trace_bytes));

    // Pass 1: trace headers — grid discovery (no sortedness assumption).
    std::vector<std::int64_t> ilines(trace_count);
    std::vector<std::int64_t> xlines(trace_count);
    std::map<std::pair<std::int64_t, std::int64_t>, std::size_t> trace_at;
    for (std::size_t t = 0; t < trace_count; ++t) {
        std::array<unsigned char, kTraceHeaderBytes> header{};
        input.seekg(static_cast<std::streamoff>(kHeaderTotal
            + static_cast<std::streamsize>(t) * static_cast<std::streamsize>(trace_bytes)),
            std::ios::beg);
        input.read(reinterpret_cast<char*>(header.data()),
                   static_cast<std::streamsize>(kTraceHeaderBytes));
        if (!input.good()) {
            if (error != nullptr) *error = "trace header unreadable";
            return std::nullopt;
        }
        ilines[t] = be_i32(&header[kInlineOffset]);
        xlines[t] = be_i32(&header[kCrosslineOffset]);
        const auto key = std::make_pair(ilines[t], xlines[t]);
        if (!trace_at.emplace(key, t).second) {
            if (error != nullptr) {
                *error = "duplicate (inline, crossline) trace: ("
                    + std::to_string(ilines[t]) + ", " + std::to_string(xlines[t])
                    + ")";
            }
            return std::nullopt;
        }
    }
    const std::set<std::int64_t> iline_set(ilines.begin(), ilines.end());
    const std::set<std::int64_t> xline_set(xlines.begin(), xlines.end());
    const std::vector<std::int64_t> unique_ilines(iline_set.begin(), iline_set.end());
    const std::vector<std::int64_t> unique_xlines(xline_set.begin(), xline_set.end());
    std::int64_t iline_step = 1;
    std::int64_t xline_step = 1;
    if (!uniform_steps(unique_ilines, &iline_step)
        || !uniform_steps(unique_xlines, &xline_step)) {
        if (error != nullptr) {
            *error = "inline/crossline coordinates do not form a uniform grid";
        }
        return std::nullopt;
    }
    if (static_cast<std::size_t>(unique_ilines.size() * unique_xlines.size())
            != trace_count) {
        if (error != nullptr) {
            *error = "incomplete grid: " + std::to_string(trace_count)
                + " traces vs " + std::to_string(unique_ilines.size()) + "x"
                + std::to_string(unique_xlines.size()) + " grid cells";
        }
        return std::nullopt;
    }
    // Format validation stays AFTER the grid checks: the frozen read_segy
    // semantics reject grid violations first, and the window readers below
    // decode nothing unless inspection succeeded.
    if (format_code != 5 && format_code != 1) {
        if (error != nullptr) {
            *error = "unsupported sample format code "
                + std::to_string(format_code) + " (IEEE(5)/IBM(1) only)";
        }
        return std::nullopt;
    }
    const std::int64_t ni = static_cast<std::int64_t>(unique_ilines.size());
    const std::int64_t nc = static_cast<std::int64_t>(unique_xlines.size());

    SegyLayout layout;
    layout.traces.resize(trace_count);
    for (const auto& [key, trace_index] : trace_at) {
        const auto il_it = std::lower_bound(unique_ilines.begin(),
                                            unique_ilines.end(), key.first);
        const auto xl_it = std::lower_bound(unique_xlines.begin(),
                                            unique_xlines.end(), key.second);
        const std::int64_t il_index =
            std::distance(unique_ilines.begin(), il_it);
        const std::int64_t xl_index =
            std::distance(unique_xlines.begin(), xl_it);
        SegyTracePos& pos =
            layout.traces[static_cast<std::size_t>(il_index * nc + xl_index)];
        pos.inline_index = il_index;
        pos.crossline_index = xl_index;
        pos.byte_offset = kHeaderTotal
            + static_cast<std::uint64_t>(trace_index)
                  * static_cast<std::uint64_t>(trace_bytes);
    }

    VolumeDescriptor& descriptor = layout.descriptor;
    descriptor.source = file;
    descriptor.storage = "seg-y";
    descriptor.ni = ni;
    descriptor.nc = nc;
    descriptor.ns = ns;
    descriptor.iline_start = static_cast<double>(unique_ilines.front());
    descriptor.xline_start = static_cast<double>(unique_xlines.front());
    descriptor.iline_step = static_cast<double>(iline_step);
    descriptor.xline_step = static_cast<double>(xline_step);
    descriptor.sample_start = 0.0;
    descriptor.sample_step =
        dt_us == 0 ? 1.0 : static_cast<double>(dt_us) / 1000.0;
    descriptor.sample_unit = "ms";
    descriptor.sample_domain = SampleDomain::time;
    descriptor.format = format_code == 5 ? SampleFormat::ieee_f32_be
                                         : SampleFormat::ibm_f32_be;
    descriptor.byte_order = std::endian::big;
    descriptor.geometry_source = "trace-headers-188-192";
    descriptor.payload_offset_bytes = kHeaderTotal;
    descriptor.file_size_bytes = static_cast<std::uint64_t>(size);
    descriptor.bin_grid = infer_bin_grid(input, layout, ni, nc);
    return layout;
}

}  // namespace pwb::seismic_io
