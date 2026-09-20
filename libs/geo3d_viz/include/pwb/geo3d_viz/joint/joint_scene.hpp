// WellSeismicScene — primary public seam for joint well–seismic analysis.
// Port of geoviz_well_seismic_3d/scene.py @ 08851951 (frozen behavior
// source). Qt-free scene-graph state: survey, wells, vertical domain,
// fences, probe and volume; world↔render coordinate maps feed the
// CONV-GEO3D SceneTransform seam.
#pragma once

#include <map>
#include <memory>
#include <optional>
#include <string>
#include <tuple>
#include <vector>

#include "depth_transform.hpp"
#include "fence.hpp"
#include "joint_types.hpp"
#include "probe.hpp"
#include "registration.hpp"
#include "survey.hpp"
#include "volume_access.hpp"

namespace pwb::geo3d_viz::joint {

inline constexpr const char* kDefaultCurveFallback[] = {"GR", "DT", "RHOB"};

// Well projected onto the active fence for 2D assembly.
struct ProfileWellHit {
    JointWellId id;
    std::string name;
    std::string display_name;
    double s_m = 0.0;
    double distance_m = 0.0;
    std::vector<std::pair<std::string, double>> tops;  // (name, z in domain)
    std::optional<std::string> curve_name;
    std::optional<std::vector<double>> curve_md;
    std::optional<std::vector<double>> curve_z;
    std::optional<std::vector<double>> curve_values;
};

// Stable well identity and user-facing label for joint-workbench chrome.
struct JointWellPresentation {
    JointWellId id;
    std::string name;
    std::string display_name;
    bool visible = true;
};

// One (md, values) curve.
using WellCurve = std::pair<std::vector<double>, std::vector<double>>;

// Joint scene state (survey, wells, domain, fences, probe, volume).
class WellSeismicScene {
public:
    WellSeismicScene();

    // ---- Survey ----------------------------------------------------------
    const SurveySpec* survey() const { return survey_ ? &*survey_ : nullptr; }
    void set_survey(SurveySpec survey);
    SurveySpec set_survey_from_corners(
        const Corner& p1, const Corner& p2, const Corner& p3,
        std::int64_t n_samples, double dt_ms, double t0_ms = 0.0,
        std::optional<std::int64_t> iline_step = std::nullopt,
        std::optional<std::int64_t> xline_step = std::nullopt,
        std::optional<std::int64_t> n_inlines = std::nullopt,
        std::optional<std::int64_t> n_crosslines = std::nullopt);
    // (ok, message) — corner round-trip consistency (25 m / 1 IL-XL
    // tolerances by default).
    std::pair<bool, std::string> validate_against_corners(
        const Corner& p1, const Corner& p2, const Corner& p3,
        double tol_m = 25.0, double tol_il_xl = 1.0) const;

    // ---- Vertical domain / depth -----------------------------------------
    VerticalDomain vertical_domain() const { return domain_; }
    const JointDisplaySettings& display_settings() const {
        return display_settings_;
    }
    void set_display_settings(JointDisplaySettings settings);

    const OrthogonalSliceState& orthogonal_slice_state() const {
        return slice_state_;
    }
    const std::string& slice_state_warning() const {
        return slice_state_warning_;
    }
    // Restore project state now; reconcile once survey/volume are ready.
    void restore_orthogonal_slice_state(OrthogonalSliceState state);
    void set_orthogonal_slice_indices(
        std::optional<std::int64_t> inline_index,
        std::optional<std::int64_t> crossline_index);
    // Add or activate a snapped Time slice; throws at the eight-item cap.
    double add_time_slice(double time_ms);
    // Move one slice, merging with an existing slice after snapping.
    double update_time_slice(double current_time_ms, double new_time_ms);
    bool remove_time_slice(double time_ms);
    void set_time_slice_visible(double time_ms, bool visible);
    void set_active_time_slice(double time_ms);
    void set_time_slice_opacity(double opacity);
    // Compatibility/probe seam: move only ActiveTimeSlice.
    double move_active_time_slice_to_sample(std::int64_t sample_index);
    // Snap one TWT value onto the loaded sample lattice (public read-side
    // helper; the slice ops above all route through it).
    double snap_time_ms(double time_ms) const;
    // Renderer-ready preview indices for the orthogonal planes; null when
    // the stack is not ready. (il, xl, [(sample, visible)], active,
    // opacity.)
    std::optional<std::tuple<std::int64_t, std::int64_t,
                             std::vector<std::pair<std::int64_t, bool>>,
                             std::int64_t, double>>
    orthogonal_slice_render_state() const;

