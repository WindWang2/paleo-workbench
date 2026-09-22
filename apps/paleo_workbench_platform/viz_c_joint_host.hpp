#pragma once

// VIZ-C — the REAL joint 3D host behind the #1394 JointHostController
// seam: a WellSeismicScene (plan V4 joint core) driving the geo3d_viz
// viewport. Volume OPEN and every COLD-TILE slice/fence read run through
// the JobCenter (06 closure: the GUI never blocks on a disk read; the
// worker returns raw extraction strips + a colorized time plane and the
// GUI applies them behind generation guards). The CONV-GEO3D
// SceneTransform seam is installed from the scene's world↔render maps,
// and the joint state persists as version-compatible JSON under a
// PROJECT-SCOPED key (the Geo3DWorkspaceState seven-key schema is
// untouched).
#ifdef PWB_WITH_UI_WELLSEIS

#include <cstdint>
#include <map>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include <QPointer>
#include <QObject>
#include <QString>

#include <pwb/geo3d_viz/geo3d_viewport_widget.hpp>
#include <pwb/geo3d_viz/joint/fence.hpp>
#include <pwb/geo3d_viz/joint/joint_scene.hpp>
#include <pwb/geo3d_viz/workspace_controller.hpp>
#include <pwb/seismic_service/volume_service.hpp>
#include <pwb/ui_wellseis/qt/engine_seams.hpp>

#include "job_center.hpp"

namespace pwb::app::viz_c {

class VizCTimeSliceMap;
class VizCJointHost;

// Everything the worker needs to prepare the joint visual data for one
// scene state: pure value copies + the shared volume access — the job
// body never touches the GUI-affine scene.
struct JointPrepRequest {
    std::uint64_t generation = 0;  // host-side volume/scene generation
    std::shared_ptr<const pwb::geo3d_viz::joint::IVolumeAccess> access;
    pwb::geo3d_viz::joint::SurveySpec survey;
    // nullopt when the scene has no registration yet (the registration
    // ctor validates its sizes — never default-construct with zeros).
    std::optional<pwb::geo3d_viz::joint::VolumeRegistration> registration;
    std::vector<pwb::geo3d_viz::joint::FenceSection> fences;  // visible only
    std::int64_t n_along = 128;
    std::vector<double> sample_axis;  // extraction saxis (active domain)
    std::int64_t slice_native_sample = -1;  // -1 → no time-plane read
    std::string color_scale;
};

// Worker output for one JointPrepRequest (GUI applies it to the scene).
struct JointPrepData {
    struct FenceStrip {
        std::string fence_id;
        pwb::geo3d_viz::joint::FenceExtraction extraction;
    };
    std::vector<FenceStrip> strips;
    // Colorized active time plane (RGBA8888, n_crossline * n_inline * 4);
    // empty when no active time slice exists.
    std::vector<unsigned char> slice_rgba;
    std::int64_t n_inline = 0;
    std::int64_t n_crossline = 0;
    std::int64_t active_sample = -1;
    std::string error;
};

class VizCJointHost : public pwb::ui_wellseis::qt::JointHostController {
    Q_OBJECT
public:
    // dock_controller/viewport: the geo3d dock composition root (may be
    // null in headless tests — the host then runs scene-only).
    VizCJointHost(JobCenter& job_center,
                  pwb::geo3d_viz::Geo3DWorkspaceController* dock_controller,
                  pwb::geo3d_viz::Geo3DViewportWidget* viewport,
                  QObject* parent = nullptr);
    ~VizCJointHost() override;

    // ---- volume / data loading (GUI entry, worker reads) --------------
    // Opens a published PWBVOL1/SEG-Y volume through the tiled service on
    // a background job and wires survey + registration + joint scene on
    // the GUI thread. Returns false + error honestly (no fake scenes).
    bool open_volume(const std::shared_ptr<pwb::seismic_service::SeismicVolumeService>& service,
                     const std::filesystem::path& path, QString* error);
    void set_wells(std::vector<pwb::geo3d_viz::joint::WellHead> wells,
                   std::map<std::string, pwb::geo3d_viz::joint::TimeDepthTable>
                       td_tables);

    // ---- project identity (06: state must not leak across projects) ---
    // Scopes save_state/restore_state to one project. An empty identity
    // keeps the legacy global key (standalone tests / examples).
    void set_project_identity(const std::string& identity);
    [[nodiscard]] const std::string& project_identity() const {
        return project_identity_;
    }

    // Joint-scene persistence (own QSettings key; version-compatible).
    void save_state();
    void restore_state();

    // ---- multi-fence management (06) -----------------------------------
    // Activates one existing fence (multi-fence scene: all VISIBLE fences
    // render curtains; the active one drives the 2D profile view).
    void activate_fence(const std::string& fence_id);
    void set_fence_visible(const std::string& fence_id, bool visible);
    // Manual (drawn) fence from world-XY vertices — the second fence
    // source beside the single well-order fence (Python add_fence
    // parity; draw-mode seam).
    void add_fence_vertices(
        const std::vector<std::array<double, 2>>& vertices_xy,
        const std::string& name);

