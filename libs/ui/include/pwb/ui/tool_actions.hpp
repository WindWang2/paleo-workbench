#pragma once

// ToolActionSet — presentation adapter over Pwb::ToolPolicy. Builds QActions
// from evaluate_all and maps results onto enabled/checked/tooltip; it never
// grows a second gate rule (V8 contract). Parity between QAction state and
// the policy output is asserted by tests.

#include <map>
#include <set>
#include <string>
#include <vector>

#include <QAction>
#include <QString>

#include <pwb/tool_policy/tool_availability.hpp>
#include <pwb/tool_policy/tool_context.hpp>

namespace pwb::ui {

class ToolActionSet {
public:
    ~ToolActionSet();   // deletes only the actions it still owns

    // Rebuilds/updates one QAction per availability entry. Without a
    // parent the set owns (deletes) the actions itself — the legacy
    // contract; with a host QObject the actions are parented into the
    // host's QObject tree (Qt owns them, destruction order follows the
    // tree instead of member order — the D3 hardening for shells whose
    // member order must not be load-bearing).
    void apply(const std::map<std::string, pwb::tool_policy::ToolAvailability>&
                   availability,
               QObject* parent = nullptr);

    QAction* action(const std::string& tool_id) const;
    std::vector<std::string> action_ids() const;

    // Readback for parity tests: enabled/checked straight off the QAction.
    bool action_enabled(const std::string& tool_id) const;
    bool action_checked(const std::string& tool_id) const;
    bool action_visible(const std::string& tool_id) const;
    QString action_tooltip(const std::string& tool_id) const;

private:
    std::map<std::string, QAction*> actions_;
    // Actions handed to a host QObject tree (not deleted here).
    std::set<QAction*> parented_;
};

}  // namespace pwb::ui
