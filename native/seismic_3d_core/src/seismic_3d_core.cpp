#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <vector>
#include <cmath>
#include <algorithm>
#include <limits>

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
        {
            py::gil_scoped_release release;
            std::copy(ptr + idx * slice_size, ptr + (idx + 1) * slice_size, r_ptr);
        }
        return result;
    } else if (ax == 1) {
        int idx = std::max(0, std::min(index, static_cast<int>(dim1) - 1));
        auto result = py::array_t<float>({dim0, dim2});
        auto r_buf = result.request();
        float* r_ptr = static_cast<float*>(r_buf.ptr);
        {
            py::gil_scoped_release release;
            for (size_t i = 0; i < dim0; ++i) {
                size_t src_offset = i * (dim1 * dim2) + idx * dim2;
                size_t dst_offset = i * dim2;
                std::copy(ptr + src_offset, ptr + src_offset + dim2, r_ptr + dst_offset);
            }
        }
        return result;
    } else {
        int idx = std::max(0, std::min(index, static_cast<int>(dim2) - 1));
        auto result = py::array_t<float>({dim0, dim1});
        auto r_buf = result.request();
        float* r_ptr = static_cast<float*>(r_buf.ptr);
        {
            py::gil_scoped_release release;
            for (size_t i = 0; i < dim0; ++i) {
                for (size_t j = 0; j < dim1; ++j) {
                    r_ptr[i * dim1 + j] = ptr[i * (dim1 * dim2) + j * dim2 + idx];
                }
            }
        }
        return result;
    }
}

// Fast 2D Slice Extraction directly into normalized uint8 Indexed8 array
py::tuple fast_slice_to_indexed8(py::array_t<float, py::array::c_style | py::array::forcecast> input, int axis, int index) {
    py::array_t<float> raw_slice = fast_slice_extract(input, axis, index);
    auto buf = raw_slice.request();
    size_t rows = buf.shape[0];
    size_t cols = buf.shape[1];
    size_t total = rows * cols;
    const float* ptr = static_cast<const float*>(buf.ptr);

    float min_val = std::numeric_limits<float>::infinity();
    float max_val = -std::numeric_limits<float>::infinity();

    {
        py::gil_scoped_release release;
        for (size_t i = 0; i < total; ++i) {
            float v = ptr[i];
            if (std::isnan(v) || std::isinf(v)) continue;
            if (v < min_val) min_val = v;
            if (v > max_val) max_val = v;
        }
    }

    auto u8_result = py::array_t<uint8_t>({rows, cols});
    auto u8_buf = u8_result.request();
    uint8_t* dst = static_cast<uint8_t*>(u8_buf.ptr);

    if (min_val >= max_val || std::isinf(min_val) || std::isinf(max_val)) {
        std::fill(dst, dst + total, static_cast<uint8_t>(0));
        return py::make_tuple(u8_result, 0.0f, 0.0f);
    }

    float inv_range = 255.0f / (max_val - min_val);
    {
        py::gil_scoped_release release;
        for (size_t i = 0; i < total; ++i) {
            float v = ptr[i];
            if (std::isnan(v) || std::isinf(v)) {
                dst[i] = 0;
            } else {
                float norm = (v - min_val) * inv_range;
                dst[i] = static_cast<uint8_t>(std::max(0.0f, std::min(255.0f, norm)));
            }
        }
    }

    return py::make_tuple(u8_result, min_val, max_val);
}

// Fast 3D Volume Resampling
py::array_t<float> fast_resample_volume_3d(py::array_t<float, py::array::c_style | py::array::forcecast> input, py::tuple target_shape) {
    auto buf = input.request();
    if (buf.ndim != 3) {
        throw std::runtime_error("Input volume must be 3D");
    }

    size_t s0 = buf.shape[0];
    size_t s1 = buf.shape[1];
    size_t s2 = buf.shape[2];
    const float* src = static_cast<const float*>(buf.ptr);

    size_t t0 = target_shape[0].cast<size_t>();
    size_t t1 = target_shape[1].cast<size_t>();
    size_t t2 = target_shape[2].cast<size_t>();

    auto result = py::array_t<float>({t0, t1, t2});
    auto r_buf = result.request();
    float* dst = static_cast<float*>(r_buf.ptr);

    float step0 = static_cast<float>(s0) / static_cast<float>(std::max<size_t>(1, t0));
    float step1 = static_cast<float>(s1) / static_cast<float>(std::max<size_t>(1, t1));
    float step2 = static_cast<float>(s2) / static_cast<float>(std::max<size_t>(1, t2));

    {
        py::gil_scoped_release release;
        for (size_t i = 0; i < t0; ++i) {
            size_t src_i = std::min(s0 - 1, static_cast<size_t>(i * step0));
            for (size_t j = 0; j < t1; ++j) {
                size_t src_j = std::min(s1 - 1, static_cast<size_t>(j * step1));
                for (size_t k = 0; k < t2; ++k) {
                    size_t src_k = std::min(s2 - 1, static_cast<size_t>(k * step2));
                    dst[i * (t1 * t2) + j * t2 + k] = src[src_i * (s1 * s2) + src_j * s2 + src_k];
                }
            }
        }
    }

    return result;
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

    {
        py::gil_scoped_release release;
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
    }
    return result;
}

