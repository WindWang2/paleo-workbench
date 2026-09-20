// pwb::providers — versioned plugin boundary (line-10 mandate: dynamic tool
// providers with ABI + capability negotiation). The static registry above
// stays the composition-root default (ADR 0055 track P.REG, "no directory
// scanning, ever" is unchanged); this header defines the *opt-in module
// contract* a third party ships as a shared library, and the host side of
// the negotiation. Qt-free, Python-free.
//
// Design (no Python oracle exists for this surface — no dynamic plugin
// loading exists on the Python side either):
//   * C ABI only: the module exports six C functions; everything else
//     crosses as UTF-8 JSON, so neither side shares C++ types or a compiler.
//   * kPluginAbiVersion gates the load: a module compiled against a
//     different ABI is rejected with PluginAbiError before any descriptor
//     is parsed (reproducible failure behavior, tested).
//   * capability negotiation: the module declares what it needs from the
//     host (requires_host_capabilities) and what it adds
//     (provides_host_capabilities); the host checks its own advertised set
//     and refuses the load with PluginCapabilityError when a requirement
//     cannot be met.
//   * unload safety: executions pin the module through PluginLoader::Lease
//     (plugin_loader.hpp); an unload requested while a task is inside the
//     module is *deferred* until the last lease releases — running tasks
//     complete, new executions fail fast with PluginUnloadPendingError.
#pragma once

#include <pwb/providers/errors.hpp>

#include <string>
#include <vector>

#define PWB_PLUGIN_ABI_VERSION 1

namespace pwb::providers {

// Host-side ABI version this build negotiates for.
inline constexpr int kPluginAbiVersion = PWB_PLUGIN_ABI_VERSION;

// The one capability every host advertises; modules require it to opt into
// this contract. Hosts may advertise more (e.g. a build with the catalog
// port adds "pwb.catalog-port/1") — the strings are vocabulary, versioned
// by suffix, never guessed by either side.
inline constexpr const char* kPluginHostCapability = "pwb.plugin-host/1";

// --- C ABI (shared with plugin_module.hpp; keep in sync verbatim) ----------

// Progress/cancel bridge: the host passes fn pointers + a user word; the
// module may call progress() from any thread and must treat it as
// best-effort (the host swallows errors), and poll cancel_probe() at its
// own checkpoints (nonzero return = cancelled).
extern "C" typedef struct PwbPluginHostBridge {
    void* user;
    void (*progress)(void* user, double fraction, const char* message_utf8);
    int (*cancel_probe)(void* user);
} PwbPluginHostBridge;

extern "C" typedef struct PwbPluginDescription {
    int abi_version;  // must equal kPluginAbiVersion on the host
    const char* plugin_id;
    const char* plugin_version;
    const char* const* requires_host_capabilities;
    int requires_host_capability_count;
    const char* const* provides_host_capabilities;
    int provides_host_capability_count;
} PwbPluginDescription;

// The six entry points every plugin module exports. Descriptor/result text
// is UTF-8 JSON owned by the module and stays valid until shutdown().
// execute() returns a ProviderResult JSON payload, or NULL when the run
// failed — pwb_plugin_last_error() then returns an error envelope:
//   {"kind": "cancelled"|"rejected"|"invalid_parameters"|"execution"|"internal",
//    "message": "..."}
extern "C" typedef const PwbPluginDescription* (*PwbFnPluginDescribe)(void);
extern "C" typedef int (*PwbFnPluginProviderCount)(void);
extern "C" typedef const char* (*PwbFnPluginProviderDescriptor)(int index);
extern "C" typedef const char* (*PwbFnPluginExecute)(
    int index, const char* inputs_json, const char* parameters_json,
    const char* context_json, const PwbPluginHostBridge* bridge);
extern "C" typedef const char* (*PwbFnPluginLastError)(void);
extern "C" typedef void (*PwbFnPluginShutdown)(void);

// --- host-side typed failures ----------------------------------------------
//
// Every failure mode of load/negotiate/unload has a distinct type so hosts
// can explain it (the task acceptance calls each one out as reproducible).

class PluginError : public ProviderError {
public:
    using ProviderError::ProviderError;
};

// dlopen/dlsym failed: file missing, not a shared library, or a required
// symbol absent. what() carries the OS loader detail verbatim.
class PluginLoadError : public PluginError {
public:
    PluginLoadError(std::string path, std::string detail)
        : PluginError("插件加载失败: " + detail + " (" + path + ")"),
          path_(std::move(path)), detail_(std::move(detail)) {}
    const std::string& path() const noexcept { return path_; }
    const std::string& detail() const noexcept { return detail_; }

private:
    std::string path_;
    std::string detail_;
};

// The module's abi_version differs from kPluginAbiVersion.
class PluginAbiError : public PluginError {
public:
    PluginAbiError(std::string path, int expected, int actual)
        : PluginError("插件 ABI 不兼容: 期望 " + std::to_string(expected) +
                      ", 实际 " + std::to_string(actual) + " (" + path + ")"),
          path_(std::move(path)), expected_(expected), actual_(actual) {}
    const std::string& path() const noexcept { return path_; }
    int expected() const noexcept { return expected_; }
    int actual() const noexcept { return actual_; }

private:
    std::string path_;
    int expected_;
    int actual_;
};

// The module requires a host capability this build does not advertise.
class PluginCapabilityError : public PluginError {
public:
    PluginCapabilityError(std::string path, std::vector<std::string> missing)
        : PluginError("插件所需宿主能力缺失: " + join(missing) + " (" + path + ")"),
          path_(std::move(path)), missing_(std::move(missing)) {}
    const std::string& path() const noexcept { return path_; }
    const std::vector<std::string>& missing() const noexcept { return missing_; }

private:
    static std::string join(const std::vector<std::string>& values) {
        std::string out;
        for (const auto& value : values) {
            if (!out.empty()) out += ", ";
            out += value;
        }
        return out;
    }
    std::string path_;
    std::vector<std::string> missing_;
};

// A descriptor string from the module is absent, unparsable, or fails
// validate_descriptor. Registry quarantine semantics stay untouched: the
// module is rejected whole, nothing is registered.
class PluginDescriptorError : public PluginError {
public:
    PluginDescriptorError(std::string path, std::string provider_id,
                          std::string detail)
        : PluginError("插件 provider 描述无效: " + provider_id + ": " + detail +
                      " (" + path + ")"),
          path_(std::move(path)), provider_id_(std::move(provider_id)),
          detail_(std::move(detail)) {}
    const std::string& path() const noexcept { return path_; }
    const std::string& provider_id() const noexcept { return provider_id_; }
    const std::string& detail() const noexcept { return detail_; }

private:
    std::string path_;
    std::string provider_id_;
    std::string detail_;
};

// An execution/lookup arrived after unload was requested but before the
// module could be finalized (still pinned by running tasks).
class PluginUnloadPendingError : public PluginError {
public:
    explicit PluginUnloadPendingError(std::string plugin_id)
        : PluginError("插件正在卸载: " + plugin_id),
          plugin_id_(std::move(plugin_id)) {}
    const std::string& plugin_id() const noexcept { return plugin_id_; }

private:
    std::string plugin_id_;
};

}  // namespace pwb::providers
