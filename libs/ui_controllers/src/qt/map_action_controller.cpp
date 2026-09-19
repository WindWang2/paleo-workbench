#include <pwb/ui_controllers/qt/map_action_controller.hpp>

#include <QKeySequence>
#include <QSignalBlocker>
#include <QSize>

#include <algorithm>
#include <filesystem>

namespace pwb::ui_controllers::qt {

namespace {

namespace fs = std::filesystem;

fs::path g_icon_root;  // set_icon_root; empty → icon lookup misses honestly

// _resolve_icon parity: map/ first, root fallback; .svg suffix implied.
fs::path resolve_icon_path(const std::string& stem) {
    if (g_icon_root.empty()) return {};
    for (const fs::path& dir : {g_icon_root / "map", g_icon_root}) {
        const fs::path candidate = dir / (stem + ".svg");
        std::error_code ec;
        if (fs::exists(candidate, ec) && !ec) return candidate;
    }
    return {};
}

const MapActionSpec* spec_of(const std::string& action_id) {
    const auto it = action_specs().find(action_id);
    return it != action_specs().end() ? &it->second : nullptr;
}

bool is_checkable_command(const std::string& action_id) {
    const auto& ids = map_checkable_command_ids();
    return std::find(ids.begin(), ids.end(), action_id) != ids.end();
}

}  // namespace

// The icon root is host-configured (Python resolves the package assets
// dir statically); the integration adapter points it at the deployed
// assets/icons directory. Unset → icons resolve to null, same as a
// missing asset.
void set_map_icon_root(const std::filesystem::path& root) {
    g_icon_root = root;
}

QIcon map_action_icon(const std::string& icon_name,
                      const std::string& fallback) {
    for (const std::string* name : {&icon_name, &fallback}) {
        if (name->empty()) continue;
        const fs::path path = resolve_icon_path(*name);
        if (!path.empty()) {
            return QIcon(QString::fromStdString(path.generic_string()));
        }
    }
    return QIcon();
}

MapActionController::MapActionController(QObject* parent)
    : QObject(parent) {
    tool_group_ = new QActionGroup(this);
    tool_group_->setExclusive(true);

    // _TOOL_IDS — checkable canvas MapTools in one exclusive group;
    // tool_requested fires only when the trigger lands checked.
    for (const auto& tool_id : map_tool_ids()) {
        QAction* action = make_action_(tool_id, /*checkable=*/true, {});
        tool_group_->addAction(action);
        connect(action, &QAction::triggered, this,
                [this, tool_id](bool checked) {
                    if (checked)
                        emit tool_requested(QString::fromStdString(tool_id));
                });
    }
    // _COMMAND_IDS — one-shot commands (checkable subset keeps state).
    for (const auto& command_id : map_command_ids()) {
        const MapActionSpec* spec = spec_of(command_id);
        QAction* action = make_action_(
            command_id, is_checkable_command(command_id),
            spec != nullptr ? spec->shortcut : std::string{});
        connect(action, &QAction::triggered, this,
                [this, command_id](bool) {
                    emit command_requested(
                        QString::fromStdString(command_id));
                });
    }
    if (auto* pan = action("pan")) pan->setChecked(true);
    // _SURFACE_EXTENSION_IDS — V7 extension commands appended after the
    // core set (build order is the contract).
    for (const auto& action_id : map_surface_extension_ids()) {
        QAction* action = make_action_(action_id, /*checkable=*/false, {});
        connect(action, &QAction::triggered, this,
                [this, action_id](bool) {
                    emit command_requested(
                        QString::fromStdString(action_id));
                });
    }
}

QAction* MapActionController::action(const std::string& action_id) const {
    const auto it = actions_.find(action_id);
    return it != actions_.end() ? it->second : nullptr;
}

QAction* MapActionController::make_action_(
    const std::string& action_id, bool checkable,
    const std::string& shortcut) {
    const MapActionSpec* spec = spec_of(action_id);
    // Icon chain parity: spec.icon (covers the extension ids' surface
    // icons) → action_id fallback → empty icon on miss.
    const std::string icon_name =
        (spec != nullptr && !spec->icon.empty()) ? spec->icon : action_id;
    const std::string label =
        (spec != nullptr && !spec->label.empty()) ? spec->label : action_id;
    auto* action = new QAction(
        map_action_icon(icon_name), QString::fromStdString(label), this);
    action->setObjectName(
        QStringLiteral("MapAction:%1").arg(QString::fromStdString(action_id)));
    action->setCheckable(checkable);
    action->setToolTip(QString::fromStdString(label));
    action->setStatusTip(QString::fromStdString(label));
    if (!shortcut.empty()) {
        action->setShortcut(QKeySequence(QString::fromStdString(shortcut)));
        // The window also binds Ctrl+S to project save: keep this action's
        // shortcut confined to the editing widget tree (WidgetWithChildren
        // parity) so the two don't collide.
        action->setShortcutContext(
            Qt::ShortcutContext::WidgetWithChildrenShortcut);
    }
    actions_[action_id] = action;
    return action;
}

void MapActionController::apply_availability(
    const std::map<std::string, tool_policy::ToolAvailability>& availability,
    const std::map<std::string, std::pair<std::string, std::string>>*
        help_texts) {
    for (const auto& [tool_id, result] : availability) {
        QAction* target = action(tool_id);
        if (target == nullptr) {
            continue;  // evaluator may cover tools this host has no action for
        }
        std::optional<std::pair<std::string, std::string>> override_text;
        if (help_texts != nullptr) {
            const auto it = help_texts->find(tool_id);
            if (it != help_texts->end()) override_text = it->second;
        }
        const MapActionPresentation plan =
            availability_text(tool_id, result, override_text);
        target->setEnabled(plan.enabled);
        target->setVisible(plan.visible);
        target->setToolTip(QString::fromStdString(plan.tooltip));
        target->setStatusTip(QString::fromStdString(plan.status_tip));
        if (target->isCheckable() &&
            target->isChecked() != plan.checked) {
            // Checkable updates never re-emit (blockSignals parity).
            const QSignalBlocker blocker(target);
            target->setChecked(plan.checked);
        }
    }
}

QToolBar* MapActionController::toolbar(
    const QString& title,
    const std::vector<std::vector<std::string>>& action_id_entries,
    QWidget* parent) {
    auto* bar = new QToolBar(title, parent);
    bar->setObjectName(QStringLiteral("MapToolbar:%1")
                           .arg(QString(title).remove(' ')));
    bar->setMovable(false);
    bar->setToolButtonStyle(Qt::ToolButtonStyle::ToolButtonIconOnly);
    bar->setIconSize(QSize(18, 18));
    const auto plan = toolbar_plan(action_id_entries);
    for (const auto& entry : plan) {
        if (entry.separator) {
            bar->addSeparator();
            continue;
        }
        QAction* target = action(entry.action_id);
        if (target != nullptr) bar->addAction(target);
    }
    return bar;
}

}  // namespace pwb::ui_controllers::qt
