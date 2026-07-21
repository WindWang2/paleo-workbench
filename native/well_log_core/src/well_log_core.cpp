#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <pybind11/stl.h>
#include <vector>
#include <string>
#include <sstream>
#include <cmath>
#include <algorithm>

namespace py = pybind11;

// Min-Max 4-Point LOD Downsampling Algorithm for 60 FPS Well Log Rendering
py::tuple minmax_downsample(
    py::array_t<float, py::array::c_style | py::array::forcecast> depth,
    py::array_t<float, py::array::c_style | py::array::forcecast> values,
    int target_pixels
) {
    auto d_buf = depth.request();
    auto v_buf = values.request();

    size_t n_pts = d_buf.shape[0];
    const float* d_ptr = static_cast<const float*>(d_buf.ptr);
    const float* v_ptr = static_cast<const float*>(v_buf.ptr);

    if (n_pts <= static_cast<size_t>(target_pixels * 2)) {
        auto r_d = py::array_t<float>(n_pts);
        auto r_v = py::array_t<float>(n_pts);
        std::copy(d_ptr, d_ptr + n_pts, static_cast<float*>(r_d.request().ptr));
        std::copy(v_ptr, v_ptr + n_pts, static_cast<float*>(r_v.request().ptr));
        return py::make_tuple(r_d, r_v);
    }

    size_t bin_size = std::max<size_t>(1, static_cast<size_t>(std::ceil(static_cast<double>(n_pts) / target_pixels)));

    std::vector<float> out_d;
    std::vector<float> out_v;
    out_d.reserve(target_pixels * 2);
    out_v.reserve(target_pixels * 2);

    {
        py::gil_scoped_release release;
        for (size_t i = 0; i < n_pts; i += bin_size) {
            size_t end = std::min(n_pts, i + bin_size);
            size_t min_idx = i;
            size_t max_idx = i;
            float min_val = v_ptr[i];
            float max_val = v_ptr[i];

            for (size_t j = i + 1; j < end; ++j) {
                float val = v_ptr[j];
                if (val < min_val) {
                    min_val = val;
                    min_idx = j;
                }
                if (val > max_val) {
                    max_val = val;
                    max_idx = j;
                }
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
py::tuple fast_las_parse_data(const std::string& content, double null_value = -999.0) {
    std::istringstream stream(content);
    std::string line;
    bool in_data = false;
    std::vector<std::string> headers;
    std::vector<std::vector<double>> rows;

    while (std::getline(stream, line)) {
        size_t start = line.find_first_not_of(" \t\r\n");
        if (start == std::string::npos) continue;
        std::string stripped = line.substr(start);

        if (stripped[0] == '#') continue;

        if (stripped.rfind("~A", 0) == 0 || stripped.rfind("~a", 0) == 0) {
            // Marks the start of the data section. Inline tokens are only
            // treated as column headers when separated from `~A` by
            // whitespace (`~A DEPT GR DEN`); a directly-attached suffix is
            // part of the section name (`~Ascii` must not yield "scii").
            in_data = true;
            headers.clear();
            if (stripped.size() > 2 && (stripped[2] == ' ' || stripped[2] == '\t')) {
                std::istringstream h_stream(stripped.substr(2));
                std::string token;
                while (h_stream >> token) {
                    headers.push_back(token);
                }
            }
            continue;
        }

        if (in_data) {
            std::istringstream d_stream(stripped);
            std::vector<double> row;
            std::string token;
            while (d_stream >> token) {
                try {
                    double val = std::stod(token);
                    if (std::isnan(val) || val <= -999.0 || val == null_value) {
                        row.push_back(std::numeric_limits<double>::quiet_NaN());
                    } else {
                        row.push_back(val);
                    }
                } catch (...) {
                    row.push_back(std::numeric_limits<double>::quiet_NaN());
                }
            }
            if (!row.empty()) {
                rows.push_back(row);
            }
        }
    }

    size_t num_rows = rows.size();
    size_t num_cols = headers.empty() ? (num_rows > 0 ? rows[0].size() : 0) : headers.size();

    auto result = py::array_t<double>({num_rows, num_cols});
    auto r_buf = result.request();
    double* ptr = static_cast<double*>(r_buf.ptr);

    for (size_t r = 0; r < num_rows; ++r) {
        for (size_t c = 0; c < num_cols; ++c) {
            if (c < rows[r].size()) {
                ptr[r * num_cols + c] = rows[r][c];
            } else {
                ptr[r * num_cols + c] = std::numeric_limits<double>::quiet_NaN();
            }
        }
    }

    py::tuple py_headers(headers.size());
    for (size_t i = 0; i < headers.size(); ++i) {
        py_headers[i] = py::str(headers[i]);
    }

    return py::make_tuple(py_headers, result);
}

// Crossover Fill Vertices Generator
py::tuple generate_crossover_fill(
    py::array_t<float, py::array::c_style | py::array::forcecast> depth,
    py::array_t<float, py::array::c_style | py::array::forcecast> curve_a,
    py::array_t<float, py::array::c_style | py::array::forcecast> curve_b
) {
    auto d_buf = depth.request();
    auto ca_buf = curve_a.request();
    auto cb_buf = curve_b.request();

    size_t n_pts = d_buf.shape[0];
    const float* d_ptr = static_cast<const float*>(d_buf.ptr);
    const float* ca_ptr = static_cast<const float*>(ca_buf.ptr);
    const float* cb_ptr = static_cast<const float*>(cb_buf.ptr);

    std::vector<float> poly_a_gt;
    std::vector<float> poly_b_gt;

    {
        py::gil_scoped_release release;
        for (size_t i = 0; i < n_pts; ++i) {
            if (ca_ptr[i] >= cb_ptr[i]) {
                poly_a_gt.push_back(ca_ptr[i]);
                poly_a_gt.push_back(d_ptr[i]);
            }
            if (cb_ptr[i] >= ca_ptr[i]) {
                poly_b_gt.push_back(cb_ptr[i]);
                poly_b_gt.push_back(d_ptr[i]);
            }
        }
    }

    size_t n_a = poly_a_gt.size() / 2;
    size_t n_b = poly_b_gt.size() / 2;

    auto r_a = py::array_t<float>({n_a, size_t(2)});
    auto r_b = py::array_t<float>({n_b, size_t(2)});

    std::copy(poly_a_gt.begin(), poly_a_gt.end(), static_cast<float*>(r_a.request().ptr));
    std::copy(poly_b_gt.begin(), poly_b_gt.end(), static_cast<float*>(r_b.request().ptr));

    return py::make_tuple(r_a, r_b);
}

PYBIND11_MODULE(well_log_core, m) {
    m.doc() = "Native well log curve processing, LOD downsampling and fast LAS parsing acceleration";
    m.def("minmax_downsample", &minmax_downsample, py::arg("depth"), py::arg("values"), py::arg("target_pixels") = 1000);
    m.def("fast_las_parse_data", &fast_las_parse_data, py::arg("content"), py::arg("null_value") = -999.0);
    m.def("generate_crossover_fill", &generate_crossover_fill, py::arg("depth"), py::arg("curve_a"), py::arg("curve_b"));
}
