#pragma once

// pwb::geomodel — interactive horizon sculpting kernel, a faithful C++ port
// of paleo_workbench/viz/horizon_sculpting.py (CONV-12). Frozen against
// tools/oracle/generate_geomodel_volume_fixtures.py:
//   * all mesh state is float32 (vertices.astype(np.float32) on the Python
//     side); scalar array arithmetic follows numpy NEP-50 weak-scalar
//     semantics (python floats fold back to float32);
//   * Gaussian brush weights are renormalized by the tail so they hit
//     EXACTLY zero at the rim (#846); radius <= 0 is a no-op (#897);
//   * smooth_anneal is the edge-padded (4-neighbor + 4*center)/8 laplacian,
//     evaluated in float32 with left-associated numpy operand order;
//   * undo patches record only the vertices that actually moved (float32
//     != comparison); sculpt/set_heights clear the redo stack.
// Qt-free, Python-free, numpy-free.

#include <array>
#include <cstddef>
#include <optional>
#include <utility>
#include <vector>

namespace pwb::geomodel {

struct SparseDeltaPatch {
    std::vector<std::size_t> indices;
    std::vector<float> old_z;
    std::vector<float> new_z;
};

struct SculptVertex {
    float x = 0.0f;
    float y = 0.0f;
    float z = 0.0f;
};

class SculptableHorizonMesh {
public:
    // vertices are stored as float32 like the Python astype(copy=True).
    explicit SculptableHorizonMesh(
        const std::vector<SculptVertex>& vertices,
        std::optional<std::pair<int, int>> grid_shape = std::nullopt);

    // Radial Gaussian brush; no-op (no patch) when radius <= 0 or no
    // vertex is within the radius.
    void sculpt_surface(double center_x, double center_y, double delta_z,
                        double radius = 5.0);

    // Single sanctioned mutation path for picked values; one undo patch.
    void set_heights(const std::vector<std::size_t>& flat_indices,
                     const std::vector<float>& new_z);

    // Laplacian smooth annealing; requires grid_shape (Python message).
    void smooth_anneal(int iterations = 1);

    bool can_undo() const { return !undo_stack_.empty(); }
    bool can_redo() const { return !redo_stack_.empty(); }
    bool undo();
    bool redo();

    const std::vector<SculptVertex>& vertices() const { return vertices_; }
    const std::vector<SparseDeltaPatch>& undo_patches() const {
        return undo_stack_;
    }

private:
    void push_patch(SparseDeltaPatch patch);

    std::vector<SculptVertex> vertices_;
    std::optional<std::pair<int, int>> grid_shape_;
    std::vector<SparseDeltaPatch> undo_stack_;
    std::vector<SparseDeltaPatch> redo_stack_;
};

// Stateless convenience wrapper mirroring HorizonSculpting.sculpt_surface:
// builds a temporary mesh and returns the sculpted vertices.
std::vector<SculptVertex> sculpt_surface_vertices(
    const std::vector<SculptVertex>& vertices, double center_x,
    double center_y, double delta_z, double radius = 5.0);

// Stateless smooth_anneal on a 2-D height grid (HorizonSculpting.
// smooth_anneal): builds the meshgrid vertex stack internally and returns
// the reshaped float32 z grid (row-major).
std::vector<float> smooth_anneal_grid(const std::vector<float>& z_grid,
                                      int rows, int cols, int iterations = 1);

}  // namespace pwb::geomodel
