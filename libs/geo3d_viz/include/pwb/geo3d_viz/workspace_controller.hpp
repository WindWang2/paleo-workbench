#pragma once

// pwb::geo3d_viz — Geo3D workspace controller (CONV-GEO3D).
//
// C++ port of paleo_workbench/ui/pages/geo3d_workspace.py
// (Geo3DWorkspaceController): the page-facing facade over the V5 geological
// workspace —
//   * object management (ModelAssembly + adapter sync + incremental QC);
//   * selection with well broadcast (the 2D map synchronization seam);
//   * measurement tool state machine (6 modes, thickness pairing rules);
//   * object clip planes driven by 0-1 axis controls over live bounds
//     (bounds-derived, never a hardcoded ±80);
//   * named camera view presets and workspace persistence.
//
// Persistence contract (frozen against Geo3DWorkspaceState,
// paleo_workbench/project/models.py:497-529):
//   * seven-key payload: objects/measurements/display/clip/camera/views/
//     selected, in that key order;
//   * arrays never enter the payload (ADR-03: bulk geometry reloads from
//     Catalog artifacts) — restored wells/horizons are metadata references
//     the sync skips until real arrays arrive;
//   * demo-provenance objects are NEVER persisted;
//   * restore degrades per entry — a corrupted value never blocks opening
//     a project ("false" never truthifies: strict _as_bool/_as_float).
//
// The host page supplies a ViewportFacade (implemented by the Qt widget);
// a null facade — or a facade whose viewport is gone — degrades every
// camera/bounds/pick call exactly like the Python provider=None contract.
// The controller holds no GL state.

#include <QObject>

#include <array>
#include <map>
#include <optional>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/geo3d_viz/orbit_camera.hpp>
#include <pwb/geo3d_viz/scene_adapter.hpp>
#include <pwb/geomodel/builders.hpp>
#include <pwb/geomodel/domain_contract.hpp>
#include <pwb/geomodel/measurements.hpp>
#include <pwb/geomodel/qc_contract.hpp>

namespace pwb::geo3d_viz {

using pwb::domain::Json;
using pwb::geomodel::DomainObject;
using Bounds = std::pair<std::array<double, 3>, std::array<double, 3>>;

// Per-axis clip slider state (value is the 0-1 UI position, not world).
struct ClipAxisState {
    bool enabled = false;
    double value = 0.5;
    bool invert = false;

    Json to_json() const;
    static ClipAxisState from_json(const Json& value, bool* ok = nullptr);
};

// Viewport seam (implemented by Geo3DViewportWidget; fakes in tests).
class Geo3DViewportFacade {
public:
    virtual ~Geo3DViewportFacade() = default;
    virtual std::optional<CameraPose> camera_pose() const = 0;
    virtual void apply_camera_pose(const CameraPose& pose) = 0;
    // Union bounds of current scene objects (visible_only=False semantics).
    virtual std::optional<Bounds> scene_bounds(bool visible_only) = 0;
    virtual bool fit_objects(
        const std::optional<std::vector<std::string>>& names) = 0;
    // Screen pick at widget pixel coordinates (engine-space hit; the
    // controller resolves it to domain space through the adapter).
    virtual std::optional<PickHit> pick_at(
        double px, double py, const std::vector<ObjectKind>& kinds) = 0;
};

// geo3d_workspace._MEASURE_MODES — mode → (label, points needed).
struct MeasureModeSpec {
    const char* mode;
    const char* label;
    int points_needed;
};
const std::vector<MeasureModeSpec>& measure_modes();
const MeasureModeSpec* find_measure_mode(const std::string& mode);

// geo3d_workspace._as_bool: strict-ish coercion ("false" never truthifies).
bool state_as_bool(const Json& value, bool default_value);
// geo3d_workspace._as_float: float() coercion + finite check + clamp.
double state_as_float(const Json& value, double default_value,
                      const double* lo = nullptr, const double* hi = nullptr);

class Geo3DWorkspaceController : public QObject {
    Q_OBJECT

public:
    // manager_provider: the live scene registry (nullptr while torn down).
    Geo3DWorkspaceController(
        std::function<SceneObjectManager*()> manager_provider,
        QObject* parent = nullptr);

    // Non-owning viewport hookup; nullptr detaches (teardown-safe).
    void set_viewport(Geo3DViewportFacade* facade);
    Geo3DViewportFacade* viewport() const { return facade_; }

    GeologicalSceneAdapter& adapter() { return adapter_; }
    const GeologicalSceneAdapter& adapter() const { return adapter_; }
    const pwb::geomodel::ModelAssembly& assembly() const { return assembly_; }

