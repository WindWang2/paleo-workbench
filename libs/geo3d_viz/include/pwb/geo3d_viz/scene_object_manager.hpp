#pragma once

// pwb::geo3d_viz — named scene-object registry (CONV-GEO3D).
//
// C++ port of geo-viz-engine geoviz_seismic/scene_objects.py:
// SceneObjectManager (add/remove/clear/visibility/opacity/color/pickable/
// clip_planes/bounds/pick) plus the pure math helpers ray_triangles_first_hit
// / ray_segments_closest / screen_point_to_ray (matrix math supplied by
// orbit_camera.hpp). The registry is GL-less by design: it is the scene
// state authority, and the Qt widget renders from it (the Python
// "renderer absent → graceful no-op" contract degrades to "no widget
// attached" here by construction).
//
// Qt-free, Python-free, numpy-free.

#include <array>
#include <cstdint>
#include <functional>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

#include <pwb/geo3d_viz/scene_types.hpp>

namespace pwb::geo3d_viz {

// One named overlay/actor object (scene_objects.SceneObject + payload).
struct SceneObject {
    std::string name;
    ObjectKind kind = ObjectKind::Generic;
    ObjectMode mode = ObjectMode::Mesh;

    // float32 engine-space geometry; lines use line strips (line_mode).
    std::vector<Vec3f> verts;
    std::vector<std::array<std::int64_t, 3>> faces;  // mesh only
    bool line_strip = true;  // lines: true = GL_LINE_STRIP, false = segments

    Rgba color{0.85f, 0.85f, 0.9f, 1.0f};
    // Per-face colors (volume facies); when set, rendering is flat.
    std::vector<Rgba> face_colors;
    bool smooth = true;

    bool pickable = false;
    float pick_radius = 0.0f;   // engine-unit click tolerance (lines mode)
    float width = 1.0f;         // line width
    float size = 1.0f;          // point size
    std::string text;           // text mode label

    bool visible = true;
    float opacity = 1.0f;
    std::optional<std::vector<ClipEquation>> clip_planes;

    // Bounds (min, max) over finite verts; nullopt when empty (matches
    // SceneObject.bounds returning None for empty vert sets).
    std::optional<std::pair<std::array<double, 3>, std::array<double, 3>>> bounds() const;
};

// ---------------------------------------------------------------------------
// pick math (scene_objects.py pure helpers, Möller–Trumbore + clamped sweeps)
// ---------------------------------------------------------------------------

// Nearest ray-triangle hit; (distance, face_index) or nullopt. Degenerate
// triangles are skipped; epsilon bias matches the Python (-1e-9, +1e-9).
std::optional<std::pair<double, std::int64_t>> ray_triangles_first_hit(
    const std::array<double, 3>& origin, const std::array<double, 3>& direction,
    const std::vector<Vec3f>& verts,
    const std::vector<std::array<std::int64_t, 3>>& faces,
    std::optional<double> max_distance = std::nullopt);

// Nearest ray-to-polyline hit within pick_radius; (ray_distance, segment
// index) or nullopt (two clamped closest-point sweeps, like the Python).
std::optional<std::pair<double, std::int64_t>> ray_segments_closest(
    const std::array<double, 3>& origin, const std::array<double, 3>& direction,
    const std::vector<Vec3f>& verts, double pick_radius,
    std::optional<double> max_distance = std::nullopt);

// Unproject a widget-space point into a world ray given column-major 4x4
// view/projection matrices (row-major nested arrays, OpenGL memory order).
// Mirrors screen_point_to_ray: NDC y is flipped between widget and NDC and
// the ray spans the NDC near/far planes. Returns nullopt for degenerate
// viewports / non-invertible matrices.
struct Ray {
    std::array<double, 3> origin;
    std::array<double, 3> direction;  // unit length
};
using Mat4 = std::array<float, 16>;  // column-major, QMatrix4x4::constData()
std::optional<Ray> screen_point_to_ray(double px, double py, double width,
                                       double height, const Mat4& view,
                                       const Mat4& projection);

// ---------------------------------------------------------------------------
// SceneObjectManager — the GL-less registry (scene_objects.SceneObjectManager)
// ---------------------------------------------------------------------------

class SceneObjectManager {
public:
    // Payload validation with the Python SceneObjectError texts.
    // add: replaces any existing object of the same name (replace semantics
    // per name — the adapter relies on remove-then-add ordering).
    const SceneObject& add(SceneObject object);
    bool remove(const std::string& name);
    int clear(const std::optional<ObjectKind>& kind = std::nullopt);
    bool has(const std::string& name) const;
    const SceneObject* get(const std::string& name) const;

    std::vector<std::string> names(
        const std::optional<ObjectKind>& kind = std::nullopt) const;
    std::size_t count(const std::optional<ObjectKind>& kind = std::nullopt) const;

    void set_visibility(const std::string& name, bool visible);
    void set_opacity(const std::string& name, float opacity);   // clamped 0..1
    void set_color(const std::string& name, const Rgba& color);
    void set_pickable(const std::string& name, bool pickable);
    void set_clip_planes(const std::string& name,
                         const std::optional<std::vector<ClipEquation>>& planes);

    // objects_bounds(kinds, visible_only): union bounds or nullopt when no
    // contributing object has bounds (Python returns None).
    std::optional<std::pair<std::array<double, 3>, std::array<double, 3>>> bounds(
        const std::vector<ObjectKind>& kinds = {},
        bool visible_only = true) const;

    // Screen-space pick over visible + pickable objects; nearest hit wins
    // (meshes by ray-t, lines by ray distance within pick_radius). kinds
    // filter: empty = all kinds.
    std::optional<PickHit> pick(const Ray& ray,
                                const std::vector<ObjectKind>& kinds = {}) const;

    // Mutation revision — the widget caches GL buffers per object and
    // rebuilds when this counter moves (lifecycle-safe, no GL handles here).
    std::uint64_t revision() const { return revision_; }

private:
    static void validate_mesh_arrays(SceneObject& object);
    static void validate_clip_planes(SceneObject& object);

    std::unordered_map<std::string, SceneObject> objects_;
    std::vector<std::string> order_;  // insertion order for names()
    std::uint64_t revision_ = 0;
    void touch() { ++revision_; }
};

}  // namespace pwb::geo3d_viz
