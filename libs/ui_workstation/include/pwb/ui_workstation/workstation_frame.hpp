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
#include <QTabBar>
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
#include <pwb/ui_workstation/workflow_panel.hpp>

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
    // True when a real panel factory is registered for this dock — a
    // dock without one renders a "(占位页, 待实现)" placeholder and must
    // not be force-shown by a stage profile (#1450). Adopted docks carry
    // their own real widget → count as factory-backed.
    bool has_panel_factory(const std::string& dock_id) const {
        const auto it = factories_.find(dock_id);
        if (it != factories_.end() && static_cast<bool>(it->second)) {
            return true;
        }
        if (auto* d = dock(dock_id)) {
            return d->property("pwbAdopted").toBool();
        }
        return false;
    }
    void install_default_panels();
    // Build every dock from the registry (idempotent — re-call is a
    // no-op).
    void build_docks();

    QDockWidget* dock(const std::string& dock_id) const;
    void set_dock_visible(const std::string& dock_id, bool visible);
    bool dock_visible(const std::string& dock_id) const;
    // 收编外部真实 QDockWidget（如窗口级 ConstraintPanel）进 dock 宿主
    // —— 注销注册表占位 dock、按描述符区域停靠、并入同区 tab 组。
    // dock_id 须是注册表 id；adopted dock 标 pwbAdopted，profile/
    // set_dock_visible/面板菜单照常驱动。
    void adopt_dock(const std::string& dock_id, QDockWidget* adopted);

    // 层位标签行（中央区上方，ws1-4 显示）：target_horizon 权威的又一
    // 视图/编辑器——与 StatusBar/Ribbon 尾部选择器同一权威，点击只发
    // horizon_requested；无候选时整行隐藏（诚实缺席）。
    void set_horizon_state(const QString& horizon,
                           const std::vector<QString>& options);
    QString current_horizon() const;
    // 工作区门禁：ws0 数据管理不显示层位行（prototype parity）。
    void set_horizon_strip_enabled(bool enabled);

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

    // V14-THREE-STAGE-UX: mount a host-provided global bar (the mapping
    // stage bar) on the app-bar toolbar row, right of the app bar.
    // One-shot: a second call is refused (returns false) — the bar is an
    // identity surface, not a swappable slot. Ownership transfers here
    // (reparent into the toolbar).
    bool mount_top_bar(QWidget* bar);
    bool top_bar_mounted() const { return top_bar_ != nullptr; }

    WorkstationAppBar* app_bar() const { return app_bar_; }
    ActivityRail* activity_rail() const { return rail_; }
    WorkstationExplorer* explorer() const { return explorer_; }
    // 左栏下部工作流面板（nav dock 内，explorer 之下的竖向分格）。
    WorkflowPanel* workflow_panel() const { return workflow_panel_; }
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
    // 层位标签行编辑请求（宿主接 stage_flow 权威写路径）。
    void horizon_requested(const QString& horizon);

protected:
    bool eventFilter(QObject* obj, QEvent* event) override;

private:
    QDockWidget* make_dock(const ui_shell::DockDescriptor& desc);
    QWidget* content_for(const std::string& dock_id, QWidget* parent);
    void sync_floating_minimum(QDockWidget* dock,
                               const ui_shell::DockDescriptor& desc);
    void apply_inspector_policy(int width);
    // Deferred dock tab grouping — runs once after the dock host's
    // first Show (see eventFilter).
    void finish_dock_layout();

    QMainWindow* dock_host_ = nullptr;
    QToolBar* app_bar_toolbar_ = nullptr;
    QWidget* central_ = nullptr;
    std::map<std::string, QDockWidget*> docks_;
    std::map<std::string, PanelFactory> factories_;
    std::string current_preset_;
    bool built_ = false;
    bool tabs_built_ = false;
    bool tearing_down_ = false;
    bool explorer_expanded_ = true;
    bool inspector_hidden_by_viewport_ = false;
    // The user's explicit inspector visibility choice (viewport policy
    // restores to this, not unconditionally to visible).
    bool inspector_user_visible_ = true;

    WorkstationAppBar* app_bar_ = nullptr;
    QWidget* top_bar_ = nullptr;
    ActivityRail* rail_ = nullptr;
    WorkstationExplorer* explorer_ = nullptr;
    QWidget* nav_column_ = nullptr;  // explorer + workflow 竖向分格容器
    WorkflowPanel* workflow_panel_ = nullptr;
    WorkstationInspector* inspector_ = nullptr;
    WorkstationTaskCenter* task_center_ = nullptr;
    WorkstationLogViewer* log_viewer_ = nullptr;
    AgentWorkspacePanel* agent_panel_ = nullptr;
    QTabBar* horizon_tabs_ = nullptr;
    bool horizon_strip_enabled_ = false;
    bool syncing_horizon_tabs_ = false;
};

}  // namespace pwb::ui_workstation
