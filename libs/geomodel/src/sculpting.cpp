#include <pwb/geomodel/sculpting.hpp>

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <string>

namespace pwb::geomodel {

namespace {

// NEP-50 weak-scalar semantics: a python float folded into a float32 array
// op is cast to float first, then the arithmetic happens in float32.
float f32(double v) { return static_cast<float>(v); }

}  // namespace

SculptableHorizonMesh::SculptableHorizonMesh(
    const std::vector<SculptVertex>& vertices,
    std::optional<std::pair<int, int>> grid_shape)
    : vertices_(vertices), grid_shape_(std::move(grid_shape)) {}

void SculptableHorizonMesh::push_patch(SparseDeltaPatch patch) {
    undo_stack_.push_back(std::move(patch));
    redo_stack_.clear();
}

void SculptableHorizonMesh::sculpt_surface(double center_x, double center_y,
                                           double delta_z, double radius) {
    // A non-positive brush touches nothing (#897; ZeroDivisionError removed).
    if (radius <= 0.0) {
        return;
    }
    const float cx = f32(center_x);
    const float cy = f32(center_y);
    // dist = np.hypot(x - cx, y - cy), float32; within_mask = dist <= radius
    // with radius folded to float32.
    std::vector<std::size_t> indices;
    std::vector<float> dists;
    for (std::size_t i = 0; i < vertices_.size(); ++i) {
        const float dx = vertices_[i].x - cx;
        const float dy = vertices_[i].y - cy;
        const float dist = std::hypot(dx, dy);
        if (dist <= f32(radius)) {
            indices.push_back(i);
            dists.push_back(dist);
        }
    }
    if (indices.empty()) {
        return;
    }
    const double sigma = radius * 0.5;
    const double tail = std::exp(-((radius / sigma) * (radius / sigma)));
    const double denom = 1.0 - tail;
    SparseDeltaPatch patch;
    patch.indices = indices;
    patch.old_z.reserve(indices.size());
    patch.new_z.reserve(indices.size());
    for (std::size_t k = 0; k < indices.size(); ++k) {
        const float d = dists[k];
        // weights = (exp(-((d/sigma)^2)) - tail) / denom, all folding back
        // to float32 (numpy weak scalars).
        const float q = d / f32(sigma);
        const float w = (std::exp(-(q * q)) - f32(tail)) / f32(denom);
        SculptVertex& v = vertices_[indices[k]];
        patch.old_z.push_back(v.z);
        const float new_z = v.z + f32(delta_z) * w;
        v.z = new_z;
        patch.new_z.push_back(new_z);
    }
    push_patch(std::move(patch));
}

void SculptableHorizonMesh::set_heights(
    const std::vector<std::size_t>& flat_indices,
    const std::vector<float>& new_z) {
    if (flat_indices.empty()) {
        return;
    }
    if (new_z.size() != flat_indices.size()) {
        // numpy raises a broadcast error here; the text is environment-
        // specific, so this guard carries a plain C++ message (D14).
        throw std::invalid_argument(
            "set_heights: new_z size must match flat_indices");
    }
    SparseDeltaPatch patch;
    patch.indices = flat_indices;
    patch.old_z.reserve(flat_indices.size());
    patch.new_z.reserve(flat_indices.size());
    for (std::size_t k = 0; k < flat_indices.size(); ++k) {
        SculptVertex& v = vertices_[flat_indices[k]];
        patch.old_z.push_back(v.z);
        v.z = new_z[k];
        patch.new_z.push_back(new_z[k]);
    }
    push_patch(std::move(patch));
}

void SculptableHorizonMesh::smooth_anneal(int iterations) {
    if (!grid_shape_.has_value()) {
        throw std::invalid_argument(
            "grid_shape is required for smooth_anneal: vertex count alone "
            "cannot identify the (rows, cols) topology (N=36 is both 4x9 "
            "and 6x6)");
    }
    const int rows = grid_shape_->first;
    const int cols = grid_shape_->second;
    if (vertices_.size() !=
        static_cast<std::size_t>(rows) * static_cast<std::size_t>(cols)) {
        // numpy reshape error text, verbatim format.
        throw std::invalid_argument(
            "cannot reshape array of size " +
            std::to_string(vertices_.size()) + " into shape (" +
            std::to_string(rows) + "," + std::to_string(cols) + ")");
    }
    std::vector<float> grid(vertices_.size());
    for (std::size_t i = 0; i < vertices_.size(); ++i) {
        grid[i] = vertices_[i].z;
    }
    for (int it = 0; it < iterations; ++it) {
        // np.pad(grid, 1, mode="edge"); float32 left-associated sum exactly
        // like (A + B + C + D + E*4.0) / 8.0 on the numpy side.
        std::vector<float> smoothed(static_cast<std::size_t>(rows) * cols);
        auto padded = [&](int pi, int pj) {
            const int i = std::clamp(pi, 0, rows - 1);
            const int j = std::clamp(pj, 0, cols - 1);
            return grid[static_cast<std::size_t>(i) * cols + j];
        };
        for (int i = 0; i < rows; ++i) {
            for (int j = 0; j < cols; ++j) {
                const float a = padded(i - 1, j);  // padded[:-2, 1:-1]
                const float b = padded(i + 1, j);  // padded[2:, 1:-1]
                const float c = padded(i, j - 1);  // padded[1:-1, :-2]
                const float d = padded(i, j + 1);  // padded[1:-1, 2:]
                const float e = padded(i, j);
                smoothed[static_cast<std::size_t>(i) * cols + j] =
                    ((((a + b) + c) + d) + e * 4.0f) / 8.0f;
            }
        }
        grid = std::move(smoothed);
    }
    // Patch records only the vertices that actually moved (#846).
    SparseDeltaPatch patch;
    for (std::size_t i = 0; i < vertices_.size(); ++i) {
        if (grid[i] != vertices_[i].z) {
            patch.indices.push_back(i);
            patch.old_z.push_back(vertices_[i].z);
            patch.new_z.push_back(grid[i]);
        }
    }
    if (!patch.indices.empty()) {
        push_patch(std::move(patch));
    }
    for (std::size_t i = 0; i < vertices_.size(); ++i) {
        vertices_[i].z = grid[i];
    }
}

bool SculptableHorizonMesh::undo() {
    if (undo_stack_.empty()) {
        return false;
    }
    SparseDeltaPatch patch = std::move(undo_stack_.back());
    undo_stack_.pop_back();
    for (std::size_t k = 0; k < patch.indices.size(); ++k) {
        vertices_[patch.indices[k]].z = patch.old_z[k];
    }
    redo_stack_.push_back(std::move(patch));
    return true;
}

bool SculptableHorizonMesh::redo() {
    if (redo_stack_.empty()) {
        return false;
    }
    SparseDeltaPatch patch = std::move(redo_stack_.back());
    redo_stack_.pop_back();
    for (std::size_t k = 0; k < patch.indices.size(); ++k) {
        vertices_[patch.indices[k]].z = patch.new_z[k];
    }
    undo_stack_.push_back(std::move(patch));
    return true;
}

std::vector<SculptVertex> sculpt_surface_vertices(
    const std::vector<SculptVertex>& vertices, double center_x,
    double center_y, double delta_z, double radius) {
    SculptableHorizonMesh mesh(vertices);
    mesh.sculpt_surface(center_x, center_y, delta_z, radius);
    return mesh.vertices();
}

std::vector<float> smooth_anneal_grid(const std::vector<float>& z_grid,
                                      int rows, int cols, int iterations) {
    std::vector<SculptVertex> verts(static_cast<std::size_t>(rows) * cols);
    for (int i = 0; i < rows; ++i) {
        for (int j = 0; j < cols; ++j) {
            SculptVertex& v = verts[static_cast<std::size_t>(i) * cols + j];
            v.x = f32(j);
            v.y = f32(i);
            v.z = z_grid[static_cast<std::size_t>(i) * cols + j];
        }
    }
    SculptableHorizonMesh mesh(verts, std::make_pair(rows, cols));
    mesh.smooth_anneal(iterations);
    std::vector<float> out(verts.size());
    for (std::size_t i = 0; i < out.size(); ++i) {
        out[i] = mesh.vertices()[i].z;
    }
    return out;
}

}  // namespace pwb::geomodel
