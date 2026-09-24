// app_shell — see the header for the composition contract.
//
// QGIS-native two-page frame: RibbonBar over a two-page stack.
// Page 0 数据管理 = DataManagementPage (list + info); page 1 编图 =
// QgisAuthoringPage (QgisApp-idiom inner QMainWindow: message bar +
// session canvas central, layer/browser docks in the page's dock areas).
// The legacy feature pages/dock hosts are retired from the UI — their
// call-sites keep compiling against honest nullptr/no-op surfaces.

#include "app_shell.hpp"

#include <QComboBox>
#include <QDockWidget>
#include <QHBoxLayout>
#include <QLabel>
#include <QSignalBlocker>
#include <QTabWidget>
#include <QVBoxLayout>

#include <qgsmapcanvas.h>
#include <qgspointxy.h>

#include <pwb/tool_policy/stages.hpp>
#include <pwb/ui_data_core/preview_provider.hpp>
#include <pwb/ui_ribbon/qt/ribbon_bar.hpp>
#include <pwb/ui_ribbon/ribbon_spec.hpp>
#include <pwb/ui_shell/command_palette.hpp>
#include <pwb/ui_shell/command_registry.hpp>
#include <pwb/ui_shell/shortcut_registry.hpp>
#include <pwb/ui_shell/status_bar.hpp>

#include "data_management_page.hpp"
#include "qgis_authoring_page.hpp"

