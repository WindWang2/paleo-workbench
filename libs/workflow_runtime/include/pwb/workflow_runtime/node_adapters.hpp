#pragma once

// Task adapter bridge + runtime resource model (CONV-26).
//
// Bridge (E): existing C++ node operations — the workflow_engine registry
// built-ins ("test.noop") and the mapping_kernel wrappers
// ("map.extract_factors", "map.interpolate_idw") — become workflow runtime
// node ADAPTERS: registry key + node function + resource hints + display
// metadata. No algorithm is duplicated; the adapter layer adds the runtime
// concerns the engine slice deliberately left out (resource hints,
// admission, progress surface, error mapping documentation).
//
// Resource model (G): ResourceHints declares a node's CPU/RAM budget;
// AdmissionGate is a bounded-concurrency latch with cancel-aware acquire —
// the runtime scheduler admits at most max_concurrent task bodies and never
// spawns unbounded threads. The deterministic schedule (default
// max_concurrency == 1) drives plan steps strictly in plan order.
//
// Typed input/output contract: node params may bind catalog versions with
// {"$version": "ver_…"} values — the runtime resolves them to run inputs
// (provenance) before invoking the op; op outputs are Json + optional typed
// payload (engine NodeResult). Error mapping: op exceptions land the node
// FAILED with the exception message (engine semantics, frozen in CONV-07).
//
// Qt-free, Python-free.

#include <pwb/domain/json.hpp>
#include <pwb/workflow_engine/engine.hpp>

#include <atomic>
#include <condition_variable>
#include <cstdint>
#include <map>
#include <mutex>
#include <optional>
#include <string>
#include <vector>

namespace pwb::workflow_runtime {

using pwb::domain::Json;
using pwb::workflow_engine::CancelToken;
using pwb::workflow_engine::NodeFunction;

// Declared resource budget of one node operation.
struct ResourceHints {
    unsigned cpu_slots = 1;      // abstract compute slots (admission units)
    std::uint64_t ram_mib = 0;   // 0 == undeclared
    std::string display_name;    // deterministic UI label ("" == operation)
};

struct NodeAdapter {
    std::string operation;       // registry key (Python action id)
    NodeFunction fn;
    ResourceHints hints;
};

class NodeAdapterRegistry {
public:
    void add(NodeAdapter adapter);
    [[nodiscard]] const NodeAdapter* find(const std::string& operation) const;
    // Sorted — deterministic listing for inspect/UI.
    [[nodiscard]] std::vector<std::string> operations() const;

    // "test.noop" adapter (engine built-in).
    void register_builtin_adapters();
    // "map.extract_factors" + "map.interpolate_idw" over the mapping
    // kernels (engine wrappers — same NodeFunction bodies, wrapped with
    // runtime hints). No algorithm duplication.
    void register_mapping_adapters();

private:
    std::map<std::string, NodeAdapter> adapters_;
};

// Bounded-concurrency admission latch. acquire() blocks until a slot is
// free or the token is cancelled (returns false — never queues past a
// cancel). Thread-safe; RAII lease returns the slot.
// The returned Lease is RAII and MUST NOT outlive its gate (destroy the
// lease first, or move it within the gate's scope).
class AdmissionGate {
public:
    class Lease {
    public:
        Lease() noexcept = default;
        explicit Lease(AdmissionGate* gate) noexcept : gate_(gate) {}
        Lease(const Lease&) = delete;
        Lease& operator=(const Lease&) = delete;
        Lease(Lease&& other) noexcept : gate_(other.gate_) {
            other.gate_ = nullptr;
        }
        Lease& operator=(Lease&& other) noexcept;
        ~Lease();
        [[nodiscard]] bool holds() const noexcept { return gate_ != nullptr; }

    private:
        AdmissionGate* gate_ = nullptr;
    };

    explicit AdmissionGate(unsigned max_concurrent) noexcept;

    // Non-blocking: true when a slot was acquired immediately.
    bool try_acquire();
    // Cancel-aware blocking acquire.
    bool acquire(const CancelToken& token);
    void release();
    void cancel_all();  // unblock waiting acquirers (terminal shutdown)
    void reset();       // re-arm after cancel_all (new plan generation)

    [[nodiscard]] unsigned max_concurrent() const noexcept {
        return max_concurrent_;
    }
    [[nodiscard]] unsigned active() const noexcept;

private:
    const unsigned max_concurrent_;
    mutable std::mutex mutex_;
    std::condition_variable cancel_cv_;
    unsigned in_flight_ = 0;
    bool cancelled_ = false;
};

// Extract {"$version": "ver_…"} bindings from node params (typed input
// surface): returns the referenced version ids in key order; the params
// copy with the bindings replaced by the raw version id string is written
// to *bound_params when provided.
std::vector<std::string> extract_version_bindings(
    const Json& params, Json* bound_params = nullptr);

}  // namespace pwb::workflow_runtime
