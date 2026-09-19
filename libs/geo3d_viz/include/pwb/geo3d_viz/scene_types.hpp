#pragma once

// pwb::geo3d_viz — native scene model types (CONV-GEO3D).
//
// C++ port of the named scene-object contract shared by
// geo-viz-engine/packages/geoviz_seismic/geoviz_seismic/scene_objects.py
// (modes/kinds/clip-plane limit/validation text) and
// paleo_workbench/viz/geomodel/scene_adapter.py (style constants, facies
// palette). The Python modules stay as the behavior oracle for this port;
// the C++ side is the product chain.
//
// Qt-free, Python-free, numpy-free.

#include <array>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

namespace pwb::geo3d_viz {

// Render-space vertex (float32, engine space — matches the Python payloads
// submitted to add_scene_object).
using Vec3f = std::array<float, 3>;
using Rgba = std::array<float, 4>;           // 0..1 RGBA, opacity folded in
using ClipEquation = std::array<double, 4>;  // (a, b, c, d): keep a*x+b*y+c*z <= d

// scene_objects.OBJECT_MODES — order frozen (registry + tests index it).
enum class ObjectMode { Mesh, Lines, Points, Text };

const char* object_mode_name(ObjectMode mode);
// Parse with the Python error text on unknown names (SceneObjectError).
ObjectMode object_mode_from_name(const std::string& name);

// scene_objects.OBJECT_KINDS — order frozen.
enum class ObjectKind { Generic, Well, Horizon, Fault, Volume, Annotation, Measurement };

const char* object_kind_name(ObjectKind kind);
ObjectKind object_kind_from_name(const std::string& name);

// scene_objects._MAX_CLIP_PLANES — fixed-function slots the fixed pipeline
// allowed; the modern-GL renderer keeps the same per-object ceiling.
inline constexpr std::size_t kMaxClipPlanes = 6;

// scene_objects.SceneObjectError — invalid scene-object payloads fail loud
// with the Python message text (host bugs must not degrade silently).
struct SceneObjectError : std::runtime_error {
    using std::runtime_error::runtime_error;
};

// scene_objects.PickHit — nearest ray hit on one named object.
struct PickHit {
    std::string name;
    std::string kind;
    std::array<double, 3> point{0.0, 0.0, 0.0};
    double distance = 0.0;
    std::int64_t face_index = -1;  // segment index for lines picks
};

// ---------------------------------------------------------------------------
// ObjectStyle — frozen defaults from scene_adapter.ObjectStyle (:50-65).
// ---------------------------------------------------------------------------

struct ObjectStyle {
    Rgba color{0.85f, 0.85f, 0.9f, 1.0f};
    float opacity = 1.0f;
    Rgba well_color{0.98f, 0.75f, 0.18f, 1.0f};
    float well_width = 3.0f;
    Rgba horizon_color{0.98f, 0.9f, 0.3f, 0.65f};
    Rgba fault_color{0.9f, 0.25f, 0.25f, 0.6f};
    Rgba volume_color{0.35f, 0.65f, 0.9f, 0.8f};
    Rgba tunnel_color{0.7f, 0.7f, 0.75f, 1.0f};
    Rgba measurement_color{0.2f, 0.95f, 0.6f, 1.0f};
    Rgba selected_color{0.3f, 1.0f, 1.0f, 1.0f};
    Rgba label_color{1.0f, 0.88f, 0.28f, 1.0f};
    bool show_well_labels = true;
};

// scene_adapter._FACIES_PALETTE (float32 rows, order frozen).
const std::vector<Rgba>& facies_palette();

// ---------------------------------------------------------------------------
// small shared helpers
// ---------------------------------------------------------------------------

// Point-in-half-space test for one clip equation (keep <= d half-space).
inline bool clipped_out(const ClipEquation& plane,
                        const std::array<double, 3>& p) {
    return plane[0] * p[0] + plane[1] * p[1] + plane[2] * p[2] > plane[3];
}

}  // namespace pwb::geo3d_viz
