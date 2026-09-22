// workflow_install.hpp — the UI-14 composition-root wiring for the
// native product shell.
//
// Owns, per window:
//   * qt::WorkflowController — the cross-page orchestration core
//     (recompute run, 发送制备, 发送编图, page-update fan-out, demo
//     draft) with EVERY seam bound to the real services (workflow_runtime,
//     closure_workflow compilers, the shared factor grid store/rail);
//   * the per-project catalog closure — the deep CatalogServiceApi
//     (line-01 InstalledCatalogClosure) + the canonical SQLite
//     workflow_runtime::CatalogRepository rail that factor prep, map
//     compile and product assembly all share;
//   * the composite stage-action dispatch + factor-shelf action routing
//     (Python stage_actions.py / mapping shell handler parity).
//
// Lifetime: one binding object per window (QObject child, recovered via
// the "pwb_workflow_binding" dynamic property — the same recovery pattern
// as closure_mapping_context). notify_project_changed() re-opens the
// catalog rails after every project open/close.
#pragma once

class QMainWindow;

namespace pwb::app {
class AppShell;
class AppContext;
class JobCenter;
}  // namespace pwb::app

namespace pwb::app::workflow_wiring {

// Install once after the mapping closure + stage flow exist (the
// preparation page and document bank must be adopted first — the binding
// shares their grid store and catalog). Returns false when the AppShell
// composition is absent (honest skip — the shell-less build keeps its
// existing surfaces).
bool install(QMainWindow* window, AppShell* shell, AppContext* context,
             JobCenter* jobs);

// Re-open the per-project catalog rails + rebind the controller's
// catalog bag. Call after every project open AND on the no-store close
// path (a closed project detaches both rails — fail-closed, never stale
// writes into the previous project's store).
void notify_project_changed(QMainWindow* window);

}  // namespace pwb::app::workflow_wiring
