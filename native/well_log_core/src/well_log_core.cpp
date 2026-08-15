#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <pybind11/stl.h>
#include <vector>
#include <string>
#include <sstream>
#include <cmath>
#include <cerrno>
#include <cstdlib>
#include <cctype>
#include <limits>
#include <algorithm>

// Floating-point std::from_chars needs GCC 11+ / Clang 14+ even though
// __cpp_lib_to_chars >= 201611L only guarantees the integer overloads.
#if defined(__cpp_lib_to_chars) && __cpp_lib_to_chars >= 201611L && \
    (defined(__clang__) ? (__clang_major__ >= 14) : (defined(__GNUC__) ? (__GNUC__ >= 11) : true))
#include <charconv>
#define WL_HAS_FROM_CHARS_DOUBLE 1
#else
#define WL_HAS_FROM_CHARS_DOUBLE 0
#endif

namespace py = pybind11;

// Min-Max 4-Point LOD Downsampling Algorithm for 60 FPS Well Log Rendering
py::tuple minmax_downsample(
    py::array_t<float, py::array::c_style | py::array::forcecast> depth,
    py::array_t<float, py::array::c_style | py::array::forcecast> values,
    int target_pixels
) {
    auto d_buf = depth.request();
    auto v_buf = values.request();

    // Validate shapes (cpp-core-review C4): n_pts was taken from depth only and
    // v_ptr[j] read for j<n_pts with no check that values matches length ->
    // OOB read when len(values)<len(depth). Also no ndim check: a 0-d array
    // made d_buf.shape[0] UB and a 2-d array was silently mis-flattened.
    if (d_buf.ndim != 1 || v_buf.ndim != 1) {
        throw std::invalid_argument("depth and values must be 1-D arrays");
    }
    if (d_buf.shape[0] != v_buf.shape[0]) {
        throw std::invalid_argument(
            "depth and values must have the same length (got " +
            std::to_string(d_buf.shape[0]) + " and " + std::to_string(v_buf.shape[0]) + ")");
    }
    // Validate target_pixels (cpp-core-review I5): <=0 gave n_pts/0 -> UB,
    // and *2 overflowed int for large values.
    if (target_pixels <= 0) {
        throw std::invalid_argument("target_pixels must be positive (got " + std::to_string(target_pixels) + ")");
    }
    if (target_pixels > (std::numeric_limits<int>::max)() / 2) {
        throw std::invalid_argument("target_pixels too large (would overflow)");
    }

    size_t n_pts = d_buf.shape[0];
    const float* d_ptr = static_cast<const float*>(d_buf.ptr);
    const float* v_ptr = static_cast<const float*>(v_buf.ptr);

    if (n_pts <= static_cast<size_t>(target_pixels) * 2) {
        auto r_d = py::array_t<float>(n_pts);
        auto r_v = py::array_t<float>(n_pts);
        std::copy(d_ptr, d_ptr + n_pts, static_cast<float*>(r_d.request().ptr));
        std::copy(v_ptr, v_ptr + n_pts, static_cast<float*>(r_v.request().ptr));
        return py::make_tuple(r_d, r_v);
    }

    size_t bin_size = std::max<size_t>(1, static_cast<size_t>(std::ceil(static_cast<double>(n_pts) / target_pixels)));

    std::vector<float> out_d;
    std::vector<float> out_v;
    out_d.reserve(static_cast<size_t>(target_pixels) * 2);
    out_v.reserve(static_cast<size_t>(target_pixels) * 2);

    {
        py::gil_scoped_release release;
        for (size_t i = 0; i < n_pts; i += bin_size) {
            size_t end = std::min(n_pts, i + bin_size);
            // NaN policy (cpp-core-review M7): initialise min/max from the
            // first FINITE value in the bucket and skip NaNs/Infs in the scan.
            // Previously a leading NaN survived as both min and max and was
            // emitted (silent garbage in the LOD output).
            size_t min_idx = i;
            size_t max_idx = i;
            float min_val = std::numeric_limits<float>::quiet_NaN();
            float max_val = std::numeric_limits<float>::quiet_NaN();
            bool bucket_finite = false;
            for (size_t j = i; j < end; ++j) {
                float val = v_ptr[j];
                if (std::isnan(val) || std::isinf(val)) continue;  // M7 + M9
                if (!bucket_finite) {
                    min_val = val;
                    max_val = val;
                    min_idx = j;
                    max_idx = j;
                    bucket_finite = true;
                    continue;
                }
                if (val < min_val) {
                    min_val = val;
                    min_idx = j;
                }
                if (val > max_val) {
                    max_val = val;
                    max_idx = j;
                }
            }
            if (!bucket_finite) {
                // All-NaN/Inf bucket: emit NaN depth+value to preserve row
                // structure (a gap in the curve), rather than dropping it.
                out_d.push_back(d_ptr[i]);
                out_v.push_back(std::numeric_limits<float>::quiet_NaN());
                continue;
            }

            if (min_idx <= max_idx) {
                out_d.push_back(d_ptr[min_idx]);
                out_v.push_back(v_ptr[min_idx]);
                if (min_idx != max_idx) {
                    out_d.push_back(d_ptr[max_idx]);
                    out_v.push_back(v_ptr[max_idx]);
                }
            } else {
                out_d.push_back(d_ptr[max_idx]);
                out_v.push_back(v_ptr[max_idx]);
                out_d.push_back(d_ptr[min_idx]);
                out_v.push_back(v_ptr[min_idx]);
            }
        }
    }

    size_t out_len = out_d.size();
    auto r_d = py::array_t<float>(out_len);
    auto r_v = py::array_t<float>(out_len);

    std::copy(out_d.begin(), out_d.end(), static_cast<float*>(r_d.request().ptr));
    std::copy(out_v.begin(), out_v.end(), static_cast<float*>(r_v.request().ptr));

    return py::make_tuple(r_d, r_v);
}

