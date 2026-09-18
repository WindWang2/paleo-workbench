// WorkflowSpec static + runtime validation, ported from
// paleo_workbench/workflow/dag/validation.py (CONV-06). The registry
// dependency collapses to an ActionCatalog lookup table (D2): the Python
// validator only consumes registry.get() success/failure and the action's
// risk value. All problem messages are frozen against the Python oracle —
// full-list order equality is part of the contract.
#pragma once

#include <map>
#include <set>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>

#include <pwb/workflow_spec/model.hpp>

namespace pwb::workflow_spec {

// validation._NODE_ID_RE / _SLOT_RE: ^[a-z][a-z0-9_]*$
[[nodiscard]] bool matches_node_id_pattern(const std::string& text);

// workflow_id pattern in validate_workflow_spec: ^[a-z][a-z0-9_.-]{1,63}$
[[nodiscard]] bool matches_workflow_id_pattern(const std::string& text);

// validation.CONTEXT_BINDING_WHITELIST (sorted form is embedded in error
// messages; std::set iteration is already sorted, matching sorted(...)).
[[nodiscard]] const std::set<std::string>& context_binding_whitelist();

// D2: the slice of Python's ActionRegistry validate_workflow_spec reads —
// risk values are the ActionRisk vocabulary ("read"/"compute"/"write"/
// "destructive").
using ActionCatalog = std::map<std::string, std::string>;

// validation.validate_workflow_spec — the fail-closed static gate.
[[nodiscard]] std::vector<std::string>
validate_workflow_spec(const WorkflowSpec& spec, const ActionCatalog& catalog);

// validation.BindingError
struct BindingError : std::runtime_error {
    using std::runtime_error::runtime_error;
};

// D7: minimal run surface for resolve_value/bind_parameters — slot values,
// per-node receipt outputs, and whitelisted context values (null == the
// Python "not available in this session" case).
struct BindEnv {
    domain::Json slot_values = domain::Json::object();
    std::map<std::string, domain::Json> results;
    std::map<std::string, domain::Json> context_values;
};

// validation.resolve_value over one parameter value.
[[nodiscard]] domain::Json resolve_value(const domain::Json& value,
                                         const BindEnv& env);

// validation.bind_parameters — concrete parameters for one node execution.
[[nodiscard]] domain::Json bind_parameters(const NodeSpec& node,
                                           const BindEnv& env);

// providers.execution.validate_parameters — the dependency-free JSON-schema
// subset (type incl. unions, enum, minimum/maximum, minItems/maxItems,
// items, properties, required, additionalProperties=false).
[[nodiscard]] std::vector<std::string>
validate_parameters(const domain::Json& schema, const domain::Json& parameters,
                    const std::string& label = "parameters");

// validation.slot_schema_problems over explicit values.
[[nodiscard]] std::vector<std::string>
slot_schema_problems(const WorkflowSpec& spec, const domain::Json& slot_values);

// validation.materialize_slot_defaults — declared defaults for absent slots.
[[nodiscard]] domain::Json
materialize_slot_defaults(const WorkflowSpec& spec,
                          const domain::Json& slot_values);

}  // namespace pwb::workflow_spec
