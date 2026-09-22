#pragma once

// M4 (ribbon five-workspaces, plan 00-plan.md §4-M4 / design R:20,29,33) —
// the ribbon command-band fill: every one of the 58 ui_ribbon placeholder
// ids becomes a REAL CommandRegistry command:
//
//   * real backends route to the EXISTING implementations (DataToolbar
//     ingest signals, governed ToolActionSet QActions, PreparationPage
//     generate/contour, validation run-QC, review export, stage actions)
//     — no parallel command paths (D4);
//   * capabilities without a backend register DISABLED with an honest
//     Chinese reason ("M5 接入：…" / "无后端：…") — never a fake enable;
//   * the five per-workspace primary actions are enforced (data.import /
//     predict.run / factor.compute / map.export / verify.run) with the
//     run-guard wired to the real busy state where a backend exists.
//
// Registration rides the process-global CommandRegistry, so the palette,
// the ribbon buttons and any menu reuse one spec per id. The window
// unregisters its ids in ~MainWindow (process-global registry, per-window
// closures — the stage_flow precedent).

class QMainWindow;

#include <string>
#include <vector>

namespace pwb::app {

class AppShell;
class AppContext;
class JobCenter;

namespace ribbon_commands {

struct Install {
    QMainWindow* window = nullptr;  // the platform MainWindow
    AppShell* shell = nullptr;
    AppContext* context = nullptr;
    JobCenter* jobs = nullptr;
    // Collects every registered id (the window unregisters them at
    // destruction — same ownership contract as stage_flow_command_ids_).
    std::vector<std::string>* registered_ids = nullptr;
};

// Idempotent per window (same-id re-register replaces). GUI thread only.
void install(const Install& install);

}  // namespace ribbon_commands

}  // namespace pwb::app
