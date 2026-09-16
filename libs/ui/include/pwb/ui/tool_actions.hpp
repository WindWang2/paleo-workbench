#pragma once

// ToolActionSet — presentation adapter over Pwb::ToolPolicy. Builds QActions
// from evaluate_all and maps results onto enabled/checked/tooltip; it never
// grows a second gate rule (V8 contract). Parity between QAction state and
// the policy output is asserted by tests.

#include <map>
#include <string>

#include <QAction>
#include <QString>

#include <pwb/tool_policy/tool_availability.hpp>
#include <pwb/tool_policy/tool_context.hpp>

namespace pwb::ui {

class ToolActionSet {
public:
    // Rebuilds/updates one QAction per availability entry. Actions are
    // owned by this object (parented QObject tree); toolbar binding keeps
    // whatever subset the surface wants.
    void apply(const std::map<std::string, pwb::tool_policy::ToolAvailability>&
                   availability);

    QAction* action(const std::string& tool_id) const;
    std::vector<std::string> action_ids() const;

    // Readback for parity tests: enabled/checked straight off the QAction.
    bool action_enabled(const std::string& tool_id) const;
    bool action_checked(const std::string& tool_id) const;
    bool action_visible(const std::string& tool_id) const;
    QString action_tooltip(const std::string& tool_id) const;

private:
    std::map<std::string, QAction*> actions_;
};

}  // namespace pwb::ui
