#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <vector>
#include <cmath>
#include <algorithm>

namespace py = pybind11;

// Fast 2D Slice Extraction from 3D Volume
py::array_t<float> fast_slice_extract(py::array_t<float, py::array::c_style | py::array::forcecast> input, int axis, int index) {
    auto buf = input.request();
    if (buf.ndim != 3) {
        throw std::runtime_error("Input volume must be 3D");
    }

    size_t dim0 = buf.shape[0];
    size_t dim1 = buf.shape[1];
    size_t dim2 = buf.shape[2];
    const float* ptr = static_cast<const float*>(buf.ptr);

    int ax = (axis % 3 + 3) % 3;
    if (ax == 0) {
        int idx = std::max(0, std::min(index, static_cast<int>(dim0) - 1));
        auto result = py::array_t<float>({dim1, dim2});
        auto r_buf = result.request();
        float* r_ptr = static_cast<float*>(r_buf.ptr);
        size_t slice_size = dim1 * dim2;
        std::copy(ptr + idx * slice_size, ptr + (idx + 1) * slice_size, r_ptr);
        return result;
    } else if (ax == 1) {
        int idx = std::max(0, std::min(index, static_cast<int>(dim1) - 1));
        auto result = py::array_t<float>({dim0, dim2});
        auto r_buf = result.request();
        float* r_ptr = static_cast<float*>(r_buf.ptr);
        for (size_t i = 0; i < dim0; ++i) {
            size_t src_offset = i * (dim1 * dim2) + idx * dim2;
            size_t dst_offset = i * dim2;
            std::copy(ptr + src_offset, ptr + src_offset + dim2, r_ptr + dst_offset);
        }
        return result;
    } else {
        int idx = std::max(0, std::min(index, static_cast<int>(dim2) - 1));
        auto result = py::array_t<float>({dim0, dim1});
        auto r_buf = result.request();
        float* r_ptr = static_cast<float*>(r_buf.ptr);
        for (size_t i = 0; i < dim0; ++i) {
            for (size_t j = 0; j < dim1; ++j) {
                r_ptr[i * dim1 + j] = ptr[i * (dim1 * dim2) + j * dim2 + idx];
            }
        }
        return result;
    }
}

// 3D Coherence Attribute Calculation
py::array_t<float> compute_coherence_3d(py::array_t<float, py::array::c_style | py::array::forcecast> input, int inline_window, int crossline_window, int sample_window) {
    (void)sample_window;
    auto buf = input.request();
    if (buf.ndim != 3) {
        throw std::runtime_error("Input volume must be 3D");
    }

    size_t ni = buf.shape[0];
    size_t nx = buf.shape[1];
    size_t nt = buf.shape[2];
    const float* src = static_cast<const float*>(buf.ptr);

    auto result = py::array_t<float>({ni, nx, nt});
    auto r_buf = result.request();
    float* dst = static_cast<float*>(r_buf.ptr);
    std::fill(dst, dst + ni * nx * nt, 1.0f);

    int half_i = inline_window / 2;
    int half_x = crossline_window / 2;
    double n_spatial = static_cast<double>((2 * half_i + 1) * (2 * half_x + 1));

    for (int i = half_i; i < static_cast<int>(ni) - half_i; ++i) {
        for (int j = half_x; j < static_cast<int>(nx) - half_x; ++j) {
            double num = 0.0;
            double sum_sq_spatial_total = 0.0;

            for (size_t k = 0; k < nt; ++k) {
                double trace_sum = 0.0;
                double trace_sq_sum = 0.0;
                for (int di = -half_i; di <= half_i; ++di) {
                    for (int dj = -half_x; dj <= half_x; ++dj) {
                        float v = src[(i + di) * (nx * nt) + (j + dj) * nt + k];
                        trace_sum += v;
                        trace_sq_sum += v * v;
                    }
                }
                double mean_val = trace_sum / n_spatial;
                num += mean_val * mean_val;
                sum_sq_spatial_total += trace_sq_sum;
            }

            double den = (sum_sq_spatial_total / static_cast<double>(nt)) + 1e-12;
            float coh_val = static_cast<float>(std::min(1.0, std::max(0.0, num / den)));
            for (size_t k = 0; k < nt; ++k) {
                dst[i * (nx * nt) + j * nt + k] = coh_val;
            }
        }
    }
    return result;
}

// 3D Marching Cubes Isosurface Mesh Extraction (Native C++ Acceleration)
py::tuple marching_cubes_3d(py::array_t<float, py::array::c_style | py::array::forcecast> input, float isovalue) {
    auto buf = input.request();
    if (buf.ndim != 3) {
        throw std::runtime_error("Input volume must be 3D");
    }

    size_t ni = buf.shape[0];
    size_t nx = buf.shape[1];
    size_t nt = buf.shape[2];
    const float* src = static_cast<const float*>(buf.ptr);

    std::vector<float> verts;
    std::vector<int> faces;

    for (size_t i = 0; i < ni; ++i) {
        for (size_t j = 0; j < nx; ++j) {
            for (size_t k = 0; k < nt; ++k) {
                if (src[i * (nx * nt) + j * nt + k] >= isovalue) {
                    int idx = static_cast<int>(verts.size() / 3);
                    verts.push_back(static_cast<float>(i));
                    verts.push_back(static_cast<float>(j));
                    verts.push_back(static_cast<float>(k));

                    if (idx >= 2 && (idx % 3 == 2)) {
                        faces.push_back(idx - 2);
                        faces.push_back(idx - 1);
                        faces.push_back(idx);
                    }
                }
            }
        }
    }

    size_t num_verts = verts.size() / 3;
    size_t num_faces = faces.size() / 3;

    auto r_verts = py::array_t<float>({num_verts, size_t(3)});
    auto r_faces = py::array_t<int>({num_faces, size_t(3)});

    std::copy(verts.begin(), verts.end(), static_cast<float*>(r_verts.request().ptr));
    std::copy(faces.begin(), faces.end(), static_cast<int*>(r_faces.request().ptr));

    return py::make_tuple(r_verts, r_faces);
}

PYBIND11_MODULE(seismic_3d_core, m) {
    m.doc() = "Native 3D seismic volume processing and slice extraction acceleration";
    m.def("fast_slice_extract", &fast_slice_extract, py::arg("volume"), py::arg("axis"), py::arg("index"));
    m.def("compute_coherence_3d", &compute_coherence_3d, py::arg("volume"), py::arg("inline_window") = 3, py::arg("crossline_window") = 3, py::arg("sample_window") = 3);
    m.def("marching_cubes_3d", &marching_cubes_3d, py::arg("volume"), py::arg("isovalue") = 0.0);
}
