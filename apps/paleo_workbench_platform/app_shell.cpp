#include "app_shell.hpp"

#include <cstddef>

#include <QDebug>
#include <QHBoxLayout>
#include <QLabel>
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

#include <pwb/ui_composite/composite_document.hpp>
#include <pwb/ui_composite/layer_manager_panel.hpp>
#include <pwb/ui_composite/mapping_stage_panel.hpp>
#include <pwb/ui_data_core/preview_provider.hpp>
#include <pwb/ui_map/mapping_page.hpp>
#include <pwb/ui_pages_data/qt/data_workspace.hpp>
#include <pwb/ui_pages_data/qt/home_page.hpp>
#include <pwb/ui_pages_data/qt/hub_page.hpp>
#include <pwb/ui_review/qt/review_export_page.hpp>
#include <pwb/ui_ribbon/qt/ribbon_bar.hpp>
#include <pwb/ui_seqviz/geoviz_provider.hpp>
#include <pwb/ui_seqviz/qt/correlation_page.hpp>
#include <pwb/ui_seqviz/qt/sequence_framework_page.hpp>
#include <pwb/ui_seqviz/qt/visualization_page.hpp>
#include <pwb/ui_shell/adaptive_page_stack.hpp>
#include <pwb/ui_shell/command_palette.hpp>
#include <pwb/ui_shell/command_registry.hpp>
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
                   ui_wellseis::qt::JointHostController* joint_host)
    : QWidget(parent), joint_host_(joint_host) {
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
    build_workspace_host();
    workstation_ = new ui_workstation::WorkstationFrame(this);
    workstation_->set_central_widget(workspace_host_);
    wire_workstation();
    workstation_->build_docks();
    workstation_->apply_first_run_sizes();

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
    static pwb::seismic_service::SeismicVolumeService
        closure_seismic_volume_service;
    pwb::closure_seismic::install_seismic_page(
        {seismic_page_, &closure_seismic_volume_service});
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

// Thin host for the migrated full pages living in the stage bottom tabs:
// the pages carry full-page minimum heights (e.g. 预测任务 ~934px) which
// would squeeze the canvas out of the 65:35 contract (F:46). Ignored size
// policy lets the splitter shrink the host to the compact band; the page
// content behaves like any IDE bottom tool (its inner panes scroll/clip
// as designed for narrow hosts).
QWidget* as_bottom_tab(QWidget* page, QWidget* parent) {
    if (page == nullptr) return nullptr;
    auto* host = new QWidget(parent);
    host->setObjectName(page->objectName() + QStringLiteral("BottomHost"));
    auto* layout = new QVBoxLayout(host);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(0);
    page->setParent(host);
    page->setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Ignored);
    layout->addWidget(page);
    host->setMinimumHeight(120);
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

    // Page 1 科学宿主 (M3, D2): 65:35 vertical splitter — the composite
    // document (ONE QGIS canvas authority for workspaces 1/2/3) over the
    // per-stage bottom stack. The compose install fills each bottom page
    // with the real panels; until then each page carries an honest
    // empty-state label.
    auto* science_page = new QWidget(this);
    science_page->setObjectName(QStringLiteral("ScienceHostPage"));
    science_splitter_ = new QSplitter(Qt::Vertical, science_page);
    auto* science_layout = new QVBoxLayout(science_page);
    science_layout->setContentsMargins(0, 0, 0, 0);
    science_layout->setSpacing(0);
    science_layout->addWidget(science_splitter_);

    science_bottom_ = new QStackedWidget(this);
    science_bottom_->setObjectName(QStringLiteral("ScienceStageBottom"));
    const char* kStageBottomNames[kStageBottomCount] = {
        "StageBottomPrediction", "StageBottomConstraint",
        "StageBottomCompilation"};
    const char* kStageBottomHints[kStageBottomCount] = {
        "地震剖面 + 测井轨道两联（打开工程后从数据管理载入体版本 / 井曲线）",
        "连井剖面 + 数据制备（载入井数据后出现剖面）",
        "单因素参考图带（运行单因素计算后出现缩略图）"};
    for (int i = 0; i < kStageBottomCount; ++i) {
        QWidget* page = nullptr;
        if (i == 0) {
            // M5-3 ws1: bottom = tabs [井震两联 | 预测任务 | 地震预测]。
            // 两联占位由 compose install 换成地震+测井 splitter；
            // 预测/地震页是智能预测的输入与证据页（F:56-58 组版）。
            stage1_tabs_ = new QTabWidget(science_bottom_);
            stage1_tabs_->setObjectName(
                QStringLiteral("StageBottomPredictionTabs"));
            auto* pair_placeholder = new QLabel(
                QString::fromUtf8(kStageBottomHints[i]), stage1_tabs_);
            pair_placeholder->setObjectName(
                QStringLiteral("PredictionPairPlaceholder"));
            pair_placeholder->setAlignment(Qt::AlignCenter);
            stage1_tabs_->addTab(pair_placeholder,
                                 QStringLiteral("井震两联"));
            stage1_tabs_->addTab(as_bottom_tab(well_log_page_, stage1_tabs_),
                                 QStringLiteral("预测任务"));
            stage1_tabs_->addTab(as_bottom_tab(seismic_page_, stage1_tabs_),
                                 QStringLiteral("地震预测"));
            page = stage1_tabs_;
        } else if (i == 1) {
            // Stage 2's bottom hosts the 连井剖面 + 数据制备 tabs from
            // the start — adopt_preparation_page swaps the 数据制备
            // placeholder for the real closure-assembled page. M5-3 adds
            // 地层对比（连井解释对照）与层序格架 tabs —— hub1 遗留页
            // 迁入 ws2（约束输入，F 契约）。
            stage2_tabs_ = new QTabWidget(science_bottom_);
            stage2_tabs_->setObjectName(
                QStringLiteral("StageBottomConstraintTabs"));
            auto* prep_placeholder = new QLabel(
                QString::fromUtf8(kStageBottomHints[i]), stage2_tabs_);
            prep_placeholder->setObjectName(
                QStringLiteral("PreparationPlaceholder"));
            prep_placeholder->setAlignment(Qt::AlignCenter);
            stage2_tabs_->addTab(prep_placeholder,
                                 QStringLiteral("数据制备"));
            stage2_tabs_->addTab(
                as_bottom_tab(stratigraphy_page_, stage2_tabs_),
                QStringLiteral("地层对比"));
            stage2_tabs_->addTab(
                as_bottom_tab(sequence_page_, stage2_tabs_),
                QStringLiteral("层序格架"));
            page = stage2_tabs_;
        } else if (i == 2) {
            // M5-2 版式模式 (F:70): the stage-3 bottom is a stack — page
            // 0 keeps the DEFAULT composition (factor reference strip,
            // added by the compose install into stage3_home_), page 1 is
            // the layout-compose panel (set_stage3_compose). Entering
            // 版式模式 swaps the BOTTOM only — the central canvas and
            // the default bottom stay exactly as M3 left them.
            stage3_stack_ = new QStackedWidget(science_bottom_);
            stage3_stack_->setObjectName(
                QStringLiteral("StageBottomCompilationStack"));
            stage3_home_ = new QWidget(stage3_stack_);
            stage3_home_->setObjectName(
                QStringLiteral("StageBottomCompilationHome"));
            new QVBoxLayout(stage3_home_);
            stage3_stack_->addWidget(stage3_home_);
            stage3_stack_->addWidget(new QWidget());  // compose slot
            page = stage3_stack_;
        } else {
            page = new QWidget(science_bottom_);
            auto* layout = new QVBoxLayout(page);
            layout->setContentsMargins(0, 0, 0, 0);
            auto* hint = new QLabel(QString::fromUtf8(kStageBottomHints[i]),
                                    page);
            hint->setObjectName(QStringLiteral("StageBottomHint"));
            hint->setAlignment(Qt::AlignCenter);
            layout->addWidget(hint);
        }
        page->setObjectName(QString::fromLatin1(kStageBottomNames[i]));
        science_bottom_->addWidget(page);
    }

    science_splitter_->addWidget(composite_);
    science_splitter_->addWidget(science_bottom_);
    // 主图:底部 ≈ 65:35 (F:46) — stretch 保持比例，首次 show 时播种
    // 实际尺寸（构造期 splitter 无高度，setSizes 会被夹紧）。
    science_splitter_->setStretchFactor(0, 65);
    science_splitter_->setStretchFactor(1, 35);
    workspace_host_->addWidget(science_page);

    // Page 2 验证 (M3, D5): the real composition page — read-only compare
    // canvas + seismic pane slot + structured issues + review detail with
    // locate. The M5 gaps stay explicit placeholders inside the page.
    validation_page_ = new ValidationWorkspacePage(this);
    // M5-3: hub 遗留页迁入验证右列 —— 报告导出（成图审核页的 QC 报告
    // 导出/定稿入口，closure_review 绑定不变）与 3D 对照（井震联合
    // 3D，可选视图，D6）。
    if (auto* tabs = validation_page_->findChild<QTabWidget*>(
            QStringLiteral("ValidationRightTabs"));
        tabs != nullptr) {
        tabs->addTab(as_bottom_tab(review_page_, tabs),
                     QStringLiteral("报告导出"));
        tabs->addTab(as_bottom_tab(geomodel_page_, tabs),
                     QStringLiteral("3D 对照"));
    }
    workspace_host_->addWidget(validation_page_);
}