// Fast LAS ASCII Data Parser
namespace {

inline bool wl_is_space(char c) {
    // Matches the whitespace set used by istringstream tokenization so
    // trailing '\r' on CRLF files is treated as a separator, not a token.
    return c == ' ' || c == '\t' || c == '\r' || c == '\n' || c == '\v' || c == '\f';
}

struct WlToken {
    double value;
    const char* next;  // one past the whitespace-delimited token
};

// Parses one whitespace-delimited token. Mirrors the original
// istringstream >> token + std::stod semantics: non-numeric tokens and
// out-of-range conversions (std::stod throws) both yield NaN.
inline WlToken wl_parse_token(const char* p, const char* end) {
    const char* tok_end = p;
    while (tok_end < end && !wl_is_space(*tok_end)) ++tok_end;
    const double nan = std::numeric_limits<double>::quiet_NaN();
    double val = 0.0;
    bool ok = false;
#if WL_HAS_FROM_CHARS_DOUBLE
    auto res = std::from_chars(p, tok_end, val);
    if (res.ec == std::errc()) {
        ok = true;
    } else if (res.ec == std::errc::result_out_of_range) {
        return {nan, tok_end};  // stod throws out_of_range -> NaN
    }
    // invalid_argument: fall through to strtod, which also accepts
    // leading '+' and inf/nan spellings that from_chars rejects.
#endif
    if (!ok) {
        errno = 0;
        char* next = nullptr;
        val = std::strtod(p, &next);
        if (next == p || next > tok_end || errno == ERANGE) {
            val = nan;
        }
    }
    // strtod accepts "inf"/"infinity" spellings (from_chars does not), and
    // those leak infinite values into the output array (cpp-core-review M9).
    // Map any Inf to NaN so downstream curves see a gap, not infinity.
    if (std::isinf(val)) {
        val = nan;
    }
    return {val, tok_end};
}

}  // namespace

