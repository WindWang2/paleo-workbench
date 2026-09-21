#pragma once

// CONV-GEO3D — the native 3D geomodel viewer dock (platform wiring).
//
// Self-contained composition root for the C++ geo-viz runtime: the Qt6
// viewport + the workspace controller + the minimal tool surface (fit /
// clip sliders / measurement modes / object visibility / screenshot). All
// the Python page glue this replaces (geo3d_workspace.py + the 3D half of
// geological_modeling_3d_page.py) lives in the controller; this dock is
// product wiring only. Selection of wells is re-broadcast through
// well_selected() — the 2D map synchronization seam.
//
// VIZ-C (plan V4): the dock is also the composition root of the joint
// well-seismic host — the #1394 JointHostController seam over the
// WellSeismicScene core, sharing this viewport and controller.

#include <QDockWidget>

#include <memory>

#include <pwb/geo3d_viz/geo3d_viewport_widget.hpp>
#include <pwb/geo3d_viz/workspace_controller.hpp>

#ifdef PWB_WITH_UI_WELLSEIS
namespace pwb::app {
class JobCenter;
}
namespace pwb::app::viz_c {
class VizCJointHost;
}
#endif

class QListWidget;
class QLabel;
class QCheckBox;
class QSlider;
class QComboBox;

class Geo3DDock : public QDockWidget {
    Q_OBJECT

public:
    explicit Geo3DDock(QWidget* parent = nullptr);

    pwb::geo3d_viz::Geo3DViewportWidget* viewport() const {
        return viewport_;
    }
    pwb::geo3d_viz::Geo3DWorkspaceController* controller() const {
        return controller_.get();
    }

#ifdef PWB_WITH_UI_WELLSEIS
    // VIZ-C: the joint well-seismic host (WellSeismicScene + JobCenter
    // volume loading + the SceneTransform seam). Lazily created once per
    // dock; at teardown the JobCenter is destroyed BEFORE this dock's
    // host (MainWindow declares the JobCenter member last → reverse
    // member order destroys it first — see main_window.hpp).
    pwb::app::viz_c::VizCJointHost* joint_host();
#endif

    // ---- project persistence (the cross_well_workspace.json pattern) ------
    // The controller's seven-key Geo3DWorkspaceState payload (objects/
    // measurements/display/clip/camera/views/selected) stored as a sidecar
    // in the project directory. restore_project_workspace() after a
    // project open (missing sidecar = fresh workspace, same as VIZ-B);
    // persist_project_workspace() on project close / window close.
    void set_project_directory(const QString& directory);
    void restore_project_workspace();
    void persist_project_workspace();

signals:
    // 2D map synchronization seam (selected well name).
    void well_selected(const QString& well_name);

private slots:
    void refresh_objects();
    void show_status(const QString& message);

private:
    void build_toolbar(QWidget* toolbar);
    void sync_clip_ui();

    pwb::geo3d_viz::Geo3DViewportWidget* viewport_ = nullptr;
    std::unique_ptr<pwb::geo3d_viz::Geo3DWorkspaceController>
        controller_;
    QListWidget* object_list_ = nullptr;
    QLabel* status_label_ = nullptr;
    QCheckBox* clip_enabled_[3] = {nullptr, nullptr, nullptr};
    QSlider* clip_slider_[3] = {nullptr, nullptr, nullptr};
    QCheckBox* clip_invert_[3] = {nullptr, nullptr, nullptr};
    QComboBox* measure_combo_ = nullptr;
    QString project_directory_;
#ifdef PWB_WITH_UI_WELLSEIS
    std::unique_ptr<pwb::app::viz_c::VizCJointHost> joint_host_;
#endif
};