    // ------------------------------------------------------------------
    // object management
    // ------------------------------------------------------------------

    // Add (or replace), resync + incremental QC. Returns the stored object,
    // or nullptr when the assembly rejected the id (status emitted).
    const DomainObject* add_object(DomainObject object);
    bool remove_object(const std::string& object_id);
    int clear(const std::optional<std::string>& kind = std::nullopt);
    void reset();

    void set_visibility(const std::string& object_id, bool visible);
    bool visibility(const std::string& object_id) const;
    void set_opacity(const std::string& object_id, double opacity);
    void sync_scene();

    // ------------------------------------------------------------------
    // selection + the 2D map synchronization seam
    // ------------------------------------------------------------------

    const std::optional<std::string>& selected_id() const { return selected_id_; }
    void set_selected(const std::optional<std::string>& object_id,
                      bool broadcast = true);

    // 2D seam getters (map view consumes these when the 3D selection moves).
    std::string assembly_crs() const;
    std::optional<Bounds> scene_bounds() const;  // visible_only=False

    // ------------------------------------------------------------------
    // QC
    // ------------------------------------------------------------------

    const pwb::geomodel::QCReport& qc_report() const { return qc_report_; }
    pwb::geomodel::QCReport refresh_qc();
    // Identity/provenance/geometry/QC summary (Python inspector text).
    std::string inspector_text(
        const std::optional<std::string>& object_id = std::nullopt) const;

    // ------------------------------------------------------------------
    // measurement tool
    // ------------------------------------------------------------------

    const std::optional<std::string>& measure_mode() const {
        return measure_mode_;
    }
    bool set_measure_mode(const std::optional<std::string>& mode);
    // Pick-filter hook: measurement accumulation or select-on-click.
    // True = consumed. The widget resolves (px, py) through the facade.
    bool handle_viewport_click(double px, double py);

    // ------------------------------------------------------------------
    // clipping (view state, bounds-derived)
    // ------------------------------------------------------------------

    const std::map<std::string, ClipAxisState>& clip_state() const {
        return clip_state_;
    }
    void set_axis_clip(const std::string& axis, bool enabled, double value01,
                       bool invert);
    void apply_clip_state();
    void reset_clip();

    // ------------------------------------------------------------------
    // camera / view presets
    // ------------------------------------------------------------------

    std::optional<CameraPose> capture_camera();
    bool save_view_preset(const std::string& name);
    bool restore_view_preset(const std::string& name);
    const std::map<std::string, CameraPose>& view_presets() const {
        return view_presets_;
    }
    const std::optional<CameraPose>& camera() const { return camera_; }
    bool fit_all();
    bool fit_selected();

    // ------------------------------------------------------------------
    // persistence (seven-key payload; caller stores it in the project)
    // ------------------------------------------------------------------

    Json save_state();
    std::vector<std::string> restore_state(const Json& payload);

signals:
    void selection_changed(const QString& object_id);  // "" = cleared
    void qc_updated();
    void measurements_changed();
    void status_message(const QString& message);
    // 2D map synchronization seam: emitted on well selection broadcast.
    void well_selected(const QString& well_name);

private:
    void qc_single(const DomainObject& object);
    std::optional<DomainPick> pick_via_facade(double px, double py);
    bool finish_thickness_pick();
    void finish_measurement(const std::string& kind);
    void emit_measurement(pwb::geomodel::MeasurementResult result,
                          const std::vector<std::array<double, 3>>& points);
    const DomainObject* first_of_kind(
        const std::string& kind,
        const std::vector<std::string>& name_hints) const;
    pwb::geomodel::HorizonGrid horizon_grid(const DomainObject& horizon) const;

    pwb::geomodel::ModelAssembly assembly_;
    GeologicalSceneAdapter adapter_;
    Geo3DViewportFacade* facade_ = nullptr;
    pwb::geomodel::QCReport qc_report_;
    std::optional<std::string> selected_id_;
    std::optional<std::string> measure_mode_;
    std::vector<std::array<double, 3>> measure_points_;
    std::map<std::string, ClipAxisState> clip_state_;
    std::map<std::string, CameraPose> view_presets_;
    std::optional<CameraPose> camera_;
    // Persisted camera shape (may be partial after restore — Python keeps
    // {k: _as_float(v, 0.0)} over the keys present only).
    Json camera_json_ = Json::object();
    std::map<std::string, long long> measure_counters_;  // kind → counter
};

}  // namespace pwb::geo3d_viz