// BEGIN CLOSURE-MAPPING (08-line adopt)
void AppShell::adopt_preparation_page(QWidget* page) {
    if (page == nullptr) return;
    // M3 (P0-2): the PreparationPage lives in the 约束与单因素 (ws2) bottom
    // as the 数据制备 tab — the hub dock slot stays a legacy route only.
    if (stage2_tabs_ != nullptr) {
        // QTabWidget pages live in its internal stack — recursive lookup.
        auto* placeholder = stage2_tabs_->findChild<QLabel*>(
            QStringLiteral("PreparationPlaceholder"));
        const int index =
            placeholder != nullptr ? stage2_tabs_->indexOf(placeholder) : -1;
        if (index >= 0) {
            stage2_tabs_->removeTab(index);
            delete placeholder;
            stage2_tabs_->insertTab(
                index, as_bottom_tab(page, stage2_tabs_),
                QStringLiteral("数据制备"));
            stage2_tabs_->setCurrentIndex(index);
            return;
        }
    }
}
// END CLOSURE-MAPPING

void AppShell::wire_ribbon() {
    // File button: minimal menu reusing the AppShell project-action
    // signals (the host window owns the implementations — no parallel
    // QAction logic, D4). The full menu convergence lands in M4.
    auto* file_menu = new QMenu(ribbon_);
    file_menu->addAction(tr("新建工程…"), this,
                         [this] { emit new_project_requested(); });
    file_menu->addAction(tr("打开工程…"), this,
                         [this] { emit open_project_requested(); });
    file_menu->addAction(tr("打开样例工程"), this,
                         [this] { emit open_sample_project_requested(); });
    file_menu->addAction(tr("保存工程"), this,
                         [this] { emit save_project_requested(); });
    file_menu->addSeparator();
    file_menu->addAction(tr("工程属性…"), this,
                         [this] { emit properties_requested(); });
    file_menu->addSeparator();
    file_menu->addAction(tr("退出"), this, [this] { emit exit_requested(); });
    ribbon_->set_file_menu(file_menu);

    // Ctrl+F1 collapse entry through the central registry (conflicts()
    // gate lives in the ribbon library).
    ribbon_->set_shortcut_registry(&ui_shell::shortcut_registry());

    // 命令搜索 — the same Ctrl+K palette entry, second surface (R:20).
    connect(ribbon_, &ui_ribbon::qt::RibbonBar::searchRequested, this,
            [this] { palette_->popup(); });

    // Availability channel over the process CommandRegistry: a command the
    // registry does not know stays enabled — the ribbon table still carries
    // M4 semantic placeholders that the registry rebinds later; a known
    // command answers with the registry verdict (fail-closed reason).
    ribbon_->set_command_evaluator(
        [](const std::string& command_id) -> ui_ribbon::CommandState {
            auto& registry = ui_shell::command_registry();
            if (registry.get(command_id) == nullptr) return {true, ""};
            const auto verdict = registry.evaluate(command_id, nullptr);
            return {verdict.enabled, verdict.reason};
        });

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
    workstation_->set_panel_factory(
        "composite_layer",
        [this](const std::string&, QWidget*) -> QWidget* {
            return composite_->layer_manager;
        });
    workstation_->set_panel_factory(
        "composite_input",
        [this](const std::string&, QWidget*) -> QWidget* {
            return composite_->input_tree;
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

    // Navigation: explorer -> navigate_to (the M2 legacy routing seam —
    // Python activate_legacy parity).
    connect(workstation_->explorer(),
            &ui_workstation::WorkstationExplorer::navigation_requested,
            this, [this](int hub_index, const QString& key) {
                navigate_to(hub_index, key);
            });

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
                });
        connect(qgs_canvas, &QgsMapCanvas::extentsChanged, composite_,
                &ui_composite::CompositeDocument::on_extent_changed);
    }
}