    const DepthTransformState& depth_transform() const {
        return depth_transform_;
    }
    bool depth_available() const { return depth_transform_.available(); }
    void set_depth_transform(DepthTransformState state);
    // Fail-closed: Depth is refused when no time-depth transform is
    // available — uniform scaling must never masquerade as depth.
    void set_vertical_domain(VerticalDomain domain);

    // ---- Wells -------------------------------------------------------------
    void set_wells(std::vector<WellHead> wells,
                   std::map<std::string, TimeDepthTable> td_tables = {});
    std::vector<JointWellPresentation> well_presentations() const;
    void set_well_visibility(const JointWellId& well_id, bool visible);
    std::map<JointWellId, WellTrajectory3D> well_trajectories(
        bool visible_only = false) const;
    // Tops as (name, z) already in active domain units (ms or m).
    void set_formation_tops(
        std::map<std::string, std::vector<std::pair<std::string, double>>>
            tops_by_well);
    // curves_by_well[well][curve] = (md, values).
    void set_well_curves(
        std::map<std::string, std::map<std::string, WellCurve>>
            curves_by_well);
    // One robust P2–P98 GR range shared by all loaded wells.
    std::optional<std::pair<double, double>> gr_value_range() const;
    std::map<JointWellId, WellGrTrajectory> gr_well_trajectories(
        bool visible_only = false) const;
    void set_curve_names(std::vector<std::string> names);
    void set_near_well_distance_m(double distance_m);

    // ---- Volume -------------------------------------------------------------
    void set_volume_access(std::shared_ptr<IVolumeAccess> access);
    IVolumeAccess* volume_access() const { return volume_.get(); }
    // Shared, refcount-safe view for off-thread readers (the joint host
    // captures it into job requests; the scene keeps owning the lifetime).
    std::shared_ptr<const IVolumeAccess> volume_access_shared() const {
        return volume_;
    }
    // Survey ↔ loaded volume index map (preview-aware).
    const VolumeRegistration* registration() const {
        return registration_ ? &*registration_ : nullptr;
    }
    void set_preview_mode(bool enabled) { preview_mode_ = enabled; }
    bool preview_mode() const { return preview_mode_; }
    std::vector<float> slice_inline(std::int64_t il_index) const;
    std::vector<float> slice_crossline(std::int64_t xl_index) const;
    std::vector<float> slice_time(std::int64_t sample_index) const;

    // ---- Fences (#60–#61) ---------------------------------------------------
    std::vector<FenceSection> fences() const { return fences_; }
    const std::string* active_fence_id() const {
        return active_fence_id_ ? &*active_fence_id_ : nullptr;
    }
    FenceSection add_fence(FenceSection fence, bool activate = true);
    void set_active_fence(const std::string& fence_id);
    void remove_fence(const std::string& fence_id);
    bool remove_active_fence();
    // Drop all fences (survey/project rebind): stale vertices are
    // meaningless against a new survey and would silently clamp into
    // invalid extraction strips.
    void clear_fences();
    void set_fence_visible(const std::string& fence_id, bool visible);
    FenceSection add_well_to_well_fence(
        const std::vector<JointWellId>& well_refs,
        const std::string& name = "Wells");
    std::vector<JointWellId> fence_well_ids() const { return fence_well_ids_; }
    // Visible wells that intersect ActiveTimeSlice (Time domain only).
    std::vector<WellPierce> pierce_points_on_active_time(
        bool visible_only = true) const;
    // Append a piercing well to the Time-slice path (duplicates ignored).
    bool append_fence_well(const JointWellId& well_ref);
    std::optional<JointWellId> pop_fence_well();
    const FenceSection* active_fence() const;
    // Extract the active fence strip; extraction-time domain override is
    // kept for callers managing their own domain (the workbench passes
    // null so 2D and 3D share the single scene domain).
    std::optional<FenceExtraction> extract_active_fence(
        std::int64_t n_along = 128,
        std::optional<VerticalDomain> domain = std::nullopt) const;
    // Extract any fence by id (multi-fence rendering): same cache and
    // read path as the active-fence variant; nullopt when the id is
    // unknown or the volume/survey is not ready.
    std::optional<FenceExtraction> extract_fence(
        const std::string& fence_id, std::int64_t n_along = 128,
        std::optional<VerticalDomain> domain = std::nullopt) const;

    // ---- Active 2D assembly (#62) -------------------------------------------
    std::vector<ProfileWellHit> assemble_active_profile_wells(
        std::optional<VerticalDomain> domain = std::nullopt) const;

