#include <pwb/seismic_io/tile_read.hpp>

#include <algorithm>
#include <array>
#include <bit>
#include <cstring>
#include <fstream>
#include <limits>

#include <pwb/domain/json.hpp>

namespace pwb::seismic_io {
namespace {

constexpr std::size_t kTraceHeaderBytes = 240;

std::uint32_t le_u32(const unsigned char* p) {
    return static_cast<std::uint32_t>(p[0])
        | (static_cast<std::uint32_t>(p[1]) << 8)
        | (static_cast<std::uint32_t>(p[2]) << 16)
        | (static_cast<std::uint32_t>(p[3]) << 24);
}

// IBM System/360 float (format code 1): sign(1) exponent(7, base-16,
// excess-64) mantissa(24). Big-endian on disk. Same conversion the frozen
// segy_reader has always applied.
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
    if (mantissa == 0) value = 0.0;  // IBM zero is exact zero
    return static_cast<float>(negative ? -value : value);
}

// Big-endian IEEE float32 -> host.
float be_f32(const unsigned char* p) {
    std::uint32_t raw = (static_cast<std::uint32_t>(p[0]) << 24)
        | (static_cast<std::uint32_t>(p[1]) << 16)
        | (static_cast<std::uint32_t>(p[2]) << 8)
        | static_cast<std::uint32_t>(p[3]);
    float out;
    std::memcpy(&out, &raw, sizeof(out));
    return out;
}

// Little-endian IEEE float32 -> host (PWBVOL1 payload).
float le_f32(const unsigned char* p) {
    std::uint32_t raw = le_u32(p);
    float out;
    std::memcpy(&out, &raw, sizeof(out));
    return out;
}

}  // namespace

bool window_in_bounds(const VolumeDescriptor& descriptor,
                      const WindowSpec& window) {
    const std::array<std::int64_t, 3> shape{descriptor.ni, descriptor.nc,
                                            descriptor.ns};
    for (std::size_t axis = 0; axis < 3; ++axis) {
        if (window.extent[axis] < 0) {
            return false;
        }
        if (window.origin[axis] < 0) {
            return false;
        }
        // Overflow-safe upper check (#1456): `origin + extent > shape` can
        // wrap int64 for hostile windows (origin = extent = INT64_MAX would
        // compare a wrapped negative and pass). `origin > shape - extent`
        // cannot wrap — both operands are non-negative and at most int64
        // range, and a negative right-hand side (extent > shape) correctly
        // reads as out of bounds.
        if (window.origin[axis] > shape[axis] - window.extent[axis]) {
            return false;
        }
    }
    // An empty window (any zero extent) is refused: callers ask for data or
    // ask for nothing, never for a silently-degenerate gather.
    return window.elements() > 0;
}