// ---------------------------------------------------------------------------
// M2 — the five-workspace navigation authority (D1/D2)
// ---------------------------------------------------------------------------

void AppShell::navigate_workspace(int workspace_index) {
    if (workspace_index < 0 ||
        workspace_index >= ui_ribbon::kWorkspaceCount) {
        return;
    }
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
    if (!stage.has_value() || science_bottom_ == nullptr) return;
    const int bottom =
        *stage == pwb::tool_policy::MappingStage::FaciesCalibration    ? 0
        : *stage == pwb::tool_policy::MappingStage::ConstraintFactor   ? 1
        : *stage == pwb::tool_policy::MappingStage::IntegratedCompilation
            ? 2
            : -1;
    if (bottom >= 0 && science_bottom_->currentIndex() != bottom) {
        science_bottom_->setCurrentIndex(bottom);
    }
    // M5-2: 版式模式只作用于综合编图的底部栈页。
    apply_compose_mode();
}

void AppShell::set_stage3_compose(QWidget* panel) {
    if (panel == nullptr || stage3_stack_ == nullptr) return;
    if (stage3_stack_->count() > 1) {
        if (auto* old = stage3_stack_->widget(1)) {
            stage3_stack_->removeWidget(old);
            old->deleteLater();
        }
    }
    stage3_stack_->addWidget(panel);
    apply_compose_mode();
}

