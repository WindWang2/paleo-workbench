// pwb::providers — plugin-side authoring helpers for the plugin_abi.hpp
// contract. A module includes this header, fills one PluginModuleDef with
// static storage, instantiates PWB_PLUGIN_MODULE(def) at file scope, and the
// six C entry points are generated. Everything still crosses the boundary as
// C + JSON; this header only removes the boilerplate (and keeps the ABI
// struct layout in exactly one place).
//
// Execution contract for implementors:
//   * run(inputs_json, parameters_json, context_json, bridge) returns the
//     ProviderResult JSON text (caller copies before your next call), or
//     nullptr after last_error was set (see error_kinds below).
//   * cancelled: poll bridge->cancel_probe(bridge->user) at checkpoints and
//     finish with kind "cancelled" — the host rethrows TaskCancelled.
//   * bridge may be null (catalog-less/host-optional runs).
#pragma once

#include <pwb/domain/json.hpp>
#include <pwb/providers/plugin_abi.hpp>

#include <string>
#include <vector>

namespace pwb::providers {

using Json = pwb::domain::Json;  // descriptor/result payload encoding

namespace plugin {

// Error envelope kinds (host-side mapping in plugin_loader.cpp).
inline constexpr const char* kCancelled = "cancelled";
inline constexpr const char* kRejected = "rejected";
inline constexpr const char* kInvalidParameters = "invalid_parameters";
inline constexpr const char* kExecution = "execution";
inline constexpr const char* kInternal = "internal";

// One provider the module exposes, expressed as data + a run function.
struct ProviderDef {
    // ProviderDescriptor JSON (ProviderDescriptor.to_json() shape).
    std::string descriptor_json;
    // Returns the ProviderResult JSON, or nullptr on failure (then
    // (*last_error) must hold the envelope). Called from the host thread(s);
    // must be ready for serialized calls only.
    const char* (*run)(const char* inputs_json, const char* parameters_json,
                       const char* context_json, const PwbPluginHostBridge* bridge);
};

struct PluginModuleDef {
    const char* plugin_id;
    const char* plugin_version;
    std::vector<const char*> requires_host_capabilities;
    std::vector<const char*> provides_host_capabilities;
    std::vector<ProviderDef> providers;
    // Optional: called once before the module is unloaded.
    void (*shutdown)() = nullptr;
};

}  // namespace plugin

// Generates the C entry points for `def` (a pwb::providers::plugin::
// PluginModuleDef l-value with static storage duration).
#define PWB_PLUGIN_MODULE(def)                                                \
    extern "C" {                                                              \
    static const pwb::providers::plugin::PluginModuleDef*                     \
        pwb_plugin_module_def_instance = &(def);                              \
                                                                              \
    const pwb::providers::PwbPluginDescription* pwb_plugin_describe(void) {   \
        static pwb::providers::PwbPluginDescription description;              \
        static std::vector<const char*> requires_list =                       \
            pwb_plugin_module_def_instance->requires_host_capabilities;       \
        static std::vector<const char*> provides_list =                       \
            pwb_plugin_module_def_instance->provides_host_capabilities;       \
        description.abi_version = pwb::providers::kPluginAbiVersion;          \
        description.plugin_id = pwb_plugin_module_def_instance->plugin_id;    \
        description.plugin_version =                                          \
            pwb_plugin_module_def_instance->plugin_version;                   \
        description.requires_host_capabilities = requires_list.data();        \
        description.requires_host_capability_count =                          \
            static_cast<int>(requires_list.size());                           \
        description.provides_host_capabilities = provides_list.data();        \
        description.provides_host_capability_count =                          \
            static_cast<int>(provides_list.size());                           \
        return &description;                                                  \
    }                                                                         \
    int pwb_plugin_provider_count(void) {                                     \
        return static_cast<int>(                                              \
            pwb_plugin_module_def_instance->providers.size());                \
    }                                                                         \
    const char* pwb_plugin_provider_descriptor(int index) {                   \
        if (index < 0 ||                                                      \
            index >= static_cast<int>(                                        \
                         pwb_plugin_module_def_instance->providers.size()))   \
            return nullptr;                                                   \
        return pwb_plugin_module_def_instance->providers[index]               \
            .descriptor_json.c_str();                                         \
    }                                                                         \
    const char* pwb_plugin_execute(                                           \
        int index, const char* inputs_json, const char* parameters_json,      \
        const char* context_json,                                             \
        const pwb::providers::PwbPluginHostBridge* bridge) {                  \
        if (index < 0 ||                                                      \
            index >= static_cast<int>(                                        \
                         pwb_plugin_module_def_instance->providers.size()))   \
            return nullptr;                                                   \
        return pwb_plugin_module_def_instance->providers[index].run(          \
            inputs_json, parameters_json, context_json, bridge);              \
    }                                                                         \
    const char* pwb_plugin_last_error(void) {                                 \
        return pwb::providers::plugin::module_error_buffer().c_str();         \
    }                                                                         \
    void pwb_plugin_shutdown(void) {                                          \
        if (pwb_plugin_module_def_instance->shutdown != nullptr)              \
            pwb_plugin_module_def_instance->shutdown();                       \
    }                                                                         \
    }                                                                         \
    static_assert(true);

// Error-envelope storage the PWB_PLUGIN_MODULE glue wires into
// pwb_plugin_last_error(); call set_plugin_error(kind, message) before
// returning nullptr from a run function. Thread-local: the host reads the
// buffer on the same thread execute() ran in.
namespace plugin {

std::string& module_error_buffer();
void set_plugin_error(const std::string& kind, const std::string& message);

}  // namespace plugin
}  // namespace pwb::providers
