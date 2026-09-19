#pragma once

// pwb::geo3d_viz — geological scene adapter (CONV-GEO3D).
//
// C++ port of paleo_workbench/viz/geomodel/scene_adapter.py: the single
// bridge between the pwb::geomodel domain model (CONV-22 ModelAssembly) and
// the native scene-object registry (SceneObjectManager).
//
//   ModelAssembly (authority)
//     → GeologicalSceneAdapter (transform + payload + diff)
//       → SceneObjectManager (named registry)
//         → Geo3DViewportWidget (rendering; GL-less safe by construction)
//
// Ported contracts (frozen against the Python oracle fixtures):
//   * content-addressed payload tokens: unchanged objects are never rebuilt;
//   * scene identity participates in every token (scene rebind ⇒ rebuild);
//   * per-kind payload shapes and derived naming ("<oid>", "<oid>#head",
//     "<oid>#label", "<oid>#line"), pick radius, widths and point sizes;
//   * horizon display decimation ceiling (≤512 per axis, NaN holes never
//     triangulated) reusing the already-frozen pwb::geomodel triangulation;
//   * facies per-face palette colors (flat shading);
//   * view state: visibility (clip replay on reveal), opacity clamp,
//     selection recolor without rebuild, overlay registration, ≤6 clip
//     planes applied to visible objects only;
//   * provider-null ⇒ every sync degrades to an empty report and records
//     no token (viewport teardown can never wedge the cache).
//
// The domain→render transform is a seam (SceneTransform): identity for pure
// geomodel scenes; a later well-seismic host installs its index/render
// mapping exactly like scene.world_to_render_xyz_array +
// widget.index_xyz_to_world do in Python.
//
// Qt-free, Python-free; consumes pwb::geomodel + pwb::domain::Json.

#include <array>
#include <functional>
#include <map>
#include <optional>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/geo3d_viz/scene_object_manager.hpp>
#include <pwb/geomodel/domain_contract.hpp>

namespace pwb::geo3d_viz {

// Display decimation ceiling per horizon axis (scene_adapter:49).
inline constexpr std::size_t kMaxHorizonDim = 512;

struct SceneSyncReport {
    std::vector<std::string> added;
    std::vector<std::string> updated;
    std::vector<std::string> removed;
    int unchanged = 0;

    std::size_t size() const {
        return added.size() + updated.size() + removed.size();
    }
    // "+a ~u -r =n" — the Python debug format.
    std::string to_string() const;
};

// A pick resolved back into domain space (scene_adapter.DomainPick).
struct DomainPick {
    std::string object_id;  // "#..." suffix stripped
    std::string kind;
    std::array<double, 3> domain_xyz{0.0, 0.0, 0.0};
    double distance = 0.0;
    bool has_xyz = true;  // false when the back-transform failed (NaN XYZ)
};

// Domain↔render coordinate seam. Identity by default; hosts replace both
// directions together (to_domain must invert to_render).
struct SceneTransform {
    std::function<std::vector<std::array<double, 3>>(
        const std::vector<std::array<double, 3>>& world)>
        to_render;
    std::function<std::vector<std::array<double, 3>>(
        const std::vector<std::array<double, 3>>& render)>
        to_domain;

    std::vector<std::array<double, 3>> forward(
        const std::vector<std::array<double, 3>>& world) const;
    std::vector<std::array<double, 3>> inverse(
        const std::vector<std::array<double, 3>>& render) const;
};

class GeologicalSceneAdapter {
public:
    using ManagerProvider = std::function<SceneObjectManager*()>;

    // provider returns the live manager (nullptr while torn down / GL-less
    // — mirrors the Python widget_provider contract).
    explicit GeologicalSceneAdapter(ManagerProvider provider,
                                    ObjectStyle styles = {});

    // Scene identity (e.g. "scene-0x7f...:depth"): a rebind changes every
    // payload token, forcing a rebuild even when domain objects are equal.
    void set_scene_identity(const std::string& identity) {
        scene_identity_ = identity;
    }
    const std::string& scene_identity() const { return scene_identity_; }

    // Coordinate seam (see SceneTransform).
    void set_scene_transform(SceneTransform transform);
    const SceneTransform& scene_transform() const { return transform_; }

    ObjectStyle& styles() { return styles_; }
    const ObjectStyle& styles() const { return styles_; }

    // ------------------------------------------------------------------
    // sync API
    // ------------------------------------------------------------------

    SceneSyncReport sync(const pwb::geomodel::ModelAssembly& assembly);

    // View-state snapshot for one object (save path): {"visible", "opacity"}.
    pwb::domain::Json display_state(const std::string& object_id) const;
    // Bulk restore of view state (clamped; tolerates malformed entries).
    void restore_display(const pwb::domain::Json& display);

