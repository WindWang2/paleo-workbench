// Artifact lifecycle enforcement — see lifecycle_enforcement.hpp.
#include "pwb/data/lifecycle_enforcement.hpp"

#include "pwb/catalog/policies.hpp"

namespace pwb::data {

LifecycleDecision lifecycle_for_artifact(std::string_view artifact_kind) {
    LifecycleDecision decision;
    if (artifact_kind.empty()) return decision;
    decision.applies = true;
    const catalog::ArtifactPolicy policy =
        catalog::artifact_policy_for(artifact_kind);
    decision.known_kind =
        catalog::is_registered_artifact_kind(artifact_kind);
    decision.artifact_kind = std::string(artifact_kind);
    decision.artifact_class = policy.artifact_class;
    decision.must_register = policy.must_register;
    decision.stage = policy.data_stage;
    decision.retention_class = policy.retention_class;
    decision.rationale = policy.rationale;
    return decision;
}

std::optional<std::string> lifecycle_registration_error(
    std::string_view artifact_kind) {
    if (artifact_kind.empty()) return std::nullopt;
    const LifecycleDecision decision = lifecycle_for_artifact(artifact_kind);
    if (decision.applies && !decision.must_register) {
        return "artifact kind '" + std::string(artifact_kind) +
               "' is class " + decision.artifact_class +
               " and must not be registered into the managed store (" +
               decision.rationale + ")";
    }
    return std::nullopt;
}

domain::DataStage resolve_publish_stage(std::string_view artifact_kind,
                                        domain::DataStage caller_stage) {
    const LifecycleDecision decision = lifecycle_for_artifact(artifact_kind);
    if (decision.applies && decision.known_kind && decision.stage.has_value()) {
        return *decision.stage;
    }
    return caller_stage;
}

void stamp_lifecycle_metadata(domain::Json& version_metadata,
                              const LifecycleDecision& decision) {
    if (!decision.applies) return;
    if (!version_metadata.is_object()) return;
    if (version_metadata.contains("lifecycle") &&
        version_metadata["lifecycle"].is_object()) {
        return;  // idempotent: an explicit lifecycle record wins
    }
    domain::Json lifecycle = domain::Json::object();
    lifecycle["class"] = decision.artifact_class;
    lifecycle["artifact_kind"] = decision.artifact_kind;
    lifecycle["retention_class"] = decision.retention_class;
    lifecycle["known_kind"] = decision.known_kind;
    if (!decision.rationale.empty()) {
        lifecycle["rationale"] = decision.rationale;
    }
    version_metadata["lifecycle"] = std::move(lifecycle);
    // Readers of the effective retention (cleanup_eligibility, the Python
    // service_v11 policy path) look at the TOP-LEVEL key, so mirror it
    // there too — the nested record alone would be inert.
    if (!decision.retention_class.empty() &&
        !version_metadata.contains("retention_class")) {
        version_metadata["retention_class"] = decision.retention_class;
    }
}

}  // namespace pwb::data
