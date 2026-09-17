#include <pwb/seismic_io/segy_reader.hpp>

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

// IBM System/360 float (format code 1): sign(1) exponent(7, base-16,
// excess-64) mantissa(24, fraction). Big-endian on disk.
float ibm_to_float(const unsigned char* p) {
    const std::uint32_t raw = (static_cast<std::uint32_t>(p[0]) << 24)
        | (static_cast<std::uint32_t>(p[1]) << 16)
        | (static_cast<std::uint32_t>(p[2]) << 8)
        | static_cast<std::uint32_t>(p[3]);
    const bool negative = (raw >> 31) != 0;
    const int exponent = static_cast<int>((raw >> 24) & 0x7f) - 64;
    const std::uint32_t mantissa = raw & 0x00ffffff;
    double value = std::ldexp(static_cast<double>(mantissa),
                              4 * exponent - 24);
    if (mantissa == 0) value = 0.0;   // IBM zero is exact zero
    return static_cast<float>(negative ? -value : value);
}

float be_f32(const unsigned char* p) {
    std::uint32_t raw = (static_cast<std::uint32_t>(p[0]) << 24)
        | (static_cast<std::uint32_t>(p[1]) << 16)
        | (static_cast<std::uint32_t>(p[2]) << 8)
        | static_cast<std::uint32_t>(p[3]);
    float out;
    std::memcpy(&out, &raw, sizeof(out));
    return out;
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

}  // namespace

std::optional<SegyVolume> read_segy(const std::filesystem::path& file,
                                    std::string* error) {
    std::ifstream input(file, std::ios::binary);
    if (!input.good()) {
        if (error != nullptr) *error = "cannot open file: " + file.string();
        return std::nullopt;
    }
    input.seekg(0, std::ios::end);
    const std::streamsize size = input.tellg();
    input.seekg(0, std::ios::beg);
    constexpr std::streamsize kHeaderTotal =
        static_cast<std::streamsize>(kTextHeaderBytes) + 400;
    if (size < kHeaderTotal) {
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
    const std::streamsize body = size - kHeaderTotal;
    if (body <= 0 || static_cast<std::streamsize>(body / trace_bytes) * trace_bytes
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

    // Pass 1: headers — grid discovery (no assumption of sorted order).
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
        ilines[t] = be_i32(&header[188]);
        xlines[t] = be_i32(&header[192]);
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
    std::vector<std::int64_t> unique_ilines(iline_set.begin(), iline_set.end());
    std::vector<std::int64_t> unique_xlines(xline_set.begin(), xline_set.end());
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
    const std::int64_t ni = static_cast<std::int64_t>(unique_ilines.size());
    const std::int64_t nc = static_cast<std::int64_t>(unique_xlines.size());

    SegyVolume volume;
    volume.ni = ni;
    volume.nc = nc;
    volume.ns = ns;
    volume.iline_start = static_cast<double>(unique_ilines.front());
    volume.xline_start = static_cast<double>(unique_xlines.front());
    volume.iline_step = static_cast<double>(iline_step);
    volume.xline_step = static_cast<double>(xline_step);
    volume.dt_ms = dt_us == 0 ? 1.0 : static_cast<double>(dt_us) / 1000.0;
    volume.unit = "ms";
    volume.samples.resize(static_cast<std::size_t>(ni * nc * ns));

    // Pass 2: samples — each trace lands at its grid position.
    std::vector<unsigned char> sample_bytes(trace_bytes - kTraceHeaderBytes);
    for (const auto& [key, trace_index] : trace_at) {
        const auto il_it = std::lower_bound(unique_ilines.begin(),
                                            unique_ilines.end(), key.first);
        const auto xl_it = std::lower_bound(unique_xlines.begin(),
                                            unique_xlines.end(), key.second);
        const std::int64_t il = std::distance(unique_ilines.begin(), il_it);
        const std::int64_t xl = std::distance(unique_xlines.begin(), xl_it);
        input.seekg(static_cast<std::streamoff>(kHeaderTotal
            + static_cast<std::streamsize>(trace_index)
                  * static_cast<std::streamsize>(trace_bytes)
            + static_cast<std::streamsize>(kTraceHeaderBytes)),
            std::ios::beg);
        input.read(reinterpret_cast<char*>(sample_bytes.data()),
                   static_cast<std::streamsize>(sample_bytes.size()));
        if (!input.good()) {
            if (error != nullptr) *error = "trace samples unreadable";
            return std::nullopt;
        }
        float* dest = &volume.samples[static_cast<std::size_t>(
            (il * nc + xl) * ns)];
        switch (format_code) {
            case 5:
                for (std::int64_t s = 0; s < ns; ++s) {
                    dest[s] = be_f32(&sample_bytes[static_cast<std::size_t>(s) * 4]);
                }
                break;
            case 1:
                for (std::int64_t s = 0; s < ns; ++s) {
                    dest[s] = ibm_to_float(
                        &sample_bytes[static_cast<std::size_t>(s) * 4]);
                }
                break;
            default:
                if (error != nullptr) {
                    *error = "unsupported sample format code "
                        + std::to_string(format_code) + " (IEEE(5)/IBM(1) only)";
                }
                return std::nullopt;
        }
    }
    return volume;
}

}  // namespace pwb::seismic_io
