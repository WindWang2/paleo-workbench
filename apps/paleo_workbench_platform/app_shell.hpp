#pragma once

// AppShell — the page-navigation composition root, rebuilt as the
// QGIS-native two-page frame (docs/ui-redesign/two-page-shell-2026-09-24):
//
//   outer layout: RibbonBar (数据管理 | 编图 tabs + file menu + QAT)
//                 over WorkspaceHostWidget (QStackedWidget, 2 pages)
//   page 0 数据管理 = DataManagementPage — 数据列表 + 信息展示
//                     (QSplitter 两栏; catalog 条目经宿主注入)
//   page 1 编图     = QgisAuthoringPage — an inner QMainWindow composed
//                     the QgisApp way: QgsMessageBar + QgsMapCanvas
//                     central, layer-tree/browser docks adopted into
//                     the page's own dock areas (Qt dock idiom).
//
// 所有旧功能面板（CompositeDocument/WorkstationFrame dock 宿主、阶段行、
// 验证页、测井/地震/三维页）已退役出界面——代码保留在项目内，但不再
// 实例化进壳层。本类保留既有公开签名供仍编译的宿主接线：退役面一律
// 返回 nullptr / 诚实 no-op，绝不伪造。
//
// Navigation: TWO WORKSPACES are the top-level axis. 编图页内三模式
// （智能预测/约束与单因素/综合编图）⇄ MappingStage —— mode commands
// (request_authoring_mode / mode.*) are the stage write surface; page
// entry never writes the stage (D1 preserved).
//
// Ctrl+K opens the CommandPalette over the global CommandRegistry; the
// ribbon command search button shares that registry.

#include <functional>
#include <memory>
#include <optional>
#include <string>

#include <QString>
#include <QStackedWidget>
#include <QWidget>

#include <pwb/tool_policy/stages.hpp>

class QComboBox;
class QDockWidget;
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
class PreparationPage;
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
namespace pwb::seismic_service {
class SeismicVolumeService;
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

class DataManagementPage;
class QgisAuthoringPage;
class ValidationWorkspacePage;
struct DataEntry;

// Central workspace stack — two-page shell. Two pages, fixed order:
// 数据管理 / 编图. A plain QStackedWidget subclass so tests and the
// host can address it by type.
class WorkspaceHostWidget : public QStackedWidget {
    Q_OBJECT
public:
    static constexpr int kPageData = 0;
    static constexpr int kPageAuthoring = 1;

    explicit WorkspaceHostWidget(QWidget* parent = nullptr);
};

class AppShell : public QWidget {
    Q_OBJECT
public:
    // Signature kept for the compiled install call-sites; the joint-host /
    // seismic-service seams are unused now that the feature pages are
    // retired from the shell frame.
    explicit AppShell(
        QWidget* parent = nullptr,
        pwb::ui_wellseis::qt::JointHostController* joint_host = nullptr,
        pwb::seismic_service::SeismicVolumeService* seismic_volume_service =
            nullptr);
    ~AppShell() override;

    // Host assembly (call once, before show): the session map canvas
    // becomes the authoring page's central canvas. The shell reparents
    // the widget — the owning session keeps its pointer.
    void install_canvas(QWidget* canvas, bool uses_native_stack = false);

    // 图层树 dock → 编图页左栏（QGIS 原版停靠区）。
    void adopt_layer_tree_dock(QDockWidget* dock);
    // 通用编图面板入口：外部 dock 收编进编图页的 dock 宿主（数据
    // 浏览器、后续功能面板都走这里；tabify_on 非空时并入同区页签）。
    void adopt_authoring_dock(QDockWidget* dock, Qt::DockWidgetArea area,
                              QDockWidget* tabify_on = nullptr);

    // ---- two-workspace navigation authority ------------------------------
    // User-intent entry (ribbon tab click, digit shortcuts, commands).
    // Workspace 0 → 数据管理 page; 1 → 编图 page. NEVER writes the stage
    // authority (D1) — the 编图 modes do that through
    // request_authoring_mode.
    void navigate_workspace(int workspace_index);

