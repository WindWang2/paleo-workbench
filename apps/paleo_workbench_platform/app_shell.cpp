#include "app_shell.hpp"

#include <cstddef>
#include <iterator>

#include <QComboBox>
#include <QDebug>
#include <QDockWidget>
#include <QFrame>
#include <QHBoxLayout>
#include <QLabel>
#include <QLocale>
#include <QMenu>
#include <QScrollArea>
#include <QShowEvent>
#include <QTimer>
#include <QSignalBlocker>
#include <QSplitter>
#include <QTabWidget>
#include <QVBoxLayout>

#include <qgsmapcanvas.h>
#include <qgspointxy.h>
#include <qgscoordinatereferencesystem.h>

#include <pwb/ui_composite/composite_document.hpp>
#include <pwb/ui_composite/input_tree_panel.hpp>
#include <pwb/ui_composite/linked_views_panel.hpp>
#include <pwb/ui_composite/linked_workspace.hpp>
#include <pwb/ui_composite/mapping_stage_panel.hpp>
#include <pwb/ui_data_core/preview_provider.hpp>
#include <pwb/ui_map/map_chrome_panel.hpp>
#include <pwb/ui_map/mapping_page.hpp>
#include <pwb/ui_pages_data/qt/data_reader_panel.hpp>
#include <pwb/ui_pages_data/qt/data_workspace.hpp>
#include <pwb/ui_pages_data/qt/home_page.hpp>
#include <pwb/ui_pages_data/qt/hub_page.hpp>
#include <pwb/ui_pages_data/qt/navigation_tree_widget.hpp>
#include <pwb/ui_pages_data/qt/preparation_page.hpp>
#include <pwb/ui_review/qt/review_export_page.hpp>
#include <pwb/ui_ribbon/qt/ribbon_bar.hpp>
#include <pwb/ui_seqviz/geoviz_provider.hpp>
#include <pwb/ui_seqviz/qt/correlation_page.hpp>
#include <pwb/ui_seqviz/qt/sequence_framework_page.hpp>
#include <pwb/ui_seqviz/qt/visualization_page.hpp>

#include "compilation_layer_panel.hpp"
#include "factor_atlas_panel.hpp"
#include "reference_legend_panel.hpp"
#include <pwb/ui_shell/adaptive_page_stack.hpp>
#include <pwb/ui_shell/command_palette.hpp>
#include <pwb/ui_shell/command_registry.hpp>
#include <pwb/ui_shell/map_status_bar.hpp>
#include <pwb/ui_shell/navigation.hpp>
#include <pwb/ui_shell/page_placeholder.hpp>
#include <pwb/ui_shell/shortcut_registry.hpp>
#include <pwb/ui_shell/status_bar.hpp>
// BEGIN CLOSURE-SEISMIC (07) — real seismic display binding for hub 2.
#if defined(PWB_WITH_CLOSURE_SEISMIC)
#include "closure_seismic_install.hpp"
#include <pwb/seismic_service/volume_service.hpp>
#endif
// END CLOSURE-SEISMIC
#include <pwb/ui_wellseis/qt/engine_seams.hpp>
#include <pwb/ui_wellseis/qt/geological_modeling_3d_page.hpp>
#include <pwb/ui_wellseis/qt/seismic_prediction_page.hpp>
#include <pwb/ui_wellseis/qt/well_log_prediction_page.hpp>
#include <pwb/ui_widgets/facies_palette_widget.hpp>
#include <pwb/ui_workstation/activity_rail.hpp>
#include <pwb/ui_workstation/app_bar.hpp>
#include <pwb/ui_workstation/explorer_panel.hpp>
#include <pwb/ui_workstation/verify_records_panel.hpp>
#include <pwb/ui_workstation/workflow_panel.hpp>
#include <pwb/ui_workstation/workstation_frame.hpp>

#include "validation_workspace_page.hpp"

namespace pwb::app {

namespace {

// Joint-host seam fallback (06 closure): used only when the window has
// no real host to inject (no Geo3D dock — e.g. GEO3D_VIZ disabled). It
// reports the honest unavailable state — GeologicalModeling3DPage
// renders its Python-parity placeholder path (has_scene() == false)
// instead of a fabricated scene.
class UnavailableJointHost : public ui_wellseis::qt::JointHostController {
public:
    using ui_wellseis::qt::JointHostController::JointHostController;