py::tuple fast_las_parse_data(const std::string& content, double null_value = -999.0) {
    const double nan = std::numeric_limits<double>::quiet_NaN();
    std::vector<std::string> headers;
    std::vector<std::string> curve_mnemonics;  // authoritative columns from ~CURVE
    std::vector<double> values;       // flat row-major buffer
    std::vector<size_t> row_widths;   // values per row (short rows pad to num_cols with NaN)

    {
        py::gil_scoped_release release;
        bool in_data = false;
        bool in_curve_info = false;
        const char* base = content.data();
        const size_t n = content.size();
        size_t pos = 0;
        while (pos < n) {
            size_t line_end = pos;
            while (line_end < n && base[line_end] != '\n') ++line_end;
            size_t begin = pos;
            pos = line_end + 1;

            while (begin < line_end && wl_is_space(base[begin])) ++begin;
            if (begin >= line_end) continue;

            const char first = base[begin];
            if (first == '#') continue;

            if (first == '~' && begin + 1 < line_end) {
                const char section = static_cast<char>(std::tolower(static_cast<unsigned char>(base[begin + 1])));
                if (section == 'c') {
                    // ~CURVE block: the authoritative curve list. Mnemonics
                    // become the column headers (CWLS ~C section).
                    in_curve_info = true;
                    in_data = false;
                    continue;
                }
                if (section == 'a') {
                    // Start of the data section. Inline tokens are only
                    // treated as column headers when separated from `~A` by
                    // whitespace (`~A DEPT GR DEN`); a directly-attached suffix
                    // is part of the section name (`~Ascii` must not yield
                    // "scii"). Per CWLS the trailing words of `~A` (e.g.
                    // "~A LOG DATA") are a title, not headers, so the ~CURVE
                    // mnemonics win whenever the file declares a ~CURVE block.
                    in_data = true;
                    in_curve_info = false;
                    std::vector<std::string> inline_headers;
                    if (begin + 2 < line_end &&
                        (base[begin + 2] == ' ' || base[begin + 2] == '\t')) {
                        std::istringstream h_stream(content.substr(begin + 2, line_end - (begin + 2)));
                        std::string token;
                        while (h_stream >> token) {
                            inline_headers.push_back(token);
                        }
                    }
                    if (!curve_mnemonics.empty()) {
                        headers = curve_mnemonics;
                    } else {
                        headers = std::move(inline_headers);
                    }
                    continue;
                }
                in_curve_info = false;
                continue;
            }

            if (in_curve_info) {
                std::istringstream c_stream(content.substr(begin, line_end - begin));
                std::string token;
                if (c_stream >> token) {
                    // "MNEM.UNIT : DESCRIPTION" -> mnemonic up to the first dot.
                    const size_t dot = token.find('.');
                    curve_mnemonics.push_back(dot == std::string::npos ? token : token.substr(0, dot));
                }
                continue;
            }

            if (in_data) {
                const char* p = base + begin;
                const char* end = base + line_end;
                const size_t row_start = values.size();
                while (p < end) {
                    while (p < end && wl_is_space(*p)) ++p;
                    if (p >= end) break;
                    WlToken tok = wl_parse_token(p, end);
                    double val = tok.value;
                    // Null masking (cpp-core-review I4): only mask the value
                    // that equals null_value. The previous hard-coded
                    // `val <= -999.0` silently NaN'd legitimate measurements
                    // (e.g. -1000.0, -999.25) even when the caller passed a
                    // different null_value — silent data corruption that the
                    // default null_value=-999.0 hid from tests.
                    if (std::isnan(val) || std::isinf(val) || val == null_value) {
                        val = nan;
                    }
                    values.push_back(val);
                    p = tok.next;
                }
                if (values.size() > row_start) {
                    row_widths.push_back(values.size() - row_start);
                }
            }
        }
    }

    const size_t num_rows = row_widths.size();
    const size_t num_cols = headers.empty() ? (num_rows > 0 ? row_widths[0] : 0) : headers.size();

    auto result = py::array_t<double>({num_rows, num_cols});
    double* ptr = static_cast<double*>(result.request().ptr);

    const double* src = values.data();
    size_t truncated_rows = 0;  // cpp-core-review M8: surface dropped columns
    for (size_t r = 0; r < num_rows; ++r) {
        const size_t width = row_widths[r];
        double* dst = ptr + r * num_cols;
        const size_t copy = std::min(width, num_cols);
        for (size_t c = 0; c < copy; ++c) dst[c] = src[c];
        for (size_t c = copy; c < num_cols; ++c) dst[c] = nan;
        if (width > num_cols) ++truncated_rows;
        src += width;
    }

    // Surface long-row truncation (M8): previously extra columns vanished
    // silently. py::warn requires the GIL, which is held again here.
    if (truncated_rows > 0 && !headers.empty()) {
        if (PyErr_WarnEx(
                PyExc_UserWarning,
                ("LAS data has " + std::to_string(truncated_rows) + " row(s) with more "
                 "columns than the " + std::to_string(num_cols) + " declared header(s); "
                 "extra columns were truncated").c_str(),
                1) < 0) {
            // Warning escalated to error (-W error): a Python exception is now
            // set. Returning a value with a pending exception would surface as
            // a bogus SystemError, so propagate the real error (audit I11).
            throw py::error_already_set();
        }
    }

    py::tuple py_headers(headers.size());
    for (size_t i = 0; i < headers.size(); ++i) {
        py_headers[i] = py::str(headers[i]);
    }

    return py::make_tuple(py_headers, result);
}

PYBIND11_MODULE(well_log_core, m) {
    m.doc() = "Native well log curve processing, LOD downsampling and fast LAS parsing acceleration";
    m.def("minmax_downsample", &minmax_downsample, py::arg("depth"), py::arg("values"), py::arg("target_pixels") = 1000);
    m.def("fast_las_parse_data", &fast_las_parse_data, py::arg("content"), py::arg("null_value") = -999.0);
}
