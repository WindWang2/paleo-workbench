// pwb::providers — plugin module loader over the plugin_abi.hpp contract:
// dlopen/LoadLibrary, ABI + capability negotiation, registry integration and
// the refcounted unload policy (running executions pin the module; unload is
// deferred until the last lease releases; executions requested after an
// unload fail fast with PluginUnloadPendingError).
//
// Borrowing contract (registry.hpp's rule, extended to plugins): unload()
// unregisters provider objects; a concurrent get()-between-lookup-and-
// execute window remains the host's serialization duty exactly as for
// static providers. What the loader guarantees beyond that: an execution
// already inside the module completes (lease pin), and the module's code is
// never removed while any such execution is on the stack.
//
// Ownership model:
//   * PluginLoader owns the OS module handles and the per-module state.
//   * The ProviderRegistry owns the PluginProvider instances (normal
//     register/unregister semantics — line 11's static-SDK view is
//     unchanged; plugin providers are ordinary IProviders).
//   * A Lease pins module state, not the provider object, so unregistering
//     (destroying provider objects) is only ever done at zero leases.
//   * The loader must outlive every Lease it issued (enforced by contract,
//     asserted in tests); its destructor unregisters + closes what it can
//     and deliberately leaves pinned modules in process memory rather than
//     risking code removal under a running task.
#pragma once

#include <pwb/domain/json.hpp>
#include <pwb/providers/contracts.hpp>
#include <pwb/providers/plugin_abi.hpp>
#include <pwb/providers/registry.hpp>

#include <filesystem>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

namespace pwb::providers {

using Json = pwb::domain::Json;

// What the host advertises during capability negotiation. Defaults to the
// base plugin-host capability; hosts extend the list for builds that offer
// more (catalog port, deployment-specific kernels).
struct HostCapabilities {
    std::vector<std::string> provides{kPluginHostCapability};
    bool provides_capability(const std::string& name) const {
        for (const auto& value : provides) {
            if (value == name) return true;
        }
        return false;
    }
};

// Load-time summary of one module (returned by load(), kept in loaded()).
struct PluginInfo {
    std::string plugin_id;
    std::string plugin_version;
    std::filesystem::path path;
    int abi_version = kPluginAbiVersion;
    std::vector<std::string> provided_capabilities;
    std::vector<std::string> provider_ids;  // registered into the registry, order kept

    Json to_json() const;
};

class PluginLoader {
public:
    // RAII pin: holds one reference on the module while an execution (or a
    // test simulating one) is inside it. Move-only; release happens on the
    // last move-assignment/destruction and may finalize a pending unload.
    class Lease {
    public:
        Lease() = default;
        Lease(Lease&& other) noexcept;
        Lease& operator=(Lease&& other) noexcept;
        Lease(const Lease&) = delete;
        Lease& operator=(const Lease&) = delete;
        ~Lease();
        explicit operator bool() const { return state_ != nullptr; }

    private:
        friend class PluginLoader;
        explicit Lease(std::shared_ptr<void> state) : state_(std::move(state)) {}
        std::shared_ptr<void> state_;
    };

    // registry must outlive the loader (documented in the destructor).
    explicit PluginLoader(ProviderRegistry& registry,
                          HostCapabilities capabilities = {});

    ~PluginLoader();

    // dlopen + negotiate + register every provider the module declares.
    // Throws PluginLoadError / PluginAbiError / PluginCapabilityError /
    // PluginDescriptorError; a rejected load leaves no trace (module
    // closed, nothing registered). Loading the same path twice is refused
    // (PluginLoadError "重复加载") — ids collide would quarantine otherwise.
    PluginInfo load(const std::filesystem::path& module_path);

    // Request unload. Returns true when the module is gone now, false when
    // it is only marked pending (running executions still inside). Unknown
    // id → false is ambiguous with pending; use is_unload_pending /
    // find to disambiguate (tests do).
    bool unload(const std::string& plugin_id);

    // Resolve a loaded module's info; nullptr when unknown.
    const PluginInfo* find(const std::string& plugin_id) const;
    std::vector<PluginInfo> loaded() const;
    bool is_unload_pending(const std::string& plugin_id) const;

    // Pin a module for a hand-rolled execution (PluginProvider::execute
    // does exactly this). Unknown id → UnknownProviderError; pending unload
    // → PluginUnloadPendingError.
    Lease acquire(const std::string& plugin_id);

private:
    struct ModuleState;  // shared_ptr<void> payload of every Lease

    // Unregister + shutdown + dlclose one module (must be at zero leases
    // and not finalized; used by unload()'s uncontended path and by the
    // sweep).
    void finalize_module_now(ModuleState& state) const;
    // Finalize every pending-unload module that is at zero leases. Called
    // at the top of every public loader entry point so a deferred unload
    // completes on the NEXT loader interaction — never inside the stack of
    // the execution that released the last lease (the SDK executor still
    // borrows the provider object after execute() returns).
    void sweep_pending() const;

    ProviderRegistry& registry_;
    HostCapabilities capabilities_;
    mutable std::mutex mutex_;
    std::vector<std::pair<std::string, std::unique_ptr<ModuleState>>> modules_;  // insertion order

    friend struct ModuleState;
};

// IProvider adapter executing through the C ABI. Registered under the
// module's provider ids; execute()/verify() pin the module for their
// duration (a pending unload cannot interrupt a started execution, and an
// unload requested mid-execution is honored only after it).
class PluginProvider final : public IProvider {
public:
    PluginProvider(PluginLoader& loader, std::string plugin_id,
                   ProviderDescriptor descriptor)
        : loader_(loader), plugin_id_(std::move(plugin_id)),
          descriptor_(std::move(descriptor)) {}

    const ProviderDescriptor& descriptor() const override { return descriptor_; }

    ProviderResult execute(const ProviderInputs& inputs, const Json& parameters,
                           ProviderContext& context) override;

    std::optional<Verification> verify(const ProviderResult& result,
                                       ProviderContext& context) override;

    // Loader-only: bind the C entry points + the module-internal provider
    // index right before registration (entry points are immutable after
    // load, so the provider object needs no state lookup per call).
    void attach_entry(int index, PwbFnPluginExecute execute,
                      PwbFnPluginLastError last_error);

private:
    PluginLoader& loader_;
    std::string plugin_id_;
    ProviderDescriptor descriptor_;
    int provider_index_ = 0;
    PwbFnPluginExecute execute_ = nullptr;
    PwbFnPluginLastError last_error_ = nullptr;
};

}  // namespace pwb::providers
