#pragma once

// Action contracts — C++ port of paleo_workbench/harness/spec.py (P2-C,
// Harness 2.0). An ActionSpec is the single source of truth for one stable
// geological action: runtime validation, the agent tool schema and the docs
// derive from it — never a second hand-written copy.
//
// Statuses are the canonical Harness 2.0 six (no aliases): `rejected` means
// a guard refused the request before/at admission; `failed` means the
// execution or its verification did not hold; `unavailable` means a required
// production capability is missing — never a fake result. Qt-free,
// Python-free; Json is pwb::domain::Json so key order matches the Python
// dicts exactly.

#include <pwb/domain/json.hpp>

#include <functional>
#include <optional>
#include <string>
#include <vector>

namespace pwb::closure_agent {

using Json = pwb::domain::Json;

enum class ActionRisk {
    Read,         // observe workspace/catalog/context — no mutation
    Compute,      // derive new data through providers/services
    Write,        // mutate documents/versions via domain services
    Destructive,  // purge/overwrite; never installable in the default registry
};

std::string to_string(ActionRisk risk);
// "read" -> Read; unknown -> nullopt (Python ActionRisk(value) ValueError).
std::optional<ActionRisk> action_risk_from_string(const std::string& value);

// Canonical terminal states of one action execution (Harness 2.0).
enum class ActionStatus {
    Success,
    Degraded,
    Failed,
    Cancelled,
    Rejected,
    Unavailable,
};

std::string to_string(ActionStatus status);
// Statuses an agent may treat as "the work happened" (data was produced).
bool is_positive_status(ActionStatus status);

// Typed-ref vocabulary validation consumes the providers SDK's vocabulary —
// the single authority (line 10); this header only exposes the check.
// Forward-declared free function, defined in spec.cpp against
// pwb::providers::typed_refs().
bool is_known_typed_ref(const std::string& ref);

// Handler signature: callable(context, parameters) -> payload (JSON value).
// The context is an opaque pointer here to keep spec.hpp dependency-light;
// executor.hpp pins it to ActionContext&.
using ActionHandler = std::function<Json(void* context, const Json& parameters)>;

// Action-specific verification hook: callable(payload, parameters, context)
// -> {"verdict": pass|warning|fail, "reasons": [...]}. Fail-closed: a
// crashing verifier is a FAILED report, never a blessing.
using ActionVerifier =
    std::function<Json(const Json& payload, const Json& parameters, void* context)>;

struct ActionSpec {
    std::string action_id;
    std::string description;
    ActionHandler handler;  // empty == None (registry requires handler or provider_id)
    Json input_schema = Json::object();
    Json output_schema = Json::object();
    ActionRisk risk = ActionRisk::Read;
    std::string category = "background.compute";  // TaskCategory value
    Json resource_profile = Json(nullptr);        // null -> Python default profile
    std::vector<std::string> required_context;    // ActionContext attrs that must be present
    bool supports_cancel = false;
    std::optional<std::string> provider_id;  // execution delegates to a capability provider
    std::string side_effect_notes;
    // --- Harness 2.0 ---
    std::string version = "1.0";  // action contract version; cache/receipt identity
    bool deterministic = false;   // same inputs+params+version -> same outputs
    bool cacheable = false;       // may reuse a prior catalog-complete execution
    bool idempotent = false;      // re-execution with same inputs is safe
    ActionVerifier verifier;      // custom verification hook (fail-closed)
    std::vector<std::string> domain_tags;
    std::vector<std::string> input_refs;   // typed-ref vocabulary names consumed
    std::vector<std::string> output_refs;  // typed-ref vocabulary names produced

    // action_id up to the first '.'.
    std::string domain() const;

    // Python resource_profile default when resource_profile is null:
    // {"estimated_cpu_cores":0.5,"estimated_ram_bytes":0,
    //  "estimated_vram_bytes":0,"io_weight":0.5}
    Json effective_resource_profile() const;

    // Python to_dict() — key order frozen against the Python oracle.
    Json to_dict() const;

    // Agent tool definition (OpenAI/Gemini function-calling shape), derived —
    // the schema is never re-authored anywhere else.
    Json tool_schema() const;
};

// Recursively check that `schema` is a well-formed JSON-schema subset.
// Registration-time gate; problem strings are byte-identical to the Python
// oracle (validate_schema_shape).
std::vector<std::string> validate_schema_shape(const Json& schema,
                                               const std::string& path = "schema");

// Python validate_action_spec(spec) — the registration-time problems list.
std::vector<std::string> validate_action_spec(const ActionSpec& spec);

}  // namespace pwb::closure_agent
