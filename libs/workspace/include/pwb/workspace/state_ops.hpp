// V14 workspace state operations — the behavior surface of
// MappingWorkspaceState/StageViewState (port of the stage_state.py
// behavior methods that the layer control plane consumes;
// layer_group_controller.py / controller.py call these on every path).
//
// The codec (state.hpp) stays a pure projection; these helpers are the
// in-memory mutation/read surface used by the controllers. Persistence
// still goes through to_json() + the project save path — no second
// storage. Python enums arrive as their string wire values; unknown
// values stay unknown ("" handling per the domain contract, never
// guessed).
#pragma once

#include "pwb/workspace/state.hpp"

#include <map>
#include <optional>
#include <string>
#include <vector>

namespace pwb::workspace {

// Per-stage view state access (creates on first touch, Python
// view_state()).
StageViewState& view_state(MappingWorkspaceState& state,
                           const std::string& stage_value);
const StageViewState* find_view_state(const MappingWorkspaceState& state,
                                      const std::string& stage_value);

// Stage profile defaults + user overrides -> effective group visibility.
// (Defaults copied; explicit non-null overrides win.)
std::map<std::string, bool> effective_group_visibility(
    const StageViewState& view,
    const std::map<std::string, bool>& defaults);

// User-gesture recorders (ONLY from user echo entry points; programmatic
// stage pushes must never freeze defaults into overrides — contract
// 03 §7). Each sets customized = true; opacity clamps to [0.05, 1.0].
void record_group_visibility(StageViewState& view,
                             const std::string& group_id, bool visible);
void record_layer_visibility(StageViewState& view,
                             const std::string& layer_id, bool visible);
void record_layer_opacity(StageViewState& view, const std::string& layer_id,
                          double opacity);

// "Restore Stage Defaults": clear the overlay, back to profile defaults.
void reset_stage_view_to_defaults(StageViewState& view);

// Membership accessors (Python membership()/set_membership()/
// layers_with_role()). set_membership ignores empty layer ids; role
// normalization to the known vocabulary happens at the read boundary
// (unknown roles stay unknown strings — legacy fallback is the caller's
// routing concern, not silent coercion).
const LayerBinding* membership(const MappingWorkspaceState& state,
                               const std::string& layer_id);
void set_membership(MappingWorkspaceState& state, LayerBinding binding);
void drop_membership(MappingWorkspaceState& state,
                     const std::string& layer_id);
std::vector<std::string> layers_with_role(const MappingWorkspaceState& state,
                                          const std::string& role_value);

// Layers pinned to a catalog version (kind == catalog_version effective).
// convenience overload mirroring MappingWorkspaceState::catalog_bindings.
std::vector<LayerBinding> catalog_bindings_of(const MappingWorkspaceState& state);

}  // namespace pwb::workspace
