#include <pwb/viz_charts/fence.hpp>

#include <cmath>

namespace pwb::viz_charts {

FenceMesh generate_fence_mesh(const std::vector<FenceWell>& wells,
                              int nz_samples) {
    FenceMesh mesh;
    if (wells.size() < 2) {
        return mesh;
    }
    const auto nz = static_cast<std::size_t>(nz_samples);

    std::size_t vert_offset = 0;
    for (std::size_t w_idx = 0; w_idx + 1 < wells.size(); ++w_idx) {
        const FenceWell& w1 = wells[w_idx];
        const FenceWell& w2 = wells[w_idx + 1];

        // z_left / z_right: linspace(0, -depth, nz) as float32.
        std::vector<float> z_left(nz), z_right(nz);
        for (std::size_t k = 0; k < nz; ++k) {
            if (nz == 1) {
                z_left[k] = 0.0f;
                z_right[k] = 0.0f;
            } else {
                const double t = static_cast<double>(k) / (nz - 1);
                z_left[k] = static_cast<float>(t * (-w1.depth));
                z_right[k] = static_cast<float>(t * (-w2.depth));
            }
        }

        for (std::size_t k = 0; k < nz; ++k) {
            mesh.vertices.push_back(static_cast<float>(w1.x));
            mesh.vertices.push_back(static_cast<float>(w1.y));
            mesh.vertices.push_back(z_left[k]);
        }
        for (std::size_t k = 0; k < nz; ++k) {
            mesh.vertices.push_back(static_cast<float>(w2.x));
            mesh.vertices.push_back(static_cast<float>(w2.y));
            mesh.vertices.push_back(z_right[k]);
        }

        const double max_d = std::max(w1.depth, w2.depth);
        for (std::size_t k = 0; k + 1 < nz; ++k) {
            const auto idx_l1 = static_cast<std::int32_t>(vert_offset + k);
            const auto idx_l2 = static_cast<std::int32_t>(vert_offset + k + 1);
            const auto idx_r1 =
                static_cast<std::int32_t>(vert_offset + nz + k);
            const auto idx_r2 =
                static_cast<std::int32_t>(vert_offset + nz + k + 1);

            for (const auto idx : {idx_l1, idx_r1, idx_l2}) {
                mesh.faces.push_back(idx);
            }
            for (const auto idx : {idx_r1, idx_r2, idx_l2}) {
                mesh.faces.push_back(idx);
            }

            const double depth_ratio =
                std::fabs(static_cast<double>(z_left[k])) / std::max(max_d, 1.0);
            const float c[4] = {0.1f,
                                static_cast<float>(0.4 + 0.5 * (1 - depth_ratio)),
                                static_cast<float>(0.7 + 0.3 * depth_ratio), 0.75f};
            mesh.face_colors.insert(mesh.face_colors.end(), c, c + 4);
            mesh.face_colors.insert(mesh.face_colors.end(), c, c + 4);
        }
        vert_offset += 2 * nz;
    }
    return mesh;
}

std::vector<float> extract_seismic_slice(const std::vector<float>& seismic,
                                         int ni, int nx, int nz,
                                         const std::vector<FenceWell>& wells,
                                         int n_samples_per_segment) {
    std::vector<float> slice;
    if (wells.size() < 2 || ni <= 0 || nx <= 0 || nz <= 0 ||
        seismic.size() != static_cast<std::size_t>(ni) * nx * nz) {
        return slice;
    }
    std::vector<double> path_x, path_y;
    for (std::size_t i = 0; i + 1 < wells.size(); ++i) {
        const FenceWell& w1 = wells[i];
        const FenceWell& w2 = wells[i + 1];
        const auto n = static_cast<std::size_t>(n_samples_per_segment);
        for (std::size_t k = 0; k < n; ++k) {
            if (i > 0 && k == 0) {
                continue;  // later segments drop their first sample
            }
            const double t =
                n <= 1 ? 0.0 : static_cast<double>(k) / (n - 1);
            path_x.push_back(w1.x + t * (w2.x - w1.x));
            path_y.push_back(w1.y + t * (w2.y - w1.y));
        }
    }
    slice.resize(path_x.size() * static_cast<std::size_t>(nz), 0.0f);
    for (std::size_t p = 0; p < path_x.size(); ++p) {
        // int(np.clip(...)) truncates; values are already >= 0 after clip.
        const auto ix = static_cast<long long>(
            std::min(std::max(path_x[p], 0.0), double(ni - 1)));
        const auto iy = static_cast<long long>(
            std::min(std::max(path_y[p], 0.0), double(nx - 1)));
        for (int z = 0; z < nz; ++z) {
            const std::size_t src =
                (static_cast<std::size_t>(ix) * nx + static_cast<std::size_t>(iy)) *
                    nz +
                z;
            slice[static_cast<std::size_t>(z) * path_x.size() + p] = seismic[src];
        }
    }
    return slice;
}

}  // namespace pwb::viz_charts
