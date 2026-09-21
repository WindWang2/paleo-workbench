// Artifact lifecycle enforcement (V14-DATA-LINEAGE) — wires the FROZEN
// catalog decision table (catalog/policies.hpp artifact_policy_for —
// intermediate_policy.py parity) into the production registration path.
//
// The table classifies artifact kinds into
//   EPHEMERAL     task-scoped, must NOT enter the managed store
//   CACHE          deletable, recomputable, registered only when reused
//   INTERMEDIATE   scientific process meaning, registered, downstream input
//   DERIVED        scientific derived result
//   OUTPUT         user/workflow-accepted deliverable
// with stage + retention defaults. Enforcement rules applied here:
//   * must_register == false kinds are REFUSED by the managed publish
//     funnel before any write (fail-closed; no tempfile catalogization);
//   * a known kind's policy stage wins over the request default (the
//     classification is the point of providing the kind);
//   * version metadata records metadata["lifecycle"] =
//     {class, artifact_kind, retention_class} — idempotent, an existing
//     "lifecycle" object is never overwritten.
#pragma once

#include "pwb/domain/json.hpp"
#include "pwb/domain/stage.hpp"

#include <optional>
#include <string>
#include <string_view>

namespace pwb::data {

struct LifecycleDecision {
    bool applies = false;  // artifact_kind was provided
    bool known_kind = true;
    std::string artifact_kind;  // the requested kind (verbatim)
    std::string artifact_class;  // ephemeral|cache|intermediate|derived|output
    bool must_register = true;
    std::optional<domain::DataStage> stage;
    std::string retention_class;
    std::string rationale;
};

// Empty kind → non-applying decision (caller keeps its own defaults).
// Unknown kind → the frozen table's INTERMEDIATE fallback (known_kind =
// false; registered with the honest "未登记 kind" rationale).
LifecycleDecision lifecycle_for_artifact(std::string_view artifact_kind);

// Fail-closed gate for the managed publish funnel: returns the error
// message when this kind must NOT be registered, nullopt when allowed.
std::optional<std::string> lifecycle_registration_error(
    std::string_view artifact_kind);

// Stage resolution: policy stage for known kinds, caller stage otherwise.
domain::DataStage resolve_publish_stage(std::string_view artifact_kind,
                                        domain::DataStage caller_stage);

// Idempotent metadata stamping — an existing "lifecycle" object wins.
void stamp_lifecycle_metadata(domain::Json& version_metadata,
                              const LifecycleDecision& decision);

}  // namespace pwb::data
