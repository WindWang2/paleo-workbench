// UI-06 — AssetContextMenu shell (see qt/asset_context_menu.hpp).
#include <pwb/ui_pages_data/qt/asset_context_menu.hpp>

#include <QAction>
#include <QDesktopServices>
#include <QUrl>

namespace pwb::ui_pages_data::qt {

DestructiveIconFn AssetContextMenu::destructive_icon_fn_;

AssetContextMenu::AssetContextMenu(QWidget* parent) : QMenu(parent) {}

void AssetContextMenu::set_destructive_icon_fn(DestructiveIconFn fn) {
    destructive_icon_fn_ = std::move(fn);
}

void AssetContextMenu::build(const AssetView& view, AssetKind kind,
                             const MenuCapabilities& caps) {
    build_from_entries(build_asset_menu_model(view, kind, caps));
}

void AssetContextMenu::build_multi(int count) {
    build_from_entries(build_multi_menu_model(count));
}

void AssetContextMenu::build_from_entries(
    const std::vector<MenuEntry>& entries) {
    clear();
    action_registry_.clear();
    export_actions_.clear();
    for (const auto& entry : entries) {
        add_entry(entry, this);
    }
}

QAction* AssetContextMenu::add_entry(const MenuEntry& entry, QMenu* menu) {
    switch (entry.kind) {
    case MenuEntry::Kind::Separator:
        menu->addSeparator();
        return nullptr;
    case MenuEntry::Kind::Submenu: {
        auto* sub = new QMenu(QString::fromStdString(entry.label), menu);
        for (const auto& child : entry.children) {
            QAction* action = add_entry(child, sub);
            if (action != nullptr) {
                // _export_actions parity: classify children register under
                // "classify_<rtype>", exports under their format label,
                // the manifest under "INVENTORY".
                if (child.object_name.rfind("ctx_classify_", 0) == 0) {
                    export_actions_.emplace_back(
                        child.object_name.substr(4), action);  // drop "ctx_"
                } else if (child.object_name == "ctx_export_INVENTORY") {
                    export_actions_.emplace_back("INVENTORY", action);
                } else {
                    export_actions_.emplace_back(child.label, action);
                }
            }
        }
        auto* parent_action =
            new QAction(QString::fromStdString(entry.label), menu);
        parent_action->setMenu(sub);
        menu->addAction(parent_action);
        return parent_action;
    }
    case MenuEntry::Kind::Action:
    default: {
        auto* action = new QAction(QString::fromStdString(entry.label), menu);
        action->setObjectName(QString::fromStdString(entry.object_name));
        if (!entry.tooltip.empty()) {
            action->setToolTip(QString::fromStdString(entry.tooltip));
        }
        action->setEnabled(entry.enabled);
        if (entry.destructive) style_destructive(action);
        if (!entry.open_local_path.empty()) {
            const QString path =
                QString::fromStdString(entry.open_local_path);
            connect(action, &QAction::triggered, this, [path] {
                QDesktopServices::openUrl(QUrl::fromLocalFile(path));
            });
        }
        menu->addAction(action);
        if (!entry.object_name.empty()) {
            action_registry_[entry.object_name] = action;
        }
        return action;
    }
    }
}

void AssetContextMenu::style_destructive(QAction* action) {
    if (destructive_icon_fn_) destructive_icon_fn_(action);
}

QAction* AssetContextMenu::find_action(const std::string& object_name) const {
    if (const auto it = action_registry_.find(object_name);
        it != action_registry_.end()) {
        return it->second;
    }
    for (QAction* action : actions()) {
        if (action->objectName().toStdString() == object_name) return action;
    }
    return nullptr;
}

QAction* AssetContextMenu::find_export_action(const std::string& label) const {
    for (const auto& [lbl, action] : export_actions_) {
        if (lbl == label) return action;
    }
    return nullptr;
}

}  // namespace pwb::ui_pages_data::qt
