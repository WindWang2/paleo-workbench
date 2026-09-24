#include <pwb/ui/tool_actions.hpp>

#include <QStringList>

namespace pwb::ui {

ToolActionSet::~ToolActionSet() {
    for (auto& [id, action] : actions_) {
        if (parented_.find(action) == parented_.end()) delete action;
    }
}

void ToolActionSet::apply(
    const std::map<std::string, pwb::tool_policy::ToolAvailability>&
        availability,
    QObject* parent) {
    for (const auto& [tool_id, verdict] : availability) {
        QAction* action = nullptr;
        const auto it = actions_.find(tool_id);
        if (it == actions_.end()) {
            action = new QAction(QString::fromStdString(tool_id), parent);
            action->setObjectName(QString::fromStdString(tool_id));
            if (parent != nullptr) parented_.insert(action);
            actions_[tool_id] = action;
        } else {
            action = it->second;
            // D3: adopt previously-unparented stock into the host tree
            // (Qt then owns destruction order, not member order).
            if (parent != nullptr && action->parent() == nullptr) {
                action->setParent(parent);
                parented_.insert(action);
            }
        }
        // Pure projection: no gate logic lives here. setChecked is a no-op
        // on non-checkable actions, so a checked verdict promotes the
        // action to checkable first (parity tests read it back).
        if (verdict.checked) action->setCheckable(true);
        action->setEnabled(verdict.enabled);
        action->setChecked(verdict.checked);
        action->setVisible(verdict.visible);
        action->setToolTip(verdict.disabled_reason.empty()
            ? QString()
            : QString::fromStdString(verdict.disabled_reason));
        action->setStatusTip(QString::fromStdString(verdict.disabled_reason));
    }
}

QAction* ToolActionSet::action(const std::string& tool_id) const {
    const auto it = actions_.find(tool_id);
    return it == actions_.end() ? nullptr : it->second;
}

std::vector<std::string> ToolActionSet::action_ids() const {
    std::vector<std::string> ids;
    ids.reserve(actions_.size());
    for (const auto& [id, action] : actions_) ids.push_back(id);
    return ids;
}

bool ToolActionSet::action_enabled(const std::string& tool_id) const {
    const QAction* act = action(tool_id);
    return act != nullptr && act->isEnabled();
}

bool ToolActionSet::action_checked(const std::string& tool_id) const {
    const QAction* act = action(tool_id);
    return act != nullptr && act->isChecked();
}

bool ToolActionSet::action_visible(const std::string& tool_id) const {
    const QAction* act = action(tool_id);
    return act != nullptr && act->isVisible();
}

QString ToolActionSet::action_tooltip(const std::string& tool_id) const {
    const QAction* act = action(tool_id);
    return act != nullptr ? act->toolTip() : QString();
}

}  // namespace pwb::ui