namespace pwb::app {

// ---------------------------------------------------------------------------
// WorkspaceHostWidget — the two-page central stack.
// ---------------------------------------------------------------------------

WorkspaceHostWidget::WorkspaceHostWidget(QWidget* parent)
    : QStackedWidget(parent) {
    setObjectName(QStringLiteral("WorkspaceHost"));
}

AppShell::AppShell(QWidget* parent,
                   ui_wellseis::qt::JointHostController* /*joint_host*/,
                   seismic_service::SeismicVolumeService* /*volume_service*/)
    : QWidget(parent) {
    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(0, 0, 0, 0);
    outer->setSpacing(0);

    ribbon_ = new ui_ribbon::qt::RibbonBar(this);
    outer->addWidget(ribbon_);

    workspace_host_ = new WorkspaceHostWidget(this);
    build_pages();
    outer->addWidget(workspace_host_, 1);

    status_bar_ = new ui_shell::StatusBar(this);
    outer->addWidget(status_bar_);

    // Ctrl+K palette over the global registry (non-modal child).
    palette_ = new ui_shell::CommandPalette(
        this, ui_shell::command_registry());

    wire_ribbon();
    setup_shortcuts();

    // First landing: 数据管理 — instant, no fade.
    navigate_workspace(0);
    // 编图模式组首注：静态带只含模式切换与常驻输出，模式命令集按当前
    // 模式注入为上下文组（进入编图页时已就位）。
    inject_mode_groups(authoring_mode());
}

AppShell::~AppShell() = default;

void AppShell::build_pages() {
    data_page_ = new DataManagementPage(this);
    connect(data_page_, &DataManagementPage::refresh_requested, this,
            [this] {
                // 数据权威在宿主侧 —— 刷新走工程重推；这里给诚实反馈。
                emit status_message(
                    QStringLiteral("数据列表随工程打开/保存自动刷新"));
            });
    workspace_host_->addWidget(data_page_);

    authoring_page_ = new QgisAuthoringPage(this);
    workspace_host_->addWidget(authoring_page_);
}

// ---------------------------------------------------------------------------
// Host assembly seams
// ---------------------------------------------------------------------------

void AppShell::install_canvas(QWidget* canvas, bool /*uses_native_stack*/) {
    if (authoring_page_ == nullptr) return;
    authoring_page_->set_canvas(canvas);
    // Canvas duck-type wiring: the session canvas is a QgsMapCanvas — its
    // xyCoordinates/extentsChanged feed the status-bar context segment.
    if (auto* qgs_canvas = qobject_cast<QgsMapCanvas*>(canvas)) {
        connect(qgs_canvas, &QgsMapCanvas::xyCoordinates, this,
                [this](const QgsPointXY& p) {
                    status_coords_ =
                        QStringLiteral("X: %1  Y: %2")
                            .arg(p.x(), 0, 'f', 2)
                            .arg(p.y(), 0, 'f', 2);
                    sync_status_context();
                });
        connect(qgs_canvas, &QgsMapCanvas::extentsChanged, this,
                [this, qgs_canvas] {
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

void AppShell::adopt_layer_tree_dock(QDockWidget* dock) {
    if (dock == nullptr || authoring_page_ == nullptr) return;
    authoring_page_->adopt_dock(dock, Qt::LeftDockWidgetArea);
}

void AppShell::adopt_authoring_dock(QDockWidget* dock,
                                  Qt::DockWidgetArea area,
                                  QDockWidget* tabify_on) {
    if (dock == nullptr || authoring_page_ == nullptr) return;
    authoring_page_->adopt_dock(dock, area, tabify_on);
}

void AppShell::set_data_entries(const QVector<DataEntry>& entries) {
    if (data_page_ != nullptr) data_page_->set_entries(entries);
}

void AppShell::sync_status_context() {
    if (status_bar_ == nullptr) return;
    status_bar_->update_context(status_coords_, {}, status_crs_,
                                status_scale_);
}

// ---------------------------------------------------------------------------
// Two-page navigation authority (D1: page entry never writes the stage)
// ---------------------------------------------------------------------------

void AppShell::navigate_workspace(int workspace_index) {
    if (workspace_index < 0 ||
        workspace_index >= ui_ribbon::kWorkspaceCount) {
        return;
    }
    const auto workspace =
        ui_ribbon::kWorkspaceOrder[static_cast<size_t>(workspace_index)];
    const int page =
        workspace == ui_ribbon::Workspace::DataManagement
            ? WorkspaceHostWidget::kPageData
            : WorkspaceHostWidget::kPageAuthoring;
    workspace_host_->setCurrentIndex(page);

    // Ribbon tab mirror — blocked so the programmatic sync can never
    // re-enter navigate_workspace (no activation loop).
    {
        const QSignalBlocker block(ribbon_);
        ribbon_->set_current_workspace(workspace_index);
    }
    persist_workspace(workspace_index);
    palette_->dismiss();
}

int AppShell::authoring_mode_index() const {
    const auto stage = pwb::tool_policy::stage_from_value(
        authoring_mode_value_);
    for (size_t i = 0; i < pwb::tool_policy::kStageOrder.size(); ++i) {
        if (stage.has_value() &&
            pwb::tool_policy::kStageOrder[i] == *stage) {
            return static_cast<int>(i);
        }
    }
    return 0;
}

pwb::tool_policy::MappingStage AppShell::authoring_mode() const {
    const auto stage = pwb::tool_policy::stage_from_value(
        authoring_mode_value_);
    return stage.value_or(pwb::tool_policy::MappingStage::FaciesCalibration);
}

void AppShell::request_authoring_mode(
    pwb::tool_policy::MappingStage stage) {
    const std::string value = pwb::tool_policy::stage_value(stage);
    // 命令面语义：点了就要落在编图页 —— 先同步模式镜像再导航。
    set_authoring_mode(value);
    if (ribbon_ == nullptr ||
        ribbon_->current_workspace() !=
            static_cast<int>(ui_ribbon::Workspace::Authoring)) {
        navigate_workspace(
            static_cast<int>(ui_ribbon::Workspace::Authoring));
    }
    // 唯一 stage 写路径（宿主 seam → applyStageValue）；宿主回写经
    // sync_workspace_for_stage 重入 set_authoring_mode —— 幂等。
    if (stage_apply_ != nullptr) {
        stage_apply_(value);
    }
}

void AppShell::set_authoring_mode(const std::string& stage_value) {
    const auto stage = pwb::tool_policy::stage_from_value(stage_value);
    if (!stage.has_value()) return;
    authoring_mode_value_ = pwb::tool_policy::stage_value(*stage);
    inject_mode_groups(*stage);
}

void AppShell::inject_mode_groups(pwb::tool_policy::MappingStage stage) {
    if (ribbon_ == nullptr) return;
    const int ws = static_cast<int>(ui_ribbon::Workspace::Authoring);
    // 同键原位替换：先清掉上一模式注入的组键，再按序注入新模式。
    for (const QString& key : injected_mode_groups_) {
        ribbon_->clear_context_group(ws, key);
    }
    injected_mode_groups_.clear();
    for (const auto& spec : ui_ribbon::authoring_mode_groups(stage)) {
        const QString key =
            QStringLiteral("mode.") + QString::fromStdString(spec.id);
        ribbon_->set_context_group(ws, key, spec);
        injected_mode_groups_.push_back(key);
    }
}

void AppShell::show_validation_dock() {
    // 验证页已退役出界面（功能保留在项目内）—— 诚实缺席，不伪造面板。
    emit status_message(
        QStringLiteral("验证界面未启用（本轮壳层只保留数据管理与编图两页）"));
}

void AppShell::sync_workspace_for_stage(const std::string& stage_value) {
    const auto stage = pwb::tool_policy::stage_from_value(stage_value);
    if (!stage.has_value()) return;
    // stage = 编图页内模式 —— 模式镜像永远跟随权威。
    set_authoring_mode(pwb::tool_policy::stage_value(*stage));
    // Ribbon tab 只在编图页当前时镜像 —— 数据管理页上的 stage 变更
    // 不把用户拽走（D1）。
    if (workspace_host_->currentIndex() !=
        WorkspaceHostWidget::kPageAuthoring) {
        return;
    }
    const int index =
        static_cast<int>(ui_ribbon::Workspace::Authoring);
    if (ribbon_->current_workspace() == index) return;
    const QSignalBlocker block(ribbon_);
    ribbon_->set_current_workspace(index);
}

// ---------------------------------------------------------------------------
// Legacy hub axis — pure routing seam onto the two pages.
// ---------------------------------------------------------------------------

void AppShell::navigate_to(int hub_index, const QString& submodule_key) {
    (void)submodule_key;
    palette_->dismiss();
    // hub 0 → 数据管理；其余 hub 轴目标一律落编图页（功能面板退役，
    // 状态条给诚实提示）。
    if (hub_index == 0) {
        navigate_workspace(
            static_cast<int>(ui_ribbon::Workspace::DataManagement));
        return;
    }
    navigate_workspace(
        static_cast<int>(ui_ribbon::Workspace::Authoring));
}

void AppShell::show_hub_page(const QString& title) {
    emit status_message(QStringLiteral("「%1」面板未启用").arg(title));
}

void AppShell::focus_stage_dock(const QString& /*title*/) {}

void AppShell::set_stage3_compose(QWidget* /*panel*/) {}

void AppShell::set_compose_mode(bool on) { compose_mode_ = on; }

void AppShell::handle_workstation_command(const QString& text) {
    const QString command = text.trimmed();
    if (command.isEmpty()) return;
    palette_->set_filter_text(command);
    palette_->popup();
}

// ---------------------------------------------------------------------------
// Ribbon wiring
// ---------------------------------------------------------------------------

void AppShell::wire_ribbon() {
    // Ctrl+F1 collapse entry through the central registry.
    ribbon_->set_shortcut_registry(&ui_shell::shortcut_registry());

    // 命令搜索 — the same Ctrl+K palette entry, second surface.
    connect(ribbon_, &ui_ribbon::qt::RibbonBar::searchRequested, this,
            [this] { palette_->popup(); });

    // Command routing: bound commands live in the registry (palette
    // parity: record recent + run the one callback); an unbound
    // placeholder is an honest no-op until the host rebinds it.
    connect(ribbon_, &ui_ribbon::qt::RibbonBar::commandTriggered, this,
            [this](const QString& command_id) {
                auto& registry = ui_shell::command_registry();
                const auto* spec =
                    registry.get(command_id.toStdString());
                if (spec == nullptr || !spec->callback) {
                    qInfo() << "ribbon command not bound yet:"
                            << command_id;
                    return;
                }
                registry.record_recent(command_id.toStdString());
                spec->callback();
            });

    // THE workspace axis: ribbon tab -> navigate_workspace.
    connect(ribbon_, &ui_ribbon::qt::RibbonBar::workspaceActivated, this,
            &AppShell::navigate_workspace);

    // Ribbon 命令带尾部常驻槽：层位选择器 —— 与状态条层位下拉同一
    // target_horizon 权威的又一视图/编辑器，只回发 horizon_requested。
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

    // Nav-row 任务/Agent 入口 —— 对应 dock 已退役：诚实提示。
    connect(ribbon_, &ui_ribbon::qt::RibbonBar::taskCenterRequested, this,
            [this] {
                emit status_message(QStringLiteral(
                    "任务中心面板未启用（本轮壳层不含该 dock）"));
            });
    connect(ribbon_, &ui_ribbon::qt::RibbonBar::agentRequested, this,
            [this] {
                emit status_message(QStringLiteral(
                    "Agent 面板未启用（本轮壳层不含该 dock）"));
            });

    // Mode persistence (D7): the host store binds later; the seam
    // resolves lazily so pre-bind toggles are simply not persisted.
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

void AppShell::setup_shortcuts() {
    auto& registry = ui_shell::shortcut_registry();
    // Workspace digits 1..2 (two-page shell — 数据管理/编图). Digit keys
    // inert in text fields (enabled_in_text_input=false).
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

// ---------------------------------------------------------------------------
// Persistence / seams
// ---------------------------------------------------------------------------

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
        } else if (*workspace == "predict" || *workspace == "factor" ||
                   *workspace == "map") {
            // 旧五工作区持久化值 → 编图页。
            index = static_cast<int>(ui_ribbon::Workspace::Authoring);
        }
    }
    navigate_workspace(index);
}

void AppShell::set_project_name(const QString& name) {
    if (status_bar_ != nullptr) status_bar_->set_project_name(name);
}

void AppShell::set_horizon_state(const QString& horizon,
                                 const std::vector<QString>& options) {
    if (status_bar_ != nullptr) {
        status_bar_->set_horizon_state(horizon, options);
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
}

// ---------------------------------------------------------------------------
// Retired adopt seams — honest no-ops (feature installs are not wired).
// ---------------------------------------------------------------------------

void AppShell::adopt_preparation_page(QWidget* /*page*/) {}

QWidget* AppShell::adopt_data_page(QWidget* /*composite*/) {
    return nullptr;
}

void AppShell::bind_visualization_preview(
    pwb::ui_data_core::PreviewProvider /*provider*/) {}

void AppShell::shutdown_workers() {
    // The feature pages owning worker lanes are retired from the shell —
    // nothing page-scoped remains to drain.
}

}  // namespace pwb::app
