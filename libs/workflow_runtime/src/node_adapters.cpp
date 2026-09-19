// node_adapters.cpp — task adapter bridge + resource model (CONV-26).
// See include/pwb/workflow_runtime/node_adapters.hpp.

#include <pwb/workflow_runtime/node_adapters.hpp>

#include <pwb/workflow_engine/ops.hpp>

#include <algorithm>
#include <chrono>
#include <initializer_list>
#include <utility>

namespace pwb::workflow_runtime {

void NodeAdapterRegistry::add(NodeAdapter adapter) {
    std::string key = adapter.operation;
    adapters_[std::move(key)] = std::move(adapter);
}

const NodeAdapter* NodeAdapterRegistry::find(
    const std::string& operation) const {
    const auto it = adapters_.find(operation);
    return it == adapters_.end() ? nullptr : &it->second;
}

std::vector<std::string> NodeAdapterRegistry::operations() const {
    std::vector<std::string> out;
    out.reserve(adapters_.size());
    for (const auto& [op, adapter] : adapters_) {
        (void)adapter;
        out.push_back(op);
    }
    return out;  // std::map iteration is already sorted/deterministic
}

void NodeAdapterRegistry::register_builtin_adapters() {
    // "test.noop" — engine built-in, looked up by registry key (the engine
    // registry has no enumeration surface; keys are this slice's contract).
    pwb::workflow_engine::NodeRegistry engine_registry;
    pwb::workflow_engine::register_builtin_ops(engine_registry);
    const pwb::workflow_engine::NodeFunction* fn =
        engine_registry.find("test.noop");
    if (fn == nullptr) return;
    NodeAdapter adapter;
    adapter.operation = "test.noop";
    adapter.fn = *fn;
    adapter.hints = ResourceHints{1, 0, "空操作"};
    add(std::move(adapter));
}

void NodeAdapterRegistry::register_mapping_adapters() {
    // The mapping wrappers registered into a scratch engine registry, then
    // lifted into adapters keyed by the same operation ids — the
    // NodeFunction bodies are the engine's (no algorithm duplication).
    pwb::workflow_engine::NodeRegistry engine_registry;
    pwb::workflow_engine::register_mapping_ops(engine_registry);
    struct MappingSpec {
        const char* op;
        unsigned cpu;
        std::uint64_t ram;
        const char* label;
    };
    for (const MappingSpec& spec : std::initializer_list<MappingSpec>{
             {"map.extract_factors", 1, 256, "因子样点提取"},
             {"map.interpolate_idw", 2, 512, "IDW 网格插值"},
         }) {
        const pwb::workflow_engine::NodeFunction* fn =
            engine_registry.find(spec.op);
        if (fn == nullptr) continue;
        NodeAdapter adapter;
        adapter.operation = spec.op;
        adapter.fn = *fn;
        adapter.hints = ResourceHints{spec.cpu, spec.ram, spec.label};
        add(std::move(adapter));
    }
}

// ---- AdmissionGate ----------------------------------------------------

AdmissionGate::Lease& AdmissionGate::Lease::operator=(
    Lease&& other) noexcept {
    if (this != &other) {
        if (gate_ != nullptr) gate_->release();
        gate_ = other.gate_;
        other.gate_ = nullptr;
    }
    return *this;
}

AdmissionGate::Lease::~Lease() {
    if (gate_ != nullptr) gate_->release();
}

AdmissionGate::AdmissionGate(unsigned max_concurrent) noexcept
    : max_concurrent_(max_concurrent == 0 ? 1 : max_concurrent) {}

bool AdmissionGate::try_acquire() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (cancelled_ || in_flight_ >= max_concurrent_) return false;
    ++in_flight_;
    return true;
}

bool AdmissionGate::acquire(const CancelToken& token) {
    std::unique_lock<std::mutex> lock(mutex_);
    while (!cancelled_ && in_flight_ >= max_concurrent_) {
        if (token.is_cancelled()) return false;
        // Wake on cancel_all() or a release(); re-check the token.
        cancel_cv_.wait_for(lock, std::chrono::milliseconds(50));
    }
    if (cancelled_ || token.is_cancelled()) return false;
    ++in_flight_;
    return true;
}

void AdmissionGate::release() {
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (in_flight_ > 0) --in_flight_;
    }
    cancel_cv_.notify_all();
}

void AdmissionGate::cancel_all() {
    {
        std::lock_guard<std::mutex> lock(mutex_);
        cancelled_ = true;
    }
    cancel_cv_.notify_all();
}

void AdmissionGate::reset() {
    {
        std::lock_guard<std::mutex> lock(mutex_);
        cancelled_ = false;
    }
}

unsigned AdmissionGate::active() const noexcept {
    std::lock_guard<std::mutex> lock(mutex_);
    return in_flight_;
}

// ---- typed input bindings ---------------------------------------------

std::vector<std::string> extract_version_bindings(const Json& params,
                                                  Json* bound_params) {
    std::vector<std::string> versions;
    Json bound = params;
    if (params.is_object()) {
        bound = Json::object();
        for (auto it = params.begin(); it != params.end(); ++it) {
            const Json& value = it.value();
            if (value.is_object() && value.size() == 1 &&
                value.contains("$version") &&
                value.at("$version").is_string()) {
                versions.push_back(value.at("$version").get<std::string>());
                bound[it.key()] = value.at("$version");
            } else if (value.is_array()) {
                Json replaced = Json::array();
                for (const auto& item : value) {
                    if (item.is_object() && item.size() == 1 &&
                        item.contains("$version") &&
                        item.at("$version").is_string()) {
                        versions.push_back(
                            item.at("$version").get<std::string>());
                        replaced.push_back(item.at("$version"));
                    } else {
                        replaced.push_back(item);
                    }
                }
                bound[it.key()] = std::move(replaced);
            } else {
                bound[it.key()] = value;
            }
        }
    }
    if (bound_params != nullptr) *bound_params = std::move(bound);
    return versions;
}

}  // namespace pwb::workflow_runtime
