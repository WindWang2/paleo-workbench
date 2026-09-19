#pragma once

// UI-14 — MapActionController Qt shell (map_action_controller.py parity).
//
// One source of QAction checked/enabled state across menus and toolbars.
// The QObject owns the action map + exclusive tool QActionGroup; the
// static identity, availability→text contract and toolbar grouping live
// in the Qt-free pwb::ui_controllers::map_actions core — this class only
// materializes/applies them onto real QActions.
//
// Signal parity: tool_requested(str) for checkable canvas MapTools
// (exclusive group members; emitted only when the trigger lands checked),
// command_requested(str) for one-shot command-surface actions.

#include <QAction>
#include <QActionGroup>
#include <QObject>
#include <QString>
#include <QToolBar>

#include <filesystem>
#include <map>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include <pwb/tool_policy/tool_availability.hpp>

#include <pwb/ui_controllers/map_actions.hpp>

class QWidget;
class QIcon;

namespace pwb::ui_controllers::qt {

// The deployed assets/icons directory (map/ subdir searched first).
// Host-configured once at startup; unset → every lookup misses like a
// missing asset.
void set_map_icon_root(const std::filesystem::path& root);

// _map_icon(action_id, fallback) parity — resolves assets/icons/{name}.svg
// from the icon search paths (see .cpp); empty/missing → fallback icon.
QIcon map_action_icon(const std::string& icon_name,
                      const std::string& fallback = "");

class MapActionController : public QObject {
    Q_OBJECT
public:
    explicit MapActionController(QObject* parent = nullptr);

    // actions dict parity — nullptr for ids outside the vocabularies.
    QAction* action(const std::string& action_id) const;
    const std::map<std::string, QAction*>& actions() const {
        return actions_;
    }

    // apply_availability(availability, help_texts=None) parity: only Qt
    // presentation — the evaluator verdict is authoritative.
    // `help_texts`: tool_id → (tooltip, statusTip) overrides the host
    // derives from the same contract (action_help parity).
    void apply_availability(
        const std::map<std::string, tool_policy::ToolAvailability>&
            availability,
        const std::map<std::string, std::pair<std::string, std::string>>*
            help_texts = nullptr);

    // toolbar(title, action_ids, parent) parity — icon-only QToolBar with
    // a separator BETWEEN grouped (multi-id) entries, never for lone ids.
    QToolBar* toolbar(
        const QString& title,
        const std::vector<std::vector<std::string>>& action_id_entries,
        QWidget* parent = nullptr);

signals:
    void tool_requested(const QString& tool_id);
    void command_requested(const QString& action_id);

private:
    QAction* make_action_(const std::string& action_id, bool checkable,
                          const std::string& shortcut);

    std::map<std::string, QAction*> actions_;
    QActionGroup* tool_group_ = nullptr;
};

}  // namespace pwb::ui_controllers::qt
