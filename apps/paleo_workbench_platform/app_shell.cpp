#include "app_shell.hpp"

#include <QHBoxLayout>
#include <QLineEdit>
#include <QScrollArea>
#include <QScrollBar>
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

AppShell::AppShell(QWidget* parent,
                   ui_wellseis::qt::JointHostController* joint_host)
    : QWidget(parent), joint_host_(joint_host) {
    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(0, 0, 0, 0);
    outer->setSpacing(0);

    // --- hub pages (Python app_shell page-stack assembly parity) --------
    page_stack_ = new ui_shell::AdaptivePageStack(this);

    build_pages();

    // --- workstation frame: composite document is the central content,
    // the page stack lives in the 功能页 (hub) dock — Python shell parity.
    composite_ = new ui_composite::CompositeDocument(this);
    workstation_ = new ui_workstation::WorkstationFrame(this);
    workstation_->set_central_widget(composite_);
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

    // First landing: 数据 / 项目概述 — instant, no fade (Python parity:
    // the fade's QGraphicsOpacityEffect forces GL children of hidden
    // sibling pages to initialize offscreen).
    deferred_.flush(ui_shell::kPageIndexData);
    page_stack_->setCurrentIndex(ui_shell::kPageIndexData);
    hub_data_->switch_to(ui_shell::default_submodule(ui_shell::kPageIndexData));
}

AppShell::~AppShell() = default;

void AppShell::build_pages() {
    using ui_pages_data::qt::HubPage;

    // hub 0 数据: 项目概述 + 数据管理 (DataPage's composite is deferred —
    // the ported DataWorkspace hosts the management surface).
    home_page_ = new ui_pages_data::qt::HomePage(page_stack_);
    data_workspace_ = new ui_pages_data::qt::DataWorkspace(page_stack_);
    hub_data_ = new HubPage(ui_shell::kPageIndexData, page_stack_);
    hub_data_->add_submodule("overview", "项目概述", home_page_);
    hub_data_->add_submodule("management", "数据管理", data_workspace_);
    hub_data_->finish();
    page_stack_->addWidget(hub_data_);

    // hub 1 井: 测井预测 + 层序格架 + 地层对比
    well_log_page_ =
        new ui_wellseis::qt::WellLogPredictionPage(page_stack_);
    sequence_page_ =
        new ui_seqviz::qt::SequenceFrameworkPage(page_stack_);
    stratigraphy_page_ =
        new ui_seqviz::qt::StratigraphyCorrelationPage(page_stack_);
    hub_well_ = new HubPage(ui_shell::kPageIndexWell, page_stack_);
    hub_well_->add_submodule("well_log", "测井预测", well_log_page_);
    hub_well_->add_submodule("sequence", "层序格架", sequence_page_);
    hub_well_->add_submodule("stratigraphy", "地层对比",
                             stratigraphy_page_);
    hub_well_->finish();
    page_stack_->addWidget(hub_well_);

    // hub 2 地震: 地震预测 + 井震联合 3D. 06 closure: the window injects
    // the REAL joint host (Geo3D dock's VizCJointHost — shared viewport,
    // JobCenter-backed volume/pipe reads); without it the page keeps the
    // honest deferred-backend placeholder.
    seismic_page_ = new ui_wellseis::qt::SeismicPredictionPage(page_stack_);
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
    geomodel_page_ = new ui_wellseis::qt::GeologicalModeling3DPage(
        page_stack_, joint_host_);
    hub_seismic_ = new HubPage(ui_shell::kPageIndexSeismic, page_stack_);
    hub_seismic_->add_submodule("seismic", "地震预测", seismic_page_);
    hub_seismic_->add_submodule("geomodel", "井震联合 3D",
                                geomodel_page_);
    hub_seismic_->finish();
    page_stack_->addWidget(hub_seismic_);

    // hub 3 编图: 编图画布 + 数据制备 + 成图审核 (PreparationPage's
    // composite is deferred — honest placeholder, never a fake page).
    mapping_page_ = new ui_map::MappingPage(page_stack_);
    // Review actions seam (IReviewActions) is a project-backend binding
    // — absent in the shell host: the provider returns nullptr and the
    // page renders its Python-parity "未绑定工程" guard.
    review_page_ = new ui_review::qt::ReviewExportPage(
        page_stack_,
        []() -> ui_review::IReviewActions* { return nullptr; });
    hub_mapping_ = new HubPage(ui_shell::kPageIndexMapping, page_stack_);
    hub_mapping_->add_submodule("canvas", "编图画布", mapping_page_);
    hub_mapping_->add_submodule(
        "preparation", "数据制备",
        new ui_shell::PagePlaceholder("数据制备", hub_mapping_));
    hub_mapping_->add_submodule("review", "成图审核", review_page_);
    hub_mapping_->finish();
    page_stack_->addWidget(hub_mapping_);

    // hub 4 可视化 (临时 flat page — Python parity). The preview
    // provider binds the real LocalVizProvider seam; the parser-registry
    // base builder is deferred → the honest message-mode fallback, never
    // a fabricated preview (engine absent → GeoVizError(Unsupported)
    // parity).
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
        page_stack_, viz_provider.request_provider());
    page_stack_->addWidget(visualization_page_);
}

