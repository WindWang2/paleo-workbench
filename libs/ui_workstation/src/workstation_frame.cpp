#include "pwb/ui_workstation/workstation_frame.hpp"

#include <QEvent>
#include <QHBoxLayout>
#include <QScrollArea>
#include <QSplitter>
#include <QVBoxLayout>

#include <pwb/ui_shell/dock_resize.hpp>
#include <pwb/ui_shell/layout_presets.hpp>
#include <pwb/ui_shell/page_placeholder.hpp>

namespace pwb::ui_workstation {

namespace {

Qt::DockWidgetArea area_for(const std::string& area) {
    if (area == ui_shell::kAreaRight) {
        return Qt::DockWidgetArea::RightDockWidgetArea;
    }
    if (area == ui_shell::kAreaBottom) {
        return Qt::DockWidgetArea::BottomDockWidgetArea;
    }
    return Qt::DockWidgetArea::LeftDockWidgetArea;
}

// Dock 分组 —— finish_dock_layout 的成组依据 + adopt_dock 的归组锚
//（build 后收编的 dock 必须落进同一行/组，而不是同区第一个 dock）。
//   右栏组        = 原型右列单条 tab 面（各工作区显示其子集）
//   底部阶段行    = dock 嵌套 row0（每工作区的阶段/预览面板）
//   底部工具行    = row1 常驻工具条（任务|日志|验证记录|…）
// ws0 的 数据属性/数据血缘 不在任何组 —— 它们在右栏竖向二分同显。
constexpr const char* kRightGroup[] = {
    "composite_layer", "inspector",      "constraint_panel",
    "composite_input", "predict_compare", "reference_maps",
    "facies_palette",  "map_decor",      "layout_output",
    "hub",
};
constexpr const char* kStageRow[] = {
    "data_preview",  "data_history",  "data_relations",
    "pair_link",     "predict_task",  "seismic_predict",
    "crosswell",     "data_prep",     "strat_compare",
    "seq_frame",     "factor_refs",
};
constexpr const char* kUtilityRow[] = {
    "tasks",      "logs",  "verify_records", "factor_stats",
    "console",    "agent", "composite_linked", "well",
    "seismic",
};

template <std::size_t N>
bool in_group(const char* const (&ids)[N], const std::string& id) {
    for (const char* group_id : ids) {
        if (id == group_id) return true;
    }
    return false;
}

}  // namespace

WorkstationFrame::WorkstationFrame(QWidget* parent) : QFrame(parent) {
    setObjectName("WorkstationFrame");
    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(0, 0, 0, 0);
    outer->setSpacing(0);

    // The dock host: QMainWindow must be top-level-shaped, so it lives
    // as the frame's single child (Python shell parity — the frame is
    // the composite's dock host).
    dock_host_ = new QMainWindow(this);
    // QMainWindow's ctor ORs in Qt::Window — an embedded dock host must
    // be a plain child widget or it stays a hidden top-level window.
    dock_host_->setWindowFlags(Qt::Widget);
    dock_host_->setDockOptions(
        QMainWindow::DockOption::AnimatedDocks |
        QMainWindow::DockOption::AllowNestedDocks |
        QMainWindow::DockOption::AllowTabbedDocks);
    // 嵌套布局 —— 底部区需要两行（阶段/预览面板行 + 任务|日志 工具
    // 行），右侧区需要竖向二分（ws0 数据属性/数据血缘 同显）。
    dock_host_->setDockNestingEnabled(true);
    dock_host_->setTabPosition(
        Qt::DockWidgetArea::AllDockWidgetAreas,
        QTabWidget::TabPosition::North);
    dock_host_->installEventFilter(this);
    outer->addWidget(dock_host_, 1);

    // App bar on the host's top toolbar row — full width, immovable.
    // qt_ribbon_native parity: the ribbon nav row already carries 文件 +
    // 命令搜索 + 任务/Agent, so the legacy app-bar row starts hidden; a
    // host mount_top_bar() bar (or the panels menu) can re-show it.
    app_bar_toolbar_ = new QToolBar("工作站全局栏", dock_host_);
    app_bar_toolbar_->setObjectName("WorkstationAppBarToolbar");
    app_bar_toolbar_->setMovable(false);
    app_bar_toolbar_->setFloatable(false);
    app_bar_ = new WorkstationAppBar(app_bar_toolbar_);
    app_bar_toolbar_->addWidget(app_bar_);
    dock_host_->addToolBar(Qt::ToolBarArea::TopToolBarArea,
                           app_bar_toolbar_);
    app_bar_toolbar_->hide();

    install_default_panels();
}

void WorkstationFrame::set_central_widget(QWidget* page_stack) {
    // 中央区 = [层位标签行][页栈]：层位条是 target_horizon 权威的一处
    // 视图（qt_ribbon_native 画布上方层位标签），ws0 隐藏、ws1-4 显示；
    // 点击只发 horizon_requested，不持有状态。
    auto* column = new QWidget(dock_host_);
    column->setObjectName("WorkstationCenterColumn");
    auto* column_layout = new QVBoxLayout(column);
    column_layout->setContentsMargins(0, 0, 0, 0);
    column_layout->setSpacing(0);
    horizon_tabs_ = new QTabBar(column);
    horizon_tabs_->setObjectName(QStringLiteral("WorkstationHorizonTabs"));
    horizon_tabs_->setExpanding(false);
    horizon_tabs_->setDrawBase(false);
    horizon_tabs_->setUsesScrollButtons(true);
    horizon_tabs_->hide();  // 无候选时整行隐藏（诚实缺席）；ws0 永不显示。
    connect(horizon_tabs_, &QTabBar::currentChanged, this,
            [this](int index) {
                if (syncing_horizon_tabs_ || index < 0) return;
                emit horizon_requested(horizon_tabs_->tabText(index));
            });
    // 原型层位条贴左（◁ 滚动钮 + 页签自左排布）。
    auto* horizon_row = new QHBoxLayout();
    horizon_row->setContentsMargins(0, 0, 0, 0);
    horizon_row->addWidget(horizon_tabs_);
    horizon_row->addStretch(1);
    column_layout->addLayout(horizon_row);
    central_ = page_stack;
    if (central_ != nullptr) {
        column_layout->addWidget(central_, 1);
    }
    dock_host_->setCentralWidget(column);
}

void WorkstationFrame::set_horizon_state(
    const QString& horizon, const std::vector<QString>& options) {
    if (horizon_tabs_ == nullptr) return;
    syncing_horizon_tabs_ = true;
    QStringList choices;
    for (const QString& option : options) {
        if (!option.isEmpty() && !choices.contains(option)) {
            choices.push_back(option);
        }
    }
    const QString target = horizon.trimmed();
    if (!target.isEmpty() && !choices.contains(target)) {
        // 权威值必须存活——未知层位插入而非丢弃（StatusBar 同语义）。
        choices.push_front(target);
    }
    QStringList existing;
    for (int i = 0; i < horizon_tabs_->count(); ++i) {
        existing << horizon_tabs_->tabText(i);
    }
    if (existing != choices) {
        while (horizon_tabs_->count() > 0) horizon_tabs_->removeTab(0);
        for (const QString& choice : choices) horizon_tabs_->addTab(choice);
    }
    const int index = target.isEmpty() ? -1 : choices.indexOf(target);
    if (index >= 0) horizon_tabs_->setCurrentIndex(index);
    horizon_tabs_->setVisible(horizon_strip_enabled_ && !choices.isEmpty());
    syncing_horizon_tabs_ = false;
}

QString WorkstationFrame::current_horizon() const {
    if (horizon_tabs_ == nullptr || horizon_tabs_->currentIndex() < 0) {
        return {};
    }
    return horizon_tabs_->tabText(horizon_tabs_->currentIndex()).trimmed();
}

void WorkstationFrame::set_horizon_strip_enabled(bool enabled) {
    horizon_strip_enabled_ = enabled;
    if (horizon_tabs_ != nullptr) {
        horizon_tabs_->setVisible(enabled && horizon_tabs_->count() > 0);
    }
}

void WorkstationFrame::adopt_dock(const std::string& dock_id,
                                  QDockWidget* adopted) {
    if (adopted == nullptr) return;
    if (auto* old = dock(dock_id)) {
        // 注册表占位 dock 退役 —— 真实 dock 接管同一 dock_id。
        dock_host_->removeDockWidget(old);
        docks_.erase(dock_id);
        old->deleteLater();
    }
    if (auto* parent_window =
            qobject_cast<QMainWindow*>(adopted->parent())) {
        parent_window->removeDockWidget(adopted);
    }
    adopted->setParent(dock_host_);
    adopted->setObjectName(QStringLiteral("WorkstationDock_%1")
                             .arg(QString::fromStdString(dock_id)));
    // 收编 dock 自带真实内容 —— has_panel_factory 语义上等价于已注入
    // factory（#1450 占位护栏不应把它判成占位页）。
    adopted->setProperty("pwbDockId", QString::fromStdString(dock_id));
    adopted->setProperty("pwbAdopted", true);
    // 与固定面板同一 chrome 处理：标题栏并入 tab 组（原型右栏只见
    // tab 条，无 dock 标题栏）；悬浮时还原原生标题栏供拖动/关闭。
    adopted->setProperty("pwbBlankTitle", true);
    sync_titlebar_for_float(adopted, adopted->isFloating());
    const auto* desc =
        ui_shell::workstation_dock_registry().get(dock_id);
    dock_host_->addDockWidget(
        area_for(desc != nullptr ? desc->preferred_area : "right"),
        adopted);
    adopted->hide();
    docks_[dock_id] = adopted;
    connect(adopted, &QDockWidget::visibilityChanged, this,
            [this](bool) {
                if (!tearing_down_) {
                    note_user_layout_change();
                }
            });
    connect(adopted, &QDockWidget::topLevelChanged, this,
            [this](bool floating) {
                if (auto* d = qobject_cast<QDockWidget*>(sender())) {
                    sync_titlebar_for_float(d, floating);
                }
            });
    if (tabs_built_ && desc != nullptr) {
        // 组已建成 → 并进所属分组的锚 dock（底部两行布局下，阶段行
        // 收编必须落进 row0 组而非同区首个 dock —— 后者可能是工具行）。
        QDockWidget* anchor = nullptr;
        const auto area = area_for(desc->preferred_area);
        if (in_group(kStageRow, dock_id)) {
            for (const char* id : kStageRow) {
                anchor = dock(id);
                if (anchor != nullptr) break;
            }
        } else if (in_group(kUtilityRow, dock_id)) {
            for (const char* id : kUtilityRow) {
                anchor = dock(id);
                if (anchor != nullptr) break;
            }
        }
        if (anchor == nullptr &&
            area == Qt::DockWidgetArea::RightDockWidgetArea) {
            for (const char* id : kRightGroup) {
                if (dock_id == id) continue;
                anchor = dock(id);
                if (anchor != nullptr) break;
            }
        }
        if (anchor != nullptr && anchor != adopted) {
            dock_host_->tabifyDockWidget(anchor, adopted);
        }
    }
}

void WorkstationFrame::set_panel_factory(const std::string& dock_id,
                                         PanelFactory factory) {
    factories_[dock_id] = std::move(factory);
}

QWidget* WorkstationFrame::content_for(const std::string& dock_id,
                                       QWidget* parent) {
    const auto it = factories_.find(dock_id);
    if (it != factories_.end() && it->second) {
        if (QWidget* w = it->second(dock_id, parent)) return w;
    }
    return new ui_shell::PagePlaceholder(
        QString::fromStdString(
            ui_shell::workstation_dock_registry()
                .require(dock_id)
                .title),
        parent);
}

void WorkstationFrame::install_default_panels() {
    // nav dock = 细图标轨 + [explorer / 工作流面板] 竖向分格
    // (qt_ribbon_native prototype: rail | 资源管理器 over 当前工作流).
    set_panel_factory("nav", [this](const std::string&,
                                    QWidget* parent) -> QWidget* {
        auto* region = new QFrame(parent);
        region->setObjectName("WorkstationNavigationRegion");
        auto* layout = new QHBoxLayout(region);
        layout->setContentsMargins(0, 0, 0, 0);
        layout->setSpacing(0);
        rail_ = new ActivityRail(region);
        rail_->set_icon_only(true);
        explorer_ = new WorkstationExplorer(region);
        workflow_panel_ = new WorkflowPanel(region);
        auto* column = new QSplitter(Qt::Orientation::Vertical, region);
        column->setObjectName("WorkstationNavColumn");
        column->setChildrenCollapsible(false);
        column->addWidget(explorer_);
        column->addWidget(workflow_panel_);
        column->setStretchFactor(0, 3);
        column->setStretchFactor(1, 2);
        nav_column_ = column;
        layout->addWidget(rail_);
        layout->addWidget(nav_column_, 1);
        connect(rail_, &ActivityRail::mode_requested, this,
                [this](const QString& mode) {
                    explorer_->set_mode(mode.toStdString());
                });
        connect(rail_, &ActivityRail::collapse_requested, this,
                [this] { set_explorer_expanded(!explorer_expanded_); });
        return region;
    });
    set_panel_factory("inspector",
                      [this](const std::string&,
                             QWidget* parent) -> QWidget* {
                          inspector_ = new WorkstationInspector(parent);
                          return inspector_;
                      });
    set_panel_factory("tasks",
                      [this](const std::string&,
                             QWidget* parent) -> QWidget* {
                          task_center_ = new WorkstationTaskCenter(parent);
                          connect(task_center_,
                                  &WorkstationTaskCenter::
                                      active_count_changed,
                                  app_bar_,
                                  &WorkstationAppBar::set_task_count);
                          return task_center_;
                      });
    set_panel_factory("logs",
                      [this](const std::string&,
                             QWidget* parent) -> QWidget* {
                          log_viewer_ = new WorkstationLogViewer(parent);
                          return log_viewer_;
                      });
    set_panel_factory("console",
                      [](const std::string&, QWidget* parent) {
                          return new WorkstationConsolePane(parent);
                      });
    set_panel_factory("agent",
                      [this](const std::string&,
                             QWidget* parent) -> QWidget* {
                          agent_panel_ = new AgentWorkspacePanel(parent);
                          return agent_panel_;
                      });
    // mapping_stage / composite_* / facies_palette / hub / well /
    // seismic stay factory-injected → PagePlaceholder by default.
}

QDockWidget* WorkstationFrame::make_dock(
    const ui_shell::DockDescriptor& desc) {
    auto* dock = new QDockWidget(QString::fromStdString(desc.title),
                                 dock_host_);
    dock->setObjectName(QString::fromStdString(desc.object_name));
    // pwbDockId is the persistence/lookup identity (Python parity).
    dock->setProperty("pwbDockId",
                      QString::fromStdString(desc.dock_id));
    auto features = QDockWidget::DockWidgetFeature::DockWidgetMovable |
                    QDockWidget::DockWidgetFeature::DockWidgetClosable;
    if (desc.can_float) {
        features |= QDockWidget::DockWidgetFeature::DockWidgetFloatable;
    }
    dock->setFeatures(features);
    dock->setWidget(content_for(desc.dock_id, dock));
    connect(dock, &QDockWidget::topLevelChanged, this,
            [this, dock, desc](bool floating) {
                // 浮动最小尺寸仅在浮动时挂：停靠 dock 永不带结构性下限。
                if (floating) {
                    dock->setMinimumSize(desc.min_floating_size.first,
                                         desc.min_floating_size.second);
                } else {
                    dock->setMinimumSize(0, 0);
                }
                sync_titlebar_for_float(dock, floating);
            });
    return dock;
}

void WorkstationFrame::build_docks() {
    if (built_) return;
    built_ = true;
    const auto& registry = ui_shell::workstation_dock_registry();
    for (const auto& desc : registry.descriptors()) {
        QDockWidget* dock = make_dock(desc);
        dock_host_->addDockWidget(area_for(desc.preferred_area), dock);
        if (!desc.default_visible) {
            dock->hide();
        }
        docks_[desc.dock_id] = dock;
        connect(dock, &QDockWidget::visibilityChanged, this,
                [this](bool) {
                    if (!tearing_down_) {
                        note_user_layout_change();
                    }
                });
    }

    // Prototype 面板自带标题（资源管理器/图层管理 headers）——固定布局
    // 面的原生 dock 标题栏是重复 chrome；显隐由 面板菜单/profile 管，
    // tab 组仍有 tab bar。pwbBlankTitle 标记让悬浮切换还原原生标题栏
    //（sync_titlebar_for_float：悬浮面板需要可拖动/关闭的 chrome）。
    // 可选查看器（agent/console/well/seismic 等）保留标题栏。
    for (const char* id :
         {"nav", "inspector", "composite_layer", "facies_palette",
          "composite_input", "predict_compare", "reference_maps",
          "map_decor", "layout_output", "tasks", "logs",
          "verify_records", "data_preview", "data_history",
          "data_relations", "pair_link", "predict_task",
          "seismic_predict", "crosswell", "data_prep",
          "strat_compare", "seq_frame", "factor_refs", "data_props",
          "data_lineage"}) {
        if (auto* d = dock(id)) {
            d->setProperty("pwbBlankTitle", true);
            auto* blank = new QWidget(d);
            blank->setFixedSize(0, 0);
            d->setTitleBarWidget(blank);
        }
    }
}

void WorkstationFrame::sync_titlebar_for_float(QDockWidget* dock,
                                               bool floating) {
    if (dock == nullptr ||
        !dock->property("pwbBlankTitle").toBool()) {
        return;
    }
    if (floating) {
        // 还原默认标题栏 —— 悬浮面板需要窗口 chrome（拖动/关闭/贴回）。
        dock->setTitleBarWidget(nullptr);
    } else {
        auto* blank = new QWidget(dock);
        blank->setFixedSize(0, 0);
        dock->setTitleBarWidget(blank);
    }
}

void WorkstationFrame::install_panel(const std::string& dock_id,
                                     QWidget* content) {
    auto* target = dock(dock_id);
    if (target == nullptr || content == nullptr) return;
    if (auto* old = target->widget()) {
        // setWidget 不接管旧部件 —— 显式退役占位/旧内容。
        old->setParent(nullptr);
        old->deleteLater();
    }
    target->setWidget(content);
    // 与 adopt_dock 同义：真实内容已注入，占位护栏视作 factory-backed。
    target->setProperty("pwbAdopted", true);
}

void WorkstationFrame::finish_dock_layout() {
    if (tabs_built_) return;
    tabs_built_ = true;

    // Prototype right column = ONE tabbed surface (检查器 | 图层管理 |
    // 相带画刷 | 输入与结果); hidden members join the group and raise as
    // tabs when a profile/user shows them. Bottom utilities form the
    // 任务|日志|… strip the same way. can_tabify=false docks stay split.
    auto tabify = [this](std::initializer_list<const char*> ids) {
        QDockWidget* anchor = nullptr;
        for (const char* id : ids) {
            auto* other = dock(id);
            if (other == nullptr) continue;
            const auto* desc =
                ui_shell::workstation_dock_registry().get(id);
            if (desc != nullptr && !desc->can_tabify) continue;
            if (anchor == nullptr) {
                anchor = other;
            } else {
                dock_host_->tabifyDockWidget(anchor, other);
            }
        }
        return anchor;
    };
    // 右栏组序 = 跨工作区原型页签的全序（每工作区只显示子集 ——
    // navigate_workspace 按目标页序重放显隐，顺序即 tab 顺序）：
    //   ws1 图层|预测参数|对比(相带画刷)；ws2 约束|单因素|参考；
    //   ws3 编图图层|图件整饰|版式输出。
    tabify({"composite_layer", "inspector", "constraint_panel",
            "composite_input", "predict_compare", "reference_maps",
            "facies_palette", "map_decor", "layout_output", "hub"});
    // ws0 右列两片同显（数据属性 上 / 数据血缘 下）—— 竖向二分，
    // 不并入 tab 组；两格默认隐藏 → ws0 之外不占地。
    if (auto* props = dock("data_props")) {
        if (auto* lineage = dock("data_lineage")) {
            dock_host_->splitDockWidget(props, lineage, Qt::Vertical);
        }
    }
    // 底部两行（DockNestingEnabled）：row0 = 阶段/预览面板组
    // （每工作区投影成员，全隐时该行塌陷为 0），row1 = 任务|日志|…
    // 工具条。Qt 怪癖：tabifyDockWidget 只对可见 dock 生效，且
    // splitDockWidget 会把锚点拖出既有 tab 组 —— 所以顺序必须是：
    // 临时显示全部阶段 dock → 工具条逐格竖分裂到 row1 → 两组各自
    // 成 tab → 阶段组重新整组（锚点在 split 时离组）→ 全隐回默认。
    // 全程在同一事件内完成，不产生可见闪烁。
    static const char* kStageDocks[] = {
        "data_preview", "data_history", "data_relations", "pair_link",
        "predict_task", "seismic_predict", "crosswell", "data_prep",
        "strat_compare", "seq_frame", "factor_refs"};
    static const char* kUtilDocks[] = {
        "logs", "verify_records", "factor_stats", "console", "agent",
        "composite_linked", "well", "seismic"};
    for (const char* id : kStageDocks) {
        if (auto* d = dock(id)) d->setVisible(true);
    }
    auto* tasks_dock = dock("tasks");
    if (auto* anchor = dock("data_preview"); anchor != nullptr &&
        tasks_dock != nullptr) {
        dock_host_->splitDockWidget(anchor, tasks_dock, Qt::Vertical);
        for (const char* id : kUtilDocks) {
            if (auto* u = dock(id)) {
                dock_host_->splitDockWidget(tasks_dock, u, Qt::Horizontal);
            }
        }
        tabify({"tasks", "logs", "verify_records", "factor_stats",
                "console", "agent", "composite_linked", "well",
                "seismic"});
    }
    tabify({"data_preview", "data_history", "data_relations",
            "pair_link", "predict_task", "seismic_predict", "crosswell",
            "data_prep", "strat_compare", "seq_frame", "factor_refs"});
    for (const char* id : kStageDocks) {
        if (auto* d = dock(id)) {
            const auto* desc =
                ui_shell::workstation_dock_registry().get(id);
            if (desc != nullptr && !desc->default_visible) {
                d->setVisible(false);
            }
        }
    }
    // 底条默认当前页 = 任务（prototype parity）；右栏当前页由
    // navigate_workspace 按工作区首个成员抬起。
    if (auto* tasks = dock("tasks")) {
        tasks->raise();
    }
    // ctor 里跑过一次时宿主还是 0x0，resizeDocks 不落地 —— 首个布局
    // 之后重放（tabs_built_ 保证本函数只进一次）。宽度+高度都重放：
    // 底部两行已就位，工具条 140px 常驻高、阶段行 preferred_height
    // 记在隐藏 cell 上（显示时按描述符高出现）。
    ui_shell::apply_first_run_sizes(dock_host_, docks_,
                                    /*include_heights=*/true);
    emit dock_layout_ready();
}

QDockWidget* WorkstationFrame::dock(const std::string& dock_id) const {
    const auto it = docks_.find(dock_id);
    return it != docks_.end() ? it->second : nullptr;
}

void WorkstationFrame::set_dock_visible(const std::string& dock_id,
                                        bool visible) {
    if (auto* d = dock(dock_id)) {
        if (dock_id == "inspector" && !inspector_hidden_by_viewport_) {
            inspector_user_visible_ = visible;
        }
        d->setVisible(visible);
    }
}

bool WorkstationFrame::dock_visible(const std::string& dock_id) const {
    const auto* d = dock(dock_id);
    return d != nullptr && d->isVisible();
}

void WorkstationFrame::apply_layout_preset(
    const std::string& preset_id) {
    const auto* preset = ui_shell::get_preset(preset_id);
    if (preset == nullptr) return;
    current_preset_ = preset_id;
    apply_visibility(preset->visibility);
    app_bar_->set_current_workspace(preset_id);
    emit layout_changed();
}

void WorkstationFrame::apply_visibility(
    const ui_shell::DockVisibilityMatrix& m) {
    for (const auto& [id, visible] : ui_shell::visibility_dict(m)) {
        if (auto* d = dock(id)) {
            if (id == "inspector" && inspector_hidden_by_viewport_) {
                continue;  // viewport policy wins while narrow
            }
            d->setVisible(visible);
            if (id == "inspector") inspector_user_visible_ = visible;
        }
    }
    set_explorer_expanded(m.explorer_expanded);
}

void WorkstationFrame::note_user_layout_change() {
    if (current_preset_.empty()) return;
    current_preset_.clear();
    app_bar_->set_current_workspace("");  // 自定义
    emit layout_changed();
}

void WorkstationFrame::apply_first_run_sizes() {
    ui_shell::apply_first_run_sizes(dock_host_, docks_);
}

bool WorkstationFrame::mount_top_bar(QWidget* bar) {
    if (bar == nullptr || top_bar_ != nullptr || app_bar_toolbar_ == nullptr) {
        return false;
    }
    if (bar == app_bar_) return false;
    top_bar_ = bar;
    bar->setParent(app_bar_toolbar_);
    app_bar_toolbar_->addWidget(bar);
    app_bar_toolbar_->setVisible(true);  // 宿主挂载条 → 顶行重新出现
    return true;
}

void WorkstationFrame::set_explorer_expanded(bool expanded) {
    explorer_expanded_ = expanded;
    // 折叠整列（explorer + 工作流面板），细轨保留 — prototype parity。
    QWidget* column = nav_column_ != nullptr ? nav_column_ : explorer_;
    if (column != nullptr) column->setVisible(expanded);
    if (rail_ != nullptr) rail_->set_explorer_expanded(expanded);
}

void WorkstationFrame::apply_viewport_class(
    ui_shell::ViewportClass cls) {
    app_bar_->set_command_input_floor(
        cls == ui_shell::ViewportClass::Compact
            ? ui_shell::kCommandInputFloorCompact
            : ui_shell::kCommandInputFloorNormal);
}

void WorkstationFrame::apply_inspector_policy(int width) {
    auto* d = dock("inspector");
    if (d == nullptr) return;
    if (width < ui_shell::kInspectorHideBelow) {
        if (!inspector_hidden_by_viewport_) {
            inspector_hidden_by_viewport_ = true;
            inspector_user_visible_ = d->isVisible();
            d->hide();
        }
    } else if (width > ui_shell::kInspectorRestoreAbove) {
        if (inspector_hidden_by_viewport_) {
            inspector_hidden_by_viewport_ = false;
            d->setVisible(inspector_user_visible_);
        }
    }
}

bool WorkstationFrame::eventFilter(QObject* obj, QEvent* event) {
    if (obj == dock_host_ && event->type() == QEvent::Type::Show &&
        !tabs_built_) {
        // tabifyDockWidget 在首个布局前建第二个 tab 组会留下孤儿
        // QTabBar（Qt dock 布局怪癖）——首次显示后再排队成组。
        QMetaObject::invokeMethod(
            this, [this] { finish_dock_layout(); },
            Qt::ConnectionType::QueuedConnection);
    }
    if (obj == dock_host_ && event->type() == QEvent::Type::Resize) {
        const int width = dock_host_->width();
        apply_viewport_class(ui_shell::classify_viewport(width));
        apply_inspector_policy(width);
    }
    return QFrame::eventFilter(obj, event);
}

void WorkstationFrame::shutdown() {
    // Teardown freeze: dock visibility churn during destruction must
    // not fire layout persistence or preset-revert writes.
    tearing_down_ = true;
    if (task_center_ != nullptr) task_center_->shutdown();
    if (log_viewer_ != nullptr) log_viewer_->shutdown();
}

}  // namespace pwb::ui_workstation
