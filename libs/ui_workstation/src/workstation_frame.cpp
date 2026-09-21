#include "pwb/ui_workstation/workstation_frame.hpp"

#include <QEvent>
#include <QHBoxLayout>
#include <QScrollArea>
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
    dock_host_->setTabPosition(
        Qt::DockWidgetArea::AllDockWidgetAreas,
        QTabWidget::TabPosition::North);
    dock_host_->installEventFilter(this);
    outer->addWidget(dock_host_, 1);

    // App bar on the host's top toolbar row — full width, immovable.
    app_bar_toolbar_ = new QToolBar("工作站全局栏", dock_host_);
    app_bar_toolbar_->setObjectName("WorkstationAppBarToolbar");
    app_bar_toolbar_->setMovable(false);
    app_bar_toolbar_->setFloatable(false);
    app_bar_ = new WorkstationAppBar(app_bar_toolbar_);
    app_bar_toolbar_->addWidget(app_bar_);
    dock_host_->addToolBar(Qt::ToolBarArea::TopToolBarArea,
                           app_bar_toolbar_);

    install_default_panels();
}

void WorkstationFrame::set_central_widget(QWidget* page_stack) {
    central_ = page_stack;
    if (central_ != nullptr) {
        dock_host_->setCentralWidget(central_);
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
    // nav dock = activity rail + explorer (Python navigation_region).
    set_panel_factory("nav", [this](const std::string&,
                                    QWidget* parent) -> QWidget* {
        auto* region = new QFrame(parent);
        region->setObjectName("WorkstationNavigationRegion");
        auto* layout = new QHBoxLayout(region);
        layout->setContentsMargins(0, 0, 0, 0);
        layout->setSpacing(0);
        rail_ = new ActivityRail(region);
        explorer_ = new WorkstationExplorer(region);
        layout->addWidget(rail_);
        layout->addWidget(explorer_, 1);
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
        if (!desc.default_visible) dock->hide();
        docks_[desc.dock_id] = dock;
        connect(dock, &QDockWidget::visibilityChanged, this,
                [this](bool) {
                    if (!tearing_down_) {
                        note_user_layout_change();
                    }
                });
    }
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
    return true;
}

void WorkstationFrame::set_explorer_expanded(bool expanded) {
    explorer_expanded_ = expanded;
    if (explorer_ != nullptr) explorer_->setVisible(expanded);
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
