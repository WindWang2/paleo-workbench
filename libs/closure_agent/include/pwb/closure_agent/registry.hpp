#pragma once

// Action registry — C++ port of paleo_workbench/harness/registry.py (P2-C).
// The single authority for harness actions: explicit, code-owned
// registration; specs are validated on the way in, duplicate ids are
// refused, DESTRUCTIVE actions are not installable, and agent tool schemas
// derive from the same ActionSpec objects used for runtime validation.

#include <pwb/closure_agent/spec.hpp>

#include <map>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

namespace pwb::closure_agent {

class UnknownActionError : public std::runtime_error {
public:
    explicit UnknownActionError(std::string action_id);
    const std::string& action_id() const noexcept { return action_id_; }

private:
    std::string action_id_;
};

class DuplicateActionError : public std::runtime_error {
public:
    explicit DuplicateActionError(std::string action_id);
    const std::string& action_id() const noexcept { return action_id_; }

private:
    std::string action_id_;
};

class InvalidActionSpecError : public std::runtime_error {
public:
    InvalidActionSpecError(std::string action_id, std::vector<std::string> problems);

    const std::string& action_id() const noexcept { return action_id_; }
    const std::vector<std::string>& problems() const noexcept { return problems_; }

private:
    std::string action_id_;
    std::vector<std::string> problems_;
};

class ActionRegistry {
public:
    // validate_action_spec + DESTRUCTIVE refusal + duplicate guard (unless
    // replace). Throws InvalidActionSpecError / DuplicateActionError.
    const ActionSpec& register_spec(const ActionSpec& spec, bool replace = false);

    bool unregister(const std::string& action_id);

    // Raises UnknownActionError ("unknown harness action 'x'").
    const ActionSpec& get(const std::string& action_id) const;
    const ActionSpec* find(const std::string& action_id) const;

    // Sorted by action_id (Python specs()).
    std::vector<const ActionSpec*> specs(
        const std::optional<std::string>& domain = std::nullopt) const;
    std::vector<std::string> domains() const;
    std::size_t size() const;

    // Agent-facing tool definitions derived from the specs.
    std::vector<Json> tool_schemas(
        const std::optional<std::string>& domain = std::nullopt) const;
    std::vector<Json> inventory() const;

private:
    mutable std::mutex mutex_;
    std::map<std::string, ActionSpec> actions_;
};

}  // namespace pwb::closure_agent