void AppShell::set_compose_mode(bool on) {
    compose_mode_ = on;
    apply_compose_mode();
}

void AppShell::apply_compose_mode() {
    if (stage3_stack_ == nullptr || stage3_stack_->count() < 2) return;
    stage3_stack_->setCurrentIndex(compose_mode_ ? 1 : 0);
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
        if (key == QStringLiteral("sequence")) {
            navigate_workspace(
                static_cast<int>(ui_ribbon::Workspace::ConstraintFactor));
            focus_stage_tab(stage2_tabs_, QStringLiteral("层序格架"));
            return;
        }
        if (key == QStringLiteral("stratigraphy")) {
            navigate_workspace(
                static_cast<int>(ui_ribbon::Workspace::ConstraintFactor));
            focus_stage_tab(stage2_tabs_, QStringLiteral("地层对比"));
            return;
        }
        // well_log（默认）→ ws1 智能预测的预测任务 tab。
        navigate_workspace(
            static_cast<int>(ui_ribbon::Workspace::IntelligentPrediction));
        focus_stage_tab(stage1_tabs_, QStringLiteral("预测任务"));
        return;
    }
    if (hub_index == ui_shell::kPageIndexSeismic) {
        if (key == QStringLiteral("geomodel")) {
            navigate_workspace(
                static_cast<int>(ui_ribbon::Workspace::Validation));
            focus_stage_tab(validation_page_->findChild<QTabWidget*>(
                                QStringLiteral("ValidationRightTabs")),
                            QStringLiteral("3D 对照"));
        } else {
            navigate_workspace(
                static_cast<int>(ui_ribbon::Workspace::IntelligentPrediction));
            focus_stage_tab(stage1_tabs_, QStringLiteral("地震预测"));
        }
        return;
    }
    if (hub_index == ui_shell::kPageIndexMapping) {
        if (key == QStringLiteral("preparation")) {
            navigate_workspace(
                static_cast<int>(ui_ribbon::Workspace::ConstraintFactor));
            focus_stage_tab(stage2_tabs_, QStringLiteral("数据制备"));
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

void AppShell::focus_stage_tab(QTabWidget* tabs, const QString& title) {
    if (tabs == nullptr) return;
    for (int i = 0; i < tabs->count(); ++i) {
        if (tabs->tabText(i) == title) {
            tabs->setCurrentIndex(i);
            return;
        }
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

void AppShell::showEvent(QShowEvent* event) {
    QWidget::showEvent(event);
    if (splitter_seeded_ || science_splitter_ == nullptr) return;
    splitter_seeded_ = true;
    const int total = science_splitter_->height();
    if (total > 100) {
        const int top = total * 65 / 100;
        science_splitter_->setSizes({top, total - top});
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
    if (workstation_ != nullptr) workstation_->shutdown();
}

}  // namespace pwb::app
