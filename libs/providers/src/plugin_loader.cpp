// Plugin loading, negotiation and the lease/refcount unload policy — the
// implementation of plugin_loader.hpp over plugin_abi.hpp. dlopen on POSIX,
// LoadLibrary on Windows (the C ABI surface keeps the two identical); the
// dl_* shims below absorb the API delta so the loader body is shared.
//
// Locking: PluginLoader::mutex_ guards the module table; each ModuleState
// has its own mutex for leases/pending/finalized transitions. The deferred
// finalizer takes the loader mutex, then the registry's own (never the
// reverse), so there is no lock-order cycle.
#include <pwb/providers/plugin_loader.hpp>

#ifdef _WIN32
#include <windows.h>
#else
#include <dlfcn.h>
#endif

#include <algorithm>
#include <memory>
#include <mutex>
#include <string>

namespace pwb::providers {

namespace {

// Platform dl shims: LoadLibrary uses HMODULE (an opaque handle that fits
// void*) and has no error string query — GetLastError plus the failing
// call name is the closest honest detail.
void* dl_open(const char* path) {
#ifdef _WIN32
    return static_cast<void*>(::LoadLibraryA(path));
#else
    return ::dlopen(path, RTLD_NOW | RTLD_LOCAL);
#endif
}

void* dl_sym(void* handle, const char* symbol) {
#ifdef _WIN32
    return reinterpret_cast<void*>(::GetProcAddress(
        static_cast<HMODULE>(handle), symbol));
#else
    return ::dlsym(handle, symbol);
#endif
}

void dl_close(void* handle) {
#ifdef _WIN32
    ::FreeLibrary(static_cast<HMODULE>(handle));
#else
    ::dlclose(handle);
#endif
}

std::string dl_error() {
#ifdef _WIN32
    return "LoadLibrary/GetProcAddress failed (GetLastError=" +
           std::to_string(::GetLastError()) + ")";
#else
    const char* detail = ::dlerror();
    return detail != nullptr ? std::string(detail) : std::string();
#endif
}

Json parse_json_or_throw(const std::string& text, const std::string& path,
                         const std::string& provider_hint) {
    Json out = Json::parse(text, nullptr, false);
    if (out.is_discarded()) {
        throw PluginDescriptorError(path, provider_hint, "JSON 解析失败");
    }
    return out;
}

// Execute results use execution-typed errors, not descriptor errors.
Json parse_result_json(const std::string& text, const std::string& provider_id) {
    Json out = Json::parse(text, nullptr, false);
    if (out.is_discarded()) {
        throw ProviderExecutionError(provider_id, "PluginError",
                                     "插件返回结果不可解析");
    }
    return out;
}

ProviderDescriptor descriptor_from_json(const Json& payload) {
    ProviderDescriptor descriptor;
    descriptor.provider_id = payload.value("provider_id", "");
    const std::string family_text = payload.value("family", "");
    if (auto family = family_from_string(family_text); family.has_value()) {
        descriptor.family = *family;
    }
    descriptor.version = payload.value("version", "");
    descriptor.display_name = payload.value("display_name", "");
    descriptor.description = payload.value("description", "");
    const auto read_strings = [](const Json& node,
                                 const char* key) {
        std::vector<std::string> out;
        if (node.contains(key) && node[key].is_array()) {
            for (const auto& value : node[key]) {
                if (value.is_string()) out.push_back(value.get<std::string>());
            }
        }
        return out;
    };
    descriptor.capabilities = read_strings(payload, "capabilities");
    descriptor.input_types = read_strings(payload, "input_types");
    descriptor.output_types = read_strings(payload, "output_types");
    if (payload.contains("parameters_schema")) {
        descriptor.parameters_schema = payload["parameters_schema"];
    }
    if (payload.contains("resource_profile") &&
        payload["resource_profile"].is_object()) {
        const Json& profile = payload["resource_profile"];
        descriptor.resource_profile.estimated_cpu_cores =
            profile.value("estimated_cpu_cores", 1.0);
        descriptor.resource_profile.estimated_ram_bytes =
            profile.value("estimated_ram_bytes", 0LL);
        descriptor.resource_profile.estimated_vram_bytes =
            profile.value("estimated_vram_bytes", 0LL);
        descriptor.resource_profile.io_weight = profile.value("io_weight", 1.0);
        descriptor.resource_profile.category =
            profile.value("category", std::string("background.compute"));
    }
    descriptor.supports_cancel = payload.value("supports_cancel", false);
    descriptor.supports_resume = payload.value("supports_resume", false);
    descriptor.deterministic = payload.value("deterministic", true);
    descriptor.threading_model =
        payload.value("threading_model", std::string("worker_thread"));
    if (payload.contains("build_identity") &&
        payload["build_identity"].is_string()) {
        descriptor.build_identity = payload["build_identity"].get<std::string>();
    }
    return descriptor;
}

// ProviderResult reconstruction from the module JSON (ArtifactRef keeps the
// to_json() key set: name/kind/version/path/metadata).
ProviderResult result_from_json(const Json& payload) {
    ProviderResult result;
    if (payload.contains("artifacts") && payload["artifacts"].is_array()) {
        for (const auto& artifact : payload["artifacts"]) {
            ArtifactRef ref;
            ref.name = artifact.value("name", "");
            ref.kind = artifact.value("kind", "file");
            ref.version = artifact.contains("version") ? artifact["version"]
                                                       : Json(nullptr);
            if (artifact.contains("path") && artifact["path"].is_string()) {
                ref.path = artifact["path"].get<std::string>();
            }
            if (artifact.contains("metadata")) {
                ref.metadata = artifact["metadata"];
            }
            result.artifacts.push_back(std::move(ref));
        }
    }
    result.warnings = [&] {
        std::vector<std::string> out;
        if (payload.contains("warnings") && payload["warnings"].is_array()) {
            for (const auto& value : payload["warnings"]) {
                if (value.is_string()) out.push_back(value.get<std::string>());
            }
        }
        return out;
    }();
    if (payload.contains("diagnostics")) result.diagnostics = payload["diagnostics"];
    if (payload.contains("provenance")) result.provenance = payload["provenance"];
    if (payload.contains("metrics")) result.metrics = payload["metrics"];
    return result;
}

std::string inputs_to_json(const ProviderInputs& inputs) {
    Json array = Json::array();
    for (const auto& [name, typed] : inputs.entries()) {
        Json entry = Json::object();
        entry["name"] = name;
        entry["type_name"] = typed.type_name;
        entry["payload"] = typed.payload;
        array.push_back(std::move(entry));
    }
    return array.dump();
}

// Host bridge: adapts ProviderContext progress/cancel onto the C fn
// pointers. Bridge lifetime == execute() lifetime; the context outlives it.
void bridge_progress(void* user, double fraction, const char* message) {
    static_cast<ProviderContext*>(user)->report_progress(
        fraction, message != nullptr ? message : "");
}

int bridge_cancel_probe(void* user) {
    auto* context = static_cast<ProviderContext*>(user);
    return context->cancel != nullptr && context->cancel->is_cancelled() ? 1 : 0;
}

}  // namespace

// --- ModuleState -------------------------------------------------------------

struct PluginLoader::ModuleState {
    // Immutable after load.
    void* handle = nullptr;
    PwbFnPluginShutdown shutdown = nullptr;
    PluginInfo info;
    PluginLoader* owner = nullptr;

