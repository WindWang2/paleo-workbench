#pragma once

// AppShell — the page-navigation composition root (W5/UI-17), port of
// paleo_workbench/ui/app_shell.py's assembly contract, M2-restructured per
// docs/development/ribbon-five-workspaces/00-plan.md (D1/D2):
//
//   outer layout: RibbonBar (five-workspace tabs + command bands) over
//                 WorkstationFrame (internal QMainWindow dock host)
//   WorkstationFrame.central = WorkspaceHostWidget (QStackedWidget, 3 pages)
//     page 0 数据管理  = the hub-0 assembly (概述 pill + the adopted
//                      composed data page) — moved OUT of the hub dock
//     page 1 科学宿主 = 纯 CompositeDocument (宿主注入画布) —— 阶段
//                      面板住进底部阶段行 dock（ws1 井震两联|预测任务|
//                      地震预测 / ws2 连井剖面|数据制备|地层对比|层序格架
//                      / ws3 单因素参考带），可悬浮/停靠/tab 化；
//                      workspaces 1/2/3 share this ONE QGIS canvas authority
//     page 2 验证     = ValidationWorkspacePage (M3, D5): 只读对照画布 +
//                      地震剖面 + QcIssueTable + InteractiveQCHub 定位
//   "hub" dock            = scroll-wrapped AdaptivePageStack (legacy
//                          vocabulary intact: slot 0 carries a migrated
//                          notice; well/seismic/viz/preparation stay
//                          reachable until M3)
//   composite_* docks     = CompositeDocument's own sub-panels
//   mapping_stage dock    = CompositeDocument's stage panel
//   nav/inspector/tasks/logs/console/agent = UI-12 default panels
//
// Navigation (M2): the FIVE WORKSPACES are the top-level axis. User intent
// (ribbon tab, digit shortcuts 1..5, nav.workspace.* commands) enters
// navigate_workspace(int); stage-backed workspaces (1/2/3) ALSO write the
// stage authority through the host-injected stage_apply seam (single write
// path: MainWindow::applyStageValue). Legacy callers (explorer cards,
// workflow pages.navigate_to) keep navigate_to(hub, subkey) — internally a
// ROUTING table onto workspaces or the legacy hub dock, never a second
// navigation implementation (F:27). Stage changes from other writers sync
// the ribbon tab back only while the science host page is current (D1:
// 数据管理/验证 never rewrite the stage).
//
// Ctrl+K opens the CommandPalette over the global CommandRegistry; the
// ribbon command search button and the ribbon's unbound placeholder
// buttons evaluate availability through the same registry.
//
// Service seams stay host-injected (DataPageServices / PrepareBackend /
// JointHost / preview providers …). Where a real adapter exists the window
// binds it; absent seams leave the ported pages' honest unavailable
// fallbacks — no fabricated backends.

#include <functional>
#include <memory>
#include <optional>
#include <string>

#include <QString>
#include <QStackedWidget>
#include <QWidget>

#include <pwb/ui_shell/deferred_page_bindings.hpp>

class QComboBox;
class QDockWidget;
class QShowEvent;
class QSplitter;
class QTabWidget;

namespace pwb::ui_composite {
class CompositeDocument;
}
namespace pwb::ui_data_core {
class PreviewProvider;
}
namespace pwb::ui_pages_data::qt {
class DataWorkspace;
class HomePage;
class HubPage;
}
namespace pwb::ui_wellseis::qt {
class GeologicalModeling3DPage;
class JointHostController;
class SeismicPredictionPage;
class WellLogPredictionPage;
}
namespace pwb::ui_seqviz::qt {
class SequenceFrameworkPage;
class StratigraphyCorrelationPage;
class VisualizationPage;
}
namespace pwb::ui_map {
class MappingPage;
}
namespace pwb::ui_review::qt {
class ReviewExportPage;
}
namespace pwb::ui_ribbon::qt {
class RibbonBar;
}
namespace pwb::ui_shell {
class AdaptivePageStack;
class CommandPalette;
class StatusBar;
}
namespace pwb::ui_workstation {
class VerifyRecordsPanel;
class WorkstationFrame;
}

namespace pwb::app {

class ValidationWorkspacePage;

// Central workspace stack (D2). Three pages, fixed order: 数据管理 /
// 科学宿主 (workspaces 1/2/3 share it) / 验证. A plain QStackedWidget
// subclass so tests and the host can address it by type.
class WorkspaceHostWidget : public QStackedWidget {
    Q_OBJECT
public:
    static constexpr int kPageData = 0;
    static constexpr int kPageScience = 1;
    static constexpr int kPageValidation = 2;