    // 编图模式 write path (ribbon mode toggles, palette, menus) — routes
    // the stage write through the ONE injected seam (stage_apply →
    // MainWindow::applyStageValue) and syncs the in-page mode projection.
    void request_authoring_mode(pwb::tool_policy::MappingStage stage);
    // Mode projection sync WITHOUT a stage write: ribbon context groups
    // follow the stage.
    void set_authoring_mode(const std::string& stage_value);
    std::string authoring_mode_value() const { return authoring_mode_value_; }
    pwb::tool_policy::MappingStage authoring_mode() const;
    // 验证 surface 已退役出界面 —— 入口保持诚实缺席（状态条提示）。
    void show_validation_dock();

    // Reverse sync (D1): called by the host when the stage authority
    // changed through another writer. The mode projection always follows;
    // the ribbon tab only mirrors while the 编图 page is current.
    void sync_workspace_for_stage(const std::string& stage_value);

    // Host-injected seams (absent = honest no-op):
    //  - stage write for the 编图 modes (routes to
    //    MainWindow::applyStageValue in the product).
    //  - presentation projection seam (retired surface: kept for the
    //    compiled call-sites; never invoked by this shell).
    void set_stage_apply(std::function<void(const std::string&)> seam);
    void set_presentation_apply(std::function<void(const std::string&)> seam);

    // Ribbon persistence (D7): (PaleoWorkbench, Workstation) QSettings
    // "ribbon/" keys through the host's services store.
    void set_ribbon_persistence(
        std::function<std::optional<std::string>(const std::string& key)> load,
        std::function<void(const std::string& key, const std::string& value)>
            save);
    // Restores ribbon mode + current workspace, then navigates (default
    // 数据管理). Called after the settings store is bound.
    void restore_ribbon_state();

    // Legacy hub-axis routing seam: hub 0 → 数据管理页; everything else →
    // 编图页（功能面已退役——状态条给出诚实提示）。
    void navigate_to(int hub_index, const QString& submodule_key = {});
    void show_hub_page(const QString& title);

    void shutdown_workers();

    // Chrome accessors. Retired surfaces return nullptr (compiled
    // call-sites null-check or are never invoked).
    pwb::ui_workstation::WorkstationFrame* workstation() const {
        return nullptr;
    }
    pwb::ui_composite::CompositeDocument* composite() const {
        return nullptr;
    }
    pwb::ui_shell::StatusBar* status_bar() const { return status_bar_; }
    pwb::ui_shell::AdaptivePageStack* page_stack() const { return nullptr; }
    pwb::ui_shell::CommandPalette* command_palette() const {
        return palette_;
    }
    pwb::ui_ribbon::qt::RibbonBar* ribbon() const { return ribbon_; }
    WorkspaceHostWidget* workspace_host() const { return workspace_host_; }

    // The two live pages.
    DataManagementPage* data_page() const { return data_page_; }
    QgisAuthoringPage* authoring_page() const { return authoring_page_; }
    // 数据管理页内容注入缝：宿主在工程打开/关闭/保存后重推 catalog
    // 条目（无工程时页面呈现诚实空态）。
    void set_data_entries(const QVector<DataEntry>& entries);

    // Retired feature surfaces — honest no-ops / nullptr for the compiled
    // call-sites (feature installs are not wired into this shell).
    void focus_stage_dock(const QString& title);
    void set_stage3_compose(QWidget* panel);
    void set_compose_mode(bool on);
    bool compose_mode() const { return compose_mode_; }
    ValidationWorkspacePage* validation_page() const { return nullptr; }
    pwb::ui_workstation::VerifyRecordsPanel* verify_records_panel() const {
        return nullptr;
    }
    QWidget* map_decor_panel() const { return nullptr; }
    QWidget* layout_output_panel() const { return nullptr; }

