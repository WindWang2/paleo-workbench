// Guarded provider execution: validate → admit → execute → provenance.
// C++ port of paleo_workbench/providers/execution.py.
//
// The only sanctioned way to run a capability provider:
// 1. resolve: provider looked up by id (unknown → UnknownProviderError);
// 2. validate: parameters against the descriptor's JSON-schema subset;
//    inputs checked to be typed refs the provider declares;
// 3. admit: through the injected IAdmissionPort (no port → no admission,
//    the catalog-less/test mode); an enclosing lease on the context is
//    inherited instead of double-admitting (#1146);
// 4. execute: provider exceptions are wrapped for isolation — except
//    TaskCancelled, which lands the run "cancelled" and propagates
//    unwrapped (#1137);
// 5. provenance: when the context has a catalog port, a DataRun wraps the
//    execution (begin/complete), providers register artifacts themselves.
#pragma once

#include <pwb/domain/json.hpp>
#include <pwb/providers/contracts.hpp>
#include <pwb/providers/context.hpp>
#include <pwb/providers/refs.hpp>
#include <pwb/providers/registry.hpp>

#include <string>

namespace pwb::providers {

using Json = pwb::domain::Json;

// Run one provider through the guarded pipeline, resolving it from a
// registry by id.
ProviderResult execute_provider(const ProviderRegistry& registry,
                                const std::string& provider_id,
                                const ProviderInputs& inputs = {},
                                const Json& parameters = Json::object(),
                                ProviderContext* context = nullptr,
                                IAdmissionPort* admission = nullptr);

// Run an already-resolved provider instance.
ProviderResult execute_provider(IProvider& provider,
                                const ProviderInputs& inputs = {},
                                const Json& parameters = Json::object(),
                                ProviderContext* context = nullptr,
                                IAdmissionPort* admission = nullptr);

}  // namespace pwb::providers
