// Catalog-owned policy layers (conv-31): governance vocabularies
// (governance.py), the intermediate-artifact decision table
// (intermediate_policy.py), typed-port role vocabulary (port_roles.py) and
// the promote-to-production gates (model_gates.py).
//
// All four are pure data/policy modules in Python — no IO, no service
// state — and stay pure here. Case folding follows the bounded ASCII fold
// precedent of entity_view.hpp (search_fold): identical to Python
// casefold() for every value these vocabularies contain (ASCII + CJK).
#pragma once

#include "pwb/domain/errors.hpp"
#include "pwb/domain/json.hpp"
#include "pwb/domain/stage.hpp"

#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace pwb::catalog {

// ---- governance.py --------------------------------------------------------

struct GovernanceFieldSpec {
    std::string key;
    std::string label;
    std::vector<std::string> vocabulary;  // empty = free text
    std::vector<std::pair<std::string, std::string>> display;  // value -> zh
    std::vector<std::pair<std::string, std::string>> aliases;  // input -> canonical
};

// GOVERNANCE_FIELDS in declared (stable) order.
const std::vector<GovernanceFieldSpec>& governance_fields();

// normalize_governance_value parity: empty/None → ""; free text is
// whitespace-collapsed and capped at 200 chars; controlled fields map
// through aliases (casefolded) / vocabulary membership or raise
// GovernanceError with the byte-identical Chinese message.
domain::Result<std::string> normalize_governance_value(
    std::string_view key, const domain::Json& value);

// normalize_governance_patch parity: reserved bookkeeping keys are
// rejected, governance keys normalized, everything else passed through
// verbatim. Object key order follows the input patch (ordered_json).
domain::Result<domain::Json> normalize_governance_patch(const domain::Json& patch);

// governance_values: the governance subset of an asset metadata object
// (values rendered with Python str() shapes: bool → True/False).
domain::Json governance_values(const domain::Json& metadata);

// governance_display: zh label for one value (free text passes through).
std::string governance_display(std::string_view key, const std::string& value);

// governance_display_rows: ordered (label, display) pairs for inspectors.
std::vector<std::pair<std::string, std::string>> governance_display_rows(
    const domain::Json& metadata);

// ---- intermediate_policy.py ------------------------------------------------

struct ArtifactPolicy {
    std::string artifact_class;
    bool must_register = false;
    std::optional<domain::DataStage> data_stage;
    std::string retention_class;
    std::string rationale;
};

// policy_for parity: exact registered kind → its policy; anything else →
// the INTERMEDIATE fallback with the honest "未登记 kind" rationale.
ArtifactPolicy artifact_policy_for(std::string_view kind);
bool is_registered_artifact_kind(std::string_view kind);
// Every registered kind in table order (oracle freeze surface).
const std::vector<std::pair<std::string, const ArtifactPolicy*>>&
known_artifact_policies();

// ---- port_roles.py ---------------------------------------------------------

// display_for parity: registered zh label, verbatim fallback for unknown
// roles (and for the empty role — Python `str(role or "")`).
std::string port_role_display(std::string_view role);
const std::vector<std::pair<std::string, std::string>>& known_port_roles();

// ---- model_gates.py --------------------------------------------------------

// The provider / model-type denylists (mirrored literals of
// prediction.providers PROVIDER_DEMO / PROVIDER_LOCAL_ASSET).
inline constexpr std::string_view kNonPromotableProviders[] = {"demo",
                                                               "local_asset"};
inline constexpr std::string_view kNonPromotableModelTypes[] = {"demo",
                                                                "heuristic"};

// Facts model_gates reads off the catalog registry (dependency inversion:
// the gate never imports the model store).
struct ModelGateFacts {
    std::string provider;
    std::string model_type;
    domain::Json metadata = domain::Json::object();
};

struct ModelVersionGateFacts {
    bool demo_only = false;
    domain::Json metadata = domain::Json::object();
    domain::Json input_schema;  // null/object; empty = absent
};

// can_promote_to_production parity. *lookup_error* carries the message a
// failed get_model / get_model_version raised in Python (→ (false, msg)).
std::pair<bool, std::string> can_promote_to_production(
    const std::optional<ModelGateFacts>& model,
    const std::optional<ModelVersionGateFacts>& version,
    const std::optional<std::string>& lookup_error,
    bool require_input_schema = true);

}  // namespace pwb::catalog
