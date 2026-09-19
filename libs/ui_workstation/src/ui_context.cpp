#include "pwb/ui_workstation/ui_context.hpp"

#include <cstdio>
#include <stdexcept>
#include <unordered_set>

namespace pwb::ui_workstation {

namespace {

// Field name -> coercion target. Mirrors UIContextSnapshot field types;
// a provider returning a non-matching variant degrades to unknown (the
// Python dataclass would accept anything, but silently accepting a
// wrong-typed authority fact is exactly the kind of fabrication the
// contract forbids — fail closed instead).
enum class FieldKind { Bool, Int, Str, StrVec, OptBool, OptInt, OptStr };

const std::map<std::string, FieldKind>& field_kinds() {
    static const std::map<std::string, FieldKind> kinds = {
        {"project_open", FieldKind::Bool},
        {"project_name", FieldKind::OptStr},
        {"mapping_stage", FieldKind::OptStr},
        {"mapping_stage_label", FieldKind::OptStr},
        {"active_layer_id", FieldKind::OptStr},
        {"active_layer_role", FieldKind::OptStr},
        {"active_layer_editable", FieldKind::OptBool},
        {"active_layer_block_reason", FieldKind::OptStr},
        {"active_layer_kind", FieldKind::OptStr},
        {"active_layer_maturity", FieldKind::OptStr},
        {"active_layer_frozen", FieldKind::Bool},
        {"active_layer_missing", FieldKind::Bool},
        {"active_layer_degraded", FieldKind::Bool},
        {"active_layer_is_raster", FieldKind::Bool},
        {"active_layer_writable", FieldKind::OptBool},
        {"editing_active", FieldKind::Bool},
        {"editing_dirty", FieldKind::OptBool},
        {"selection_count", FieldKind::OptInt},
        {"can_undo", FieldKind::OptBool},
        {"can_redo", FieldKind::OptBool},
        {"split_ready", FieldKind::OptBool},
        {"merge_ready", FieldKind::OptBool},
        {"reshape_ready", FieldKind::OptBool},
        {"native_canvas_available", FieldKind::OptBool},
        {"native_capability_flags", FieldKind::StrVec},
        {"blocking_task", FieldKind::OptStr},
        {"queryable_layer_count", FieldKind::OptInt},
        {"active_well_id", FieldKind::OptStr},
        {"active_horizon_id", FieldKind::OptStr},
        {"active_fault_id", FieldKind::OptStr},
        {"active_interpretation_id", FieldKind::OptStr},
        {"selected_layer_id", FieldKind::OptStr},
        {"edit_target_layer_id", FieldKind::OptStr},
        {"selected_asset_id", FieldKind::OptStr},
        {"selected_version_id", FieldKind::OptStr},
        {"active_survey_id", FieldKind::OptStr},
        {"active_task_id", FieldKind::OptStr},
        {"workflow_stage", FieldKind::OptStr},
        {"running_operation", FieldKind::OptStr},
        {"qgis_bridge_available", FieldKind::OptBool},
        {"capability_mode", FieldKind::OptStr},
        {"capability_reason", FieldKind::OptStr},
        {"write_granted", FieldKind::Bool},
        {"running_task_count", FieldKind::Int},
    };
    return kinds;
}

bool apply_field(UIContextSnapshot& snap, const std::string& name,
                 FieldKind kind, const UIContextFieldValue& value) {
    // Returns false when the provider value's variant type does not match
    // the field kind (caller treats the field as unknown).
    if (std::holds_alternative<std::monostate>(value)) {
        return false;
    }
    switch (kind) {
        case FieldKind::Bool: {
            if (!std::holds_alternative<bool>(value)) return false;
            const bool v = std::get<bool>(value);
            if (name == "project_open") snap.project_open = v;
            else if (name == "active_layer_frozen") snap.active_layer_frozen = v;
            else if (name == "active_layer_missing") snap.active_layer_missing = v;
            else if (name == "active_layer_degraded") snap.active_layer_degraded = v;
            else if (name == "active_layer_is_raster") snap.active_layer_is_raster = v;
            else if (name == "editing_active") snap.editing_active = v;
            else if (name == "write_granted") snap.write_granted = v;
            else return false;
            return true;
        }
        case FieldKind::Int: {
            if (!std::holds_alternative<int>(value)) return false;
            snap.running_task_count = std::get<int>(value);
            return true;
        }
        case FieldKind::StrVec: {
            if (!std::holds_alternative<std::vector<std::string>>(value))
                return false;
            snap.native_capability_flags =
                std::get<std::vector<std::string>>(value);
            return true;
        }
        case FieldKind::OptBool: {
            std::optional<bool> v;
            if (std::holds_alternative<bool>(value))
                v = std::get<bool>(value);
            else
                return false;
            if (name == "active_layer_editable") snap.active_layer_editable = v;
            else if (name == "active_layer_writable") snap.active_layer_writable = v;
            else if (name == "editing_dirty") snap.editing_dirty = v;
            else if (name == "can_undo") snap.can_undo = v;
            else if (name == "can_redo") snap.can_redo = v;
            else if (name == "split_ready") snap.split_ready = v;
            else if (name == "merge_ready") snap.merge_ready = v;
            else if (name == "reshape_ready") snap.reshape_ready = v;
            else if (name == "native_canvas_available") snap.native_canvas_available = v;
            else if (name == "qgis_bridge_available") snap.qgis_bridge_available = v;
            else return false;
            return true;
        }
        case FieldKind::OptInt: {
            std::optional<int> v;
            if (std::holds_alternative<int>(value))
                v = std::get<int>(value);
            else
                return false;
            if (name == "selection_count") snap.selection_count = v;
            else if (name == "queryable_layer_count") snap.queryable_layer_count = v;
            else return false;
            return true;
        }
        case FieldKind::OptStr: {
            std::optional<std::string> v;
            if (std::holds_alternative<std::string>(value))
                v = std::get<std::string>(value);
            else
                return false;
            if (name == "project_name") snap.project_name = v;
            else if (name == "mapping_stage") snap.mapping_stage = v;
            else if (name == "mapping_stage_label") snap.mapping_stage_label = v;
            else if (name == "active_layer_id") snap.active_layer_id = v;
            else if (name == "active_layer_role") snap.active_layer_role = v;
            else if (name == "active_layer_block_reason") snap.active_layer_block_reason = v;
            else if (name == "active_layer_kind") snap.active_layer_kind = v;
            else if (name == "active_layer_maturity") snap.active_layer_maturity = v;
            else if (name == "blocking_task") snap.blocking_task = v;
            else if (name == "active_well_id") snap.active_well_id = v;
            else if (name == "active_horizon_id") snap.active_horizon_id = v;
            else if (name == "active_fault_id") snap.active_fault_id = v;
            else if (name == "active_interpretation_id") snap.active_interpretation_id = v;
            else if (name == "selected_layer_id") snap.selected_layer_id = v;
            else if (name == "edit_target_layer_id") snap.edit_target_layer_id = v;
            else if (name == "selected_asset_id") snap.selected_asset_id = v;
            else if (name == "selected_version_id") snap.selected_version_id = v;
            else if (name == "active_survey_id") snap.active_survey_id = v;
            else if (name == "active_task_id") snap.active_task_id = v;
            else if (name == "workflow_stage") snap.workflow_stage = v;
            else if (name == "running_operation") snap.running_operation = v;
            else if (name == "capability_mode") snap.capability_mode = v;
            else if (name == "capability_reason") snap.capability_reason = v;
            else return false;
            return true;
        }
    }
    return false;
}

}  // namespace

const std::vector<std::string>& ui_context_field_names() {
    static const std::vector<std::string> names = [] {
        std::vector<std::string> out;
        out.reserve(field_kinds().size());
        for (const auto& [name, _kind] : field_kinds()) out.push_back(name);
        return out;
    }();
    return names;
}

bool ui_context_has_field(const std::string& name) {
    return field_kinds().count(name) != 0;
}

void UIContextService::set_provider(const std::string& name, Provider fn) {
    if (!ui_context_has_field(name)) {
        throw std::out_of_range("UIContextSnapshot 无字段 '" + name + "'");
    }
    providers_[name] = std::move(fn);
}

void UIContextService::clear_provider(const std::string& name) {
    providers_.erase(name);
}

bool UIContextService::has_provider(const std::string& name) const {
    return providers_.count(name) != 0;
}

UIContextSnapshot UIContextService::snapshot() const {
    UIContextSnapshot snap;
    for (const auto& [name, fn] : providers_) {
        UIContextFieldValue value;
        try {
            value = fn();
        } catch (const std::exception& exc) {
            // Authority-side exception degrades to unknown (fail-closed,
            // Python logger.warning parity — stderr keeps it observable).
            std::fprintf(stderr,
                         "ui_context: provider '%s' failed, treated as "
                         "unknown: %s\n",
                         name.c_str(), exc.what());
            continue;
        } catch (...) {
            std::fprintf(stderr,
                         "ui_context: provider '%s' failed, treated as "
                         "unknown\n",
                         name.c_str());
            continue;
        }
        apply_field(snap, name, field_kinds().at(name), value);
    }
    return snap;
}

UIContextSnapshot UIContextService::current() const {
    return last_.has_value() ? *last_ : snapshot();
}

UIContextSnapshot UIContextService::refresh() {
    UIContextSnapshot snap = snapshot();
    if (!last_.has_value() || !(snap == *last_)) {
        last_ = snap;
        if (listener_) {
            // Listener exceptions must not propagate into authority
            // signals (late/teardown emissions are dropped, not fatal).
            try {
                listener_(snap);
            } catch (...) {
            }
        }
    }
    return snap;
}

void UIContextService::set_change_listener(ChangeListener listener) {
    listener_ = std::move(listener);
}

}  // namespace pwb::ui_workstation
