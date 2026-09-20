#pragma once

// Harness execution context — C++ port of paleo_workbench/harness/context.py
// (P2-C, harness-2.0 selection snapshot fields included).
//
// The context is what an agent may *read* about the current session plus the
// service handles actions delegate to. Agents never mutate the context;
// mutations happen only inside actions, through the domain services.
// Services arrive as injected ports (catalog port, provider registry); the
// harness never opens databases or reaches into UI state by itself.

#include <pwb/closure_agent/spec.hpp>
#include <pwb/providers/context.hpp>
#include <pwb/providers/registry.hpp>

#include <array>
#include <memory>
#include <set>
#include <functional>

namespace pwb::closure_agent {

using Json = pwb::domain::Json;
using providers::CancelToken;

// Python ActionContextError (LookupError subclass): a required-context
// attribute is absent. The executor maps it to `rejected`.
class ActionContextError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

// Python DEFAULT_PERMISSIONS = {ActionRisk.READ, ActionRisk.COMPUTE}.
std::set<ActionRisk> default_permissions();

// Frozen view of the selection bus for agents; immutable by contract — the
// host re-snapshots when session state changes. Field names mirror
// SelectionSnapshot.to_dict().
struct SelectionSnapshot {
    std::optional<std::string> active_well_id;
    std::vector<std::string> selected_well_ids;
    // seismic_cursor: (inline, crossline, time_ms)
    std::optional<std::array<long long, 3>> seismic_cursor;
    std::optional<std::array<double, 2>> depth_range;
    std::optional<std::string> target_horizon;
    std::optional<std::string> active_fault_id;
    std::optional<std::string> active_interpretation_id;
    std::optional<std::string> active_layer_id;
    std::optional<std::string> selected_layer_id;
    std::optional<std::string> selected_asset_id;
    // map_extent: (x0, y0, x1, y1)
    std::optional<std::array<double, 4>> map_extent;
    std::optional<std::string> map_crs;
    std::vector<std::string> selected_feature_refs;
    std::optional<std::string> active_version_id;
    std::optional<std::array<double, 2>> spatial_cursor;
    // depth_cursor: (well_id, depth)
    std::optional<std::array<Json, 2>> depth_cursor;

    Json to_dict() const;
};

class ActionContext {
public:
    ActionContext();

    // --- identity ---
    std::string session_id;
    std::optional<std::string> workspace_id;
    std::optional<std::string> project_path;

    // --- services (single authorities; injected, never re-created) ---
    providers::ICatalogPort* catalog = nullptr;
    const void* project = nullptr;  // live project document; opaque READ handle

    // --- context awareness ---
    SelectionSnapshot selection;
    std::optional<std::string> active_survey_id;
    std::optional<std::string> active_well_id;
    // Active seismic volume typed input (Python SeismicVolumeRef/PathRef);
    // type_name is the TYPED_REFS vocabulary name of the payload.
    std::optional<providers::TypedInput> active_volume;
    std::optional<std::string> current_map_id;

    // --- governance / control ---
    std::set<ActionRisk> permissions = default_permissions();
    std::function<void(double, const std::string&)> progress;  // (ratio, message)
    CancelToken* cancel = nullptr;
    // Host-supplied cancellation probe (a foreign token type, e.g. the
    // workflow engine's CancelToken); checked alongside `cancel`.
    std::function<bool()> cancel_probe;
    Json extras = Json::object();

    // Python has()/require(): attr names the spec's required_context may name.
    // Unknown names read as absent (fail-closed) — message parity with the
    // Python LookupError text.
    bool has(const std::string& attr) const;
    void require(const std::string& attr) const;

    // True when either cancellation seam is armed.
    bool is_cancelled() const {
        if (cancel != nullptr && cancel->is_cancelled()) return true;
        return cancel_probe && cancel_probe();
    }

    bool permits(ActionRisk risk) const {
        return permissions.count(risk) > 0;
    }

    // Per-execution copy sharing services/selection but with its own extras
    // (minus the executor's admission lease slot).
    ActionContext derived() const;

    // Build the providers::ProviderContext for a nested provider execution —
    // the single sanctioned construction path. Forwards session services,
    // progress, cancellation and the enclosing admission lease while the
    // executor runs this action.
    providers::ProviderContext provider_context() const;

    // Machine-readable summary for agent prompts (read-only facts);
    // key order mirrors snapshot_description().
    Json snapshot_description() const;

    // Test/host seam: deterministic session ids (Python uuid4().hex[:12]).
    static std::function<std::string()> session_id_generator;
};

}  // namespace pwb::closure_agent
