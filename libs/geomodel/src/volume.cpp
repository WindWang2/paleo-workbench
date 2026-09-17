#include <pwb/geomodel/volume.hpp>

#include <cmath>
#include <stdexcept>
#include <string>

namespace pwb::geomodel {

namespace {

double divergence_theorem_mesh_volume(const std::vector<Vec3>& top_verts,
                                      const std::vector<Vec3>& bot_verts,
                                      std::size_t rows, std::size_t cols) {
    const std::size_t n = rows * cols;
    // Python: v_total = vstack([top, bot]).astype(float64) — accumulation
    // in float64 (float32 cross products cancel catastrophically at
    // UTM-scale coordinates).
    auto vertex = [&](std::size_t index) -> const Vec3& {
        return index < n ? top_verts[index] : bot_verts[index - n];
    };

    std::vector<double> signed_vols;
    signed_vols.reserve(2 * (rows - 1) * (cols - 1) +
                        2 * (2 * (rows - 1) + 2 * (cols - 1)));
    auto emit = [&](std::size_t i0, std::size_t i1, std::size_t i2) {
        const Vec3& p0 = vertex(i0);
        const Vec3& p1 = vertex(i1);
        const Vec3& p2 = vertex(i2);
        const double c0 = p1[1] * p2[2] - p1[2] * p2[1];
        const double c1 = p1[2] * p2[0] - p1[0] * p2[2];
        const double c2 = p1[0] * p2[1] - p1[1] * p2[0];
        signed_vols.push_back((p0[0] * c0 + p0[1] * c1 + p0[2] * c2) / 6.0);
    };

    // 1. top surface triangles (CCW, normal up)
    for (std::size_t r = 0; r + 1 < rows; ++r) {
        for (std::size_t c = 0; c + 1 < cols; ++c) {
            const std::size_t i0 = r * cols + c;
            const std::size_t i1 = r * cols + (c + 1);
            const std::size_t i2 = (r + 1) * cols + c;
            const std::size_t i3 = (r + 1) * cols + (c + 1);
            emit(i0, i1, i2);
            emit(i1, i3, i2);
        }
    }
    // 2. bottom surface triangles (CW, normal down)
    for (std::size_t r = 0; r + 1 < rows; ++r) {
        for (std::size_t c = 0; c + 1 < cols; ++c) {
            const std::size_t i0 = n + (r * cols + c);
            const std::size_t i1 = n + (r * cols + (c + 1));
            const std::size_t i2 = n + ((r + 1) * cols + c);
            const std::size_t i3 = n + ((r + 1) * cols + (c + 1));
            emit(i0, i2, i1);
            emit(i1, i2, i3);
        }
    }
    // 3. side-wall boundary strips
    for (std::size_t c = 0; c + 1 < cols; ++c) {  // top boundary (r = 0)
        const std::size_t t0 = c, t1 = c + 1;
        const std::size_t b0 = n + c, b1 = n + c + 1;
        emit(t0, b0, t1);
        emit(t1, b0, b1);
    }
    for (std::size_t c = 0; c + 1 < cols; ++c) {  // bottom (r = rows-1)
        const std::size_t t0 = (rows - 1) * cols + c;
        const std::size_t t1 = (rows - 1) * cols + c + 1;
        const std::size_t b0 = n + t0, b1 = n + t1;
        emit(t0, t1, b0);
        emit(t1, b1, b0);
    }
    for (std::size_t r = 0; r + 1 < rows; ++r) {  // left (c = 0)
        const std::size_t t0 = r * cols, t1 = (r + 1) * cols;
        const std::size_t b0 = n + t0, b1 = n + t1;
        emit(t0, t1, b0);
        emit(t1, b1, b0);
    }
    for (std::size_t r = 0; r + 1 < rows; ++r) {  // right (c = cols-1)
        const std::size_t t0 = r * cols + (cols - 1);
        const std::size_t t1 = (r + 1) * cols + (cols - 1);
        const std::size_t b0 = n + t0, b1 = n + t1;
        emit(t0, b0, t1);
        emit(t1, b0, b1);
    }

    double total = 0.0;
    for (const double v : signed_vols) {
        total += v;
    }
    return std::fabs(total);
}

}  // namespace

double closed_mesh_volume(const std::vector<Vec3>& top_vertices,
                          const std::vector<Vec3>& bot_vertices,
                          std::size_t rows, std::size_t cols) {
    if (top_vertices.size() != bot_vertices.size()) {
        throw std::invalid_argument(
            "top_vertices and bot_vertices must have matching (N, 3) shape");
    }
    const std::size_t n_pts = top_vertices.size();
    if (rows * cols != n_pts) {
        throw std::invalid_argument(
            "grid_shape (" + std::to_string(rows) + ", " +
            std::to_string(cols) + ") does not match total vertices " +
            std::to_string(n_pts));
    }
    return divergence_theorem_mesh_volume(top_vertices, bot_vertices, rows,
                                          cols);
}

}  // namespace pwb::geomodel