std::size_t read_segy_window(const SegyLayout& layout,
                             const WindowSpec& window, std::span<float> out,
                             const CancelFlag& cancel, std::string* error) {
    const VolumeDescriptor& descriptor = layout.descriptor;
    if (out.size() != static_cast<std::size_t>(window.elements())) {
        if (error != nullptr) {
            *error = "output span size " + std::to_string(out.size())
                + " != window extent " + std::to_string(window.elements());
        }
        return 0;
    }
    if (!window_in_bounds(descriptor, window)) {
        if (error != nullptr) *error = "window out of bounds";
        return 0;
    }
    std::ifstream input(descriptor.source, std::ios::binary);
    if (!input.good()) {
        if (error != nullptr) {
            *error = "cannot open file: " + descriptor.source.string();
        }
        return 0;
    }
    const std::int64_t t0 = window.origin[2];
    const std::int64_t nt = window.extent[2];
    std::vector<unsigned char> raw(
        static_cast<std::size_t>(nt) * 4);
    std::size_t written = 0;
    for (std::int64_t il = window.origin[0];
         il < window.origin[0] + window.extent[0]; ++il) {
        for (std::int64_t xl = window.origin[1];
             xl < window.origin[1] + window.extent[1]; ++xl) {
            if (cancel.cancelled()) {
                if (error != nullptr) *error = "cancelled";
                return 0;
            }
            // Checked offset chain (#1456 symmetry): trace_offset comes from
            // the validated trace map, but the header/sample additions and
            // the final streamoff cast still deserve wrap-free proof.
            const auto trace_offset_opt = [&]() -> std::optional<std::uint64_t> {
                const auto with_header =
                    checked::add(layout.trace_offset(il, xl),
                                 kTraceHeaderBytes);
                if (!with_header.has_value()) return std::nullopt;
                const auto sample_bytes = checked::mul(
                    static_cast<std::uint64_t>(t0), 4u);
                if (!sample_bytes.has_value()) return std::nullopt;
                return checked::add(*with_header, *sample_bytes);
            }();
            if (!trace_offset_opt.has_value()
                || *trace_offset_opt > descriptor.file_size_bytes
                || *trace_offset_opt + raw.size()
                       > descriptor.file_size_bytes) {
                if (error != nullptr) {
                    *error = "trace offset out of range";
                }
                return 0;
            }
            const std::uint64_t offset = *trace_offset_opt;
            input.seekg(static_cast<std::streamoff>(offset), std::ios::beg);
            input.read(reinterpret_cast<char*>(raw.data()),
                       static_cast<std::streamsize>(raw.size()));
            if (!input.good()) {
                if (error != nullptr) *error = "trace samples unreadable";
                return 0;
            }
            float* dst = out.data() + written;
            if (descriptor.format == SampleFormat::ieee_f32_be) {
                for (std::int64_t t = 0; t < nt; ++t) {
                    dst[t] = be_f32(&raw[static_cast<std::size_t>(t) * 4]);
                }
            } else {
                for (std::int64_t t = 0; t < nt; ++t) {
                    dst[t] = ibm_to_float(&raw[static_cast<std::size_t>(t) * 4]);
                }
            }
            written += static_cast<std::size_t>(nt);
        }
    }
    return written;
}

