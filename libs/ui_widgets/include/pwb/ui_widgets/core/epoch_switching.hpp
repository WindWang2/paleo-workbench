#pragma once

// UI-02 — epoch diff-switch planner + onion-skin layer set, ported from
// paleo_workbench/mapping_workspace/epoch_switching.py (Qt-free pure logic)
// plus the epoch-group helpers of layer_groups.py (epoch_group_id /
// is_epoch_group / epoch_key_of_group).
//
// Input layers are plain snapshots (MapLayerSnapshot shape); the executor
// applies the symmetric difference through the existing
// set_layer_visible / set_layer_opacity path — incremental mirror, zero
// canvas rebuilds.

#include <functional>
#include <map>
#include <optional>
#include <string>
#include <vector>

namespace pwb::ui_widgets::core {

inline constexpr const char* kEpochGroupPrefix = "epoch.";
// D2: onion skin alpha applied to adjacent-previous-epoch facies layers.
inline constexpr double kOnionOpacity = 0.30;

// epoch key -> stable group id (bound to key, decoupled from label).
[[nodiscard]] std::string epoch_group_id(const std::string& epoch_key);
[[nodiscard]] bool is_epoch_group(const std::string& group_id);
// epoch group id -> epoch key; nullopt for non-epoch groups.
[[nodiscard]] std::optional<std::string> epoch_key_of_group(
    const std::string& group_id);

// Duck-typed layer snapshot (MapLayerSnapshot shape).
struct LayerSnapshot {
    std::string id;
    std::string name;
    bool visible = true;
    double opacity = 1.0;
    std::map<std::string, std::string> metadata;
};

// Duck-typed epoch entry (key + label).
struct EpochInfo {
    std::string key;
    std::string label;
};

// Minimal visibility change set for one epoch switch. An empty plan is
// falsy in Python — `has_changes()` mirrors `__bool__`.
struct EpochSwitchPlan {
    std::string target;
    std::vector<std::string> show;
    std::vector<std::string> hide;

    [[nodiscard]] bool has_changes() const {
        return !show.empty() || !hide.empty();
    }
};

using EpochClassifier =
    std::function<std::optional<std::string>(const LayerSnapshot&)>;

// Conservative tag-only classification (no epoch catalog): explicit
// metadata epoch / horizon / epoch-group tags only.
[[nodiscard]] std::optional<std::string> tag_only_classifier(
    const LayerSnapshot& layer);

// layer -> epoch key (nullopt = unassigned).
// Signal precedence: metadata.epoch / metadata.horizon / metadata.group
// (epoch group id) -> layer name containing epoch key or label (longest
// patterns first so prefixes cannot swallow matches).
[[nodiscard]] EpochClassifier default_epoch_classifier(
    const std::vector<EpochInfo>& epochs);

// Facies surface/boundary layer predicate (onion-skin participation, D2).
[[nodiscard]] bool is_facies_layer(const LayerSnapshot& layer);

// current -> target minimal change plan (symmetric diff; same epoch ->
// empty plan; unassigned layers never switch).
[[nodiscard]] EpochSwitchPlan build_epoch_switch_plan(
    const std::vector<LayerSnapshot>& layers, const std::string* current,
    const std::string& target,
    const EpochClassifier& classifier = {});

// Facies layer ids of the adjacent previous epoch (index-1; empty for the
// oldest epoch — D2).
[[nodiscard]] std::vector<std::string> build_onion_layers(
    const std::vector<LayerSnapshot>& layers,
    const std::vector<EpochInfo>& epochs, const std::string& current,
    const EpochClassifier& classifier = {});

}  // namespace pwb::ui_widgets::core