    // Mutable: lease/pending lifecycle.
    std::mutex mutex;
    int leases = 0;
    bool pending_unload = false;
    bool finalized = false;

    // Lease token payload: decrements the lease count. Finalization is NOT
    // done here (it would destroy provider objects under a stack frame the
    // SDK executor is still using); the next loader entry point sweeps it.
    struct Token {
        ModuleState* state;
    };
    static void token_deleter(void* raw) {
        std::unique_ptr<Token> token(static_cast<Token*>(raw));
        ModuleState& state = *token->state;
        std::lock_guard<std::mutex> guard(state.mutex);
        state.leases -= 1;
    }
};

void PluginLoader::finalize_module_now(ModuleState& state) const {
    {
        std::lock_guard<std::mutex> guard(state.mutex);
        if (state.finalized || state.leases > 0) return;
    }
    // Unregister first (registry owns the PluginProvider objects; they must
    // be gone before their code disappears), then close the module.
    for (const auto& provider_id : state.info.provider_ids) {
        registry_.unregister(provider_id);
    }
    {
        std::lock_guard<std::mutex> guard(state.mutex);
        if (state.finalized || state.leases > 0) return;  // raced: keep module
        if (state.shutdown != nullptr) state.shutdown();
        if (state.handle != nullptr) {
            dl_close(state.handle);
            state.handle = nullptr;
        }
        state.finalized = true;
    }
    // The table record stays (with finalized=true) and is never destroyed:
    // raw ModuleState pointers held across lock boundaries stay valid, and
    // every query path (find/loaded/acquire/unload) treats a finalized
    // module as gone.
}

void PluginLoader::sweep_pending() const {
    std::vector<ModuleState*> candidates;
    {
        std::lock_guard<std::mutex> guard(mutex_);
        for (auto& [id, state] : modules_) {
            if (state == nullptr) continue;
            std::lock_guard<std::mutex> state_guard(state->mutex);
            if (!state->finalized && state->pending_unload &&
                state->leases <= 0) {
                candidates.push_back(state.get());
            }
        }
    }
    for (auto* state : candidates) {
        finalize_module_now(*state);
    }
}

// --- Lease -------------------------------------------------------------------

PluginLoader::Lease::Lease(Lease&& other) noexcept
    : state_(std::move(other.state_)) {}

PluginLoader::Lease& PluginLoader::Lease::operator=(Lease&& other) noexcept {
    if (this != &other) {
        state_ = std::move(other.state_);
    }
    return *this;
}

PluginLoader::Lease::~Lease() { state_.reset(); }

// --- loader ------------------------------------------------------------------

PluginLoader::PluginLoader(ProviderRegistry& registry, HostCapabilities capabilities)
    : registry_(registry), capabilities_(std::move(capabilities)) {}

PluginLoader::~PluginLoader() {
    for (auto& [plugin_id, state] : modules_) {
        if (state == nullptr) continue;
        std::lock_guard<std::mutex> guard(state->mutex);
        if (state->finalized) continue;
        if (state->leases > 0) {
            // A task is still inside the module (contract violation or a
            // process teardown race): leave the code mapped and say so.
            log_event("warning", "plugin loader destroyed with active lease: " +
                                     plugin_id);
            for (const auto& provider_id : state->info.provider_ids) {
                registry_.unregister(provider_id);
            }
            state->info.provider_ids.clear();
            state->pending_unload = true;
            continue;
        }
        for (const auto& provider_id : state->info.provider_ids) {
            registry_.unregister(provider_id);
        }
        if (state->shutdown != nullptr) state->shutdown();
        if (state->handle != nullptr) {
            dl_close(state->handle);
            state->handle = nullptr;
        }
        state->finalized = true;
    }
}

PluginInfo PluginLoader::load(const std::filesystem::path& module_path) {
    sweep_pending();
    const std::string path_text = module_path.string();
    std::error_code ec;
    if (!std::filesystem::exists(module_path, ec)) {
        throw PluginLoadError(path_text, "文件不存在");
    }
    const std::filesystem::path normalized =
        std::filesystem::weakly_canonical(module_path, ec);
    {
        std::lock_guard<std::mutex> guard(mutex_);
        for (auto& [plugin_id, state] : modules_) {
            if (state == nullptr) continue;
            // Finalized records are skipped: a module that finished
            // unloading may be loaded again (hot reload).
            std::lock_guard<std::mutex> state_guard(state->mutex);
            if (state->finalized) continue;
            if (state->info.path == normalized) {
                throw PluginLoadError(path_text, "重复加载");
            }
        }
    }

    void* handle = dl_open(path_text.c_str());
    if (handle == nullptr) {
        throw PluginLoadError(path_text, dl_error());
    }
    auto resolve = [&](const char* symbol) -> void* {
        void* address = dl_sym(handle, symbol);
        if (address == nullptr) {
            dl_close(handle);
            throw PluginLoadError(path_text, std::string("缺少符号 ") + symbol);
        }
        return address;
    };
    auto* describe =
        reinterpret_cast<PwbFnPluginDescribe>(resolve("pwb_plugin_describe"));
    auto* provider_count = reinterpret_cast<PwbFnPluginProviderCount>(
        resolve("pwb_plugin_provider_count"));
    auto* provider_descriptor =
        reinterpret_cast<PwbFnPluginProviderDescriptor>(
            resolve("pwb_plugin_provider_descriptor"));
    auto* execute =
        reinterpret_cast<PwbFnPluginExecute>(resolve("pwb_plugin_execute"));
    auto* last_error =
        reinterpret_cast<PwbFnPluginLastError>(resolve("pwb_plugin_last_error"));
    // shutdown is optional (all modules with the glue export it; hand-rolled
    // C modules may not).
    auto* shutdown = reinterpret_cast<PwbFnPluginShutdown>(
        dl_sym(handle, "pwb_plugin_shutdown"));

    const PwbPluginDescription* description = describe();
    if (description == nullptr) {
        dl_close(handle);
        throw PluginDescriptorError(path_text, "", "pwb_plugin_describe 返回空");
    }
    // Copy every field we still need BEFORE any dlclose: after it, module
    // memory is unmapped and reading `description` again would be UAF.
    const int module_abi = description->abi_version;
    std::vector<std::string> requires_list;
    for (int i = 0; i < description->requires_host_capability_count; ++i) {
        if (description->requires_host_capabilities[i] != nullptr) {
            requires_list.emplace_back(description->requires_host_capabilities[i]);
        }
    }
    if (module_abi != kPluginAbiVersion) {
        dl_close(handle);
        throw PluginAbiError(path_text, kPluginAbiVersion, module_abi);
    }
    std::vector<std::string> missing;
    for (const auto& required : requires_list) {
        if (!capabilities_.provides_capability(required)) {
            missing.push_back(required);
        }
    }
    if (!missing.empty()) {
        dl_close(handle);
        throw PluginCapabilityError(path_text, std::move(missing));
    }
    const int count = provider_count();
    if (count <= 0) {
        dl_close(handle);
        throw PluginDescriptorError(path_text, "", "模块未声明 provider");
    }

    auto state = std::make_unique<ModuleState>();
    state->handle = handle;
    state->shutdown = shutdown;
    state->owner = this;
    state->info.plugin_id =
        description->plugin_id != nullptr ? description->plugin_id : "";
    state->info.plugin_version =
        description->plugin_version != nullptr ? description->plugin_version : "";
    state->info.path = ec ? module_path : normalized;
    state->info.abi_version = description->abi_version;
    for (int i = 0; i < description->provides_host_capability_count; ++i) {
        if (description->provides_host_capabilities[i] != nullptr) {
            state->info.provided_capabilities.emplace_back(
                description->provides_host_capabilities[i]);
        }
    }

    try {
        for (int index = 0; index < count; ++index) {
            const char* descriptor_text = provider_descriptor(index);
            if (descriptor_text == nullptr) {
                throw PluginDescriptorError(path_text,
                                            "index " + std::to_string(index),
                                            "pwb_plugin_provider_descriptor 返回空");
            }
            const Json payload =
                parse_json_or_throw(descriptor_text, path_text,
                                    "index " + std::to_string(index));
            ProviderDescriptor descriptor = descriptor_from_json(payload);
            auto problems = validate_descriptor(descriptor);
            if (!problems.empty()) {
                std::string joined;
                for (const auto& problem : problems) {
                    if (!joined.empty()) joined += "; ";
                    joined += problem;
                }
                throw PluginDescriptorError(path_text, descriptor.provider_id,
                                            joined);
            }
            auto provider = std::make_unique<PluginProvider>(
                *this, state->info.plugin_id, std::move(descriptor));
            provider->attach_entry(index, execute, last_error);
            const std::string provider_id = provider->descriptor().provider_id;
            registry_.register_provider(std::move(provider));
            state->info.provider_ids.push_back(provider_id);
        }
    } catch (...) {
        // Roll the whole module back: a rejected load leaves no trace.
        for (const auto& provider_id : state->info.provider_ids) {
            registry_.unregister(provider_id);
        }
        dl_close(handle);
        throw;
    }

    PluginInfo info = state->info;
    const std::string plugin_id = info.plugin_id;
    std::lock_guard<std::mutex> guard(mutex_);
    modules_.emplace_back(plugin_id, std::move(state));
    return info;
}

bool PluginLoader::unload(const std::string& plugin_id) {
    sweep_pending();
    ModuleState* state = nullptr;
    {
        std::lock_guard<std::mutex> guard(mutex_);
        for (auto& [id, candidate] : modules_) {
            if (id == plugin_id && candidate != nullptr) {
                state = candidate.get();
                break;
            }
        }
    }
    if (state == nullptr) return false;
    {
        std::lock_guard<std::mutex> guard(state->mutex);
        if (state->finalized) return true;
        if (state->leases > 0) {
            state->pending_unload = true;
            return false;  // deferred: running executions still inside
        }
        state->pending_unload = true;
    }
    finalize_module_now(*state);
    return true;
}

const PluginInfo* PluginLoader::find(const std::string& plugin_id) const {
    sweep_pending();
    std::lock_guard<std::mutex> guard(mutex_);
    for (auto& [id, state] : modules_) {
        if (id == plugin_id && state != nullptr) {
            std::lock_guard<std::mutex> state_guard(state->mutex);
            return state->finalized ? nullptr : &state->info;
        }
    }
    return nullptr;
}

std::vector<PluginInfo> PluginLoader::loaded() const {
    sweep_pending();
    std::lock_guard<std::mutex> guard(mutex_);
    std::vector<PluginInfo> out;
    for (auto& [id, state] : modules_) {
        if (state != nullptr) {
            std::lock_guard<std::mutex> state_guard(state->mutex);
            if (!state->finalized) out.push_back(state->info);
        }
    }
    return out;
}

bool PluginLoader::is_unload_pending(const std::string& plugin_id) const {
    sweep_pending();
    std::lock_guard<std::mutex> guard(mutex_);
    for (auto& [id, state] : modules_) {
        if (id == plugin_id && state != nullptr) {
            std::lock_guard<std::mutex> state_guard(state->mutex);
            return state->pending_unload && !state->finalized;
        }
    }
    return false;
}

PluginLoader::Lease PluginLoader::acquire(const std::string& plugin_id) {
    sweep_pending();
    ModuleState* state = nullptr;
    {
        std::lock_guard<std::mutex> guard(mutex_);
        for (auto& [id, candidate] : modules_) {
            if (id == plugin_id && candidate != nullptr) {
                state = candidate.get();
                break;
            }
        }
    }
    if (state == nullptr) {
        throw UnknownProviderError(plugin_id);
    }
    std::lock_guard<std::mutex> guard(state->mutex);
    if (state->finalized) {
        throw UnknownProviderError(plugin_id);
    }
    if (state->pending_unload) {
        throw PluginUnloadPendingError(plugin_id);
    }
    state->leases += 1;
    return Lease(std::shared_ptr<void>(new ModuleState::Token{state},
                                       &ModuleState::token_deleter));
}

// --- PluginProvider ----------------------------------------------------------

void PluginProvider::attach_entry(int index, PwbFnPluginExecute execute,
                                  PwbFnPluginLastError last_error) {
    provider_index_ = index;
    execute_ = execute;
    last_error_ = last_error;
}

ProviderResult PluginProvider::execute(const ProviderInputs& inputs,
                                       const Json& parameters,
                                       ProviderContext& context) {
    // Pin before entering the module: an unload racing this execution is
    // deferred until the lease drops; an unload already requested rejects
    // the run deterministically instead of executing against a closing
    // module.
    PluginLoader::Lease lease = loader_.acquire(plugin_id_);

    Json context_payload = Json::object();
    context_payload["workspace_root"] = context.workspace_root;
    context_payload["session_id"] = context.session_id;
    context_payload["run_id"] = context.run_id;
    context_payload["work_dir"] = context.work_dir;

    PwbPluginHostBridge bridge{};
    bridge.user = &context;
    bridge.progress = &bridge_progress;
    bridge.cancel_probe = &bridge_cancel_probe;

    const char* raw = execute_(provider_index_, inputs_to_json(inputs).c_str(),
                               parameters.dump().c_str(),
                               context_payload.dump().c_str(), &bridge);
    if (raw == nullptr) {
        const char* error_raw = last_error_();
        Json parsed = Json::parse(error_raw != nullptr ? error_raw : "",
                                  nullptr, false);
        const std::string kind =
            (!parsed.is_discarded() && parsed.is_object())
                ? parsed.value("kind", std::string("internal"))
                : std::string("internal");
        const std::string message =
            (!parsed.is_discarded() && parsed.is_object())
                ? parsed.value("message", std::string("插件执行失败（无错误详情）"))
                : std::string("插件执行失败（错误详情不可解析）");
        if (kind == "cancelled") {
            throw TaskCancelled(message);
        }
        if (kind == "rejected") {
            throw ProviderRejectedInputError(descriptor_.provider_id, message);
        }
        if (kind == "invalid_parameters") {
            throw InvalidParametersError(descriptor_.provider_id, {message});
        }
        throw ProviderExecutionError(descriptor_.provider_id, "PluginError",
                                     message);
    }
    return result_from_json(
        parse_result_json(raw, descriptor_.provider_id));
}

std::optional<Verification> PluginProvider::verify(const ProviderResult& result,
                                                   ProviderContext& context) {
    // Modules own their verification semantics; the conservative default
    // keeps the executor's fail-closed stage a no-op for plugins that did
    // not declare one (parity with IProvider::verify).
    (void)result;
    (void)context;
    return std::nullopt;
}

Json PluginInfo::to_json() const {
    Json out = Json::object();
    out["plugin_id"] = plugin_id;
    out["plugin_version"] = plugin_version;
    out["path"] = path.string();
    out["abi_version"] = abi_version;
    out["provided_capabilities"] = provided_capabilities;
    out["provider_ids"] = provider_ids;
    return out;
}

}  // namespace pwb::providers