std::optional<PwbvolLayout> inspect_pwbvol(const std::filesystem::path& file,
                                           std::string* error) {
    std::ifstream input(file, std::ios::binary);
    if (!input.good()) {
        if (error != nullptr) *error = "cannot open file: " + file.string();
        return std::nullopt;
    }
    input.seekg(0, std::ios::end);
    const std::streamsize size = input.tellg();
    input.seekg(0, std::ios::beg);

    std::array<char, 8> magic{};
    input.read(magic.data(), 8);
    const char kMagic[8] = {'P', 'W', 'B', 'V', 'O', 'L', '1', '\0'};
    if (!input.good() || std::memcmp(magic.data(), kMagic, 8) != 0) {
        if (error != nullptr) {
            *error = "bad magic (not a PWBVOL1 file): " + file.string();
        }
        return std::nullopt;
    }
    std::array<unsigned char, 4> size_bytes{};
    input.read(reinterpret_cast<char*>(size_bytes.data()), 4);
    if (!input.good()) {
        if (error != nullptr) *error = "truncated header size";
        return std::nullopt;
    }
    const std::uint32_t header_size = le_u32(size_bytes.data());
    if (header_size == 0 || header_size > (16u << 20)) {
        if (error != nullptr) {
            *error = "implausible header size: " + std::to_string(header_size);
        }
        return std::nullopt;
    }
    std::string header_text(header_size, '\0');
    input.read(header_text.data(), static_cast<std::streamsize>(header_size));
    if (!input.good()) {
        if (error != nullptr) *error = "truncated header body";
        return std::nullopt;
    }
    const pwb::domain::Json header = pwb::domain::Json::parse(
        header_text, nullptr, false);
    if (header.is_discarded()) {
        if (error != nullptr) *error = "header JSON invalid";
        return std::nullopt;
    }
    if (!header.contains("version") || !header["version"].is_number()
        || header["version"].get<int>() != 1) {
        if (error != nullptr) *error = "unsupported payload version";
        return std::nullopt;
    }
    const auto is_string = [](const pwb::domain::Json& value) {
        return value.is_string();
    };
    if (!header.contains("shape") || !header["shape"].is_array()
        || header["shape"].size() != 3
        || !header["shape"][0].is_number()
        || !header["shape"][1].is_number()
        || !header["shape"][2].is_number()
        || !header.contains("axes") || !header["axes"].is_array()
        || header["axes"].size() != 3
        || !is_string(header["axes"][0]) || !is_string(header["axes"][1])
        || !is_string(header["axes"][2])
        || header["axes"][0].get<std::string>() != "inline"
        || header["axes"][1].get<std::string>() != "crossline"
        || header["axes"][2].get<std::string>() != "sample"
        || !header.contains("layout")
        || !header["layout"].is_string()
        || header["layout"].get<std::string>() != "c-order-f32") {
        if (error != nullptr) *error = "unsupported payload layout";
        return std::nullopt;
    }

    // Every field access below is guarded: a malformed header must yield
    // nullopt + a diagnostic, never an exception (the inspector is the
    // fail-closed boundary in front of GUI slots).
    const auto is_number_array = [&header](const char* key) {
        if (!header.contains(key) || !header[key].is_array()
            || header[key].size() != 3) {
            return false;
        }
        for (const auto& value : header[key]) {
            if (!value.is_number()) {
                return false;
            }
        }
        return true;
    };
    if (!is_number_array("axis_starts") || !is_number_array("axis_steps")) {
        if (error != nullptr) *error = "unsupported payload layout";
        return std::nullopt;
    }
    if (header.contains("axis_units")
        && (!header["axis_units"].is_array()
            || header["axis_units"].size() != 3
            || !header["axis_units"][0].is_string()
            || !header["axis_units"][1].is_string()
            || !header["axis_units"][2].is_string())) {
        if (error != nullptr) *error = "unsupported payload layout";
        return std::nullopt;
    }

    PwbvolLayout layout;
    VolumeDescriptor& descriptor = layout.descriptor;
    descriptor.source = file;
    descriptor.storage = "pwbvol1";
    descriptor.ni = header["shape"][0].get<std::int64_t>();
    descriptor.nc = header["shape"][1].get<std::int64_t>();
    descriptor.ns = header["shape"][2].get<std::int64_t>();
    if (descriptor.ni <= 0 || descriptor.nc <= 0 || descriptor.ns <= 0) {
        if (error != nullptr) *error = "payload shape has a zero axis";
        return std::nullopt;
    }
    descriptor.iline_start = header["axis_starts"][0].get<double>();
    descriptor.xline_start = header["axis_starts"][1].get<double>();
    descriptor.sample_start = header["axis_starts"][2].get<double>();
    descriptor.iline_step = header["axis_steps"][0].get<double>();
    descriptor.xline_step = header["axis_steps"][1].get<double>();
    descriptor.sample_step = header["axis_steps"][2].get<double>();
    // A zero/non-finite step would poison downstream physical-coordinate
    // math (origin + index*step); the writers never emit one, so refuse.
    for (const double step : {descriptor.iline_step, descriptor.xline_step,
                              descriptor.sample_step}) {
        if (!(step > 0.0) || !std::isfinite(step)) {
            if (error != nullptr) *error = "payload has a degenerate axis step";
            return std::nullopt;
        }
    }
    if (header.contains("axis_units")) {
        descriptor.sample_unit = header["axis_units"][2].get<std::string>();
    }
    descriptor.sample_domain = domain_from_unit(descriptor.sample_unit);
    descriptor.byte_order = std::endian::little;
    descriptor.geometry_source = "pwbvol1-header";
    descriptor.payload_offset_bytes = 8u + 4u + header_size;
    descriptor.file_size_bytes = static_cast<std::uint64_t>(size);
    // Overflow-checked expected size (#1456): the axis product is checked
    // BEFORE any comparison — the old code multiplied three uint64 (each
    // axis capped only at 2^31, so the product could reach 2^93), compared
    // the already-wrapped value and let hostile headers through.
    constexpr std::uint64_t kMaxElements =
        (std::numeric_limits<std::uint64_t>::max() - 12u) / 4u;
    const auto elements = checked::shape_product(
        descriptor.ni, descriptor.nc, descriptor.ns);
    if (descriptor.ni > (1LL << 31) || descriptor.nc > (1LL << 31)
        || descriptor.ns > (1LL << 31) || !elements.has_value()
        || *elements > kMaxElements) {
        if (error != nullptr) *error = "payload shape overflows";
        return std::nullopt;
    }
    const auto payload_bytes = checked::mul(*elements, 4u);
    const auto expected = payload_bytes.has_value()
        ? checked::add(8u + 4u + header_size, *payload_bytes)
        : std::optional<std::uint64_t>{};
    if (!expected.has_value()
        || static_cast<std::uint64_t>(size) < *expected) {
        if (error != nullptr) {
            *error = !expected.has_value()
                ? "payload shape overflows"
                : "payload shorter than the declared shape: file has "
                  + std::to_string(size) + " bytes, header needs "
                  + std::to_string(*expected);
        }
        return std::nullopt;
    }
    return layout;
}