    explicit WorkspaceHostWidget(QWidget* parent = nullptr);
};

// 底部阶段行（dock 嵌套 row0）：每工作区一份阶段/预览 dock 成员集
// （navigate_workspace 投影；全隐时行塌陷）。成员 id 见注册表
// data_preview…factor_refs —— 面板化后无页栈常量。

class AppShell : public QWidget {
    Q_OBJECT
public:
    // joint_host (06 closure): the real joint 3D host injected by the
    // window (owned by the Geo3D dock). Null keeps the honest deferred
    // backend stub — the joint page then renders its Python-parity
    // placeholder instead of a fabricated scene.
    explicit AppShell(
        QWidget* parent = nullptr,
        pwb::ui_wellseis::qt::JointHostController* joint_host = nullptr);
    ~AppShell() override;

    // Host assembly (call once, before show): the session map canvas becomes
    // the composite document's central canvas. The shell reparents the
    // widget — the owning session keeps its pointer (attachCanvas already
    // bound). uses_native_stack mirrors CompositeDocument::set_canvas.
    void install_canvas(QWidget* canvas, bool uses_native_stack = false);

    // Replaces the prototype layer-manager dock with the session-owned
    // native QGIS layer tree. The prototype manager remains alive as a
    // hidden compatibility surface for workflow/controller bindings.
    void adopt_layer_tree_dock(QDockWidget* dock);

    // ---- M2: five-workspace navigation authority ----------------------------
    // User-intent entry (ribbon tab click, digit shortcuts, commands).
    // Workspace 0 → data page; 1/2/3 → the science host page AND the stage
    // authority write (through the injected stage_apply seam — absent seam
    // keeps the page switch honest in reduced builds); 4 → validation page.
    // 数据管理/验证 NEVER rewrite the stage (D1).
    void navigate_workspace(int workspace_index);

    // Reverse sync (D1): called by the host when the stage authority changed
    // through another writer (stage.goto command, StageDock, restore). Only
    // syncs the ribbon tab while the science host page is current; the
    // signal is blocked so no workspaceActivated loop can form.
    void sync_workspace_for_stage(const std::string& stage_value);

    // Host-injected seams (bound by the platform install; absent = honest
    // no-op, never a fabricated authority):
    //  - stage write for workspaces 1/2/3 (routes to
    //    MainWindow::applyStageValue in the product).
    //  - presentation projection for workspaces 0/4 (StageFlowController::
    //    apply_presentation — the extended StageLayoutProfile machinery).
    void set_stage_apply(std::function<void(const std::string&)> seam);
    void set_presentation_apply(std::function<void(const std::string&)> seam);

    // Ribbon persistence (D7): (PaleoWorkbench, Workstation) QSettings
    // "ribbon/" keys through the host's services store. Null sinks = the
    // shell runs unpersisted (reduced hosts/tests stay inert).
    void set_ribbon_persistence(
        std::function<std::optional<std::string>(const std::string& key)> load,
        std::function<void(const std::string& key, const std::string& value)>
            save);
    // Called by the host AFTER the settings store is bound (the shell is
    // constructed before the window's services store exists): restores the
    // ribbon mode + current workspace, then navigates (default 数据管理).
    void restore_ribbon_state();

    // Legacy hub-axis seam (Python navigate_to parity, M2 routing table):
    // hub 0 → workspace 0; 编图 canvas → workspace 3, review → workspace 4;
    // everything else (well/seismic/viz/preparation) stays on the 功能页
    // hub dock with a status notice until M3 migrates it.
    void navigate_to(int hub_index, const QString& submodule_key = {});
    // 功能页 dock show+raise (activate_legacy/show_hub_page parity).
    void show_hub_page(const QString& title);

    void shutdown_workers();

    pwb::ui_workstation::WorkstationFrame* workstation() const {
        return workstation_;
    }
    pwb::ui_composite::CompositeDocument* composite() const {
        return composite_;
    }
    pwb::ui_shell::StatusBar* status_bar() const { return status_bar_; }
    pwb::ui_shell::AdaptivePageStack* page_stack() const {
        return page_stack_;
    }
    pwb::ui_shell::CommandPalette* command_palette() const {
        return palette_;
    }
    // M2 chrome: the five-workspace ribbon and the central workspace stack.
    pwb::ui_ribbon::qt::RibbonBar* ribbon() const { return ribbon_; }
    WorkspaceHostWidget* workspace_host() const { return workspace_host_; }
    // M3 science-host — 面板化改订：中央 = 纯 QGIS 画布；阶段面板住
    // 进底部阶段行 dock（可悬浮/停靠/tab 化），测试与宿主经
    // workstation()->dock(id) 按注册表 id 取 dock。
    // ws2 底部「数据制备」dock 由 adopt_preparation_page 注入真实页面。
    // 底部阶段行 dock 按页签标题抬起（navigate_to 路由语义）。
    void focus_stage_dock(const QString& title);
    void set_stage3_compose(QWidget* panel);
    void set_compose_mode(bool on);
    bool compose_mode() const { return compose_mode_; }
    // M3 验证 workspace page (ws4) — the real composition page (P0-4).
    ValidationWorkspacePage* validation_page() const {
        return validation_page_;
    }
    // 底条「验证记录」面板（verify_records dock）——宿主经此绑定
    // quality_reports 数据源（provider seam；nullptr 直到 dock 构建）。
    pwb::ui_workstation::VerifyRecordsPanel* verify_records_panel() const {
        return verify_records_;
    }
    // ws3 右栏「图件整饰 / 版式输出」面板 —— 宿主经此接写回闭包。
    QWidget* map_decor_panel() const { return map_decor_; }
    // 版式输出面板由 m5_compose_install 经 set_stage3_compose 收编
    // 进 dock —— 读回经 dock->widget()（未收编时为占位/nullptr）。
    QWidget* layout_output_panel() const;

