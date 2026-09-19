#pragma once

// Guarded harness executor — C++ port of paleo_workbench/harness/executor.py
// (P2-C). The execution loop every agent request goes through:
//
//   ActionRequest (action_id + parameters)
//     -> spec lookup (unknown = rejected)
//     -> parameter schema validation (providers SDK validator, oracle parity)
//     -> permission check (risk vs context permissions)
//     -> required-context resolution
//     -> resource admission (injected IAdmissionPort lease)
//     -> execute (handler over domain services, or capability provider)
//     -> verify (scientific hook + map hook + action verifier)
//     -> ActionResult (status, outputs, verification, warnings, metrics)
//
// The harness never pretends to be an LLM: planning happens outside; this
// pipeline only exposes, validates, executes and verifies. Handlers do real
// work through domain services; the executor owns the guard rails. execute()
// never throws — handler errors land in ActionResult statuses.

#include <pwb/closure_agent/context.hpp>
#include <pwb/closure_agent/registry.hpp>
#include <pwb/providers/context.hpp>
#include <pwb/providers/registry.hpp>

#include <optional>
#include <string>
#include <vector>

namespace pwb::closure_agent {

using Json = pwb::domain::Json;

class ActionPermissionError : public std::runtime_error {
public:
    ActionPermissionError(std::string action_id, ActionRisk risk);
    const std::string& action_id() const noexcept { return action_id_; }
    ActionRisk risk() const noexcept { return risk_; }

private:
    std::string action_id_;
    ActionRisk risk_;
};

class ActionValidationError : public std::runtime_error {
public:
    ActionValidationError(std::string action_id, std::vector<std::string> problems,
                          std::string label = "parameters");

    const std::vector<std::string>& problems() const noexcept { return problems_; }

private:
    std::vector<std::string> problems_;
};

// A required production capability is missing (backend, provider, engine).
// Handlers raise this instead of faking a result — the executor maps it to
// the canonical `unavailable` status.
class ActionUnavailableError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

struct ActionResult {
    std::string action_id;
    std::string status = to_string(ActionStatus::Success);
    Json outputs = Json::object();
    Json verification = Json::object();
    std::vector<std::string> warnings;
    Json metrics = Json::object();
    std::optional<std::string> error;
    double elapsed_ms = 0.0;

    bool ok() const;
    bool degraded() const;
    ActionStatus status_value() const;
    // Key order mirrors Python ActionResult.to_dict().
    Json to_dict() const;
};

// Verdict vocabulary (validation.py): pass / warning / fail; FAIL wins.
inline constexpr const char* kVerdictPass = "pass";
inline constexpr const char* kVerdictWarning = "warning";
inline constexpr const char* kVerdictFail = "fail";

// ScientificValidator.validate_grid subset for JSON-shaped action outputs:
// a numeric array (flat or nested rows) must not be silently degenerate.
// null entries count as nodata. Problem strings follow the frozen Python
// wording. Structure-only checks are the C++ faithful subset — no numpy
// dtype metadata exists in Json.
class ScientificValidator {
public:
    double max_nan_ratio = 0.9;  // above this the output is effectively empty
    int min_finite_values = 4;

    Json validate_grid(const Json& grid, const std::string& label = "grid") const;
};

// MapValidationHook subset over JSON map documents:
// layers[], extent[4], crs, composition {elements[]}.
class MapValidationHook {
public:
    Json validate(const Json& document, const Json& composition,
                  bool require_components = false) const;
};

struct ExecutorConfig {
    const providers::ProviderRegistry* providers = nullptr;  // provider actions
    providers::IAdmissionPort* admission = nullptr;  // null -> no admission (test mode)
    // Scientific/map hooks are overridable; default-constructed otherwise.
    // The scientific hook receives the output value and the label Python
    // passes (the action id) for reason-string parity.
    std::function<Json(const Json&, const std::string& label)> scientific_validator;
    std::function<Json(const Json&, const Json&, bool)> map_validator;
};

class HarnessExecutor {
public:
    explicit HarnessExecutor(const ActionRegistry& registry,
                             ExecutorConfig config = {});

    // The guarded pipeline. Never throws.
    ActionResult execute(const std::string& action_id,
                         const Json& parameters = Json::object(),
                         ActionContext* context = nullptr) const;

private:
    Json execute_provider_action(const ActionSpec& spec, const Json& parameters,
                                 ActionContext& context, ActionResult& result) const;
    Json verify(const ActionSpec& spec, const Json& payload, const Json& parameters,
                ActionContext& context) const;
    static Json merge_verification(const Json& verification, const std::string& key,
                                   const Json& report);

    const ActionRegistry* registry_;
    ExecutorConfig config_;
};

}  // namespace pwb::closure_agent