    void shutdown();  // reset + release the provider (teardown-safe)
    void reset();     // drop every scene object + sync state (project switch)

    // ------------------------------------------------------------------
    // view state
    // ------------------------------------------------------------------

    void set_visibility(const std::string& object_id, bool visible);
    bool visibility(const std::string& object_id) const;
    void set_opacity(const std::string& object_id, double opacity);
    // Selection highlight: engine color update, not a payload rebuild.
    void set_selected(const std::optional<std::string>& object_id);
    const std::optional<std::string>& selected() const { return selected_; }

    // Current clip equations (read-only view for overlay owners).
    const std::optional<std::vector<ClipEquation>>& clip_planes() const {
        return clip_planes_;
    }
    void register_overlay(const std::string& key,
                          const std::vector<std::string>& names);
    void remove_overlay(const std::string& key);
    // Apply clip equations to every derived object and every registered
    // overlay; invisible objects are skipped (reapplied on reveal).
    void set_clip_planes(
        const std::optional<std::vector<ClipEquation>>& planes);

    // ------------------------------------------------------------------
    // picking
    // ------------------------------------------------------------------

    // Ray pick over the live manager, resolved back to domain coordinates.
    // kinds filter: empty = all. nullopt when nothing hit / no manager.
    std::optional<DomainPick> pick(
        const Ray& ray,
        const std::vector<ObjectKind>& kinds = {}) const;

    // Engine-space hit → domain-space pick ("#..." suffix stripped, inverse
    // transform applied). NaN domain_xyz (has_xyz=false) on back-transform
    // failure, mirroring the Python degraded-pick path.
    DomainPick resolve_pick(const PickHit& hit) const;

    // Base (non-selected) color for an object or derived name — the kind
    // prefix picks the frozen style entry ("#..." suffix stripped).
    Rgba base_color(const std::string& name_or_id) const;

    // ------------------------------------------------------------------
    // payload inspection (tests)
    // ------------------------------------------------------------------

    std::vector<std::string> derived_names(const std::string& object_id) const;
    bool is_synced(const std::string& object_id) const;

private:
    std::optional<std::string> payload_token(
        const pwb::geomodel::DomainObject& object) const;
    std::optional<std::vector<std::string>> build_payloads(
        SceneObjectManager& manager, const pwb::geomodel::DomainObject& object);
    std::optional<std::vector<std::string>> build_well(
        SceneObjectManager& manager, const pwb::geomodel::DomainObject& well);
    std::optional<std::vector<std::string>> build_horizon(
        SceneObjectManager& manager, const pwb::geomodel::DomainObject& horizon);
    std::optional<std::vector<std::string>> build_fault(
        SceneObjectManager& manager, const pwb::geomodel::DomainObject& fault);
    std::optional<std::vector<std::string>> build_volume(
        SceneObjectManager& manager, const pwb::geomodel::DomainObject& volume);
    std::optional<std::vector<std::string>> build_tunnel(
        SceneObjectManager& manager, const pwb::geomodel::DomainObject& tunnel);
    std::optional<std::vector<std::string>> build_measurement(
        SceneObjectManager& manager,
        const pwb::geomodel::DomainObject& measure);

    std::vector<std::array<double, 3>> to_render(
        const std::vector<std::array<double, 3>>& world) const;

    void remove_tree(SceneObjectManager& manager, const std::string& oid);
    void prune_state(
        const std::vector<std::string>& live_ids);

    ManagerProvider provider_;
    ObjectStyle styles_;
    std::string scene_identity_;
    SceneTransform transform_;

    std::map<std::string, std::string> synced_tokens_;  // oid → token
    std::map<std::string, std::vector<std::string>> derived_;
    std::map<std::string, bool> visibility_;
    std::map<std::string, double> opacity_;
    std::optional<std::vector<ClipEquation>> clip_planes_;
    std::map<std::string, std::vector<std::string>> overlays_;
    std::optional<std::string> selected_;
};

// Facies per-face RGBA (scene_adapter._facies_face_colors): per-vertex
// categorical colors from the palette (clipped to range), averaged per face.
std::vector<Rgba> facies_face_colors(const std::vector<std::int64_t>& facies,
                                     const std::vector<std::array<std::int64_t, 3>>& faces);

// Tube swept along a polyline (geoviz_plots primitives port): per-station
// central-difference tangent, resolution rings, side + no caps for tubes.
struct TubeMesh {
    std::vector<Vec3f> verts;
    std::vector<std::array<std::int64_t, 3>> faces;
};
TubeMesh generate_tube_geometry(
    const std::vector<std::array<double, 3>>& path, double radius,
    int resolution = 12);

}  // namespace pwb::geo3d_viz