// 3D Isosurface Mesh Extraction via Marching Tetrahedra.
// Each cube is split into 6 tetrahedra around the body diagonal corner0->corner7.
// The face diagonals of this decomposition are consistent between axis-aligned
// neighbour cubes, so the resulting mesh is watertight by construction.
// Corner index layout: corner n -> offset (n&1, (n>>1)&1, (n>>2)&1).
py::tuple marching_cubes_3d(py::array_t<float, py::array::c_style | py::array::forcecast> input, float isovalue) {
    auto buf = input.request();
    if (buf.ndim != 3) {
        throw std::runtime_error("Input volume must be 3D");
    }

    size_t ni = buf.shape[0];
    size_t nx = buf.shape[1];
    size_t nt = buf.shape[2];
    const float* src = static_cast<const float*>(buf.ptr);

    // Grid points whose value equals the isovalue exactly would make cut edges
    // land exactly on corners, producing degenerate (zero-area) triangles and
    // non-manifold pinching (several triangle fans touching at one point).
    // Nudge such values slightly inside so every cut lands strictly inside an
    // edge; the shift (~1e-3) is far below any geometric tolerance.
    const float eps = 1e-3f * (std::fabs(isovalue) + 1.0f);

    static const int TETS[6][4] = {
        {0, 1, 3, 7}, {0, 1, 5, 7}, {0, 4, 5, 7},
        {0, 4, 6, 7}, {0, 2, 6, 7}, {0, 2, 3, 7},
    };
    static const int TET_EDGES[6][2] = {
        {0, 1}, {0, 2}, {0, 3}, {1, 2}, {1, 3}, {2, 3},
    };

    std::vector<float> verts;
    std::vector<int> faces;

    {
        py::gil_scoped_release release;
        for (size_t i = 0; i + 1 < ni; ++i) {
            for (size_t j = 0; j + 1 < nx; ++j) {
                for (size_t k = 0; k + 1 < nt; ++k) {
                    float cv[8];
                    float cp[8][3];
                    for (int c = 0; c < 8; ++c) {
                        size_t ci = i + (c & 1);
                        size_t cj = j + ((c >> 1) & 1);
                        size_t ck = k + ((c >> 2) & 1);
                        cv[c] = src[ci * (nx * nt) + cj * nt + ck];
                        if (cv[c] == isovalue) cv[c] = isovalue + eps;
                        cp[c][0] = static_cast<float>(ci);
                        cp[c][1] = static_cast<float>(cj);
                        cp[c][2] = static_cast<float>(ck);
                    }
                    int cube_mask = 0;
                    for (int c = 0; c < 8; ++c) {
                        if (cv[c] >= isovalue) cube_mask |= (1 << c);
                    }
                    if (cube_mask == 0 || cube_mask == 0xFF) continue;

                    for (const auto& tet : TETS) {
                        int tmask = 0;
                        for (int c = 0; c < 4; ++c) {
                            if (cube_mask & (1 << tet[c])) tmask |= (1 << c);
                        }
                        if (tmask == 0 || tmask == 0xF) continue;

                        // Interpolated intersection point per cut edge.
                        float pt[6][3];
                        bool cut[6] = {};
                        int n_cut = 0;
                        for (int e = 0; e < 6; ++e) {
                            int a = TET_EDGES[e][0];
                            int b = TET_EDGES[e][1];
                            bool ina = (tmask >> a) & 1;
                            bool inb = (tmask >> b) & 1;
                            if (ina == inb) continue;
                            int ca = tet[a], cb = tet[b];
                            float t = (isovalue - cv[ca]) / (cv[cb] - cv[ca]);
                            for (int d = 0; d < 3; ++d) {
                                pt[e][d] = cp[ca][d] + t * (cp[cb][d] - cp[ca][d]);
                            }
                            cut[e] = true;
                            ++n_cut;
                        }

                        // Centroid of inside corners (for outward orientation).
                        float ci[3] = {0.0f, 0.0f, 0.0f};
                        int n_inside = 0;
                        for (int c = 0; c < 4; ++c) {
                            if ((tmask >> c) & 1) {
                                ++n_inside;
                                for (int d = 0; d < 3; ++d) ci[d] += cp[tet[c]][d];
                            }
                        }
                        for (int d = 0; d < 3; ++d) ci[d] /= n_inside;

                        // Collect cut points in a deterministic order.
                        int tri_src[4];
                        int nq = 0;
                        if (n_inside == 2) {
                            // Quad: inside pair (a,b), outside pair (c,d) ->
                            // cycle p(a-c), p(a-d), p(b-d), p(b-c).
                            int ins[2], out[2], ni_ = 0, no_ = 0;
                            for (int c = 0; c < 4; ++c) {
                                if ((tmask >> c) & 1) ins[ni_++] = c; else out[no_++] = c;
                            }
                            auto edge_idx = [&](int x, int y) {
                                for (int e = 0; e < 6; ++e) {
                                    if ((TET_EDGES[e][0] == x && TET_EDGES[e][1] == y) ||
                                        (TET_EDGES[e][0] == y && TET_EDGES[e][1] == x)) return e;
                                }
                                return -1;
                            };
                            tri_src[0] = edge_idx(ins[0], out[0]);
                            tri_src[1] = edge_idx(ins[0], out[1]);
                            tri_src[2] = edge_idx(ins[1], out[1]);
                            tri_src[3] = edge_idx(ins[1], out[0]);
                            nq = 4;
                        } else {
                            // n_inside == 1 or 3: exactly 3 cut edges.
                            for (int e = 0; e < 6 && nq < 3; ++e) {
                                if (cut[e]) tri_src[nq++] = e;
                            }
                        }

                        int n_tris = (nq == 4) ? 2 : 1;
                        for (int t = 0; t < n_tris; ++t) {
                            int i0 = tri_src[(t == 0) ? 0 : 0];
                            int i1 = tri_src[(t == 0) ? 1 : 2];
                            int i2 = tri_src[(t == 0) ? 2 : 3];
                            float v0[3], v1[3], v2[3];
                            for (int d = 0; d < 3; ++d) {
                                v0[d] = pt[i0][d]; v1[d] = pt[i1][d]; v2[d] = pt[i2][d];
                            }
                            // Orient the normal away from the inside-centroid.
                            float e1[3] = {v1[0] - v0[0], v1[1] - v0[1], v1[2] - v0[2]};
                            float e2[3] = {v2[0] - v0[0], v2[1] - v0[1], v2[2] - v0[2]};
                            float nrm[3] = {
                                e1[1] * e2[2] - e1[2] * e2[1],
                                e1[2] * e2[0] - e1[0] * e2[2],
                                e1[0] * e2[1] - e1[1] * e2[0],
                            };
                            float ctr[3] = {(v0[0] + v1[0] + v2[0]) / 3.0f - ci[0],
                                            (v0[1] + v1[1] + v2[1]) / 3.0f - ci[1],
                                            (v0[2] + v1[2] + v2[2]) / 3.0f - ci[2]};
                            int base = static_cast<int>(verts.size() / 3);
                            if (nrm[0] * ctr[0] + nrm[1] * ctr[1] + nrm[2] * ctr[2] < 0.0f) {
                                faces.push_back(base);
                                faces.push_back(base + 2);
                                faces.push_back(base + 1);
                            } else {
                                faces.push_back(base);
                                faces.push_back(base + 1);
                                faces.push_back(base + 2);
                            }
                            for (int d = 0; d < 3; ++d) {
                                verts.push_back(v0[d]);
                            }
                            for (int d = 0; d < 3; ++d) {
                                verts.push_back(v1[d]);
                            }
                            for (int d = 0; d < 3; ++d) {
                                verts.push_back(v2[d]);
                            }
                        }
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
    m.def("fast_slice_to_indexed8", &fast_slice_to_indexed8, py::arg("volume"), py::arg("axis"), py::arg("index"));
    m.def("fast_resample_volume_3d", &fast_resample_volume_3d, py::arg("volume"), py::arg("target_shape"));
    m.def("compute_coherence_3d", &compute_coherence_3d, py::arg("volume"), py::arg("inline_window") = 3, py::arg("crossline_window") = 3, py::arg("sample_window") = 3);
    m.def("marching_cubes_3d", &marching_cubes_3d, py::arg("volume"), py::arg("isovalue") = 0.0);
}
