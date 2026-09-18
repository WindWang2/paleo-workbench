#include <pwb/providers/execution.hpp>

#include <pwb/providers/errors.hpp>
#include <pwb/providers/schema.hpp>

#include <algorithm>
#include <cctype>
#include <chrono>
#include <cmath>
#include <exception>
#include <memory>
#include <set>
#include <utility>

namespace pwb::providers {

namespace {

// Python repr of a string for message parity.
std::string quoted(const std::string& value) { return "'" + value + "'"; }

std::string join_problems(const std::vector<std::string>& problems) {
    std::string out;
    for (std::size_t i = 0; i < problems.size(); ++i) {
        if (i != 0) out += "; ";
        out += problems[i];
    }
    return out;
}

// _validate_inputs: every input's declared type name must be in the
// descriptor's input_types vocabulary (Python matches by class name).
void validate_inputs(const ProviderDescriptor& descriptor, const ProviderInputs& inputs) {
    if (descriptor.input_types.empty()) return;
    std::set<std::string> declared(descriptor.input_types.begin(),
                                   descriptor.input_types.end());
    for (const auto& [name, input] : inputs.entries()) {
        if (declared.find(input.type_name) == declared.end()) {
            std::string sorted_list = "[";
            std::size_t i = 0;
            for (const auto& d : declared) {
                if (i != 0) sorted_list += ", ";
                sorted_list += quoted(d);
                ++i;
            }
            sorted_list += "]";
            throw ProviderRejectedInputError(
                descriptor.provider_id,
                "input " + quoted(name) + " has type " + input.type_name +
                    ", declared input types: " + sorted_list);
        }
    }
}

AdmissionRequest admission_request_of(const ProviderDescriptor& descriptor,
                                      const std::string& provider_id) {
    AdmissionRequest request;
    request.category = descriptor.resource_profile.category;
    request.title = "provider:" + provider_id;
    request.estimated_cpu_cores = descriptor.resource_profile.estimated_cpu_cores;
    request.estimated_ram_bytes = descriptor.resource_profile.estimated_ram_bytes;
    request.estimated_vram_bytes = descriptor.resource_profile.estimated_vram_bytes;
    request.io_weight = descriptor.resource_profile.io_weight;
    return request;
}

// Input payloads carrying a catalog version identity feed the DataRun.
// Python filters on truthiness: an empty version_id string is skipped.
std::vector<std::string> input_version_ids(const ProviderInputs& inputs) {
    std::vector<std::string> ids;
    for (const auto& [name, input] : inputs.entries()) {
        if (input.payload.is_object() && input.payload.contains("version_id") &&
            input.payload.at("version_id").is_string()) {
            const std::string version_id =
                input.payload.at("version_id").get<std::string>();
            if (!version_id.empty()) ids.push_back(version_id);
        }
    }
    return ids;
}

// Python metrics.setdefault("elapsed_ms", round(elapsed_ms, 3)).
Json elapsed_ms_json(double elapsed_ms) {
    const double rounded = std::round(elapsed_ms * 1000.0) / 1000.0;
    return Json(rounded);
}

}  // namespace

ProviderResult execute_provider(IProvider& provider, const ProviderInputs& inputs,
                                const Json& parameters, ProviderContext* context,
                                IAdmissionPort* admission) {
    const ProviderDescriptor& descriptor = provider.descriptor();

    // 2. validate parameters against the declared schema subset.
    auto problems = validate_parameters(descriptor.parameters_schema, parameters);
    if (!problems.empty()) {
        throw InvalidParametersError(descriptor.provider_id, std::move(problems));
    }
    validate_inputs(descriptor, inputs);

    // 3. admission: an enclosing lease is inherited as-is (#1146); otherwise
    // admit through the injected port (pressure shedding propagates).
    const IAdmissionLease* enclosing = context ? context->admission_lease : nullptr;
    const bool owns_lease = enclosing == nullptr;
    std::unique_ptr<IAdmissionLease> lease;
    if (owns_lease && admission != nullptr) {
        lease = admission->admit(admission_request_of(descriptor, descriptor.provider_id));
    }
    if (!owns_lease) {
        // #1146: an enclosing reservation that understates this execution's
        // declared RAM is worth surfacing (Python logs a warning).
        const long long enclosing_ram = enclosing->request().estimated_ram_bytes;
        if (enclosing_ram != 0 &&
            enclosing_ram < descriptor.resource_profile.estimated_ram_bytes) {
            log_event("warning",
                      "provider " + descriptor.provider_id + " declares " +
                          std::to_string(descriptor.resource_profile.estimated_ram_bytes) +
                          " RAM bytes but the enclosing admission reserved only " +
                          std::to_string(enclosing_ram));
        }
    }

    // RAII stand-in for Python's `finally: lease.release()`.
    struct LeaseGuard {
        std::unique_ptr<IAdmissionLease> lease;
        ~LeaseGuard() {
            if (lease) lease->release();
        }
    } lease_guard{std::move(lease)};

    ProviderContext default_context;
    ProviderContext& ctx = context != nullptr ? *context : default_context;

    ICatalogPort* catalog = ctx.catalog;
    const std::string operation =
        "provider." + to_string(descriptor.family) + "." + descriptor.provider_id;
    const auto t0 = std::chrono::steady_clock::now();

    std::optional<ICatalogPort::RunRef> run_ref;
    if (catalog != nullptr) {
        ICatalogPort::RunSpec spec;
        spec.operation = operation;
        spec.input_version_ids = input_version_ids(inputs);
        spec.parameters = parameters;
        spec.generator_version = descriptor.version;
        try {
            run_ref = catalog->begin_run(spec);
        } catch (const std::exception& exc) {
            log_event("error", std::string("provider run begin failed (continuing "
                                          "without run record): ") +
                                   exc.what());
            run_ref = std::nullopt;  // continue without a run record
        } catch (...) {
            log_event("error", "provider run begin failed (continuing without run record)");
            run_ref = std::nullopt;
        }
        if (run_ref.has_value()) ctx.run_id = run_ref->run_id;
    }

    const auto complete_run = [&](const std::string& status) {
        if (run_ref.has_value() && catalog != nullptr) {
            try {
                catalog->complete_run(run_ref->run_id, status);
            } catch (const std::exception& exc) {
                log_event("error", "provider run " + status + "-status update failed: " +
                                       exc.what());
            } catch (...) {
                log_event("error",
                          "provider run " + status + "-status update failed: unknown error");
            }
        }
    };

    try {
        ProviderResult result = provider.execute(inputs, parameters, ctx);

        // Harness 2.0: optional provider-side verifier, fail-closed.
        std::optional<Verification> verification;
        try {
            verification = provider.verify(result, ctx);
        } catch (TaskCancelled&) {
            throw;
        } catch (const std::exception& exc) {
            throw ProviderVerificationError(descriptor.provider_id,
                                            "verifier crashed: " +
                                                python_exception_class(exc) + ": " +
                                                exc.what());
        } catch (...) {
            throw ProviderVerificationError(descriptor.provider_id,
                                            "verifier crashed: Exception: unknown "
                                            "non-standard exception");
        }
        if (verification.has_value()) {
            std::string verdict = verification->verdict;
            std::transform(verdict.begin(), verdict.end(), verdict.begin(),
                           [](unsigned char c) {
                               return static_cast<char>(std::tolower(c));
                           });
            if (verdict == "fail" || verdict == "failed" || verdict == "false") {
                throw ProviderVerificationError(
                    descriptor.provider_id,
                    verification->reasons.empty()
                        ? "verification failed"
                        : join_problems(verification->reasons));
            }
            for (const auto& reason : verification->reasons) {
                if (!reason.empty()) result.warnings.push_back(reason);
            }
            // Python setdefault: the key lands even when the verification
            // dict carried nothing beyond the verdict (empty object).
            if (!result.metrics.contains("verification")) {
                result.metrics["verification"] = verification->extra;
            }
        }

        // Success envelope defaults.
        const auto t1 = std::chrono::steady_clock::now();
        const double elapsed_ms =
            std::chrono::duration<double, std::milli>(t1 - t0).count();
        if (!result.metrics.contains("elapsed_ms")) {
            result.metrics["elapsed_ms"] = elapsed_ms_json(elapsed_ms);
        }
        if (!result.provenance.contains("provider_id")) {
            result.provenance["provider_id"] = descriptor.provider_id;
        }
        if (!result.provenance.contains("provider_version")) {
            result.provenance["provider_version"] = descriptor.version;
        }
        if (!result.provenance.contains("operation")) {
            result.provenance["operation"] = operation;
        }
        if (!parameters.empty() && !result.provenance.contains("parameters")) {
            result.provenance["parameters"] = parameters;
        }
        if (run_ref.has_value() && catalog != nullptr) {
            // Python parity: provenance["run_id"] only lands when the
            // completion write succeeded.
            try {
                catalog->complete_run(run_ref->run_id, "complete");
                result.provenance["run_id"] = run_ref->run_id;
            } catch (...) {
            }
        }
        return result;
    } catch (TaskCancelled&) {
        // #1137: cancellation is a first-class outcome, not a failure.
        complete_run("cancelled");
        throw;
    } catch (ProviderError&) {
        // Contract errors pass through unwrapped — they carry their semantics.
        complete_run("failed");
        throw;
    } catch (const std::exception& exc) {
        complete_run("failed");
        throw ProviderExecutionError(descriptor.provider_id, python_exception_class(exc),
                                     exc.what());
    } catch (...) {
        complete_run("failed");
        throw ProviderExecutionError(descriptor.provider_id, "Exception",
                                     "unknown non-standard exception");
    }
}

ProviderResult execute_provider(const ProviderRegistry& registry,
                                const std::string& provider_id,
                                const ProviderInputs& inputs, const Json& parameters,
                                ProviderContext* context, IAdmissionPort* admission) {
    IProvider& provider = registry.get(provider_id);
    return execute_provider(provider, inputs, parameters, context, admission);
}

}  // namespace pwb::providers