    // Page accessors for host wiring (non-owning).
    pwb::ui_pages_data::qt::HomePage* home_page() const {
        return home_page_;
    }
    pwb::ui_pages_data::qt::DataWorkspace* data_workspace() const {
        return data_workspace_;
    }
    pwb::ui_wellseis::qt::WellLogPredictionPage* well_log_page() const {
        return well_log_page_;
    }
    pwb::ui_seqviz::qt::SequenceFrameworkPage* sequence_page() const {
        return sequence_page_;
    }
    pwb::ui_seqviz::qt::StratigraphyCorrelationPage* stratigraphy_page()
        const {
        return stratigraphy_page_;
    }
    pwb::ui_wellseis::qt::SeismicPredictionPage* seismic_page() const {
        return seismic_page_;
    }
    pwb::ui_wellseis::qt::GeologicalModeling3DPage* geomodel_page() const {
        return geomodel_page_;
    }
    pwb::ui_map::MappingPage* mapping_page() const { return mapping_page_; }

    // BEGIN CLOSURE-MAPPING (08-line function lease — registered in
    // codex-coordination/cpp-close-wave/08-line.json; mirrors the 04-line
    // adopt_data_page pattern) Swap the hub-3 preparation placeholder for
    // the real page assembled by the closure installer.
    void adopt_preparation_page(QWidget* page);
    // END CLOSURE-MAPPING
    pwb::ui_review::qt::ReviewExportPage* review_page() const {
        return review_page_;
    }
    pwb::ui_seqviz::qt::VisualizationPage* visualization_page() const {
        return visualization_page_;
    }

    void set_project_name(const QString& name);

    // 层位状态投影（target_horizon 单一权威的三处视图：状态条选择器、
    // Ribbon 命令带尾部选择器、画布层位标签行）——宿主经此一处投影，
    // 三处互不复制状态；任一视图的编辑只回发 horizon_requested。
    void set_horizon_state(const QString& horizon,
                           const std::vector<QString>& options = {});

    // CLOSURE-PREVIEW (task 04, function-level lease via the wave
    // coordination registry): mount the composed data page over the bare
    // management workspace. The composite ADOPTS data_workspace_ (it is
    // reparented inside), so data_workspace() stays valid and the hub
    // submodule widget becomes `composite`. Returns the replaced widget
    // (nullptr when the composite is null). One-shot per shell lifetime.
    QWidget* adopt_data_page(QWidget* composite);

    // CLOSURE-PREVIEW (task 04, function-level lease): replace the
    // deferred message-stub base builder of the 可视化 page's preview
    // provider with the host-bound provider (parser-registry backed).
    void bind_visualization_preview(
        pwb::ui_data_core::PreviewProvider provider);

signals:
    // App bar / home-page project actions forwarded to the host window
    // (Python AppShell.*_requested parity).
    void new_project_requested();
    void open_project_requested();
    void open_sample_project_requested();
    void save_project_requested();
    void properties_requested();
    void preview_settings_requested();
    void about_requested();
    // Ribbon file-menu exit (the host window owns the close decision).
    void exit_requested();
    // View-menu requests — the host owns the theme authority.
    void theme_requested(const QString& theme_value);
    void density_requested(const QString& density_value);
    void status_message(const QString& message);
    // Ribbon 尾部层位选择器的编辑请求（宿主接 stage_flow 权威写路径，
    // 与 StatusBar::horizon_requested 同一信号语义）。
    void horizon_requested(const QString& horizon);

private:
    void build_pages();
    void build_workspace_host();
    void wire_ribbon();
    void wire_workstation();
    void setup_shortcuts();
    void handle_workstation_command(const QString& text);
    void persist_workspace(int workspace_index);
    // 状态栏「坐标 · CRS · 比例尺」段 —— 画布信号分头更新缓存后合并
    // 重发（update_context 一次写全段；horizon 段由层位权威另路投影）。
    void sync_status_context();
    // M3: 阶段组合 —— 底部阶段行 dock 投影（stage→workspace 成员集）；
    // 行内显隐走占位护栏，行高首揭时一次性播种。
    void apply_stage_composition(const std::string& stage_value);
    void apply_stage_dock_profile(int workspace_index);
    // M5-2: enter/leave 版式模式（抬起右栏「版式输出」dock，F:70）。
    void apply_compose_mode();
    // M5-3: focus a validation rail tab by title (页内页签保留)。
    static void focus_stage_tab(QTabWidget* tabs, const QString& title);
    // 左栏工作流面板按工作区换内容（步骤清单 / 验证设置勾选）；步骤
    // 点击经 command_registry 走既有命令路径（workflow_command_ids_
    // 为当前工作区的步骤→命令映射）。
    void sync_workflow_panel(int workspace_index);

