// registry.cpp — ActionRegistry behaviour with message parity against the
// frozen Python harness (harness/registry.py).
#include <pwb/closure_agent/registry.hpp>

#include <algorithm>

#include <pwb/providers/errors.hpp>
#include <pwb/providers/schema.hpp>

namespace pwb::closure_agent {

UnknownActionError::UnknownActionError(std::string action_id)
    : std::runtime_error("unknown harness action " +
                         pwb::providers::python_repr(action_id)),
      action_id_(std::move(action_id)) {}

DuplicateActionError::DuplicateActionError(std::string action_id)
    : std::runtime_error("harness action " +
                         pwb::providers::python_repr(action_id) +
                         " already registered"),
      action_id_(std::move(action_id)) {}

InvalidActionSpecError::InvalidActionSpecError(std::string action_id,
                                               std::vector<std::string> problems)
    : std::runtime_error("invalid action spec " +
                         pwb::providers::python_repr(action_id) + ": " +
                         [&] {
                             std::string joined;
                             for (std::size_t i = 0; i < problems.size(); ++i) {
                                 if (i) joined += "; ";
                                 joined += problems[i];
                             }
                             return joined;
                         }()),
      action_id_(std::move(action_id)),
      problems_(std::move(problems)) {}

const ActionSpec& ActionRegistry::register_spec(const ActionSpec& spec,
                                                bool replace) {
    auto problems = validate_action_spec(spec);
    if (spec.risk == ActionRisk::Destructive) {
        // Destructive actions exist in the vocabulary but are refused by the
        // default registry: product policy keeps purge/overwrite out of the
        // agent surface entirely.
        problems.push_back(
            "DESTRUCTIVE actions are not installable in the default registry");
    }
    if (!problems.empty()) {
        throw InvalidActionSpecError(spec.action_id, std::move(problems));
    }
    std::lock_guard<std::mutex> lock(mutex_);
    const auto it = actions_.find(spec.action_id);
    if (it != actions_.end() && !replace) {
        throw DuplicateActionError(spec.action_id);
    }
    ActionSpec copy = spec;
    return actions_.insert_or_assign(spec.action_id, std::move(copy)).first->second;
}

bool ActionRegistry::unregister(const std::string& action_id) {
    std::lock_guard<std::mutex> lock(mutex_);
    return actions_.erase(action_id) > 0;
}

const ActionSpec& ActionRegistry::get(const std::string& action_id) const {
    const ActionSpec* spec = find(action_id);
    if (spec == nullptr) throw UnknownActionError(action_id);
    return *spec;
}

const ActionSpec* ActionRegistry::find(const std::string& action_id) const {
    std::lock_guard<std::mutex> lock(mutex_);
    const auto it = actions_.find(action_id);
    return it == actions_.end() ? nullptr : &it->second;
}

std::vector<const ActionSpec*> ActionRegistry::specs(
    const std::optional<std::string>& domain) const {
    std::lock_guard<std::mutex> lock(mutex_);
    std::vector<const ActionSpec*> selected;
    // std::map is already ordered by key == sorted by action_id.
    for (const auto& [id, spec] : actions_) {
        if (domain && spec.domain() != *domain) continue;
        selected.push_back(&spec);
    }
    return selected;
}

std::vector<std::string> ActionRegistry::domains() const {
    std::vector<std::string> names;
    for (const auto* spec : specs()) names.push_back(spec->domain());
    std::sort(names.begin(), names.end());
    names.erase(std::unique(names.begin(), names.end()), names.end());
    return names;
}

std::size_t ActionRegistry::size() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return actions_.size();
}

std::vector<Json> ActionRegistry::tool_schemas(
    const std::optional<std::string>& domain) const {
    std::vector<Json> schemas;
    for (const auto* spec : specs(domain)) schemas.push_back(spec->tool_schema());
    return schemas;
}

std::vector<Json> ActionRegistry::inventory() const {
    std::vector<Json> entries;
    for (const auto* spec : specs()) entries.push_back(spec->to_dict());
    return entries;
}

}  // namespace pwb::closure_agent