    // Page accessors — the feature pages are not instantiated; all
    // return nullptr.
    pwb::ui_pages_data::qt::HomePage* home_page() const { return nullptr; }
    pwb::ui_pages_data::qt::DataWorkspace* data_workspace() const {
        return nullptr;
    }
    pwb::ui_pages_data::qt::PreparationPage* preparation_page() const {
        return nullptr;
    }
    pwb::ui_wellseis::qt::WellLogPredictionPage* well_log_page() const {
        return nullptr;
    }
    pwb::ui_seqviz::qt::SequenceFrameworkPage* sequence_page() const {
        return nullptr;
    }
    pwb::ui_seqviz::qt::StratigraphyCorrelationPage* stratigraphy_page()
        const {
        return nullptr;
    }
    pwb::ui_wellseis::qt::SeismicPredictionPage* seismic_page() const {
        return nullptr;
    }
    pwb::ui_wellseis::qt::GeologicalModeling3DPage* geomodel_page() const {
        return nullptr;
    }
    pwb::ui_map::MappingPage* mapping_page() const { return nullptr; }
    pwb::ui_review::qt::ReviewExportPage* review_page() const {
        return nullptr;
    }
    pwb::ui_seqviz::qt::VisualizationPage* visualization_page() const {
        return nullptr;
    }

    void set_project_name(const QString& name);

    // 层位状态投影 —— 状态条 + Ribbon 尾部选择器同一权威。
    void set_horizon_state(const QString& horizon,
                           const std::vector<QString>& options = {});

    // Retired adopt seams (feature installs not wired): no-op / nullptr.
    void adopt_preparation_page(QWidget* page);
    QWidget* adopt_data_page(QWidget* composite);
    void bind_visualization_preview(
        pwb::ui_data_core::PreviewProvider provider);

signals:
    // Project actions forwarded to the host window.
    void new_project_requested();
    void open_project_requested();
    void open_sample_project_requested();
    void save_project_requested();
    void properties_requested();
    void preview_settings_requested();
    void about_requested();
    void exit_requested();
    void theme_requested(const QString& theme_value);
    void density_requested(const QString& density_value);
    void status_message(const QString& message);
    // 层位选择器编辑请求（宿主接 stage 权威写路径）。
    void horizon_requested(const QString& horizon);

private:
    void build_pages();
    void wire_ribbon();
    void setup_shortcuts();
    void persist_workspace(int workspace_index);
    // 状态栏「坐标 · CRS · 比例尺」段 —— 画布信号分头更新缓存后合并
    // 重发；horizon 段由层位权威另路投影。
    void sync_status_context();
    // 编图模式投影：Ribbon 上下文组（模式命令集）注入/清除。
    void inject_mode_groups(pwb::tool_policy::MappingStage stage);
    int authoring_mode_index() const;
    void handle_workstation_command(const QString& text);

    WorkspaceHostWidget* workspace_host_ = nullptr;
    DataManagementPage* data_page_ = nullptr;
    QgisAuthoringPage* authoring_page_ = nullptr;
    pwb::ui_ribbon::qt::RibbonBar* ribbon_ = nullptr;
    bool compose_mode_ = false;
    pwb::ui_shell::StatusBar* status_bar_ = nullptr;
    pwb::ui_shell::CommandPalette* palette_ = nullptr;

    // Host-injected seams (see the setters above; absent = no-op).
    std::function<void(const std::string&)> stage_apply_;
    std::function<void(const std::string&)> presentation_apply_;
    std::function<std::optional<std::string>(const std::string&)>
        ribbon_load_;
    std::function<void(const std::string&, const std::string&)> ribbon_save_;

    // Ribbon 命令带尾部常驻槽：层位选择器。
    QComboBox* ribbon_horizon_combo_ = nullptr;
    bool syncing_ribbon_horizon_ = false;
    QString status_coords_;
    QString status_crs_;
    QString status_scale_;
    // 编图页内模式（= ProjectSession::mapping_stage 的镜像，唯一写者
    // 是 stage 权威 → sync_workspace_for_stage / request_authoring_mode）。
    std::string authoring_mode_value_ = "facies_calibration";
    // 编图带中已注入的模式上下文组键。
    QStringList injected_mode_groups_;
};

}  // namespace pwb::app