    // ---- Probe (#64) ---------------------------------------------------------
    const ProbeState* probe() const { return probe_ ? &*probe_ : nullptr; }
    ProbeState set_probe(double s_m, double z);
    std::optional<std::array<std::int64_t, 3>> probe_slice_indices() const;

    // ---- World ↔ render coordinate maps (SceneTransform source) -------------
    // Map world XY + domain Z to volume/render index space (float32 in
    // Python; double here — the render layer converts).
    std::vector<std::array<double, 3>> world_to_render_xyz_array(
        const std::vector<std::array<double, 3>>& points) const;
    std::array<double, 3> world_to_render_xyz(double x, double y,
                                              double z) const;
    // Exact inverse: registration strides and survey line steps invert on
    // the lattice; the depth transform applies in reverse in Depth
    // domain. Fails closed symmetrically (throws in Depth without an
    // available transform); identity with neither registration nor
    // survey.
    std::vector<std::array<double, 3>> render_to_world_xyz_array(
        const std::vector<std::array<double, 3>>& points) const;
    std::array<double, 3> render_to_world_xyz(double i, double x,
                                              double t) const;

    // ---- Persisted joint state (version-compatible JSON) --------------------
    // Python persists display settings + orthogonal slice state + fences
    // in project settings; the C++ host stores this JSON under its own
    // key — the Geo3DWorkspaceState seven-key schema is untouched and
    // stays readable (joint state is purely additive).
    std::string joint_state_to_json() const;
    // Returns the list of restored fence ids; unknown/legacy fields
    // degrade per-entry (never throws on old data). Returns false when
    // the payload is not a joint-state object.
    bool restore_joint_state(const std::string& json,
                             std::vector<std::string>* restored_fences);

private:
    void invalidate_traj() { traj_cache_.reset(); }
    void rebuild_registration() const;
    void reconcile_orthogonal_slice_state();
    void rescale_slice_indices(const IVolumeAccess* old_access,
                               const IVolumeAccess* new_access);
    void replace_slice_state(
        std::optional<std::int64_t> inline_index,
        std::optional<std::int64_t> crossline_index,
        std::optional<std::vector<TimeSliceState>> time_slices,
        std::optional<double> active_time_ms,
        std::optional<double> time_opacity);
    const TimeSliceState* find_time_slice(double time_ms) const;
    static bool same_time(std::optional<double> left,
                          std::optional<double> right);
    FenceSection* sync_well_order_fence(const std::string& name = "");
    void drop_well_order_fence();
    JointWellId resolve_well_ref(const JointWellId& ref) const;
    std::pair<double, double> head_xy(const JointWellId& well_id) const;
    std::tuple<std::optional<std::string>, const WellCurve*, const WellCurve*>
    pick_curve(const JointWellId& well_id, const std::string& fallback_name,
               const std::map<std::string, WellCurve>& curves) const;
    std::vector<std::pair<std::string, double>> tops_in_domain(
        const std::vector<std::pair<std::string, double>>& tops,
        VerticalDomain domain) const;

    std::optional<SurveySpec> survey_;
    VerticalDomain domain_ = VerticalDomain::Time;
    JointDisplaySettings display_settings_;
    OrthogonalSliceState slice_state_;
    std::string slice_state_warning_;
    std::vector<WellHead> wells_;
    std::vector<JointWellId> well_ids_;
    std::map<JointWellId, bool> well_visibility_;
    std::map<std::string, TimeDepthTable> td_tables_;
    std::shared_ptr<IVolumeAccess> volume_;
    mutable std::optional<std::map<JointWellId, WellTrajectory3D>>
        traj_cache_;
    std::vector<FenceSection> fences_;
    std::optional<std::string> active_fence_id_;
    std::vector<JointWellId> fence_well_ids_;
    std::optional<std::string> well_order_fence_id_;
    // Key: (fence_id, domain, n_along) so Time/Depth extracts coexist.
    mutable std::map<std::tuple<std::string, int, std::int64_t>,
                     FenceExtraction>
        extract_cache_;
    std::optional<ProbeState> probe_;
    DepthTransformState depth_transform_;
    double near_well_m_ = 100.0;
    std::vector<std::string> curve_names_ = {"GR", "DT"};
    std::map<std::string, std::vector<std::pair<std::string, double>>>
        tops_by_well_;
    std::map<std::string, std::map<std::string, WellCurve>> curves_by_well_;
    bool preview_mode_ = true;  // #65 formalization flag
    mutable std::optional<VolumeRegistration> registration_;
};

}  // namespace pwb::geo3d_viz::joint
