#pragma once

// VIZ-C — the REAL joint 3D host behind the #1394 JointHostController
// seam: a WellSeismicScene (plan V4 joint core) driving the geo3d_viz
// viewport. Volume OPEN runs through the JobCenter (metadata-only
// inspect on the worker); slice reads happen on the GUI thread — the
// single reader for the volume's lifetime. The CONV-GEO3D
// SceneTransform seam is installed from the scene's world↔render maps,
// and the joint state persists as version-compatible JSON under its own
// key (the Geo3DWorkspaceState seven-key schema is untouched).
#ifdef PWB_WITH_UI_WELLSEIS

#include <memory>

#include <QPointer>
#include <QObject>
#include <QString>

#include <pwb/geo3d_viz/geo3d_viewport_widget.hpp>
#include <pwb/geo3d_viz/joint/joint_scene.hpp>
#include <pwb/geo3d_viz/workspace_controller.hpp>
#include <pwb/seismic_service/volume_service.hpp>
#include <pwb/ui_wellseis/qt/engine_seams.hpp>

#include "job_center.hpp"

namespace pwb::app::viz_c {

class VizCTimeSliceMap;

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

    // Joint-scene persistence (own QSettings key; version-compatible).
    void save_state();
    void restore_state();

    // ---- JointHostController (the #1394 seam) --------------------------
    bool shutdown(int wait_ms) override;
    void reload() override;
    [[nodiscard]] pwb::ui_wellseis::qt::JointSceneSnapshot scene_snapshot()
        const override;
    [[nodiscard]] bool has_scene() const override;
    [[nodiscard]] std::string engine_error() const override;
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

private:
    // GUI-thread assembly of joint scene objects (wells/fence/slice) in
    // render space; generation-guarded so a late/cancelled job can never
    // overwrite a newer scene.
    void assemble_joint_objects();
    void install_scene_transform();
    void emit_status(const QString& text);

    JobCenter& job_center_;
    pwb::geo3d_viz::Geo3DWorkspaceController* dock_controller_ = nullptr;
    pwb::geo3d_viz::Geo3DViewportWidget* viewport_ = nullptr;
    pwb::geo3d_viz::joint::WellSeismicScene scene_;
    std::string engine_error_;
    std::vector<std::string> loaded_paths_;
    std::uint64_t volume_generation_ = 0;
    // QPointer: the map/owner are QObjects owned by parent trees that can
    // die independently of this host — nulls itself on either side.
    QPointer<VizCTimeSliceMap> time_map_;
    QPointer<pwb::job::qtbridge::JobOwner> volume_owner_;
};

}  // namespace pwb::app::viz_c

#endif  // PWB_WITH_UI_WELLSEIS
