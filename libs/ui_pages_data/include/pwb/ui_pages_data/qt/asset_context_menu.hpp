// UI-06 — asset_context_menu.py :: AssetContextMenu Qt shell.
//
// A QMenu populated 1:1 from the Qt-free MenuEntry model. Actions are
// looked up by objectName (find_action / find_export_action parity) and
// wired by the host page; ctx_open_system wires QDesktopServices itself,
// like Python's build.
#pragma once

#include <QMenu>

#include <functional>
#include <string>
#include <utility>
#include <vector>

#include <pwb/ui_pages_data/context_menu.hpp>

class QAction;

namespace pwb::ui_pages_data::qt {

// workstation_icon("map/delete_selected.svg", ERROR_RED) seam for the
// destructive-action icon; default = no icon.
using DestructiveIconFn = std::function<void(QAction*)>;

class AssetContextMenu : public QMenu {
    Q_OBJECT
public:
    explicit AssetContextMenu(QWidget* parent = nullptr);

    static void set_destructive_icon_fn(DestructiveIconFn fn);

    // Single-selection build (Python build(target, **caps)).
    void build(const AssetView& view, AssetKind kind,
               const MenuCapabilities& caps);
    // Multi-selection build.
    void build_multi(int count);
    // Generic entry-list render (for callers that already hold a model).
    void build_from_entries(const std::vector<MenuEntry>& entries);

    QAction* find_action(const std::string& object_name) const;
    // _export_actions parity: classify children keyed "classify_<rtype>",
    // export children keyed by format label, "INVENTORY" for the manifest.
    QAction* find_export_action(const std::string& label) const;

private:
    QAction* add_entry(const MenuEntry& entry, QMenu* menu);
    void style_destructive(QAction* action);

    std::map<std::string, QAction*> action_registry_;
    std::vector<std::pair<std::string, QAction*>> export_actions_;
    static DestructiveIconFn destructive_icon_fn_;
};

}  // namespace pwb::ui_pages_data::qt
