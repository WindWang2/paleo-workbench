#pragma once

// VIZ-C joint scene bridges: the tiled seismic service volume exposed as a
// joint IVolumeAccess, plus the mesh builders that turn joint-scene data
// (well trajectories, fence extraction, active time slice) into geo3d_viz
// SceneObjects. Pure composition code — no window state. Threading
// reality (review B): the open job inspects metadata only; every
// read_slice for a joint volume runs on the GUI thread, making the GUI
// the single reader for the volume's lifetime (the tiled backend's
// single-reader discipline in spirit; its tile cache is independently
// thread-safe).

#include <array>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

#include <pwb/geo3d_viz/joint/fence.hpp>
#include <pwb/geo3d_viz/joint/joint_scene.hpp>
#include <pwb/geo3d_viz/joint/volume_access.hpp>
#include <pwb/viz/seismic_volume.hpp>

namespace pwb::app::viz_c {

// ISeismicVolume (tiled service backend) → joint IVolumeAccess. All
// reads go through read_slice on the caller's thread; the caller owns
// the single-reader discipline (the platform routes them through the
// JobCenter background worker). No full-cube copy: one slice plane is
// materialised per call, served from the service's byte-budget tile
// cache.
class TiledVolumeAccess final : public pwb::geo3d_viz::joint::IVolumeAccess {
public:
    TiledVolumeAccess(std::shared_ptr<pwb::viz::ISeismicVolume> volume,
                      std::shared_ptr<const void> lifetime);

    std::array<std::int64_t, 3> shape() const override;
    std::vector<float> slice_inline(std::int64_t il_index) const override;
    std::vector<float> slice_crossline(
        std::int64_t xl_index) const override;
    std::vector<float> slice_time(std::int64_t sample_index) const override;

private:
    std::shared_ptr<pwb::viz::ISeismicVolume> volume_;
    std::shared_ptr<const void> lifetime_;
};

// Curtain mesh from a fence extraction: quads between consecutive
// along-fence samples over the (downsampled) sample axis. Vertices are
// built in world space (fence XY + domain z) then mapped through the
// scene's world→render transform — exactly the space the joint scene
// renders in. Returns vertices/faces/face colors ready for a SceneObject.
struct CurtainMesh {
    std::vector<std::array<float, 3>> vertices;
    std::vector<std::array<std::int64_t, 3>> faces;
    std::vector<std::array<float, 4>> face_colors;
    bool empty() const { return faces.empty(); }
};

// Downsample targets for mesh assembly (medium-data budget; the strip
// itself stays full-resolution in the FenceExtraction cache).
inline constexpr std::int64_t kCurtainMaxAlong = 64;
inline constexpr std::int64_t kCurtainMaxSample = 64;
inline constexpr std::int64_t kSliceMaxEdge = 96;

CurtainMesh build_fence_curtain(
    const pwb::geo3d_viz::joint::WellSeismicScene& scene,
    const pwb::geo3d_viz::joint::FenceExtraction& extraction,
    const std::string& seismic_color_scale);

struct SliceMesh {
    std::vector<std::array<float, 3>> vertices;
    std::vector<std::array<std::int64_t, 3>> faces;
    std::vector<std::array<float, 4>> face_colors;
    bool empty() const { return faces.empty(); }
};

// Active time-slice plane: the colorized amplitude slice at the active
// sample index, positioned in render space (vi, vx, vt).
SliceMesh build_active_time_slice(
    const pwb::geo3d_viz::joint::WellSeismicScene& scene,
    const std::string& seismic_color_scale);

// Well trajectories as render-space polylines (world XY + domain z
// through the scene transform).
std::vector<std::array<float, 3>> build_well_polyline(
    const pwb::geo3d_viz::joint::WellSeismicScene& scene,
    const std::vector<std::array<double, 3>>& world_points);

}  // namespace pwb::app::viz_c
