// Typed provider inputs + provider interface + registry — C++ port of
// paleo_workbench/providers/registry.py.
//
// Registration model (ADR 0055 track P.REG): explicit registration is the
// only automatic path — the host/composition root registers built-ins via
// register_builtin_providers(). There is deliberately NO dynamic loading,
// directory scanning or entry-point discovery: the Python SDK's own rule is
// "No directory scanning, ever", the C++ product has no ABI-stable plugin
// boundary today, and inventing one (ABI versions, load isolation, unload
// policy) would be over-design. Third parties ship static providers and
// register them explicitly.
//
// Failure isolation: one bad provider (invalid descriptor, duplicate id) is
// quarantined with a reason; the registry keeps working. Quarantine is
// inspectable, never silent.
#pragma once

#include <pwb/domain/json.hpp>
#include <pwb/providers/contracts.hpp>
#include <pwb/providers/context.hpp>
#include <pwb/providers/refs.hpp>

#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace pwb::providers {

using Json = pwb::domain::Json;

// One typed input: a TYPED_REFS vocabulary name plus its JSON payload (the
// ref itself or an in-process domain object in JSON form). Insertion order
// is preserved (Python dict parity for provenance/run input ordering).
struct TypedInput {
    std::string type_name;
    Json payload = Json::object();
};

class ProviderInputs {
public:
    void set(const std::string& name, TypedInput input) {
        for (auto& [key, existing] : entries_) {
            if (key == name) {
                existing = std::move(input);
                return;
            }
        }
        entries_.emplace_back(name, std::move(input));
    }
    const TypedInput* find(const std::string& name) const {
        for (const auto& [key, value] : entries_) {
            if (key == name) return &value;
        }
        return nullptr;
    }
    bool contains(const std::string& name) const { return find(name) != nullptr; }
    std::size_t size() const { return entries_.size(); }
    bool empty() const { return entries_.empty(); }
    const std::vector<std::pair<std::string, TypedInput>>& entries() const { return entries_; }

private:
    std::vector<std::pair<std::string, TypedInput>> entries_;
};

// Optional post-execution verifier outcome (Harness 2.0, fail-closed).
struct Verification {
    std::string verdict = "pass";
    std::vector<std::string> reasons;
    Json extra = Json::object();  // non-verdict/reason keys → metrics["verification"]
};

class IProvider {
public:
    virtual ~IProvider() = default;

    virtual const ProviderDescriptor& descriptor() const = 0;
    virtual ProviderResult execute(const ProviderInputs& inputs, const Json& parameters,
                                   ProviderContext& context) = 0;
    // nullopt = no verify hook (executor skips the verification stage).
    virtual std::optional<Verification> verify(const ProviderResult& result,
                                               ProviderContext& context) {
        (void)result;
        (void)context;
        return std::nullopt;
    }
};

class ProviderRegistry {
public:
    // Validate + install one provider instance (ownership transfers).
    // Returns the installed descriptor; throws InvalidProviderError /
    // DuplicateProviderError; never partially installs. replace=true admits
    // an id re-registration (builtin refresh semantics).
    ProviderDescriptor register_provider(std::unique_ptr<IProvider> provider,
                                         bool replace = false);

    bool unregister(const std::string& provider_id);

    // get throws UnknownProviderError; find returns nullptr.
    IProvider& get(const std::string& provider_id) const;
    IProvider* find(const std::string& provider_id) const;

    // Insertion order (Python dict parity).
    std::vector<IProvider*> by_family(ProviderFamily family) const;
    // Sorted by (family value, provider_id) — Python parity.
    std::vector<ProviderDescriptor> descriptors(
        std::optional<ProviderFamily> family = std::nullopt) const;

    std::size_t size() const;

    // provider_id → reason; copy under the lock.
    std::map<std::string, std::string> quarantined() const;

private:
    mutable std::mutex mutex_;
    std::vector<std::pair<std::string, std::unique_ptr<IProvider>>> order_;
    std::map<std::string, std::string> quarantine_;
};

// Register the built-in production providers (idempotent, replace=true).
// Built-ins are the workbench's own deep seams exposed as providers; each
// registration is individually guarded so one unavailable engine never
// blocks the others. Returns the registered ids.
std::vector<std::string> register_builtin_providers(ProviderRegistry& registry);

// Process-wide registry singleton, lazily seeded with the built-ins (Python
// get_provider_registry parity). Tests construct local registries instead of
// resetting the global.
ProviderRegistry& get_provider_registry();

}  // namespace pwb::providers