    bool shutdown(int) override { return true; }
    void reload() override {}
    ui_wellseis::qt::JointSceneSnapshot scene_snapshot() const override {
        return {};
    }
    bool has_scene() const override { return false; }
    std::string engine_error() const override {
        return "joint engine host unavailable (deferred backend)";
    }
    std::vector<std::pair<std::string, std::string>> well_options()
        const override {
        return {};
    }
    bool set_vertical_domain(const std::string&) override { return false; }
    void add_well_to_well_fence(const std::string&, const std::string&,
                                const std::string&) override {}
    void delete_active_fence() override {}
    void set_orthogonal_slice_indices(std::optional<int>,
                                      std::optional<int>) override {}
    void restore_orthogonal_slice_state(
        std::optional<int>, std::optional<int>,
        const std::vector<ui_wellseis::qt::JointTimeSliceEntry>&,
        std::optional<double>, double) override {}
    bool apply_slice_line_numbers(double, double) override { return false; }
    void add_time_slice(double) override {}
    void remove_time_slice(double) override {}
    void set_time_slice_visible(double, bool) override {}
    void set_active_time_slice(double) override {}
    void set_time_opacity(double) override {}
    void set_3d_mode(const std::string&) override {}
    void set_color_scales(const std::string&, const std::string&) override {}
    void set_well_width(int) override {}
    void set_well_visibility(const std::string&, bool) override {}
    void set_layer_visibility(const std::string&, bool) override {}
    void apply_camera_preset(const std::string&) override {}
    std::string well_identity_asset_id() const override { return {}; }
    std::map<std::string, std::string> well_identity_map() const override {
        return {};
    }
    std::map<std::string, std::string> path_hints() const override {
        return {};
    }
    std::vector<std::string> loaded_data_paths() const override { return {}; }
    bool highlight_well(const std::string&) override { return false; }
    bool focus_position(int, int, std::optional<double>) override {
        return false;
    }
    QWidget* joint_widget(QWidget*) override { return nullptr; }
    void push_scene_to_widget() override {}
};

}  // namespace

// ---------------------------------------------------------------------------
// WorkspaceHostWidget (D2) — the three-page central stack.
// ---------------------------------------------------------------------------

WorkspaceHostWidget::WorkspaceHostWidget(QWidget* parent)
    : QStackedWidget(parent) {
    setObjectName(QStringLiteral("WorkspaceHost"));
}

AppShell::AppShell(QWidget* parent,
                   ui_wellseis::qt::JointHostController* joint_host,
                   seismic_service::SeismicVolumeService* seismic_volume_service)
    : QWidget(parent),
      joint_host_(joint_host),
      seismic_volume_service_(seismic_volume_service) {
    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(0, 0, 0, 0);
    outer->setSpacing(0);

    // --- hub pages (Python app_shell page-stack assembly parity) --------
    page_stack_ = new ui_shell::AdaptivePageStack(this);

    build_pages();

    // --- M2 chrome: the five-workspace ribbon sits above the workstation
    // frame (层次 R:17: 文件菜单+五工作区标签 → Ribbon 命令带 → 停靠区).
    ribbon_ = new ui_ribbon::qt::RibbonBar(this);
    outer->addWidget(ribbon_);
    wire_ribbon();

    // --- workstation frame: the WORKSPACE HOST is the central content
    // (D2); the legacy page stack stays in the 功能页 (hub) dock.
    composite_ = new ui_composite::CompositeDocument(this);
    // 原型只有窗口底部一条状态栏 —— 复合文档内嵌 MapStatusBar（旧版
    // 画布下条带）隐藏，坐标/比例尺/CRS 经 update_context 前送到壳层
    // 状态栏（install_canvas 接线），编辑态读数（捕捉/拓扑）随宿主
    // 未绑定而保持诚实空态。
    composite_->status_bar->hide();
    build_workspace_host();
    workstation_ = new ui_workstation::WorkstationFrame(this);
    workstation_->set_central_widget(workspace_host_);
    wire_workstation();
    workstation_->build_docks();
    workstation_->apply_first_run_sizes();

    // 帧级层位条（build_docks 后才存在）—— 与状态条/Ribbon 尾部选择
    // 器同一 target_horizon 权威，只回发请求不持状态。
    connect(workstation_,
            &ui_workstation::WorkstationFrame::horizon_requested,
            this, &AppShell::horizon_requested);

    // dock 宿主首显后：重放当前工作区的页内阶段窗格选择 —— 启动时序
    // 里 navigate_workspace 先于宿主显示。
    connect(workstation_,
            &ui_workstation::WorkstationFrame::dock_layout_ready,
            this, [this] {
                const int ws =
                    ribbon_ != nullptr ? ribbon_->current_workspace() : 0;
                if (ws >= 1 && ws <= 3 && stage_stack_ != nullptr) {
                    stage_stack_->setCurrentIndex(ws - 1);
                }
            });

    // 底条「验证记录」双击行 → 验证工作区（问题详情在页内右列）。
    if (auto* records = verify_records_panel()) {
        connect(records, &ui_workstation::VerifyRecordsPanel::record_activated,
                this, [this](int) { navigate_workspace(4); });
    }

    // 左栏工作流面板（nav dock 内部件，build_docks 后才存在）：步骤
    // 点击经 command_registry 走既有命令路径（与 Ribbon 按钮同一回
    // 调——无第二实现）；勾选行只做状态镜像。
    if (auto* workflow = workstation_->workflow_panel()) {
        connect(workflow, &ui_workstation::WorkflowPanel::step_activated,
                this, [this](int index) {
                    const QString command_id =
                        workflow_command_ids_.value(index);
                    if (command_id.isEmpty()) return;
                    auto& registry = ui_shell::command_registry();
                    const auto* spec =
                        registry.get(command_id.toStdString());
                    if (spec == nullptr || !spec->callback) {
                        emit status_message(
                            QStringLiteral("命令未绑定：%1")
                                .arg(command_id));
                        return;
                    }
                    registry.record_recent(command_id.toStdString());
                    spec->callback();
                });
        connect(workflow, &ui_workstation::WorkflowPanel::check_toggled,
                this, [this](int index, bool on) {
                    static const char* names[] = {
                        "空间对齐", "井点符合", "层位一致", "输入版本"};
                    if (index < 0 || index >= 4) return;
                    emit status_message(
                        QStringLiteral("验证项「%1」已%2")
                            .arg(QString::fromUtf8(names[index]),
                                 on ? QStringLiteral("启用")
                                    : QStringLiteral("停用")));
                });
    }

    outer->addWidget(workstation_, 1);

    // 主状态条：无顶层 dock 宿主时退化为内容底部条（Python parity — the
    // host window may additionally park it on its native statusBar).
    status_bar_ = new ui_shell::StatusBar(this);
    outer->addWidget(status_bar_);

    // Ctrl+K palette over the global registry (Python parity: non-modal
    // child, offscreen safe).
    palette_ = new ui_shell::CommandPalette(
        this, ui_shell::command_registry());

    setup_shortcuts();

    // First landing: 数据管理 workspace — instant, no fade (Python parity:
    // the fade's QGraphicsOpacityEffect forces GL children of hidden
    // sibling pages to initialize offscreen).
    navigate_workspace(0);
}

AppShell::~AppShell() = default;

void AppShell::adopt_layer_tree_dock(QDockWidget* dock) {
    // The native QgsLayerTreeView dock takes over the legacy
    // "composite_layer" dock slot — the retired prototype LayerManagerPanel
    // no longer exists to be hidden here (QGIS tree = the one layer list).
    if (dock == nullptr || workstation_ == nullptr) {
        return;
    }
    // 稿式容器（主要图层 + 参考图节 + ws3 整饰行）—— navigate_workspace
    // 按工作区切 Compilation/Checklist 模式。
    layer_tab_panel_ =
        qobject_cast<CompilationLayerPanel*>(dock->widget());
    workstation_->adopt_dock("composite_layer", dock);
}

void AppShell::build_pages() {
    using ui_pages_data::qt::HubPage;

    // M5-3 hub 轴解散：页面直接成为工作区内容（见 build_workspace_host
    // 的落位）。仅 hub-0 保留 HubPage 外壳——它就是 ws0 的概述/数据管理
    // 页内导航，不是遗留 hub。workflow 的 deferred bindings 仍以
    // kPageIndex* 为 flush 键（一次性排干，见 navigate_workspace）。
    home_page_ = new ui_pages_data::qt::HomePage(this);
    data_workspace_ = new ui_pages_data::qt::DataWorkspace(this);
    hub_data_ = new HubPage(ui_shell::kPageIndexData, page_stack_);
    hub_data_->add_submodule("overview", "项目概述", home_page_);
    hub_data_->add_submodule("management", "数据管理", data_workspace_);
    hub_data_->finish();
    // Prototype ws0 lands on the data list, not the overview — and shows
    // NO pill row（子模块导航走左侧资源树的 概览/数据管理 节点）。
    hub_data_->set_switcher_visible(false);
    hub_data_->switch_to("management");
    // Prototype ws0 的左列归壳层 explorer（对象树）；页内 facet
    // 导航树（生命阶段/标签/完整性筛选）与它是重复面 —— 隐藏后
    // 页 = [数据列表 | 数据属性] 两列，过滤走表格自身工具条。
    data_workspace_->navigation_tree()->hide();
    page_stack_->addWidget(hub_data_);

    // ws1 智能预测：测井预测（输入与证据页）+ 地震预测（输入侧）。
    well_log_page_ =
        new ui_wellseis::qt::WellLogPredictionPage(this);
    sequence_page_ =
        new ui_seqviz::qt::SequenceFrameworkPage(this);
    stratigraphy_page_ =
        new ui_seqviz::qt::StratigraphyCorrelationPage(this);
    seismic_page_ = new ui_wellseis::qt::SeismicPredictionPage(this);
// BEGIN CLOSURE-SEISMIC (07) — bind the prediction page's view panel to the
// real seismic viewer stack (volume service + horizon-pick viewer). Without
// the closure deps the panel keeps its honest empty-placeholder behavior.
#if defined(PWB_WITH_CLOSURE_SEISMIC)
    // D4：宿主注入的窗口级 volume service（无函数内 static —— 每窗口
    // 壳不再暗藏进程级服务状态）；未注入时页面保持诚实的未绑定占位。
    if (seismic_volume_service_ != nullptr) {
        // binding parent 到 page 本体（随页销毁）——无需持有指针。
        (void)pwb::closure_seismic::install_seismic_page(
            {seismic_page_, seismic_volume_service_});
    }
#endif
// END CLOSURE-SEISMIC
    if (joint_host_ == nullptr) {
        fallback_joint_host_ = std::make_unique<UnavailableJointHost>();
        joint_host_ = fallback_joint_host_.get();
    }
    // ws4 验证的可选 3D 对照视图（D6）：06 closure 注入真实 joint host；
    // 无 host 时页面保持诚实 deferred-backend 占位。
    geomodel_page_ = new ui_wellseis::qt::GeologicalModeling3DPage(
        this, joint_host_);

    // 编图要素编辑页（MapEditView 宿主）→ 「编图工具」dock（hub dock
    // 收窄后的唯一内容；会话画布 CompositeDocument 仍是 ws3 主图权威）。
    mapping_page_ = new ui_map::MappingPage(this);
    page_stack_->addWidget(mapping_page_);  // dock 的单页内容
    // Review actions seam (IReviewActions) is a project-backend binding
    // — absent in the shell host: the provider returns nullptr and the
    // page renders its Python-parity "未绑定工程" guard. The page lives
    // in the ws4 验证 rail (报告导出 tab).
    review_page_ = new ui_review::qt::ReviewExportPage(
        this,
        []() -> ui_review::IReviewActions* { return nullptr; });

    // hub 4 可视化 RETIRED (D6): the page object stays alive (the
    // closure-preview provider binding and the preview-settings dialog
    // still reference it) but enters no UI surface — 预览能力由数据管理
    // 的读取面板承担。navigate_to(可视化) → ws0 + 退役说明。
    ui_seqviz::LocalVizProvider viz_provider(
        [](const ui_data_core::AssetObjectData&,
           const ui_data_core::PreviewSettings&)
            -> ui_data_core::PreviewResult {
            ui_data_core::PreviewResult result;
            result.mode = ui_data_core::preview_mode::kMessage;
            result.message = "预览服务未绑定（解析注册表 seam 未接入）";
            return result;
        });
    visualization_page_ = new ui_seqviz::qt::VisualizationPage(
        this, viz_provider.request_provider());
    visualization_page_->hide();
}

namespace {

// 页内阶段窗格（mockup 题头条 + 内容槽）：题头是窗格自身的一部
// 分（不是 dock 标题栏）——稿中「连井剖面（与地图联动）」/
// 「单因素参考 · 联动显示」式。返回内容宿主，宿主安装器往里注入
// 真实面板。
// 页内阶段窗格：带题头的外框 + 内容宿主。外框入栈（栈页 = frame），
// 返回内容宿主供安装器注入 —— 若把 host 直接入栈会被重父出离外框，
// 题头框沦为游离子控件叠在栈角（曾造成题头重影）。
QWidget* make_stage_pane(const QString& title, const QString& content_name,
                         QStackedWidget* stack) {
    auto* frame = new QFrame(stack);
    frame->setObjectName(content_name + QStringLiteral("Pane"));
    frame->setFrameShape(QFrame::StyledPanel);
    auto* layout = new QVBoxLayout(frame);
    layout->setContentsMargins(6, 2, 6, 0);
    layout->setSpacing(0);
    auto* header = new QLabel(title, frame);
    header->setObjectName(QStringLiteral("StagePaneTitle"));
    layout->addWidget(header);
    auto* host = new QWidget(frame);
    host->setObjectName(content_name);
    auto* host_layout = new QVBoxLayout(host);
    host_layout->setContentsMargins(0, 0, 0, 0);
    host_layout->setSpacing(0);
    auto* hint = new QLabel(
        QStringLiteral("（打开工程并产出对应数据后在此显示）"), host);
    hint->setObjectName(QStringLiteral("StageBottomHint"));
    hint->setAlignment(Qt::AlignCenter);
    host_layout->addWidget(hint);
    layout->addWidget(host, 1);
    stack->addWidget(frame);
    return host;
}

}  // namespace

void AppShell::build_workspace_host() {
    workspace_host_ = new WorkspaceHostWidget(this);
    // Page 0 数据管理: the hub-0 assembly (概述 pill + management tab where
    // the closure preview adopts the composed data page) BECOMES the
    // workspace page (D2: reuse the assembled product, overview stays an
    // in-page entry). M5-3: the legacy stack slots are dissolved — the
    // page_stack_ now carries ONLY the 编图工具 dock page (mapping_page_).
    page_stack_->removeWidget(hub_data_);
    workspace_host_->addWidget(hub_data_);  // reparents into the host

    // Page 1 科学宿主 (mockup-faithful-2026-09-24)：中列 = QSplitter(V)
    // { CompositeDocument（workspaces 1/2/3 共享的 QGIS 画布权威）,
    //   页内阶段窗格栈 }。稿中井震两联/连井剖面/单因素参考带是中列
    // 底部固定区（受左右栏夹界），不是全宽 dock —— 窗格住进页内
    // QStackedWidget，navigate_workspace 按工作区选页。
    auto* science_page = new QWidget(this);
    science_page->setObjectName(QStringLiteral("ScienceHostPage"));
    auto* science_layout = new QVBoxLayout(science_page);
    science_layout->setContentsMargins(0, 0, 0, 0);
    science_layout->setSpacing(0);
    auto* science_split = new QSplitter(Qt::Vertical, science_page);
    science_split->setObjectName(QStringLiteral("ScienceStageSplit"));
    science_split->setChildrenCollapsible(false);
    composite_->setParent(science_page);
    science_split->addWidget(composite_);
    stage_stack_ = new QStackedWidget(science_split);
    stage_stack_->setObjectName(QStringLiteral("ScienceStageStack"));
    // ws1 井震两联 —— 裸宿主（两幅子窗格自带题头）；compose 安装器
    // 经 stage_pane_pair() 注入地震+测井 split。
    stage_pair_host_ = new QWidget(stage_stack_);
    stage_pair_host_->setObjectName(QStringLiteral("PredictionPairHost"));
    {
        auto* layout = new QVBoxLayout(stage_pair_host_);
        layout->setContentsMargins(0, 0, 0, 0);
        auto* hint = new QLabel(
            QStringLiteral(
                "地震剖面 + 测井轨道两联（打开工程后从数据管理载入"
                "体版本 / 井曲线）"),
            stage_pair_host_);
        hint->setObjectName(QStringLiteral("StageBottomHint"));
        hint->setAlignment(Qt::AlignCenter);
        layout->addWidget(hint);
    }
    stage_stack_->addWidget(stage_pair_host_);
    // ws2 连井剖面 —— 稿内题头「连井剖面（与地图联动）」；
    // compose 安装器经 stage_pane_crosswell() 注入 VizB 剖面内容。
    stage_crosswell_host_ =
        make_stage_pane(QStringLiteral("连井剖面（与地图联动）"),
                        QStringLiteral("CrossWellStageHost"),
                        stage_stack_);
    // ws3 单因素参考带 —— 稿内题头「单因素参考 · 联动显示」；
    // compose 安装器经 stage_pane_factor() 注入 FactorReferenceStrip。
    stage_factor_host_ =
        make_stage_pane(QStringLiteral("单因素参考 · 联动显示"),
                        QStringLiteral("StageBottomCompilationHome"),
                        stage_stack_);
    science_split->addWidget(stage_stack_);
    science_split->setStretchFactor(0, 7);
    science_split->setStretchFactor(1, 3);
    science_layout->addWidget(science_split);
    workspace_host_->addWidget(science_page);

    // Page 2 验证 (M3, D5): the real composition page — read-only compare
    // canvas + seismic pane slot + structured issues + review detail with
    // locate. The M5 gaps stay explicit placeholders inside the page.
    validation_page_ = new ValidationWorkspacePage(this);
    workspace_host_->addWidget(validation_page_);
}

// BEGIN CLOSURE-MAPPING (08-line adopt)
void AppShell::adopt_preparation_page(QWidget* page) {
    if (page == nullptr || workstation_ == nullptr) return;
    // #1455: remember the page so shutdown_workers() reaches its
    // worker lanes — the adoption used to drop the pointer, leaving the
    // prepare/contour tasks to a destructor-time unbounded join (window
    // close froze the GUI until the kernel finished).
    if (auto* preparation =
            qobject_cast<pwb::ui_pages_data::qt::PreparationPage*>(page);
        preparation != nullptr) {
        preparation_page_ = preparation;
    }
    // mockup 精确还原：稿 ws2 无「数据制备」面 —— 页面留在工程内不
    // 进界面（功能存续，prepare/contour worker 仍由 shutdown_workers
    // 关停）；原 data_prep dock 已退役为隐藏注册表项。
    page->hide();
    page->setParent(this);
}
// END CLOSURE-MAPPING

void AppShell::wire_ribbon() {
    // B1（shell 收敛）：此处的临时最小文件菜单已删除——宿主
    // MainWindow::wire_ribbon_commands 安装唯一文件菜单（同一批共享
    // QAction，含 MRU/面板/布局）。这里不再制造第二个菜单 identity。
    // 项目动作信号保留：WorkstationAppBar（隐藏的全局栏）仍经它们转发。

    // Ctrl+F1 collapse entry through the central registry (conflicts()
    // gate lives in the ribbon library).
    ribbon_->set_shortcut_registry(&ui_shell::shortcut_registry());

    // 命令搜索 — the same Ctrl+K palette entry, second surface (R:20).
    connect(ribbon_, &ui_ribbon::qt::RibbonBar::searchRequested, this,
            [this] { palette_->popup(); });

    // B3（shell 收敛）：壳层不再装临时 evaluator——宿主
    // MainWindow::wire_ribbon_commands 装配带活体会话快照的正式版本
    // （unregistered 命令保持启用的 fail-open 语义在宿主版本同样成立）。

    // Command routing: bound commands live in the registry (palette parity:
    // record recent + run the one callback); an unbound placeholder is an
    // honest no-op until M4 rebinds it — never a fabricated action.
    connect(ribbon_, &ui_ribbon::qt::RibbonBar::commandTriggered, this,
            [this](const QString& command_id) {
                auto& registry = ui_shell::command_registry();
                const auto* spec =
                    registry.get(command_id.toStdString());
                if (spec == nullptr || !spec->callback) {
                    qInfo() << "ribbon command not bound yet (M4):"
                            << command_id;
                    return;
                }
                registry.record_recent(command_id.toStdString());
                spec->callback();
            });

    // THE workspace axis: ribbon tab -> navigate_workspace (the one
    // navigation implementation — F:27 no second entry).
    connect(ribbon_, &ui_ribbon::qt::RibbonBar::workspaceActivated, this,
            &AppShell::navigate_workspace);

    // Ribbon 命令带尾部常驻槽（R:49 关键选择）：层位选择器——与状态条
    // 层位下拉同一 target_horizon 权威的又一视图/编辑器，只回发
    // horizon_requested，不持有状态。
    if (auto* host = ribbon_->band_trailing_host()) {
        auto* trailing = new QWidget(host);
        trailing->setObjectName(QStringLiteral("RibbonHorizonField"));
        auto* row = new QHBoxLayout(trailing);
        row->setContentsMargins(0, 0, 0, 0);
        row->setSpacing(6);
        auto* label = new QLabel(QStringLiteral("层位"), trailing);
        row->addWidget(label);
        ribbon_horizon_combo_ = new QComboBox(trailing);
        ribbon_horizon_combo_->setObjectName(
            QStringLiteral("RibbonHorizonCombo"));
        ribbon_horizon_combo_->setEditable(false);
        ribbon_horizon_combo_->setMinimumWidth(96);
        ribbon_horizon_combo_->setPlaceholderText(
            QStringLiteral("选择层位"));
        ribbon_horizon_combo_->setAccessibleName(
            QStringLiteral("层位"));
        ribbon_horizon_combo_->setToolTip(
            QStringLiteral("目标层位（写入工程 stratigraphy）"));
        connect(ribbon_horizon_combo_, &QComboBox::currentIndexChanged,
                this, [this](int index) {
                    if (syncing_ribbon_horizon_ || index < 0) return;
                    emit horizon_requested(
                        ribbon_horizon_combo_->itemText(index));
                });
        row->addWidget(ribbon_horizon_combo_);
        ribbon_->set_band_trailing(trailing);
    }

    // Nav-row 任务/Agent 入口 — the same dock toggles the app bar used.
    connect(ribbon_, &ui_ribbon::qt::RibbonBar::taskCenterRequested, this,
            [this] {
                const auto* d = workstation_->dock("tasks");
                workstation_->set_dock_visible(
                    "tasks", d == nullptr || !d->isVisible());
            });
    connect(ribbon_, &ui_ribbon::qt::RibbonBar::agentRequested, this,
            [this] {
                const auto* d = workstation_->dock("agent");
                workstation_->set_dock_visible(
                    "agent", d == nullptr || !d->isVisible());
            });

    // Mode persistence (D7): the host store binds later; the seam resolves
    // lazily so pre-bind toggles are simply not persisted.
    connect(ribbon_, &ui_ribbon::qt::RibbonBar::modeChanged, this,
            [this](ui_ribbon::RibbonMode mode) {
                if (ribbon_save_ == nullptr) return;
                const char* value =
                    mode == ui_ribbon::RibbonMode::Compact    ? "compact"
                    : mode == ui_ribbon::RibbonMode::Collapsed ? "collapsed"
                                                               : "standard";
                ribbon_save_("mode", value);
            });
}

void AppShell::wire_workstation() {
    // M5-3: the legacy 「功能页」 hub dock is dissolved — its scroll host
    // now carries the SINGLE surviving surface: the 编图要素编辑页
    // (mapping_page_). 标题沿用 dock 注册表（id "hub"）；它是 ws3 的
    // 编辑侧伴侣（主图权威仍是 CompositeDocument）。
    workstation_->set_panel_factory(
        "hub", [this](const std::string&, QWidget* parent) -> QWidget* {
            auto* scroll = new QScrollArea(parent);
            scroll->setObjectName("HubScrollArea");
            scroll->setFrameShape(QFrame::NoFrame);
            scroll->setWidgetResizable(true);
            scroll->setHorizontalScrollBarPolicy(
                Qt::ScrollBarAsNeeded);
            scroll->setWidget(page_stack_);
            return scroll;
        });
    // Composite sub-panels dock like Python's WorkstationFrame._add_dock.
    // "composite_layer" hosts the host-adopted native QgsLayerTreeView dock
    // (see adopt_layer_tree_dock) — no prototype factory.
    // "composite_input"（ws2 右栏「单因素」）：稿的单因素图层（层位）
    // 勾选清单 —— factor_map_tasks 驱动（与参考带同一权威），勾选经
    // stage_action_requested 治理通道叠加；数据喂入在
    // workspace_compose::compose_constraint_bottom。
    workstation_->set_panel_factory(
        "composite_input",
        [this](const std::string&, QWidget* parent) -> QWidget* {
            factor_atlas_ = new FactorAtlasPanel(parent);
            return factor_atlas_;
        });
    workstation_->set_panel_factory(
        "composite_linked",
        [this](const std::string&, QWidget*) -> QWidget* {
            return composite_->linked_views;
        });
    workstation_->set_panel_factory(
        "facies_palette",
        [this](const std::string&, QWidget*) -> QWidget* {
            return composite_->facies_palette;
        });
    workstation_->set_panel_factory(
        "mapping_stage",
        [this](const std::string&, QWidget*) -> QWidget* {
            return composite_->stage_panel;
        });
    // 原型右栏每工作区页签（navigate_workspace 决定子集与标题）：
    //   ws1 图层|预测参数|样式   ws2 约束|单因素|参考
    //   ws3 编图图层|图件整饰|版式输出
    workstation_->set_panel_factory(
        "predict_compare",
        [this](const std::string&, QWidget* parent) -> QWidget* {
            // 样式（稿 ws1 右栏第三签）—— QGIS 样式面板
            // （QgsLayerStylingWidget）接入前的诚实占位。
            predict_compare_ = new QLabel(
                QStringLiteral(
                    "样式面板待接入 —— 将直接采用 QGIS "
                    "QgsLayerStylingWidget（symbology/标注/渲染）"),
                parent);
            predict_compare_->setObjectName(
                QStringLiteral("PredictStylePlaceholder"));
            qobject_cast<QLabel*>(predict_compare_)
                ->setAlignment(Qt::AlignCenter);
            qobject_cast<QLabel*>(predict_compare_)->setWordWrap(true);
            return predict_compare_;
        });
    // "reference_maps"（ws2 右栏「参考」）：稿的岩性图例 + 界面线型
    // 图例 —— 岩性色取 viz::facies_color_for 真词汇（与剖面渲染器
    // 同一取色权威）。
    workstation_->set_panel_factory(
        "reference_maps",
        [](const std::string&, QWidget* parent) -> QWidget* {
            return new ReferenceLegendPanel(parent);
        });
    workstation_->set_panel_factory(
        "map_decor",
        [this](const std::string&, QWidget* parent) -> QWidget* {
            // 图件整饰 —— 图名/图例/指北针/比例尺勾选；写回接线在
            // m5_compose_install（MapDocumentBank 单一权威）。
            map_decor_ = new pwb::ui_map::MapChromePanel(parent);
            return map_decor_;
        });
    // layout_output 无 factory —— m5_compose_install 装配好
    // LayoutComposePanel（含 map_chrome 读写闭包）后经
    // set_stage3_compose 收编进该 dock；无 closure-mapping 的构建里
    // dock 保持隐藏（占位护栏语义）。
    workstation_->set_panel_factory(
        "verify_records",
        [this](const std::string&, QWidget* parent) -> QWidget* {
            verify_records_ =
                new ui_workstation::VerifyRecordsPanel(parent);
            return verify_records_;
        });

    // ---- 页内阶段窗格（mockup 精确还原）----
    // ws1 井震两联 / ws2 连井剖面 / ws3 单因素参考带住进科学宿主页底
    // 部栈（build_workspace_host 的 stage_stack_），宿主安装器经
    // stage_pane_* 注入；ws0 的「数据预览 | 版本历史 | 关联关系」与
    // 右列「数据属性 + 数据血缘」回到 DataWorkspace 页内槽位（稿中
    // 它们是中列/右列的页内区，非全宽 dock）。原阶段行 dock id
    // （pair_link、crosswell、factor_refs、data_preview…）保留注册
    // 表描述符（Python oracle parity）但不再注册工厂 —— 永不显示。

    // Navigation: explorer -> navigate_to (the M2 legacy routing seam —
    // Python activate_legacy parity).
    connect(workstation_->explorer(),
            &ui_workstation::WorkstationExplorer::navigation_requested,
            this, [this](int hub_index, const QString& key) {
                navigate_to(hub_index, key);
            });

    // （工作流面板的接线在 build_docks 之后 —— nav 工厂在 dock 构建时
    // 才创建面板，见 ctor 末尾。）

    // M5-3: hub 外壳已拆 —— 仅剩 hub_data_（ws0 页内导航）；无 dock 标题
    // 镜像需求。

    // App bar → host-window signals (Python _wire_shell_signals parity).
    auto* bar = workstation_->app_bar();
    connect(bar, &ui_workstation::WorkstationAppBar::new_project_requested,
            this, &AppShell::new_project_requested);
    connect(bar,
            &ui_workstation::WorkstationAppBar::open_project_requested,
            this, &AppShell::open_project_requested);
    connect(bar, &ui_workstation::WorkstationAppBar::open_sample_requested,
            this, &AppShell::open_sample_project_requested);
    connect(bar, &ui_workstation::WorkstationAppBar::save_project_requested,
            this, &AppShell::save_project_requested);
    connect(bar, &ui_workstation::WorkstationAppBar::properties_requested,
            this, &AppShell::properties_requested);
    connect(bar, &ui_workstation::WorkstationAppBar::about_requested, this,
            &AppShell::about_requested);
    connect(bar, &ui_workstation::WorkstationAppBar::theme_requested, this,
            &AppShell::theme_requested);
    connect(bar, &ui_workstation::WorkstationAppBar::density_requested, this,
            &AppShell::density_requested);
    connect(bar,
            &ui_workstation::WorkstationAppBar::workspace_preset_requested,
            this, [this](const QString& preset_id) {
                workstation_->apply_layout_preset(
                    preset_id.toStdString());
            });
    connect(bar, &ui_workstation::WorkstationAppBar::task_center_requested,
            this, [this] {
                const auto* d = workstation_->dock("tasks");
                workstation_->set_dock_visible(
                    "tasks", d == nullptr || !d->isVisible());
            });
    connect(bar, &ui_workstation::WorkstationAppBar::agent_requested, this,
            [this] {
                const auto* d = workstation_->dock("agent");
                workstation_->set_dock_visible(
                    "agent", d == nullptr || !d->isVisible());
            });
    connect(bar, &ui_workstation::WorkstationAppBar::command_submitted, this,
            &AppShell::handle_workstation_command);
    connect(workstation_->activity_rail(),
            &ui_workstation::ActivityRail::settings_requested, this,
            &AppShell::preview_settings_requested);

    // Composite document → host exits (stage actions / navigation).
    connect(composite_, &ui_composite::CompositeDocument::status_message,
            this, &AppShell::status_message);
}

void AppShell::install_canvas(QWidget* canvas, bool uses_native_stack) {
    composite_->set_canvas(canvas, uses_native_stack);
    // Canvas duck-type wiring (Python getattr(canvas, sig) parity): the
    // session canvas is a QgsMapCanvas — its xyCoordinates/extentsChanged
    // feed the document's status-bar slots; other canvas kinds simply
    // leave the slots unbound — honest absence, no fake.
    if (auto* qgs_canvas = qobject_cast<QgsMapCanvas*>(canvas)) {
        connect(qgs_canvas, &QgsMapCanvas::xyCoordinates, this,
                [this](const QgsPointXY& p) {
                    composite_->on_map_position(p.x(), p.y());
                    // 原型状态栏 X/Y 读数（壳层单条；内嵌条已退役）。
                    status_coords_ =
                        QStringLiteral("X: %1  Y: %2")
                            .arg(p.x(), 0, 'f', 2)
                            .arg(p.y(), 0, 'f', 2);
                    sync_status_context();
                });
        connect(qgs_canvas, &QgsMapCanvas::extentsChanged, this,
                [this, qgs_canvas] {
                    composite_->on_extent_changed();
                    const double scale = qgs_canvas->scale();
                    status_scale_ =
                        scale > 0.0
                            ? QLocale().toString(
                                  static_cast<qint64>(scale))
                            : QString();
                    status_crs_ =
                        qgs_canvas->mapSettings()
                            .destinationCrs()
                            .authid();
                    sync_status_context();
                });
    }
}

void AppShell::sync_status_context() {
    // update_context 是整段一次写入 —— 三路来源（坐标/比例尺/CRS）各自
    // 缓存最新值后合并重发，互不覆盖。
    if (status_bar_ == nullptr) return;
    status_bar_->update_context(status_coords_, {}, status_crs_,
                                status_scale_);
}

// ---------------------------------------------------------------------------
// M2 — the five-workspace navigation authority (D1/D2)
// ---------------------------------------------------------------------------

void AppShell::navigate_workspace(int workspace_index) {
    if (workspace_index < 0 ||
        workspace_index >= ui_ribbon::kWorkspaceCount) {
        return;
    }
    const int from =
        ribbon_ != nullptr ? ribbon_->current_workspace() : 0;
    const auto workspace =
        ui_ribbon::kWorkspaceOrder[static_cast<size_t>(workspace_index)];
    const bool scientific =
        ui_ribbon::workspace_stage(workspace).has_value();

    // M5-3: legacy hub 轴的 deferred bindings（workflow 按 kPageIndex*
    // 注册）在首次工作区进入时一次性排干——页面已住进工作区，惰性
    // 语义由"第一次导航时绑定"保持，且无"永不 flush"死角。
    for (int hub = 0; hub < ui_shell::kHubCount; ++hub) {
        deferred_.flush(hub);
    }

    // Central stack: 0 → data page, 4 → validation page, 1/2/3 → the one
    // science host page.
    const int page =
        workspace == ui_ribbon::Workspace::DataManagement
            ? WorkspaceHostWidget::kPageData
        : workspace == ui_ribbon::Workspace::Validation
            ? WorkspaceHostWidget::kPageValidation
            : WorkspaceHostWidget::kPageScience;
    workspace_host_->setCurrentIndex(page);

    // Ribbon tab mirror — blocked so the programmatic sync can never
    // re-enter navigate_workspace (no activation loop).
    {
        const QSignalBlocker block(ribbon_);
        ribbon_->set_current_workspace(workspace_index);
    }
    persist_workspace(workspace_index);

    if (workspace == ui_ribbon::Workspace::DataManagement) {
        // Deferred bindings for the data hub flush when its workspace
        // opens (Python first-navigation parity).
        deferred_.flush(ui_shell::kPageIndexData);
    }
    palette_->dismiss();

    // ws4 验证：资源管理器切到勾选式「项目资源管理器」（成果/参考数据
    // 勾选 = 参与对比集）。离开验证时恢复 project；用户在其它工作区
    // 自选的 rail 模式不被打扰（只在 review→非 review 边界复位）。
    if (auto* explorer = workstation_->explorer()) {
        const std::string mode = explorer->mode();
        if (workspace_index == 4) {
            if (mode != "review") explorer->set_mode("review");
        } else if (mode == "review") {
            explorer->set_mode("project");
        }
    }

    // 原型右栏 tab 组：每个工作区一份「成员 + 标题 + 顺序」声明。先对
    // 全候选集统一隐身，再按序 set_visible —— show 顺序即 tab 顺序
    // （隐藏成员的 tabifyDockWidget 注册是惰性的，首个可见成员为锚）。
    // 标题只改 dock windowTitle，面板实例不变。
    struct RightTab {
        const char* id;
        const char* title;
    };
    static const RightTab kAllRight[] = {
        {"inspector", "检查器"},       {"composite_layer", "图层管理"},
        {"composite_input", "输入与结果"}, {"facies_palette", "相带画刷"},
        {"predict_compare", "样式"},   {"constraint_panel", "约束"},
        {"reference_maps", "参考"},    {"map_decor", "图件整饰"},
        {"layout_output", "版式输出"}, {"data_props", "数据属性"},
        {"data_lineage", "数据血缘"},
    };
    static const RightTab kWs1[] = {
        {"composite_layer", "图层"},
        {"inspector", "预测参数"},
        {"predict_compare", "样式"},
    };
    static const RightTab kWs2[] = {
        {"constraint_panel", "约束"},
        {"composite_input", "单因素"},
        {"reference_maps", "参考"},
    };
    static const RightTab kWs3[] = {
        {"composite_layer", "编图图层"},
        {"map_decor", "图件整饰"},
        {"layout_output", "版式输出"},
    };
    const RightTab* ws_tabs = nullptr;
    size_t ws_tab_count = 0;
    // ws0 右列（数据属性 + 数据血缘竖排）是页内槽位，非壳层 dock —
    // 稿 ws0 右栏两块同显不 tab 化（m5_data_install 注入页内）。
    if (workspace_index == 1) {
        ws_tabs = kWs1;
        ws_tab_count = std::size(kWs1);
    } else if (workspace_index == 2) {
        ws_tabs = kWs2;
        ws_tab_count = std::size(kWs2);
    } else if (workspace_index == 3) {
        ws_tabs = kWs3;
        ws_tab_count = std::size(kWs3);
    }
    // 稿差异：同一 composite_layer dock —— ws1「图层」= 纯勾选清单，
    // ws3「编图图层」= 参考图滑杆 + 底部图例/指北针勾选。
    if (layer_tab_panel_ != nullptr) {
        layer_tab_panel_->set_mode(
            workspace_index == 3
                ? CompilationLayerPanel::Mode::Compilation
                : CompilationLayerPanel::Mode::Checklist);
    }

    if (scientific) {
        // D1: the middle three workspaces ARE the stages — entering one
        // writes the stage authority through the ONE host-injected seam
        // (MainWindow::applyStageValue in the product; a reduced host
        // without the seam still switches the page, honestly). The stage
        // flip also drives the bottom composition (see below).
        const auto stage = *ui_ribbon::workspace_stage(workspace);
        apply_stage_composition(pwb::tool_policy::stage_value(stage));
        if (stage_apply_ != nullptr) {
            stage_apply_(pwb::tool_policy::stage_value(stage));
        }
    } else if (presentation_apply_ != nullptr) {
        // 数据管理/验证 reshape the docks through the extended
        // presentation profiles — WITHOUT touching the stage authority.
        presentation_apply_(ui_ribbon::workspace_id(workspace));
    }

    // 右栏成员/顺序是工作区权威（profile 先跑，这里收敛最终结果）；
    // 隐藏同时复位默认标题 —— 经面板菜单单开的 dock 不残留 ws 标题。
    for (const auto& tab : kAllRight) {
        if (auto* dock = workstation_->dock(tab.id)) {
            dock->setWindowTitle(QString::fromUtf8(tab.title));
        }
        workstation_->set_dock_visible(tab.id, false);
    }
    QDockWidget* first_shown = nullptr;
    for (size_t i = 0; i < ws_tab_count; ++i) {
        // 占位护栏（#1450）：无真实面板/factory 的 dock 永不显示。
        if (!workstation_->has_panel_factory(ws_tabs[i].id)) continue;
        if (auto* dock = workstation_->dock(ws_tabs[i].id)) {
            dock->setWindowTitle(QString::fromUtf8(ws_tabs[i].title));
        }
        workstation_->set_dock_visible(ws_tabs[i].id, true);
        if (first_shown == nullptr) {
            first_shown = workstation_->dock(ws_tabs[i].id);
        }
    }
    // 默认当前页 = 首个 tab（图层/约束类主面）。
    if (first_shown != nullptr) {
        first_shown->raise();
    }

    // 页内阶段窗格选择（mockup：ws1 井震两联 / ws2 连井剖面 /
    // ws3 单因素参考带 —— 中列底部固定区）。ws0/4 是别的页，
    // 栈只在科学页内。
    if (scientific && stage_stack_ != nullptr) {
        stage_stack_->setCurrentIndex(workspace_index - 1);
    }

    // 层位条：科学工作区 + 验证都显示（原型 ws1–4 顶部均有层位页签）；
    // ws0 数据管理隐藏。
    workstation_->set_horizon_strip_enabled(workspace_index != 0);

    sync_workflow_panel(workspace_index);
    emit workspace_changed(from, workspace_index);
}

void AppShell::sync_workflow_panel(int workspace_index) {
    auto* panel = workstation_ != nullptr ? workstation_->workflow_panel()
                                          : nullptr;
    if (panel == nullptr) return;
    workflow_command_ids_.clear();

    // ws0 原型左列只有 rail + 全高资源树 —— 无流程面板。
    panel->setVisible(workspace_index != 0);

    // (标题, 步骤|分隔, 对应 ribbon 命令 id|分隔) — 步骤文案取自
    // qt_ribbon_native prototype；命令 id 走 ribbon spec / registry。
    struct Row {
        const char* title;
        const char* steps;
        const char* commands;
    };
    static const Row rows[] = {
        {"数据管理流程", "数据导入|质检与整理|关联与版本|成果输出",
         "data.import|data.check|data.lineage|data.export_table"},
        {"智能预测工作流",
         "相团几何检查|草稿编辑|叠加地震相预测|叠加测井相预测|"
         "结果评估与导出",
         "predict.params|predict.overlay_well|predict.overlay_seismic|"
         "predict.overlay_well|predict.save"},
        {"约束分析",
         "约束编辑|单因素插值|连井剖面（本页）|组合分析|结果输出",
         "factor.edit_sourcing|factor.compute|factor.crosswell_path|"
         "factor.contour|factor.save"},
        {"编图工作流",
         "单因素图检查|综合编图|图件整饰|版式输出|成果导出",
         "map.show_reference|map.edit_facies|map.legend|map.template|"
         "map.export"},
    };

    if (workspace_index == 4) {
        // 验证工作区（prototype 左下 = 验证设置勾选清单）。
        panel->set_checks(QStringLiteral("验证设置"),
                          {QStringLiteral("空间对齐"),
                           QStringLiteral("井点符合"),
                           QStringLiteral("层位一致"),
                           QStringLiteral("输入版本")});
        return;
    }
    if (workspace_index < 0 || workspace_index >= 4) return;
    const Row& row = rows[workspace_index];
    panel->set_steps(QString::fromUtf8(row.title),
                     QString::fromUtf8(row.steps)
                         .split(QLatin1Char('|')));
    workflow_command_ids_ = QString::fromUtf8(row.commands)
                                .split(QLatin1Char('|'));
}

void AppShell::sync_workspace_for_stage(const std::string& stage_value) {
    const auto stage = pwb::tool_policy::stage_from_value(stage_value);
    if (!stage.has_value()) return;
    const auto workspace = ui_ribbon::workspace_for_stage(*stage);
    if (!workspace.has_value()) return;
    // Only mirror while the science host page is current — a stage change
    // reached from 数据管理/验证 must not yank the user into a scientific
    // workspace (D1: the stage is out of view there, not wrong).
    if (workspace_host_->currentIndex() != WorkspaceHostWidget::kPageScience) {
        return;
    }
    apply_stage_composition(stage_value);
    const int index = static_cast<int>(*workspace);
    if (ribbon_->current_workspace() == index) return;
    const QSignalBlocker block(ribbon_);
    ribbon_->set_current_workspace(index);
}



void AppShell::apply_stage_composition(const std::string& stage_value) {
    const auto stage = pwb::tool_policy::stage_from_value(stage_value);
    if (!stage.has_value()) return;
    // 阶段 = 工作区（1/2/3）——页内阶段窗格随工作区切换；外部
    // stage 写者（stage.goto/恢复）经 sync_workspace_for_stage 走这里。
    const auto workspace = ui_ribbon::workspace_for_stage(*stage);
    if (workspace.has_value() && stage_stack_ != nullptr) {
        stage_stack_->setCurrentIndex(static_cast<int>(*workspace) - 1);
    }
    // M5-2: 版式模式 = 抬起右栏「版式输出」dock。
    apply_compose_mode();
}

QWidget* AppShell::layout_output_panel() const {
    auto* dock = workstation_ != nullptr
                     ? workstation_->dock("layout_output")
                     : nullptr;
    return dock != nullptr ? dock->widget() : nullptr;
}

void AppShell::set_stage3_compose(QWidget* panel) {
    if (panel == nullptr || workstation_ == nullptr) return;
    // 版式输出面板住进右栏 dock（prototype ws3 右页签「版式输出」）——
    // 原 stage3 底部栈第 2 页退役；收编标记让 has_panel_factory 视作
    // 真实面板（#1450 占位护栏语义不变）。
    if (auto* dock = workstation_->dock("layout_output")) {
        dock->setWidget(panel);
        dock->setProperty("pwbAdopted", true);
    }
    apply_compose_mode();
}

void AppShell::set_compose_mode(bool on) {
    compose_mode_ = on;
    apply_compose_mode();
}

void AppShell::apply_compose_mode() {
    // 版式模式 = 抬起右栏「版式输出」dock（底部栈保持单因素参考带，
    // prototype ws3 底部组成不变）；未收编（无 closure-mapping）时
    // 占位护栏保持隐藏。
    if (!compose_mode_ || workstation_ == nullptr) return;
    if (!workstation_->has_panel_factory("layout_output")) return;
    if (auto* dock = workstation_->dock("layout_output")) {
        workstation_->set_dock_visible("layout_output", true);
        dock->raise();
    }
}

void AppShell::persist_workspace(int workspace_index) {
    if (ribbon_save_ == nullptr) return;
    const auto workspace =
        ui_ribbon::kWorkspaceOrder[static_cast<size_t>(workspace_index)];
    ribbon_save_("workspace", ui_ribbon::workspace_id(workspace));
}

void AppShell::set_stage_apply(std::function<void(const std::string&)> seam) {
    stage_apply_ = std::move(seam);
}

void AppShell::set_presentation_apply(
    std::function<void(const std::string&)> seam) {
    presentation_apply_ = std::move(seam);
    // The seam lands AFTER ctor navigation (navigate_workspace(0) ran
    // with presentation_apply_==nullptr) — re-apply the current
    // non-scientific workspace's dock projection so ws0/ws4 profiles
    // aren't missed on first landing.
    const int ws = ribbon_ != nullptr ? ribbon_->current_workspace() : 0;
    const auto workspace =
        ui_ribbon::kWorkspaceOrder[static_cast<size_t>(ws)];
    if (presentation_apply_ != nullptr &&
        !ui_ribbon::workspace_stage(workspace).has_value()) {
        presentation_apply_(ui_ribbon::workspace_id(workspace));
    }
}

void AppShell::set_ribbon_persistence(
    std::function<std::optional<std::string>(const std::string& key)> load,
    std::function<void(const std::string& key, const std::string& value)>
        save) {
    ribbon_load_ = std::move(load);
    ribbon_save_ = std::move(save);
}

void AppShell::restore_ribbon_state() {
    std::optional<std::string> mode;
    std::optional<std::string> workspace;
    if (ribbon_load_ != nullptr) {
        mode = ribbon_load_("mode");
        workspace = ribbon_load_("workspace");
    }
    if (mode.has_value()) {
        if (*mode == "compact") {
            ribbon_->set_compact(true);
        } else if (*mode == "collapsed") {
            ribbon_->set_collapsed(true);
        }
    }
    int index = 0;
    if (workspace.has_value()) {
        if (const auto parsed = ui_ribbon::workspace_from_id(*workspace)) {
            index = static_cast<int>(*parsed);
        }
    }
    navigate_workspace(index);
}

// ---------------------------------------------------------------------------
// Legacy hub axis — dissolved (M5-3): navigate_to is a pure ROUTING seam.
// Every legacy page has a workspace home (build_workspace_host); the hub
// dock survives only as the 编图要素编辑 surface. kPageIndex* stay as
// the legacy routing vocabulary + deferred-binding flush keys (the frozen
// ui_shell oracle keeps the data table; screen_inventory keeps reading).
// ---------------------------------------------------------------------------

void AppShell::navigate_to(int hub_index, const QString& submodule_key) {
    if (hub_index < 0 || hub_index >= ui_shell::kHubCount) return;
    const QString key = submodule_key;
    palette_->dismiss();

    if (hub_index == ui_shell::kPageIndexData) {
        navigate_workspace(
            static_cast<int>(ui_ribbon::Workspace::DataManagement));
        if (hub_data_ != nullptr) {
            QString sub = key.isEmpty()
                ? QString::fromStdString(
                      ui_shell::default_submodule(ui_shell::kPageIndexData))
                : key;
            hub_data_->switch_to(sub.toStdString());
        }
        return;
    }
    if (hub_index == ui_shell::kPageIndexWell) {
        // 层序格架/地层对比/预测任务均不在稿界面 —— 功能留在工程内，
        // 路由收敛为工作区切换（稿内各工作区阶段窗格随页自明）。
        if (key == QStringLiteral("sequence") ||
            key == QStringLiteral("stratigraphy")) {
            navigate_workspace(
                static_cast<int>(ui_ribbon::Workspace::ConstraintFactor));
            return;
        }
        navigate_workspace(
            static_cast<int>(ui_ribbon::Workspace::IntelligentPrediction));
        return;
    }
    if (hub_index == ui_shell::kPageIndexSeismic) {
        navigate_workspace(
            key == QStringLiteral("geomodel")
                ? static_cast<int>(ui_ribbon::Workspace::Validation)
                : static_cast<int>(
                      ui_ribbon::Workspace::IntelligentPrediction));
        return;
    }
    if (hub_index == ui_shell::kPageIndexMapping) {
        if (key == QStringLiteral("preparation")) {
            navigate_workspace(
                static_cast<int>(ui_ribbon::Workspace::ConstraintFactor));
            return;
        }
        if (key == QStringLiteral("review")) {
            navigate_workspace(
                static_cast<int>(ui_ribbon::Workspace::Validation));
            return;
        }
        // canvas（默认）→ ws3；编图要素编辑页随叫随到（编图工具 dock）。
        navigate_workspace(
            static_cast<int>(ui_ribbon::Workspace::IntegratedCompilation));
        show_hub_page(QStringLiteral("编图工具"));
        return;
    }
    if (hub_index == ui_shell::kPageIndexVisualization) {
        // D6 退役：预览能力由数据管理的读取面板承担。
        navigate_workspace(
            static_cast<int>(ui_ribbon::Workspace::DataManagement));
        emit status_message(tr("「可视化」页已退役：数据预览由数据管理的"
                               "读取面板承担"));
        return;
    }
}

void AppShell::show_hub_page(const QString& title) {
    auto* dock = workstation_->dock("hub");
    if (dock == nullptr) return;
    dock->setWindowTitle(title.isEmpty() ? QStringLiteral("编图工具") : title);
    dock->show();
    dock->raise();
}

void AppShell::handle_workstation_command(const QString& text) {
    const QString command = text.trimmed();
    if (command.isEmpty()) return;
    // Python _handle_workstation_command: agent-shaped commands route to
    // the Agent dock; everything else pre-fills the Ctrl+K palette.
    static const char* kMarkers[] = {
        "打开", "显示", "生成", "比较", "把",   "绘制",
        "分析", "计算", "open ", "show ", "generate ", "compare ",
        "plot ", "agent ",
    };
    const QString lower = command.toLower();
    for (const char* marker : kMarkers) {
        if (lower.contains(QLatin1String(marker))) {
            workstation_->set_dock_visible("agent", true);
            emit status_message(command);
            return;
        }
    }
    palette_->set_filter_text(command);
    palette_->popup();
}

void AppShell::setup_shortcuts() {
    auto& registry = ui_shell::shortcut_registry();
    // Workspace 1..5 (M2 remap — the five ribbon tabs are the navigation
    // axis now; the retired hub/Alt+submodule shortcuts are gone, so
    // conflicts() stays clean). Digit keys inert in text fields like
    // Python (enabled_in_text_input=false).
    for (int i = 0; i < ui_ribbon::kWorkspaceCount; ++i) {
        const auto workspace =
            ui_ribbon::kWorkspaceOrder[static_cast<size_t>(i)];
        registry.register_shortcut(
            this,
            ui_shell::ShortcutSpec{
                .id = "core:nav.workspace" + std::to_string(i + 1),
                .key = std::to_string(i + 1),
                .label = "切换到" +
                         std::string(ui_ribbon::workspace_label(workspace)),
            },
            [this, i] { navigate_workspace(i); },
            /*enabled_in_text_input=*/false);
    }
    registry.register_shortcut(
        this,
        ui_shell::ShortcutSpec{
            .id = "core:palette", .key = "Ctrl+K", .label = "命令面板",
        },
        [this] { palette_->popup(); });
    registry.register_shortcut(
        this,
        ui_shell::ShortcutSpec{
            .id = "core:density.toggle",
            .key = "Ctrl+Alt+D",
            .label = "切换密度",
        },
        [this] { emit density_requested(QString()); });
}

void AppShell::set_project_name(const QString& name) {
    status_bar_->set_project_name(name);
}

void AppShell::set_horizon_state(const QString& horizon,
                                 const std::vector<QString>& options) {
    // 单一 target_horizon 权威的三处视图同步投影（状态条选择器 /
    // Ribbon 尾部选择器 / 帧级层位条——后者悬于中央页宿主之上，
    // ws1–4 可见）。
    if (status_bar_ != nullptr) {
        status_bar_->set_horizon_state(horizon, options);
    }
    if (workstation_ != nullptr) {
        workstation_->set_horizon_state(horizon, options);
    }
    if (ribbon_horizon_combo_ != nullptr) {
        syncing_ribbon_horizon_ = true;
        QStringList choices;
        for (const QString& option : options) {
            if (!option.isEmpty() && !choices.contains(option)) {
                choices << option;
            }
        }
        const QString target = horizon.trimmed();
        if (!target.isEmpty() && !choices.contains(target)) {
            choices.push_front(target);
        }
        QStringList existing;
        for (int i = 0; i < ribbon_horizon_combo_->count(); ++i) {
            existing << ribbon_horizon_combo_->itemText(i);
        }
        if (existing != choices) {
            ribbon_horizon_combo_->clear();
            ribbon_horizon_combo_->addItems(choices);
        }
        ribbon_horizon_combo_->setCurrentIndex(
            target.isEmpty() ? -1 : choices.indexOf(target));
        syncing_ribbon_horizon_ = false;
    }
    // ws2「单因素」签标题的层位后缀 —— 同一权威的第四处投影。
    if (factor_atlas_ != nullptr) {
        factor_atlas_->set_horizon(horizon);
    }
}

QWidget* AppShell::adopt_data_page(QWidget* composite) {
    if (composite == nullptr || hub_data_ == nullptr) return nullptr;
    if (data_page_adopted_) return nullptr;  // one-shot: a second adopt
    // would strand the first composite (no parent, no hub slot)
    data_page_adopted_ = true;
    // The management submodule's workspace moves INSIDE the composite
    // (the composite's ctor already reparented it) — data_workspace_
    // stays a valid non-owning pointer; only the hub slot changes.
    return hub_data_->replace_submodule("management", composite);
}

void AppShell::bind_visualization_preview(
    pwb::ui_data_core::PreviewProvider provider) {
    if (visualization_page_ != nullptr) {
        visualization_page_->set_preview_provider(std::move(provider));
    }
}

void AppShell::shutdown_workers() {
    // Python shutdown_workers parity: pages own their workers; the
    // composite document owns its controller — stop them before the
    // session/canvas teardown (idempotent, safe on partial binding).
    if (home_page_ != nullptr) home_page_->shutdown_workers();
    if (visualization_page_ != nullptr) {
        visualization_page_->shutdown_workers();
    }
    // ws1 右栏「对比」页是真实联动工作区 —— 其 worker 随页级关停。
    if (auto* compare =
            qobject_cast<ui_composite::LinkedInterpretationWorkspace*>(
                predict_compare_);
        compare != nullptr) {
        compare->shutdown_workers();
    }
    // #1455: the adopted preparation page (factor prepare / contour
    // draft worker lanes) joins the same bounded shutdown — before any
    // destructor can ever see a still-running task.
    if (preparation_page_ != nullptr) {
        preparation_page_->shutdown_workers();
    }
    if (workstation_ != nullptr) workstation_->shutdown();
}

}  // namespace pwb::app
