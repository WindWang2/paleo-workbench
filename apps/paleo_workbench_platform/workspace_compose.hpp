#pragma once

// M3 (ribbon five-workspaces, plan 00-plan.md §4-M3) — the workspace
// composition install: fills the science-host per-stage bottom stack and
// the validation page with the REAL panels, reusing existing widgets and
// authorities (no parallel views, no second linkage):
//
//   ws1 bottom: 地震剖面 + 测井轨道 两联 (new SeismicSliceWidget /
//               WellLogHostWidget instances; MainWindow routes volume/LAS
//               opens into them — the same catalog authority, a second
//               view of it, never a second loader)
//   ws2 bottom: 连井剖面 tab = VizBCrossWellDock 的内容 widget
//               (PWB_WITH_VIZ_B; the empty dock chrome hides)
//   ws3 bottom: FactorReferenceStrip fed by project.factor_map_tasks +
//               LiveFactorGridStore thumbnails (cached per
//               task+fingerprint — one downsample per grid, never a
//               re-parse); 叠加 routes through the EXISTING governed
//               stage-action dispatch (composite->stage_action_requested)
//   ws4:        validation page seismic pane (SeismicSliceWidget)
//
// Everything degrades honestly per feature guard — absent slices keep the
// AppShell empty-state labels. One call per window, after the closure
// installs (buildUi tail).

class QMainWindow;

namespace pwb::app {

class AppShell;
class AppContext;
class JobCenter;

namespace workspace_compose {

struct Install {
    QMainWindow* window = nullptr;
    AppShell* shell = nullptr;
    AppContext* context = nullptr;
    JobCenter* jobs = nullptr;
};

// Idempotent per window. GUI thread only.
void compose(const Install& install);

}  // namespace workspace_compose

}  // namespace pwb::app
