#pragma once

// Workstation composition frame (UI-12) — port of
// paleo_workbench/ui/workstation/shell.py's dock contract:
//
//  * a QMainWindow dock host inside the frame, app bar on the top
//    toolbar row (full width, immovable);
//  * one native QDockWidget per workstation_dock_registry() descriptor:
//    native title bars, "pwbDockId" property, movable/closable,
//    descriptor-controlled floatable (GL-bearing surfaces never
//    float — reparenting a GL viewport is the documented EGL crash);
//  * floating minimum size synced on topLevelChanged;
//  * panel content via injected factories — absent factories produce
//    PagePlaceholder, never a fabricated panel;
//  * viewport policy: classify width → app-bar command floor +
//    inspector hide/restore with hysteresis;
//  * first-run sizes from descriptors; preset visibility matrices
//    without touching user sizes.

#include <functional>
#include <map>
#include <optional>
#include <string>

#include <QDockWidget>
#include <QFrame>
#include <QMainWindow>
#include <QToolBar>

#include <pwb/ui_shell/dock_registry.hpp>
#include <pwb/ui_shell/layout_presets.hpp>
#include <pwb/ui_workstation/activity_rail.hpp>
#include <pwb/ui_workstation/agent_panel.hpp>
#include <pwb/ui_workstation/app_bar.hpp>
#include <pwb/ui_workstation/explorer_panel.hpp>
#include <pwb/ui_workstation/inspector_panel.hpp>
#include <pwb/ui_workstation/process_hub.hpp>
#include <pwb/ui_workstation/task_center.hpp>

namespace pwb::ui_workstation {

class WorkstationFrame : public QFrame {
    Q_OBJECT
public:
    // dock_id → content widget. Returning nullptr → PagePlaceholder.
    using PanelFactory =
        std::function<QWidget*(const std::string& dock_id,
                               QWidget* parent)>;

    explicit WorkstationFrame(QWidget* parent = nullptr);

    // The central page widget (project hub stack). The caller keeps
    // ownership semantics of a normal child widget — the frame
    // reparents it into the dock host's central area.
    void set_central_widget(QWidget* page_stack);

    // Panel factories. `install_default_panels()` wires the UI-12
    // widgets (rail+explorer, inspector, task center, log viewer,
    // console, agent) and PagePlaceholder for the rest; callers may
    // override individual ids before build().
    void set_panel_factory(const std::string& dock_id,
                           PanelFactory factory);
    void install_default_panels();
    // Build every dock from the registry (idempotent — re-call is a
    // no-op).
    void build_docks();

    QDockWidget* dock(const std::string& dock_id) const;
    void set_dock_visible(const std::string& dock_id, bool visible);
    bool dock_visible(const std::string& dock_id) const;

    // Workspace presets: apply a visibility matrix (does NOT resize —
    // preset switches never disturb user-arranged sizes).
    void apply_layout_preset(const std::string& preset_id);
    void apply_visibility(
        const ui_shell::DockVisibilityMatrix& matrix);
    std::string current_preset() const { return current_preset_; }
    // Dock toggles by the user drop the preset back to 自定义 ("").
    void note_user_layout_change();

    // First-run sizing (descriptor preferred_size; grow-only).
    void apply_first_run_sizes();

    WorkstationAppBar* app_bar() const { return app_bar_; }
    ActivityRail* activity_rail() const { return rail_; }
    WorkstationExplorer* explorer() const { return explorer_; }
    WorkstationInspector* inspector() const { return inspector_; }
    WorkstationTaskCenter* task_center() const { return task_center_; }
    WorkstationLogViewer* log_viewer() const { return log_viewer_; }
    AgentWorkspacePanel* agent_panel() const { return agent_panel_; }
    QMainWindow* dock_host() const { return dock_host_; }

    // Explorer collapsed state (rail collapse button parity).
    void set_explorer_expanded(bool expanded);
    bool explorer_expanded() const { return explorer_expanded_; }

    // Viewport policy: inspector hide <1100, restore >1200 (hysteresis),
    // command-input floor per class. Called on host resize.
    void apply_viewport_class(ui_shell::ViewportClass cls);

    void shutdown();

signals:
    // Preset/dock-visibility mirror for host persistence.
    void layout_changed();

protected:
    bool eventFilter(QObject* obj, QEvent* event) override;

private:
    QDockWidget* make_dock(const ui_shell::DockDescriptor& desc);
    QWidget* content_for(const std::string& dock_id, QWidget* parent);
    void sync_floating_minimum(QDockWidget* dock,
                               const ui_shell::DockDescriptor& desc);
    void apply_inspector_policy(int width);

    QMainWindow* dock_host_ = nullptr;
    QToolBar* app_bar_toolbar_ = nullptr;
    QWidget* central_ = nullptr;
    std::map<std::string, QDockWidget*> docks_;
    std::map<std::string, PanelFactory> factories_;
    std::string current_preset_;
    bool built_ = false;
    bool tearing_down_ = false;
    bool explorer_expanded_ = true;
    bool inspector_hidden_by_viewport_ = false;
    // The user's explicit inspector visibility choice (viewport policy
    // restores to this, not unconditionally to visible).
    bool inspector_user_visible_ = true;

    WorkstationAppBar* app_bar_ = nullptr;
    ActivityRail* rail_ = nullptr;
    WorkstationExplorer* explorer_ = nullptr;
    WorkstationInspector* inspector_ = nullptr;
    WorkstationTaskCenter* task_center_ = nullptr;
    WorkstationLogViewer* log_viewer_ = nullptr;
    AgentWorkspacePanel* agent_panel_ = nullptr;
};

}  // namespace pwb::ui_workstation
