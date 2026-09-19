// Test plugin module for providers.plugins — compiled four times with a
// VARIANT define to produce the whole load-failure/ok matrix:
//   PWB_TEST_PLUGIN_OK           well-formed module (echo + slow providers)
//   PWB_TEST_PLUGIN_MISSING_CAP  well-formed but requires a host capability
//                                this build does not advertise
//   PWB_TEST_PLUGIN_BADABI       hand-written describe() declaring abi 999999
//   PWB_TEST_PLUGIN_BADDESC      valid ABI but a descriptor failing
//                                validate_descriptor (bad provider_id)
// The non-BADABI paths go through plugin_module.hpp's PWB_PLUGIN_MODULE
// glue — the same authoring surface a third party would use.
#include <chrono>
#include <string>
#include <thread>

#include <pwb/providers/plugin_module.hpp>

using namespace pwb::providers;

namespace pwp = pwb::providers::plugin;
using pwb::providers::plugin::set_plugin_error;

#if defined(PWB_TEST_PLUGIN_BADABI)

// A module from a different ABI generation: same six symbols, different
// declared version. Hand-written to prove the boundary is data-driven, not
// macro-magic-dependent.
extern "C" const pwb::providers::PwbPluginDescription* pwb_plugin_describe(void) {
    static pwb::providers::PwbPluginDescription description;
    static const char* requires_list[] = {pwb::providers::kPluginHostCapability};
    description.abi_version = 999999;
    description.plugin_id = "test.badabi";
    description.plugin_version = "1.0.0";
    description.requires_host_capabilities = requires_list;
    description.requires_host_capability_count = 1;
    description.provides_host_capabilities = nullptr;
    description.provides_host_capability_count = 0;
    return &description;
}

extern "C" int pwb_plugin_provider_count(void) { return 1; }
extern "C" const char* pwb_plugin_provider_descriptor(int) { return "{}"; }
extern "C" const char* pwb_plugin_execute(int, const char*, const char*,
                                          const char*,
                                          const PwbPluginHostBridge*) {
    return nullptr;
}
extern "C" const char* pwb_plugin_last_error(void) { return "{}"; }
extern "C" void pwb_plugin_shutdown(void) {}

#else  // OK / MISSING_CAP / BADDESC — the macro-authored path

namespace {

#if defined(PWB_TEST_PLUGIN_BADDESC)
// Fails validate_descriptor: provider_id violates ^[a-z0-9][a-z0-9._-]{1,63}$.
const char* kEchoDescriptor = R"({
  "provider_id": "Bad Provider ID",
  "family": "exporter",
  "version": "1.0.0",
  "display_name": "echo",
  "description": "invalid test provider",
  "capabilities": [],
  "input_types": [],
  "output_types": [],
  "parameters_schema": {"type": "object"},
  "resource_profile": {"estimated_cpu_cores": 1.0, "estimated_ram_bytes": 0,
                        "estimated_vram_bytes": 0, "io_weight": 1.0,
                        "category": "background.compute"},
  "supports_cancel": false,
  "supports_resume": false,
  "deterministic": true,
  "threading_model": "worker_thread",
  "build_identity": null
})";
#else
const char* kEchoDescriptor = R"({
  "provider_id": "plugin.echo",
  "family": "exporter",
  "version": "1.0.0",
  "display_name": "echo",
  "description": "test echo provider",
  "capabilities": ["test.echo"],
  "input_types": ["PathRef"],
  "output_types": ["PathRef"],
  "parameters_schema": {"type": "object", "properties": {"say": {"type": "string"}}},
  "resource_profile": {"estimated_cpu_cores": 1.0, "estimated_ram_bytes": 0,
                        "estimated_vram_bytes": 0, "io_weight": 1.0,
                        "category": "background.compute"},
  "supports_cancel": false,
  "supports_resume": false,
  "deterministic": true,
  "threading_model": "worker_thread",
  "build_identity": null
})";
#endif

// Cancellable slow provider: sleeps in small slices up to parameters.hold_ms
// polling the bridge cancel probe; answers kind=cancelled when asked.
const char* kSlowDescriptor = R"({
  "provider_id": "plugin.slow",
  "family": "interpolation",
  "version": "1.0.0",
  "display_name": "slow",
  "description": "cancellable hold-in-place provider",
  "capabilities": ["test.slow"],
  "input_types": [],
  "output_types": [],
  "parameters_schema": {"type": "object", "properties": {"hold_ms": {"type": "integer"}}},
  "resource_profile": {"estimated_cpu_cores": 1.0, "estimated_ram_bytes": 0,
                        "estimated_vram_bytes": 0, "io_weight": 1.0,
                        "category": "background.compute"},
  "supports_cancel": true,
  "supports_resume": false,
  "deterministic": true,
  "threading_model": "worker_thread",
  "build_identity": null
})";