    // ---- JointHostController (the #1394 seam) --------------------------
    bool shutdown(int wait_ms) override;
    void reload() override;
    [[nodiscard]] pwb::ui_wellseis::qt::JointSceneSnapshot scene_snapshot()
        const override;
    [[nodiscard]] bool has_scene() const override;
    [[nodiscard]] std::string engine_error() const override;
    // 2D fence profile view: the curtain's cached strip + projected wells.
    [[nodiscard]] std::optional<
        pwb::ui_wellseis::qt::JointFenceProfileStrip>
    active_fence_strip() const override;
    [[nodiscard]] std::vector<
        pwb::ui_wellseis::qt::JointFenceProfileWell>
    active_fence_wells() const override;
    [[nodiscard]] std::vector<std::pair<std::string, std::string>>
    well_options() const override;
    bool set_vertical_domain(const std::string& domain) override;
    void add_well_to_well_fence(const std::string& well_a,
                                const std::string& well_b,
                                const std::string& name = {}) override;
    void delete_active_fence() override;
    void set_orthogonal_slice_indices(
        std::optional<int> inline_index,
        std::optional<int> crossline_index) override;
    void restore_orthogonal_slice_state(
        std::optional<int> inline_index, std::optional<int> crossline_index,
        const std::vector<pwb::ui_wellseis::qt::JointTimeSliceEntry>&
            time_slices,
        std::optional<double> active_time_ms, double time_opacity) override;
    bool apply_slice_line_numbers(double inline_number,
                                  double crossline_number) override;
    void add_time_slice(double time_ms) override;
    void remove_time_slice(double time_ms) override;
    void set_time_slice_visible(double time_ms, bool visible) override;
    void set_active_time_slice(double time_ms) override;
    void set_time_opacity(double fraction) override;
    void set_3d_mode(const std::string& mode) override;
    void set_color_scales(const std::string& seismic_scale,
                          const std::string& gr_scale) override;
    void set_well_width(int px) override;
    void set_well_visibility(const std::string& well_id, bool visible) override;
    void set_layer_visibility(const std::string& layer_name,
                              bool visible) override;
    void apply_camera_preset(const std::string& preset) override;
    [[nodiscard]] std::string well_identity_asset_id() const override;
    [[nodiscard]] std::map<std::string, std::string> well_identity_map()
        const override;
    [[nodiscard]] std::map<std::string, std::string> path_hints() const override;
    [[nodiscard]] std::vector<std::string> loaded_data_paths() const override;
    bool highlight_well(const std::string& well_name) override;
    bool focus_position(int il, int xl, std::optional<double> twt) override;
    QWidget* joint_widget(QWidget* parent) override;
    void push_scene_to_widget() override;

    // Test/verification surface: the prepared slice applied to the 2D
    // time map (empty while the async read is in flight or unavailable).
    [[nodiscard]] JointPrepData prepared_data() const { return prepared_; }
    [[nodiscard]] bool prep_in_flight() const { return prep_running_; }
    // True when the pipeline holds an applied-key state (false right
    // after an identity switch invalidates it).
    [[nodiscard]] bool prep_applied_state() const {
        return prep_applied_.has_value();
    }
    // Read-only scene access for product wiring (the joint-analysis
    // install reads well heads / registration / fences through it).
    [[nodiscard]] const pwb::geo3d_viz::joint::WellSeismicScene& scene()
        const {
        return scene_;
    }

signals:
    void prep_applied();

private:
    // GUI-thread assembly of joint scene objects (wells from the scene;
    // fence curtains + the active time plane from the last applied
    // worker payload). Never reads the volume.
    void assemble_joint_objects();
    // Computes the current prep key; starts (or coalesces) the worker
    // read when it differs from the applied one.
    void request_prep();
    [[nodiscard]] JointPrepRequest current_prep_request() const;
    void prep_finished(const JointPrepRequest& request, JointPrepData data);
    void install_scene_transform();
    void emit_status(const QString& text);

    JobCenter& job_center_;
    pwb::geo3d_viz::Geo3DWorkspaceController* dock_controller_ = nullptr;
    pwb::geo3d_viz::Geo3DViewportWidget* viewport_ = nullptr;
    pwb::geo3d_viz::joint::WellSeismicScene scene_;
    std::string engine_error_;
    std::vector<std::string> loaded_paths_;
    std::string project_identity_;
    std::uint64_t volume_generation_ = 0;
    // QPointer: the map/owner are QObjects owned by parent trees that can
    // die independently of this host — nulls itself on either side.
    QPointer<VizCTimeSliceMap> time_map_;

    // ---- async prep pipeline (one lane, coalesced) ----------------------
    // The JobCenter creates owners parented to this host; a finished job
    // frees the owner slot so the next request reuses make_owner once.
    pwb::job::qtbridge::JobOwner* prep_owner_ = nullptr;
    bool prep_running_ = false;
    bool shutdown_done_ = false;  // request_prep() is a no-op after it
    std::optional<JointPrepRequest> prep_in_flight_;
    // The request the applied payload was produced for (diff target).
    std::optional<JointPrepRequest> prep_applied_;
    JointPrepData prepared_;
    pwb::job::qtbridge::JobOwner* volume_owner_ = nullptr;
};

}  // namespace pwb::app::viz_c

#endif  // PWB_WITH_UI_WELLSEIS
