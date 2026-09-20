// V14 layer targets — see layer_targets.hpp.
#include "pwb/ui_composite/layer_targets.hpp"

#include <algorithm>

namespace pwb::ui_composite {

void LayerTargets::set_probes(
    std::function<bool(const std::string&)> layer_exists,
    std::function<bool(const std::string&)> layer_dirty,
    std::function<std::optional<std::string>()> native_current_layer) {
    layer_exists_ = std::move(layer_exists);
    layer_dirty_ = std::move(layer_dirty);
    native_current_layer_ = std::move(native_current_layer);
}

bool LayerTargets::layer_exists_now(const std::string& layer_id) const {
    if (layer_id.empty()) return false;
    if (layer_exists_) return layer_exists_(layer_id);
    return true;  // no probe: keep the target, degrade honestly upwards
}

void LayerTargets::set_active(const std::string& layer_id) {
    active_ = layer_id.empty() ? std::optional<std::string>{}
                               : std::optional<std::string>(layer_id);
}

void LayerTargets::note_selection(const std::string& layer_id) {
    selection_ = layer_id.empty() ? std::optional<std::string>{}
                                  : std::optional<std::string>(layer_id);
}

bool LayerTargets::start_editing(const std::string& layer_id) {
    if (layer_id.empty()) return false;
    if (std::find(editing_.begin(), editing_.end(), layer_id) !=
        editing_.end()) {
        return true;  // already open (idempotent success)
    }
    editing_.push_back(layer_id);
    return true;
}

bool LayerTargets::stop_editing(const std::string& layer_id) {
    auto it = std::find(editing_.begin(), editing_.end(), layer_id);
    if (it == editing_.end()) return false;
    editing_.erase(it);
    if (tool_target_ == layer_id) disarm_tool();
    return true;
}

bool LayerTargets::is_editing(const std::string& layer_id) const {
    return std::find(editing_.begin(), editing_.end(), layer_id) !=
           editing_.end();
}

ToolArmReport LayerTargets::arm_edit_tool(const std::string& layer_id) {
    ToolArmReport report;
    if (layer_id.empty()) {
        report.result = ToolArmResult::kRejectedNoTarget;
        report.reason = "编辑工具没有编辑目标：请在图层树选中该图层并「开始编辑」";
        return report;
    }
    if (!layer_exists_now(layer_id)) {
        report.result = ToolArmResult::kRejectedLayerGone;
        report.reason = "目标图层已不存在：" + layer_id;
        return report;
    }
    if (!is_editing(layer_id)) {
        // Fail-closed: never write outside the open edit set — "drawing a
        // provenance line into the facies boundary" is the business risk
        // this gate exists for.
        report.result = ToolArmResult::kRejectedNotEditing;
        report.reason =
            "图层未处于编辑会话中，工具未激活（先对该图层「开始编辑」）：" +
            layer_id;
        return report;
    }
    tool_target_ = layer_id;
    return report;
}

void LayerTargets::disarm_tool() {
    tool_target_.reset();
}

RevalidationReport LayerTargets::revalidate() {
    RevalidationReport report;
    // Editing set: drop layers the runtime no longer has; dirty ones are
    // reported separately so the host fails/closes those sessions (never
    // silently discards changes).
    std::vector<std::string> surviving;
    surviving.reserve(editing_.size());
    for (const std::string& layer_id : editing_) {
        if (layer_exists_now(layer_id)) {
            surviving.push_back(layer_id);
            continue;
        }
        report.dropped_editing.push_back(layer_id);
        if (layer_dirty_ && layer_dirty_(layer_id)) {
            report.dropped_dirty_editing.push_back(layer_id);
        }
    }
    editing_ = std::move(surviving);
    if (active_.has_value() && !active_->empty() &&
        !layer_exists_now(*active_)) {
        active_.reset();
        report.active_reset = true;
    }
    if (tool_target_.has_value() && !tool_target_->empty()) {
        if (!layer_exists_now(*tool_target_) || !is_editing(*tool_target_)) {
            tool_target_.reset();
            report.tool_disarmed = true;
        }
    }
    if (selection_.has_value() && !selection_->empty() &&
        !layer_exists_now(*selection_)) {
        selection_.reset();
        report.selection_reset = true;
    }
    // Runtime drift: the canvas current layer is the fact; report the
    // divergence instead of papering over it.
    if (native_current_layer_) {
        const std::optional<std::string> native = native_current_layer_();
        if (native.has_value() != active_.has_value() ||
            (native.has_value() && active_.has_value() &&
             *native != *active_)) {
            report.native_drift = true;
        }
    }
    return report;
}

}  // namespace pwb::ui_composite