const char* echo_run(const char* inputs_json, const char* parameters_json,
                     const char* context_json, const PwbPluginHostBridge* bridge) {
    (void)inputs_json;
    (void)context_json;
    (void)bridge;
    static std::string result;
    try {
        auto parameters =
            pwb::providers::Json::parse(parameters_json, nullptr, false);
        if (parameters.is_discarded()) {
            set_plugin_error(pwp::kInvalidParameters, "parameters 不可解析");
            return nullptr;
        }
        pwb::providers::Json out = pwb::providers::Json::object();
        pwb::providers::Json metrics = pwb::providers::Json::object();
        metrics["echo"] = parameters.value("say", std::string());
        out["metrics"] = std::move(metrics);
        pwb::providers::Json artifacts = pwb::providers::Json::array();
        pwb::providers::Json artifact = pwb::providers::Json::object();
        artifact["name"] = "echo";
        artifact["kind"] = "file";
        artifact["version"] = nullptr;
        artifact["path"] = nullptr;
        artifact["metadata"] = pwb::providers::Json::object();
        artifacts.push_back(std::move(artifact));
        out["artifacts"] = std::move(artifacts);
        out["warnings"] = pwb::providers::Json::array();
        out["diagnostics"] = pwb::providers::Json::object();
        out["provenance"] = pwb::providers::Json::object();
        result = out.dump();
    } catch (const std::exception& exc) {
        set_plugin_error(pwp::kInternal, exc.what());
        return nullptr;
    }
    return result.c_str();
}

const char* slow_run(const char* inputs_json, const char* parameters_json,
                     const char* context_json, const PwbPluginHostBridge* bridge) {
    (void)inputs_json;
    (void)context_json;
    static std::string result;
    auto parameters =
        pwb::providers::Json::parse(parameters_json, nullptr, false);
    const long long hold_ms =
        parameters.is_discarded() ? 0 : parameters.value("hold_ms", 0LL);
    const auto deadline =
        std::chrono::steady_clock::now() + std::chrono::milliseconds(hold_ms);
    while (std::chrono::steady_clock::now() < deadline) {
        if (bridge != nullptr && bridge->cancel_probe != nullptr &&
            bridge->cancel_probe(bridge->user) != 0) {
            set_plugin_error(pwp::kCancelled, "插件执行被取消");
            return nullptr;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }
    pwb::providers::Json out = pwb::providers::Json::object();
    out["artifacts"] = pwb::providers::Json::array();
    out["warnings"] = pwb::providers::Json::array();
    out["diagnostics"] = pwb::providers::Json::object();
    out["provenance"] = pwb::providers::Json::object();
    pwb::providers::Json metrics = pwb::providers::Json::object();
    metrics["held_ms"] = hold_ms;
    out["metrics"] = std::move(metrics);
    result = out.dump();
    return result.c_str();
}

pwb::providers::plugin::PluginModuleDef make_module_def() {
    pwb::providers::plugin::PluginModuleDef def;
#if defined(PWB_TEST_PLUGIN_OK)
    def.plugin_id = "test.ok";
#elif defined(PWB_TEST_PLUGIN_MISSING_CAP)
    def.plugin_id = "test.missing_cap";
#elif defined(PWB_TEST_PLUGIN_BADDESC)
    def.plugin_id = "test.baddesc";
#endif
    def.plugin_version = "1.0.0";
#ifdef PWB_TEST_PLUGIN_MISSING_CAP
    def.requires_host_capabilities = {pwb::providers::kPluginHostCapability,
                                      "pwb.capability.absent/1"};
#else
    def.requires_host_capabilities = {pwb::providers::kPluginHostCapability};
#endif
    def.provides_host_capabilities = {"pwb.test-plugin/1"};
    def.providers = {
        {kEchoDescriptor, &echo_run},
        {kSlowDescriptor, &slow_run},
    };
    return def;
}

const pwb::providers::plugin::PluginModuleDef kModuleDef = make_module_def();

}  // namespace

PWB_PLUGIN_MODULE(kModuleDef)

#endif  // PWB_TEST_PLUGIN_BADABI