    pwb::ui_workstation::WorkstationFrame* workstation_ = nullptr;
    pwb::ui_composite::CompositeDocument* composite_ = nullptr;
    WorkspaceHostWidget* workspace_host_ = nullptr;
    pwb::ui_ribbon::qt::RibbonBar* ribbon_ = nullptr;
    // 底部阶段行行高已播种（首次揭行一次性 resizeDocks；之后用户
    // 拖动即用户权威）。
    bool stage_row_seeded_ = false;
    bool compose_mode_ = false;
    ValidationWorkspacePage* validation_page_ = nullptr;
    pwb::ui_shell::AdaptivePageStack* page_stack_ = nullptr;
    pwb::ui_shell::StatusBar* status_bar_ = nullptr;
    pwb::ui_shell::CommandPalette* palette_ = nullptr;
    pwb::ui_shell::DeferredPageBindings deferred_;

    // M2 host-injected seams (see the setters above; absent = no-op).
    std::function<void(const std::string&)> stage_apply_;
    std::function<void(const std::string&)> presentation_apply_;
    std::function<std::optional<std::string>(const std::string&)>
        ribbon_load_;
    std::function<void(const std::string&, const std::string&)> ribbon_save_;

    // Ribbon 命令带尾部常驻槽：层位选择器（三视图之一，见
    // set_horizon_state）。
    QComboBox* ribbon_horizon_combo_ = nullptr;
    bool syncing_ribbon_horizon_ = false;
    QString status_coords_;
    QString status_crs_;
    QString status_scale_;
    QStringList workflow_command_ids_;
    // Per-workspace right-dock panel instances (created lazily by the
    // dock factories; non-owning — docks own them).
    QWidget* predict_compare_ = nullptr;
    QWidget* reference_layers_ = nullptr;
    QWidget* map_decor_ = nullptr;
    pwb::ui_workstation::VerifyRecordsPanel* verify_records_ = nullptr;

    // Joint-host seam (06): the window injects the real host (owned by
    // the Geo3D dock); without one the fallback stub reports
    // has_scene=false so GeologicalModeling3DPage renders its honest
    // engine-unavailable surface (never fabricated).
    pwb::ui_wellseis::qt::JointHostController* joint_host_ = nullptr;
    // Owns the fallback stub only when no real host was injected (the
    // real host is owned by the Geo3D dock — never double-owned here).
    std::unique_ptr<pwb::ui_wellseis::qt::JointHostController>
        fallback_joint_host_;

    pwb::ui_pages_data::qt::HubPage* hub_data_ = nullptr;
    // M5-3: hub 轴解散 —— well/seismic/mapping 的 HubPage 外壳已拆除，
    // 页面直接住在工作区（见 build_workspace_host）；page_stack_ 只
    // 剩「编图工具」dock 的单页内容（mapping_page_）。

    pwb::ui_pages_data::qt::HomePage* home_page_ = nullptr;
    pwb::ui_pages_data::qt::DataWorkspace* data_workspace_ = nullptr;
    bool data_page_adopted_ = false;  // CLOSURE-PREVIEW one-shot guard
    pwb::ui_wellseis::qt::WellLogPredictionPage* well_log_page_ = nullptr;
    pwb::ui_seqviz::qt::SequenceFrameworkPage* sequence_page_ = nullptr;
    pwb::ui_seqviz::qt::StratigraphyCorrelationPage* stratigraphy_page_ =
        nullptr;
    pwb::ui_wellseis::qt::SeismicPredictionPage* seismic_page_ = nullptr;
    pwb::ui_wellseis::qt::GeologicalModeling3DPage* geomodel_page_ = nullptr;
    pwb::ui_map::MappingPage* mapping_page_ = nullptr;
    pwb::ui_review::qt::ReviewExportPage* review_page_ = nullptr;
    pwb::ui_seqviz::qt::VisualizationPage* visualization_page_ = nullptr;
};

}  // namespace pwb::app