void AppShell::wire_workstation() {
    // 功能页 dock: scroll-wrapped page stack (Python HubScrollArea parity
    // — a dock narrower than the page minimum scrolls instead of locking
    // the splitter handle).
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

    // Navigation: explorer -> navigate_to (Python parity).
    connect(workstation_->explorer(),
            &ui_workstation::WorkstationExplorer::navigation_requested,
            this, [this](int hub_index, const QString& key) {
                navigate_to(hub_index, key);
            });

    // Hub page activation mirrors onto the 功能页 dock title
    // (Python hub.page_activated → activate_legacy parity).
    for (auto* hub : {hub_data_, hub_well_, hub_seismic_, hub_mapping_}) {
        connect(hub, &ui_pages_data::qt::HubPage::page_activated, this,
                &AppShell::on_hub_page_activated);
    }

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

void AppShell::navigate_to(int hub_index, const QString& submodule_key) {
    if (hub_index < 0 || hub_index >= page_stack_->count()) return;
    deferred_.flush(hub_index);
    page_stack_->setCurrentIndex(hub_index);
    auto* hub = qobject_cast<ui_pages_data::qt::HubPage*>(
        page_stack_->widget(hub_index));
    QString subkey = submodule_key;
    if (hub != nullptr) {
        if (subkey.isEmpty()) {
            const std::string current = hub->current_key();
            subkey = QString::fromStdString(
                current.empty()
                    ? ui_shell::default_submodule(hub_index)
                    : current);
        }
        hub->switch_to(subkey.toStdString());
        hub->activate_page();
    }
    palette_->dismiss();
    // activate_legacy parity: title = submodule title (or hub name).
    std::string title = ui_shell::hub_names().at(
        static_cast<size_t>(hub_index));
    if (hub != nullptr) {
        title = ui_shell::submodule_title(hub_index, subkey.toStdString());
    }
    show_hub_page(QString::fromStdString(title));
}

void AppShell::show_hub_page(const QString& title) {
    auto* dock = workstation_->dock("hub");
    if (dock == nullptr) return;
    dock->setWindowTitle(title.isEmpty() ? QStringLiteral("功能页") : title);
    dock->show();
    dock->raise();
}

void AppShell::on_hub_page_activated(int hub_index, const QString& key) {
    // Python _on_hub_page_activated: mirror the active submodule onto the
    // 功能页 dock chrome (hub_index + subkey semantics preserved).
    deferred_.flush(hub_index);
    show_hub_page(QString::fromStdString(
        ui_shell::submodule_title(hub_index, key.toStdString())));
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
    // Hub 1..5 + submodule Alt+1..3 + Ctrl+K palette (Python parity;
    // digit/Alt keys inert in text fields — enabled_in_text_input=false).
    const auto& names = ui_shell::hub_names();
    for (size_t i = 0; i < names.size() && i < 5; ++i) {
        registry.register_shortcut(
            this,
            ui_shell::ShortcutSpec{
                .id = "core:nav.hub" + std::to_string(i),
                .key = std::to_string(i + 1),
                .label = "切换到" + names[i] + "页",
            },
            [this, i] { navigate_to(static_cast<int>(i)); },
            /*enabled_in_text_input=*/false);
    }
    for (int p = 0; p < 3; ++p) {
        registry.register_shortcut(
            this,
            ui_shell::ShortcutSpec{
                .id = "core:nav.sub" + std::to_string(p),
                .key = "Alt+" + std::to_string(p + 1),
                .label = "切换子模块 " + std::to_string(p + 1),
            },
            [this, p] {
                auto* hub = qobject_cast<ui_pages_data::qt::HubPage*>(
                    page_stack_->currentWidget());
                if (hub == nullptr) return;
                const auto keys = ui_shell::submodule_keys(
                    hub->hub_index());
                if (p < static_cast<int>(keys.size())) {
                    hub->switch_to(keys[static_cast<size_t>(p)]);
                }
            },
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
