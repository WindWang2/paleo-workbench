#include <pwb/seismic_viewer/slice_export.hpp>

#include <cmath>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <limits>
#include <string>
#include <vector>

namespace pwb::seismic_viewer::slice_export {
namespace {

bool shape_ok(std::span<const float> data, std::int64_t rows, std::int64_t cols,
              std::string& error) {
    if (rows <= 0 || cols <= 0) {
        error = "invalid slice shape";
        return false;
    }
    if (data.size() != static_cast<std::size_t>(rows) * static_cast<std::size_t>(cols)) {
        error = "plane size does not match shape";
        return false;
    }
    return true;
}

} // namespace

bool write_npy(const std::string& path, std::span<const float> data,
               std::int64_t rows, std::int64_t cols, std::string& error) {
    error.clear();
    if (!shape_ok(data, rows, cols, error)) {
        return false;
    }
    // Header dict text (np.save layout: dict + trailing padding spaces + \n).
    const std::string shape =
        "(" + std::to_string(rows) + ", " + std::to_string(cols) + ")";
    std::string header =
        "{'descr': '<f4', 'fortran_order': False, 'shape': " + shape + ", }";
    // Preamble: magic (6) + version (2) + header_len (2) + header; the whole
    // file prefix is padded with spaces to a multiple of 64 bytes and the
    // header ends with exactly one '\n' (numpy writes >=1 and pads to 64).
    // Algebra: prefix = 10 + H0 + spaces + 1 == padded => spaces = padded -
    // (10 + H0 + 1).
    const std::size_t magic_len = 6 + 2 + 2; // magic + version + len field
    const std::size_t total = magic_len + header.size() + 1; // + '\n'
    std::size_t padded = ((total + 63) / 64) * 64;
    if (padded - total > std::numeric_limits<std::uint16_t>::max()) {
        error = "npy header too large";
        return false;
    }
    header.append(padded - total, ' ');
    header.push_back('\n');

    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    if (!out) {
        error = "cannot open file: " + path;
        return false;
    }
    out.write("\x93NUMPY", 6);
    const unsigned char version[2] = {0x01, 0x00};
    out.write(reinterpret_cast<const char*>(version), 2);
    const std::uint16_t header_len = static_cast<std::uint16_t>(header.size());
    unsigned char len_le[2] = {static_cast<unsigned char>(header_len & 0xFF),
                               static_cast<unsigned char>((header_len >> 8) & 0xFF)};
    out.write(reinterpret_cast<const char*>(len_le), 2);
    out.write(header.data(), static_cast<std::streamsize>(header.size()));
    out.write(reinterpret_cast<const char*>(data.data()),
              static_cast<std::streamsize>(data.size() * sizeof(float)));
    out.close();
    if (!out) {
        error = "write failed: " + path;
        return false;
    }
    return true;
}

bool write_csv(const std::string& path, std::span<const float> data,
               std::int64_t rows, std::int64_t cols, std::string& error) {
    error.clear();
    if (!shape_ok(data, rows, cols, error)) {
        return false;
    }
    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    if (!out) {
        error = "cannot open file: " + path;
        return false;
    }
    // np.savetxt fmt="%.6f": exactly six decimals, comma delimiter. NaN
    // prints sign-less "nan" (numpy parity; glibc would emit "-nan" for a
    // negative NaN bit pattern); inf/-inf match numpy too.
    for (std::int64_t r = 0; r < rows; ++r) {
        for (std::int64_t c = 0; c < cols; ++c) {
            if (c != 0) {
                out.put(',');
            }
            const double value =
                static_cast<double>(data[static_cast<std::size_t>(r * cols + c)]);
            if (std::isnan(value)) {
                out.write("nan", 3);
                continue;
            }
            char buf[64];
            std::snprintf(buf, sizeof(buf), "%.6f", value);
            out.write(buf, static_cast<std::streamsize>(std::strlen(buf)));
        }
        out.put('\n');
    }
    out.close();
    if (!out) {
        error = "write failed: " + path;
        return false;
    }
    return true;
}

} // namespace pwb::seismic_viewer::slice_export
