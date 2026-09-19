// ProviderService — the Application/Workflow-facing C++ contract over the
// provider registry (the facade the composition root consumes, mirroring
// libs/application's AlgorithmRunner role for kernels):
//
// - owns a registry seeded idempotently with the built-ins;
// - capability introspection as ordered JSON (descriptor envelopes);
// - one guarded run() entry point for hosts (validate → admit → execute →
//   provenance) over typed inputs.
//
// Workflow hosts bind the same service: node ops resolve provider ids
// through it and validate parameters with the SDK's validate_parameters.
#pragma once

#include <pwb/domain/json.hpp>
#include <pwb/providers/execution.hpp>
#include <pwb/providers/registry.hpp>

#include <memory>
#include <string>
#include <vector>

namespace pwb::providers {

using Json = pwb::domain::Json;

class ProviderService {
public:
    // Registry seeded with the built-ins exactly once.
    ProviderService();

    // Borrowed for wiring provider instances beyond the built-ins.
    ProviderRegistry& registry() { return registry_; }
    const ProviderRegistry& registry() const { return registry_; }

    // Capability query: ordered JSON array of descriptor envelopes
    // (optionally filtered by family value, e.g. "exporter").
    [[nodiscard]] Json capability_report(
        std::optional<std::string> family = std::nullopt) const;

    // Quarantine snapshot for host diagnostics (id → reason).
    [[nodiscard]] Json quarantine_report() const;

    // Guarded invocation through the executor; admission optional.
    ProviderResult run(const std::string& provider_id, const ProviderInputs& inputs = {},
                       const Json& parameters = Json::object(),
                       ProviderContext* context = nullptr,
                       IAdmissionPort* admission = nullptr) const {
        return execute_provider(registry_, provider_id, inputs, parameters, context,
                                admission);
    }

private:
    ProviderRegistry registry_;
};

}  // namespace pwb::providers
