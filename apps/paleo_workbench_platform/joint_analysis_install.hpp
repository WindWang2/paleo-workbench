#pragma once

// VIZ-C joint page analysis wiring — the product install for the
// GeologicalModeling3DPage Geo3DAnalysisHooks seam.
//
// The page owns controls only; every analysis action is a hook. Before this
// install the hooks were empty, so the stratal / welltie / facies / export
// tabs rendered "未接入" (or silently no-op'd) even though every kernel they
// need already existed natively:
//
//   * stratal       — ui_workers run_stratal (demo + proportional surfaces)
//                     + seismic_viewer horizon parse/fill for .dat inputs;
//   * auto-tie      — honest refusal on the joint page's placeholder
//     records (real well tie stays the VIZ-B dock path);
//   * crossplot     — seismic_viewer analyze_lithology_crossplot +
//                     geomodel lithology tables;
//   * export        — ui_workers run_export (FLAC3D/Abaqus legacy grid);
//   * advisor       — ui_workers run_advisor over geomodel rule kernels;
//   * persistence   — joint_state json codec into the project sidecar
//                     (the same cross_well_workspace.json pattern VIZ-B
//                     established in the project directory).
//
// Data honesty contract (mirrors the Python page):
//   * bh records are single-layer placeholders derived from the joint
//     scene well heads — the Python _sync_bh_raw_from_joint_scene shape.
//     The auto-tie hook therefore fails with the Python refusal text on
//     that placeholder data (constant logs → degenerate synthetic); the
//     real well-tie product path is the VIZ-B dock with actual LAS logs.
//   * faults stay an empty list (nothing in the joint scene populates
//     them — Python parity, recorded in the install notes).

#include <functional>
#include <QString>
#include <QWidget>

#ifdef PWB_WITH_UI_WELLSEIS

#include <pwb/ui_wellseis/qt/geological_modeling_3d_page.hpp>

namespace pwb::geo3d_viz {
class SceneObjectManager;
}  // namespace pwb::geo3d_viz

namespace pwb::app {
class JobCenter;

namespace viz_c {
class VizCJointHost;
}  // namespace viz_c

namespace joint_analysis {

struct JointAnalysisInstall {
    // The hub-2 井震联合 3D page (app_shell->geomodel_page()).
    pwb::ui_wellseis::qt::GeologicalModeling3DPage* page = nullptr;
    // The joint host behind the #1394 seam (geo3d dock composition root).
    pwb::app::viz_c::VizCJointHost* host = nullptr;
    // The dock viewport's named scene-object registry — analysis overlays
    // (stratal planes, RGB fusion) are added here exactly like the Python
    // "analysis:*" scene objects.
    pwb::geo3d_viz::SceneObjectManager* scene_objects = nullptr;
    JobCenter* jobs = nullptr;
    QWidget* dialog_parent = nullptr;
    // Project directory (empty outside a project) — sidecar persistence.
    std::function<QString()> project_directory;
};

// Builds the full hook set for the deps (product install + tests drive
// the same closure-backed hooks).
pwb::ui_wellseis::qt::Geo3DAnalysisHooks make_hooks(
    const JointAnalysisInstall& deps);

// Fills the page hooks; safe to call once after AppShell construction.
void install(const JointAnalysisInstall& deps);

// Read the joint-analysis sidecar for a project directory (nullopt when
// absent/corrupt) — the MainWindow restore path.
std::optional<pwb::ui_wellseis::JointAnalysisSlice> load_stored(
    const QString& project_directory);

}  // namespace joint_analysis
}  // namespace pwb::app

#endif  // PWB_WITH_UI_WELLSEIS