std::size_t read_pwbvol_window(const PwbvolLayout& layout,
                               const WindowSpec& window, std::span<float> out,
                               const CancelFlag& cancel, std::string* error) {
    const VolumeDescriptor& descriptor = layout.descriptor;
    if (out.size() != static_cast<std::size_t>(window.elements())) {
        if (error != nullptr) {
            *error = "output span size " + std::to_string(out.size())
                + " != window extent " + std::to_string(window.elements());
        }
        return 0;
    }
    if (!window_in_bounds(descriptor, window)) {
        if (error != nullptr) *error = "window out of bounds";
        return 0;
    }
    std::ifstream input(descriptor.source, std::ios::binary);
    if (!input.good()) {
        if (error != nullptr) {
            *error = "cannot open file: " + descriptor.source.string();
        }
        return 0;
    }
    const std::int64_t nc = descriptor.nc;
    const std::int64_t ns = descriptor.ns;
    const std::int64_t t0 = window.origin[2];
    const std::int64_t nt = window.extent[2];
    std::vector<unsigned char> raw(static_cast<std::size_t>(nt) * 4);
    std::size_t written = 0;
    for (std::int64_t il = window.origin[0];
         il < window.origin[0] + window.extent[0]; ++il) {
        for (std::int64_t xl = window.origin[1];
             xl < window.origin[1] + window.extent[1]; ++xl) {
            if (cancel.cancelled()) {
                if (error != nullptr) *error = "cancelled";
                return 0;
            }
            // Offset chain in checked uint64 (#1456): the old
            // `il * nc + xl` was a bare signed multiply, and every product
            // fed a streamoff cast that is only safe below int64 range.
            // Rows come back in index order, so the byte bound below also
            // proves `written + nt <= out.size()` for every row copy.
            const auto trace_offset = [&]() -> std::optional<std::uint64_t> {
                const auto row =
                    checked::mul(static_cast<std::uint64_t>(il),
                                 static_cast<std::uint64_t>(nc));
                if (!row.has_value()) return std::nullopt;
                const auto row_xl =
                    checked::add(*row, static_cast<std::uint64_t>(xl));
                if (!row_xl.has_value()) return std::nullopt;
                const auto samples = checked::mul(
                    *row_xl, static_cast<std::uint64_t>(ns));
                if (!samples.has_value()) return std::nullopt;
                const auto sample_index =
                    checked::add(*samples, static_cast<std::uint64_t>(t0));
                if (!sample_index.has_value()) return std::nullopt;
                const auto bytes = checked::mul(*sample_index, 4u);
                if (!bytes.has_value()) return std::nullopt;
                return checked::add(descriptor.payload_offset_bytes,
                                    *bytes);
            }();
            if (!trace_offset.has_value()
                || *trace_offset > descriptor.file_size_bytes
                || *trace_offset + raw.size()
                       > descriptor.file_size_bytes) {
                if (error != nullptr) {
                    *error = "payload offset out of range";
                }
                return 0;
            }
            const std::uint64_t offset = *trace_offset;
            input.seekg(static_cast<std::streamoff>(offset),
                        std::ios::beg);
            input.read(reinterpret_cast<char*>(raw.data()),
                       static_cast<std::streamsize>(raw.size()));
            if (!input.good()) {
                if (error != nullptr) *error = "payload samples unreadable";
                return 0;
            }
            // raw.size() == nt*4 was sized from the validated window, and
            // written advances by exactly nt per row of extent[0]*extent[1]
            // rows — both provably within out.size() == window.elements().
            float* dst = out.data() + written;
            if constexpr (std::endian::native == std::endian::little) {
                std::memcpy(dst, raw.data(), raw.size());
            } else {
                for (std::int64_t t = 0; t < nt; ++t) {
                    dst[t] = le_f32(&raw[static_cast<std::size_t>(t) * 4]);
                }
            }
            written += static_cast<std::size_t>(nt);
        }
    }
    return written;
}

}  // namespace pwb::seismic_io
