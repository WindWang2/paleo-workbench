#include <pwb/seismic_viewer/isosurface_core.hpp>

#include <array>
#include <cmath>

namespace pwb::seismic_viewer::isosurface {
namespace {

constexpr std::array<std::array<int, 4>, 6> kTets{{
    {0, 1, 3, 7},
    {0, 1, 5, 7},
    {0, 4, 5, 7},
    {0, 4, 6, 7},
    {0, 2, 6, 7},
    {0, 2, 3, 7},
}};
constexpr std::array<std::array<int, 2>, 6> kTetEdges{{
    {0, 1},
    {0, 2},
    {0, 3},
    {1, 2},
    {1, 3},
    {2, 3},
}};

} // namespace

IsosurfaceMesh extract_isosurface(std::span<const float> volume, std::int64_t n_i,
                                  std::int64_t n_x, std::int64_t n_s, float isovalue) {
    IsosurfaceMesh mesh;
    if (volume.size() != static_cast<std::size_t>(n_i * n_x * n_s) || n_i < 2 ||
        n_x < 2 || n_s < 2) {
        return mesh;
    }
    // Grid points exactly on the isovalue are nudged inside (native oracle:
    // eps = 1e-3 * (|iso| + 1)); classification stays consistent across
    // neighbouring cubes.
    const float eps = 1e-3f * (std::fabs(isovalue) + 1.0f);
    const auto at = [&](std::int64_t i, std::int64_t x, std::int64_t s) -> float {
        return volume[(static_cast<std::size_t>(i) * static_cast<std::size_t>(n_x) +
                       static_cast<std::size_t>(x)) *
                          static_cast<std::size_t>(n_s) +
                      static_cast<std::size_t>(s)];
    };

    for (std::int64_t i = 0; i + 1 < n_i; ++i) {
        for (std::int64_t j = 0; j + 1 < n_x; ++j) {
            for (std::int64_t k = 0; k + 1 < n_s; ++k) {
                float cv[8];
                float cp[8][3];
                bool cube_has_nan = false;
                for (int c = 0; c < 8; ++c) {
                    const std::int64_t ci = i + (c & 1);
                    const std::int64_t cj = j + ((c >> 1) & 1);
                    const std::int64_t ck = k + ((c >> 2) & 1);
                    const float v = at(ci, cj, ck);
                    // A cube touching missing data is skipped: the surface
                    // has a hole where data is missing rather than NaN
                    // vertices poisoning neighbours (native oracle I2/I5).
                    if (!std::isfinite(v)) {
                        cube_has_nan = true;
                        break;
                    }
                    cv[c] = v;
                    if (cv[c] == isovalue) {
                        cv[c] = isovalue + eps;
                    }
                    cp[c][0] = static_cast<float>(ci);
                    cp[c][1] = static_cast<float>(cj);
                    cp[c][2] = static_cast<float>(ck);
                }
                if (cube_has_nan) {
                    continue;
                }
                int cube_mask = 0;
                for (int c = 0; c < 8; ++c) {
                    if (cv[c] >= isovalue) {
                        cube_mask |= (1 << c);
                    }
                }
                if (cube_mask == 0 || cube_mask == 0xFF) {
                    continue;
                }

                for (const auto& tet : kTets) {
                    int tmask = 0;
                    for (int c = 0; c < 4; ++c) {
                        if (cube_mask & (1 << tet[c])) {
                            tmask |= (1 << c);
                        }
                    }
                    if (tmask == 0 || tmask == 0xF) {
                        continue;
                    }

                    float pt[6][3];
                    bool cut[6] = {};
                    for (int e = 0; e < 6; ++e) {
                        const int a = kTetEdges[e][0];
                        const int b = kTetEdges[e][1];
                        const bool ina = (tmask >> a) & 1;
                        const bool inb = (tmask >> b) & 1;
                        if (ina == inb) {
                            continue;
                        }
                        const int ca = tet[a];
                        const int cb = tet[b];
                        const float t = (isovalue - cv[ca]) / (cv[cb] - cv[ca]);
                        for (int d = 0; d < 3; ++d) {
                            pt[e][d] = cp[ca][d] + t * (cp[cb][d] - cp[ca][d]);
                        }
                        cut[e] = true;
                    }

                    float ctr_inside[3] = {0.0f, 0.0f, 0.0f};
                    int n_inside = 0;
                    for (int c = 0; c < 4; ++c) {
                        if ((tmask >> c) & 1) {
                            ++n_inside;
                            for (int d = 0; d < 3; ++d) {
                                ctr_inside[d] += cp[tet[c]][d];
                            }
                        }
                    }
                    for (int d = 0; d < 3; ++d) {
                        ctr_inside[d] /= static_cast<float>(n_inside);
                    }

                    int tri_src[4];
                    int nq = 0;
                    if (n_inside == 2) {
                        int ins[2], out[2];
                        int n_in = 0, n_out = 0;
                        for (int c = 0; c < 4; ++c) {
                            if ((tmask >> c) & 1) {
                                ins[n_in++] = c;
                            } else {
                                out[n_out++] = c;
                            }
                        }
                        const auto edge_idx = [](int x, int y) {
                            for (int e = 0; e < 6; ++e) {
                                if ((kTetEdges[e][0] == x && kTetEdges[e][1] == y) ||
                                    (kTetEdges[e][0] == y && kTetEdges[e][1] == x)) {
                                    return e;
                                }
                            }
                            return -1;
                        };
                        tri_src[0] = edge_idx(ins[0], out[0]);
                        tri_src[1] = edge_idx(ins[0], out[1]);
                        tri_src[2] = edge_idx(ins[1], out[1]);
                        tri_src[3] = edge_idx(ins[1], out[0]);
                        nq = 4;
                    } else {
                        for (int e = 0; e < 6 && nq < 3; ++e) {
                            if (cut[e]) {
                                tri_src[nq++] = e;
                            }
                        }
                    }

                    const int n_tris = (nq == 4) ? 2 : 1;
                    for (int t = 0; t < n_tris; ++t) {
                        const int i0 = tri_src[(t == 0) ? 0 : 0];
                        const int i1 = tri_src[(t == 0) ? 1 : 2];
                        const int i2 = tri_src[(t == 0) ? 2 : 3];
                        const float* v0 = pt[i0];
                        const float* v1 = pt[i1];
                        const float* v2 = pt[i2];
                        const float e1[3] = {v1[0] - v0[0], v1[1] - v0[1], v1[2] - v0[2]};
                        const float e2[3] = {v2[0] - v0[0], v2[1] - v0[1], v2[2] - v0[2]};
                        const float nrm[3] = {
                            e1[1] * e2[2] - e1[2] * e2[1],
                            e1[2] * e2[0] - e1[0] * e2[2],
                            e1[0] * e2[1] - e1[1] * e2[0],
                        };
                        const float ctr[3] = {
                            (v0[0] + v1[0] + v2[0]) / 3.0f - ctr_inside[0],
                            (v0[1] + v1[1] + v2[1]) / 3.0f - ctr_inside[1],
                            (v0[2] + v1[2] + v2[2]) / 3.0f - ctr_inside[2],
                        };
                        const auto base = static_cast<std::int32_t>(mesh.verts.size() / 3);
                        if (nrm[0] * ctr[0] + nrm[1] * ctr[1] + nrm[2] * ctr[2] < 0.0f) {
                            mesh.faces.push_back(base);
                            mesh.faces.push_back(base + 2);
                            mesh.faces.push_back(base + 1);
                        } else {
                            mesh.faces.push_back(base);
                            mesh.faces.push_back(base + 1);
                            mesh.faces.push_back(base + 2);
                        }
                        for (int d = 0; d < 3; ++d) {
                            mesh.verts.push_back(v0[d]);
                        }
                        for (int d = 0; d < 3; ++d) {
                            mesh.verts.push_back(v1[d]);
                        }
                        for (int d = 0; d < 3; ++d) {
                            mesh.verts.push_back(v2[d]);
                        }
                    }
                }
            }
        }
    }
    return mesh;
}

} // namespace pwb::seismic_viewer::isosurface
