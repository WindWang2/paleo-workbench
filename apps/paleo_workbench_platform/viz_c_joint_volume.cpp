// viz_c_joint_volume.cpp — tiled bridge + joint mesh builders.
#include "viz_c_joint_volume.hpp"

#include <algorithm>
#include <cmath>

#include <pwb/geo3d_viz/joint/color_scales.hpp>

namespace pwb::app::viz_c {

using pwb::geo3d_viz::joint::FenceExtraction;
using pwb::geo3d_viz::joint::WellSeismicScene;

TiledVolumeAccess::TiledVolumeAccess(
    std::shared_ptr<pwb::viz::ISeismicVolume> volume,
    std::shared_ptr<const void> lifetime)
    : volume_(std::move(volume)), lifetime_(std::move(lifetime)) {}

std::array<std::int64_t, 3> TiledVolumeAccess::shape() const {
    const auto& shape = volume_->geometry().shape;
    return {shape[0], shape[1], shape[2]};
}

std::vector<float> TiledVolumeAccess::slice_inline(
    std::int64_t il_index) const {
    const auto& shape = volume_->geometry().shape;
    std::vector<float> out(static_cast<std::size_t>(shape[1] * shape[2]),
                           0.0f);
    const std::size_t got = volume_->read_slice(
        pwb::viz::VolumeAxis::inline_, il_index, out);
    if (got != out.size()) {
        throw std::runtime_error("tiled inline slice read failed");
    }
    return out;
}

std::vector<float> TiledVolumeAccess::slice_crossline(
    std::int64_t xl_index) const {
    const auto& shape = volume_->geometry().shape;
    std::vector<float> out(static_cast<std::size_t>(shape[0] * shape[2]),
                           0.0f);
    const std::size_t got = volume_->read_slice(
        pwb::viz::VolumeAxis::crossline, xl_index, out);
    if (got != out.size()) {
        throw std::runtime_error("tiled crossline slice read failed");
    }
    return out;
}

std::vector<float> TiledVolumeAccess::slice_time(
    std::int64_t sample_index) const {
    const auto& shape = volume_->geometry().shape;
    std::vector<float> out(static_cast<std::size_t>(shape[0] * shape[1]),
                           0.0f);
    const std::size_t got = volume_->read_slice(
        pwb::viz::VolumeAxis::sample, sample_index, out);
    if (got != out.size()) {
        throw std::runtime_error("tiled time slice read failed");
    }
    return out;
}

namespace {

std::int64_t downsample_stride(std::int64_t n, std::int64_t cap) {
    if (n <= cap) return 1;
    return (n + cap - 1) / cap;
}

// Shared RGBA face color for a pair of amplitude rows.
std::array<float, 4> rgba_at(const std::vector<std::uint8_t>& rgba,
                             std::int64_t along, std::int64_t sample,
                             std::int64_t n_sample) {
    const std::size_t index =
        static_cast<std::size_t>(along * n_sample + sample);
    return {rgba[index * 4] / 255.0f, rgba[index * 4 + 1] / 255.0f,
            rgba[index * 4 + 2] / 255.0f, 1.0f};
}

}  // namespace

CurtainMesh build_fence_curtain(const WellSeismicScene& scene,
                                const FenceExtraction& extraction,
                                const std::string& seismic_color_scale) {
    CurtainMesh mesh;
    const std::int64_t n_along = extraction.n_along();
    const std::int64_t n_sample = extraction.n_sample();
    if (n_along < 2 || n_sample < 2) return mesh;

    // Along-fence XY positions from the arc-length axis (uniform
    // resample parity with sample_fence_polyline).
    const std::vector<std::array<double, 2>> fence_xy =
        [&] {
            // The extraction does not carry vertices; recover the fence
            // from the scene by id.
            const std::vector<pwb::geo3d_viz::joint::FenceSection> fences =
                scene.fences();
            for (const auto& fence : fences) {
                if (fence.id == extraction.fence_id) {
                    return pwb::geo3d_viz::joint::sample_fence_polyline(
                        fence.vertices_xy, n_along);
                }
            }
            return std::vector<std::array<double, 2>>{};
        }();
    if (fence_xy.size() != static_cast<std::size_t>(n_along)) return mesh;

    const std::int64_t stride_a = downsample_stride(n_along, kCurtainMaxAlong);
    const std::int64_t stride_s = downsample_stride(n_sample, kCurtainMaxSample);
    std::vector<std::int64_t> along_idx;
    for (std::int64_t a = 0; a < n_along; a += stride_a) {
        along_idx.push_back(a);
    }
    if (along_idx.back() != n_along - 1) along_idx.push_back(n_along - 1);
    std::vector<std::int64_t> sample_idx;
    for (std::int64_t s = 0; s < n_sample; s += stride_s) {
        sample_idx.push_back(s);
    }
    if (sample_idx.back() != n_sample - 1) sample_idx.push_back(n_sample - 1);

    // World-space vertices: (fence XY, sample axis value) mapped through
    // the scene transform into render space. The sample axis is already
    // in the active domain (ms or m); world_to_render expects domain z.
    std::vector<std::array<double, 3>> world;
    world.reserve(along_idx.size() * sample_idx.size());
    for (std::int64_t s : sample_idx) {
        for (std::int64_t a : along_idx) {
            world.push_back({fence_xy[static_cast<std::size_t>(a)][0],
                             fence_xy[static_cast<std::size_t>(a)][1],
                             extraction.sample_axis[static_cast<std::size_t>(s)]});
        }
    }
    const std::vector<std::array<double, 3>> render =
        scene.world_to_render_xyz_array(world);

    // Colorize the full-resolution strip once, then sample it.
    std::vector<float> strip(static_cast<std::size_t>(n_along * n_sample));
    for (std::size_t i = 0; i < strip.size(); ++i) {
        strip[i] = extraction.amplitude[i];
    }
    const std::vector<std::uint8_t> rgba = pwb::geo3d_viz::joint::colorize_amplitude(
        strip, seismic_color_scale);

    const std::int64_t cols = static_cast<std::int64_t>(along_idx.size());
    const std::int64_t rows = static_cast<std::int64_t>(sample_idx.size());
    mesh.vertices.reserve(render.size());
    for (const auto& v : render) {
        mesh.vertices.push_back({static_cast<float>(v[0]),
                                 static_cast<float>(v[1]),
                                 static_cast<float>(v[2])});
    }
    mesh.faces.reserve(static_cast<std::size_t>((cols - 1) * (rows - 1) * 2));
    mesh.face_colors.reserve(mesh.faces.capacity());
    for (std::int64_t r = 0; r + 1 < rows; ++r) {
        for (std::int64_t c = 0; c + 1 < cols; ++c) {
            const std::int64_t v00 = r * cols + c;
            const std::int64_t v01 = r * cols + c + 1;
            const std::int64_t v10 = (r + 1) * cols + c;
            const std::int64_t v11 = (r + 1) * cols + c + 1;
            mesh.faces.push_back({v00, v10, v11});
            mesh.faces.push_back({v00, v11, v01});
            const std::int64_t a_mid = along_idx[static_cast<std::size_t>(c)];
            const std::int64_t s_mid =
                (sample_idx[static_cast<std::size_t>(r)] +
                 sample_idx[static_cast<std::size_t>(r + 1)]) /
                2;
            const std::array<float, 4> color =
                rgba_at(rgba, a_mid, s_mid, n_sample);
            mesh.face_colors.push_back(color);
            mesh.face_colors.push_back(color);
        }
    }
    return mesh;
}

SliceMesh build_active_time_slice(const WellSeismicScene& scene,
                                  const std::string& seismic_color_scale) {
    SliceMesh mesh;
    const auto render_state = scene.orthogonal_slice_render_state();
    if (!render_state.has_value()) return mesh;
    const auto& [il, xl, times, active, opacity] = *render_state;
    (void)il;
    (void)xl;
    (void)times;
    const auto shape = scene.volume_access() != nullptr
                           ? scene.volume_access()->shape()
                           : std::array<std::int64_t, 3>{0, 0, 0};
    if (shape[0] < 2 || shape[1] < 2) return mesh;

    // Read + colorize on the caller's thread (the platform routes this
    // through the job worker before GUI assembly).
    const std::vector<float> plane = scene.slice_time(active);
    const std::vector<std::uint8_t> rgba =
        pwb::geo3d_viz::joint::colorize_amplitude(plane, seismic_color_scale);

    const std::int64_t stride_i = downsample_stride(shape[0], kSliceMaxEdge);
    const std::int64_t stride_x = downsample_stride(shape[1], kSliceMaxEdge);
    std::vector<std::int64_t> il_idx;
    for (std::int64_t i = 0; i < shape[0]; i += stride_i) il_idx.push_back(i);
    if (il_idx.back() != shape[0] - 1) il_idx.push_back(shape[0] - 1);
    std::vector<std::int64_t> xl_idx;
    for (std::int64_t x = 0; x < shape[1]; x += stride_x) xl_idx.push_back(x);
    if (xl_idx.back() != shape[1] - 1) xl_idx.push_back(shape[1] - 1);

    const std::int64_t rows = static_cast<std::int64_t>(il_idx.size());
    const std::int64_t cols = static_cast<std::int64_t>(xl_idx.size());
    mesh.vertices.reserve(static_cast<std::size_t>(rows * cols));
    for (std::int64_t r = 0; r < rows; ++r) {
        for (std::int64_t c = 0; c < cols; ++c) {
            mesh.vertices.push_back({static_cast<float>(il_idx[static_cast<std::size_t>(r)]),
                                     static_cast<float>(xl_idx[static_cast<std::size_t>(c)]),
                                     static_cast<float>(active)});
        }
    }
    mesh.faces.reserve(static_cast<std::size_t>((rows - 1) * (cols - 1) * 2));
    mesh.face_colors.reserve(mesh.faces.capacity());
    for (std::int64_t r = 0; r + 1 < rows; ++r) {
        for (std::int64_t c = 0; c + 1 < cols; ++c) {
            const std::int64_t v00 = r * cols + c;
            const std::int64_t v01 = r * cols + c + 1;
            const std::int64_t v10 = (r + 1) * cols + c;
            const std::int64_t v11 = (r + 1) * cols + c + 1;
            mesh.faces.push_back({v00, v10, v11});
            mesh.faces.push_back({v00, v11, v01});
            const std::int64_t i_mid = il_idx[static_cast<std::size_t>(r)];
            const std::int64_t x_mid = xl_idx[static_cast<std::size_t>(c)];
            const std::size_t color_index =
                static_cast<std::size_t>(i_mid * shape[1] + x_mid);
            const float alpha =
                static_cast<float>(std::max(0.0, std::min(1.0, opacity)));
            mesh.face_colors.push_back(
                {rgba[color_index * 4] / 255.0f,
                 rgba[color_index * 4 + 1] / 255.0f,
                 rgba[color_index * 4 + 2] / 255.0f, alpha});
            mesh.face_colors.push_back(
                {rgba[color_index * 4] / 255.0f,
                 rgba[color_index * 4 + 1] / 255.0f,
                 rgba[color_index * 4 + 2] / 255.0f, alpha});
        }
    }
    return mesh;
}

std::vector<std::array<float, 3>> build_well_polyline(
    const WellSeismicScene& scene,
    const std::vector<std::array<double, 3>>& world_points) {
    const std::vector<std::array<double, 3>> render =
        scene.world_to_render_xyz_array(world_points);
    std::vector<std::array<float, 3>> out;
    out.reserve(render.size());
    for (const auto& v : render) {
        out.push_back({static_cast<float>(v[0]), static_cast<float>(v[1]),
                       static_cast<float>(v[2])});
    }
    return out;
}

}  // namespace pwb::app::viz_c
