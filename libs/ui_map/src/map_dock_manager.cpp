#include <pwb/ui_map/map_dock_manager.hpp>

#include <QAction>
#include <QFrame>
#include <QIcon>
#include <QMenu>
#include <QSize>
#include <QToolButton>
#include <QVBoxLayout>

#include <pwb/ui_map/map_chrome_core.hpp>
#include <pwb/ui_shell/float_controller.hpp>
#include <pwb/ui_shell/floating_panel.hpp>

namespace pwb::ui_map {

namespace {

QString qstr(const std::string& s) {
    return QString::fromUtf8(s.data(), static_cast<qsizetype>(s.size()));
}

}  // namespace

// ---------------------------------------------------------------------------
// DockRail
// ---------------------------------------------------------------------------

DockRail::DockRail(const std::string& side_in, QWidget* parent)
    : side(side_in) {
    rail = new QFrame(parent);
    rail->setObjectName(QStringLiteral("MapDockRail"));
    rail->setProperty("side", qstr(side));
    rail->setFixedWidth(kRailWidth);
    rail_layout = new QVBoxLayout(rail);
    rail_layout->setContentsMargins(3, 6, 3, 6);
    rail_layout->setSpacing(4);
    // Box layouts on this Qt build spread extra space between fixed-size
    // items unless the layout is explicitly top-aligned.
    rail_layout->setAlignment(Qt::AlignTop);

    area = new QFrame(parent);
    area->setObjectName(QStringLiteral("MapDockArea"));
    area_layout = new QVBoxLayout(area);
    area_layout->setContentsMargins(0, 0, 0, 0);
    area_layout->setSpacing(4);
}

QToolButton* DockRail::rail_button(const QString& title,
                                   const QString& icon_name) {
    auto* button = new QToolButton(rail);
    button->setCheckable(true);
    // Theme-tinted icons are a workstation-icon concern (E2 lazy loader);
    // the C++ rail uses the icon name as its identity, matching the
    // manager's vocabulary. Named icons resolve through the platform
    // icon theme when available.
    if (!icon_name.isEmpty()) {
        button->setIcon(QIcon::fromTheme(icon_name));
    }
    button->setIconSize(QSize(kRailIconSize, kRailIconSize));
    button->setFixedSize(kRailButtonSize, kRailButtonSize);
    button->setToolTip(title);
    button->setProperty("dockRailItem", "true");
    return button;
}

void DockRail::sync_area_visibility() {
    bool visible = false;
    for (int i = 0; i < area_layout->count(); ++i) {
        QLayoutItem* item = area_layout->itemAt(i);
        if (item != nullptr && item->widget() != nullptr &&
            !item->widget()->isHidden()) {
            visible = true;
            break;
        }
    }
    area->setVisible(visible);
}

// ---------------------------------------------------------------------------
// MapDockManager
// ---------------------------------------------------------------------------

MapDockManager::MapDockManager(QObject* parent)
    : QObject(parent),
      left_dock_("left"),
      right_dock_("right") {}

void MapDockManager::attach_float_controller(
    pwb::ui_shell::FloatController* controller) {
    if (controller == float_controller_) {
        return;
    }
    float_controller_ = controller;
    connect(controller, &pwb::ui_shell::FloatController::float_changed,
            this, [this](const QString& key, bool floating) {
                on_float_changed(key, floating);
            });
    for (const auto& key : panel_order_) {
        install_rail_context_menu(key);
    }
}

void MapDockManager::add_panel(const std::string& key, const QString& title,
                               const QString& icon_name, QWidget* widget,
                               const std::string& side, bool checked,
                               const std::string& float_key) {
    DockRail* dock = side == "left" ? &left_dock_ : &right_dock_;
    QToolButton* button = dock->rail_button(title, icon_name);
    connect(button, &QToolButton::toggled, this,
            [this, key](bool on) { on_rail_toggled(key, on); });
    dock->area_layout->addWidget(widget, 1);
    PanelEntry entry;
    entry.key = key;
    entry.title = title;
    entry.icon_name = icon_name;
    entry.widget = widget;
    entry.dock = dock;
    entry.button = button;
    entry.float_key = float_key.empty() ? key : float_key;
    panels_[key] = entry;
    panel_order_.push_back(key);
    dock->rail_layout->addWidget(button);
    button->setChecked(checked);
    widget->setVisible(checked);
    dock->sync_area_visibility();
    install_rail_context_menu(key);
}

void MapDockManager::register_bottom(const std::string& key,
                                     const QString& title,
                                     const QString& icon_name,
                                     QWidget* widget,
                                     std::function<void()> apply,
                                     const std::string& float_key) {
    bottom_widget_ = widget;
    bottom_apply_ = std::move(apply);
    QToolButton* button = left_dock_.rail_button(title, icon_name);
    connect(button, &QToolButton::toggled, this,
            [this, key](bool on) { on_bottom_toggled(key, on); });
    PanelEntry entry;
    entry.key = key;
    entry.title = title;
    entry.icon_name = icon_name;
    entry.widget = widget;
    entry.dock = nullptr;
    entry.button = button;
    entry.float_key = float_key.empty() ? key : float_key;
    panels_[key] = entry;
    panel_order_.push_back(key);
    QVBoxLayout* rail_layout = left_dock_.rail_layout;
    const int stretch_index = rail_layout->count();
    rail_layout->insertStretch(stretch_index, 1);
    rail_layout->addWidget(button);
    button->setChecked(true);
    install_rail_context_menu(key);
}

// BEGIN CLOSURE-MAPPING (08-line adopt)
void MapDockManager::adopt_panel_widget(const std::string& key,
                                        QWidget* widget) {
    if (widget == nullptr) return;
    if (PanelEntry* entry = entry_for(key); entry != nullptr) {
        entry->widget = QPointer<QWidget>(widget);
    }
}
// END CLOSURE-MAPPING

void MapDockManager::set_panel_visible(const std::string& key,
                                       bool visible) {
    PanelEntry* entry = entry_for(key);
    if (entry != nullptr && entry->button != nullptr) {
        entry->button->setChecked(visible);
    }
}

bool MapDockManager::is_panel_visible(const std::string& key) const {
    const PanelEntry* entry = entry_for(key);
    return entry != nullptr && entry->button != nullptr &&
           entry->button->isChecked();
}

bool MapDockManager::is_panel_registered(const std::string& key) const {
    return entry_for(key) != nullptr;
}

QToolButton* MapDockManager::panel_button(const std::string& key) const {
    const PanelEntry* entry = entry_for(key);
    return entry != nullptr ? entry->button.data() : nullptr;
}

void MapDockManager::set_bottom_window_visible(bool visible) {
    bottom_programmatic_ = true;
    if (float_controller_ != nullptr) {
        pwb::ui_shell::FloatingPanel* panel =
            float_controller_->floating_panel(float_key_of("bottom"));
        if (panel != nullptr) {
            panel->setVisible(visible);
        }
    }
    bottom_programmatic_ = false;
}

std::string MapDockManager::panel_title(const std::string& key) const {
    const PanelEntry* entry = entry_for(key);
    if (entry == nullptr) {
        const std::string resolved = key_for_float_key(key);
        if (!resolved.empty()) {
            entry = entry_for(resolved);
        }
    }
    if (entry != nullptr) {
        return entry->title.toStdString();
    }
    return panel_title_fallback(key);
}

bool MapDockManager::is_floating(const std::string& key) const {
    if (float_controller_ == nullptr) {
        return false;
    }
    return float_controller_->is_floating(float_key_of(key));
}

void MapDockManager::toggle_float(const std::string& key) {
    if (float_controller_ != nullptr) {
        float_controller_->toggle(float_key_of(key));
    }
}

QMenu* MapDockManager::panels_menu(QWidget* parent) {
    auto* menu = new QMenu(QStringLiteral("面板"), parent);
    for (const std::string& key : panel_order_) {
        PanelEntry* entry = entry_for(key);
        if (entry == nullptr) {
            continue;
        }
        auto* action = new QAction(entry->title, menu);
        if (!entry->icon_name.isEmpty()) {
            action->setIcon(QIcon::fromTheme(entry->icon_name));
        }
        action->setObjectName(qstr("MapPanelMenu:" + key));
        action->setCheckable(true);
        action->setChecked(entry->button != nullptr &&
                           entry->button->isChecked());
        connect(action, &QAction::toggled, this,
                [this, key](bool on) { set_panel_visible(key, on); });
        menu->addAction(action);
        entry->menu_action = action;
        if (float_controller_ != nullptr) {
            QAction* float_action = float_menu_action(menu, key);
            entry->float_menu_action = float_action;
            menu->addAction(float_action);
        }
    }
    menu_ = menu;
    return menu;
}

void MapDockManager::install_rail_context_menu(const std::string& key) {
    if (float_controller_ == nullptr) {
        return;
    }
    PanelEntry* entry = entry_for(key);
    if (entry == nullptr || entry->button == nullptr) {
        return;
    }
    entry->button->setContextMenuPolicy(Qt::CustomContextMenu);
    connect(entry->button, &QWidget::customContextMenuRequested, this,
            [this, key](const QPoint& pos) { show_rail_menu(key, pos); });
}

QMenu* MapDockManager::rail_context_menu(const std::string& key) {
    PanelEntry* entry = entry_for(key);
    auto* menu = new QMenu(entry != nullptr ? entry->button.data()
                                            : nullptr);
    menu->addAction(float_menu_action(menu, key));
    return menu;
}

void MapDockManager::show_rail_menu(const std::string& key,
                                    const QPoint& pos) {
    PanelEntry* entry = entry_for(key);
    if (entry == nullptr || entry->button == nullptr) {
        return;
    }
    QMenu* menu = rail_context_menu(key);
    // Right-click menus are transient: delete menu + actions on close
    // instead of leaking one pair per right-click.
    menu->setAttribute(Qt::WA_DeleteOnClose);
    menu->exec(entry->button->mapToGlobal(pos));
}

QAction* MapDockManager::float_menu_action(QObject* parent,
                                           const std::string& key) {
    PanelEntry* entry = entry_for(key);
    const QString title =
        entry != nullptr ? entry->title : qstr(key);
    auto* action = new QAction(
        QStringLiteral("浮动 · %1").arg(title), parent);
    if (entry != nullptr && !entry->icon_name.isEmpty()) {
        action->setIcon(QIcon::fromTheme(entry->icon_name));
    }
    action->setObjectName(qstr("MapPanelFloat:" + key));
    action->setCheckable(true);
    action->setChecked(is_floating(key));
    connect(action, &QAction::toggled, this,
            [this, key](bool on) { on_float_action_toggled(key, on); });
    return action;
}

void MapDockManager::on_float_action_toggled(const std::string& key,
                                             bool on) {
    pwb::ui_shell::FloatController* controller = float_controller_;
    if (controller == nullptr || is_floating(key) == on) {
        return;
    }
    controller->toggle(float_key_of(key));
}

void MapDockManager::on_rail_toggled(const std::string& key, bool on) {
    PanelEntry* entry = entry_for(key);
    if (entry == nullptr) {
        return;
    }
    pwb::ui_shell::FloatController* controller = float_controller_;
    if (controller != nullptr && is_floating(key)) {
        // The widget currently lives in its floating window; the rail
        // button shows/hides that window instead of the bare widget.
        pwb::ui_shell::FloatingPanel* panel =
            controller->floating_panel(entry->float_key);
        if (panel != nullptr) {
            panel->setVisible(on);
        }
    } else if (entry->widget != nullptr) {
        entry->widget->setVisible(on);
    }
    if (entry->dock != nullptr) {
        entry->dock->sync_area_visibility();
    }
    sync_menu_action(key, on);
    emit panel_toggled(qstr(key), on);
}

void MapDockManager::on_float_changed(const QString& float_key_q,
                                      bool floating) {
    const std::string float_key = float_key_q.toStdString();
    const std::string key = key_for_float_key(float_key);
    if (key.empty()) {
        return;
    }
    PanelEntry* entry = entry_for(key);
    if (entry == nullptr) {
        return;
    }
    if (floating) {
        // Floating implies showing the panel; the rail button keeps
        // meaning "panel visible", so it flips on and shows the window.
        if (entry->button != nullptr) {
            entry->button->setChecked(true);
        }
        if (entry->widget != nullptr) {
            entry->widget->setVisible(true);
        }
        // Mirror externally-driven window visibility (the panel's hide
        // button, Alt+F4, restore of a saved-hidden panel) on the rail
        // button. Each float creates a fresh FloatingPanel, so this
        // connects exactly once per window.
        pwb::ui_shell::FloatingPanel* panel =
            float_controller_ != nullptr
                ? float_controller_->floating_panel(float_key)
                : nullptr;
        if (panel != nullptr) {
            connect(panel,
                    &pwb::ui_shell::FloatingPanel::visibility_changed,
                    this,
                    [this, float_key](const QString&, bool visible) {
                        on_floating_window_visibility(float_key, visible);
                    });
        }
    } else {
        // Docked again: restore the plain setVisible semantics (hidden
        // until the button — or the page's apply callback — says
        // otherwise).
        if (entry->widget != nullptr && entry->button != nullptr) {
            entry->widget->setVisible(entry->button->isChecked());
        }
    }
    if (entry->dock != nullptr) {
        // The reparent moved the widget out of (or back into) the area.
        entry->dock->sync_area_visibility();
    }
    sync_float_menu_action(key, floating);
}

void MapDockManager::on_floating_window_visibility(
    const std::string& float_key, bool visible) {
    const std::string key = key_for_float_key(float_key);
    if (key.empty()) {
        return;
    }
    PanelEntry* entry = entry_for(key);
    if (entry == nullptr || entry->button == nullptr) {
        return;
    }
    if (entry->button->isChecked() != visible) {
        entry->button->blockSignals(true);
        entry->button->setChecked(visible);
        entry->button->blockSignals(false);
        sync_menu_action(key, visible);
        emit panel_toggled(qstr(key), visible);
    }
    if (entry->dock == nullptr && !bottom_programmatic_) {
        bottom_user_visible_ = visible;
        if (bottom_apply_ != nullptr) {
            bottom_apply_();
        }
    }
}

void MapDockManager::on_bottom_toggled(const std::string& key, bool on) {
    bottom_user_visible_ = on;
    if (bottom_apply_ != nullptr) {
        bottom_apply_();
    }
    sync_menu_action(key, on);
    emit panel_toggled(qstr(key), on);
}

void MapDockManager::sync_menu_action(const std::string& key, bool on) {
    const PanelEntry* entry = entry_for(key);
    if (entry != nullptr && entry->menu_action != nullptr &&
        entry->menu_action->isChecked() != on) {
        entry->menu_action->blockSignals(true);
        entry->menu_action->setChecked(on);
        entry->menu_action->blockSignals(false);
    }
}

void MapDockManager::sync_float_menu_action(const std::string& key,
                                            bool floating) {
    const PanelEntry* entry = entry_for(key);
    if (entry != nullptr && entry->float_menu_action != nullptr &&
        entry->float_menu_action->isChecked() != floating) {
        entry->float_menu_action->blockSignals(true);
        entry->float_menu_action->setChecked(floating);
        entry->float_menu_action->blockSignals(false);
    }
}

MapDockManager::PanelEntry* MapDockManager::entry_for(
    const std::string& key) {
    const auto it = panels_.find(key);
    return it != panels_.end() ? &it->second : nullptr;
}

const MapDockManager::PanelEntry* MapDockManager::entry_for(
    const std::string& key) const {
    const auto it = panels_.find(key);
    return it != panels_.end() ? &it->second : nullptr;
}

std::string MapDockManager::float_key_of(const std::string& key) const {
    const PanelEntry* entry = entry_for(key);
    return entry != nullptr ? entry->float_key : key;
}

std::string MapDockManager::key_for_float_key(
    const std::string& float_key) const {
    for (const std::string& key : panel_order_) {
        const auto it = panels_.find(key);
        if (it != panels_.end() && it->second.float_key == float_key) {
            return key;
        }
    }
    return "";
}

}  // namespace pwb::ui_map
