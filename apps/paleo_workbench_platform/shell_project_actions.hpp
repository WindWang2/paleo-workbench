#pragma once

// cpp-close-12 — shell project-actions integration slice.
//
// The AppShell app-bar request surfaces (save / open-sample / properties)
// previously had no production handler (UI-17 deferred list); this module
// supplies the real document-level bodies on top of the store-backed
// session:
//   * save_open_project  — #1126 parity: commit the open edit session into
//     the catalog, then persist the project document through B's
//     three-phase ProjectManager save (prepare/execute/commit).
//   * project_properties_text — project_controller.project_properties_text
//     parity: the read-only summary the properties dialog shows.
//   * bootstrap_sample_project — the sample-project entry on the real
//     production path: MainWindow::newProject (document factory + empty
//     catalog + boundary bootstrap lifecycle) followed by publishing the
//     builtin 8-well fixture as a catalog version + a persisted workspace
//     binding, so the sample layer survives close/reopen like any other
//     bound layer.
//
// Every function returns "" on success or a user-presentable error text;
// callers surface it (status bar / message box). No silent success, no
// placeholder bodies.

#include <QString>

namespace pwb::app {

class MainWindow;

namespace shell_project_actions {

// Save the open project: commit the active dirty edit session (same
// stage_commit path as the close-time Save branch), then the three-phase
// document save. Returns "" on success (with the saved path in `saved_to`
// when non-null).
QString save_open_project(MainWindow& window, QString* saved_to = nullptr);

// The read-only properties summary (Python project_properties_text parity:
// 工程名称/区域/工程文件/资源数量/导出图件/显示坐标系/版本).
QString project_properties_text(MainWindow& window);

// Bootstrap the sample project under `sample_dir` through the real
// newProject lifecycle, then publish the builtin sample-wells fixture as a
// "样例井位" catalog version bound into the workspace. Refuses with the
// one-session-per-window contract text when a project is already open
// (same guard as newProject/openProject).
QString bootstrap_sample_project(MainWindow& window,
                                 const QString& sample_dir);

}  // namespace shell_project_actions

}  // namespace pwb::app
