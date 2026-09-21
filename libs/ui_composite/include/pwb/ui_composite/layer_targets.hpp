// V14 LayerTargets — the explicit active/edit/tool/selection target
// model (Prompt V14 §10; contracts 03 §5).
//
// Four distinct targets, one invariant set:
// * tree selection / active layer — what the panel highlights and what
//   identify/select act on;
// * edit target set — layers whose QGIS edit sessions are open (join
//   order matters, mirrors libs/mapping_document native_edit_session);
// * tool target — the layer armed digitizing/vertex tools will WRITE to;
// * selection layer — the layer of the last user selection gesture.
//
// Invariants (violations are P0 by contract):
// 1. a UI claiming "editing A" never lets tools write B — the armed
//    tool's write target must be inside the open edit set;
// 2. deleting a layer invalidates its targets: revalidate() drops it
//    and reports which dirty sessions the host must fail/close;
// 3. stage switches never inherit the edit target across stages (the
//    stage controller owns that rule; this model verifies the result);
// 4. multi-layer snapping never widens the WRITE target;
// 5. selecting B while vertex tools still write A is surfaced as
//    "selection_mismatch" so the presentation layer can warn visibly;
// 6. the runtime authority is the native canvas current layer —
//    note_native_current() records drift instead of silently fixing it.
//
// The model is policy/state only: QGIS remains the runtime fact; probes
// read it back. Qt-free.
#pragma once

#include <functional>
#include <optional>
#include <string>
#include <vector>

namespace pwb::ui_composite {

enum class ToolArmResult {
    kArmed,
    kRejectedNoTarget,
    kRejectedNotEditing,
    kRejectedLayerGone,
};

struct ToolArmReport {
    ToolArmResult result = ToolArmResult::kArmed;
    // Fail-closed, user-facing reason (Chinese product vocabulary).
    std::string reason;
};

// What revalidate() had to fix (host surfaces every entry; a dirty
// session drop means "fail or close that session now").
struct RevalidationReport {
    std::vector<std::string> dropped_editing;      // gone from the runtime
    std::vector<std::string> dropped_dirty_editing;  // gone AND had changes
    bool active_reset = false;
    bool tool_disarmed = false;
    bool selection_reset = false;
    bool native_drift = false;  // canvas current layer != domain active
};

class LayerTargets {
public:
    // Runtime probes against the QGIS authority (canvas current layer,
    // layer existence). Without an existence probe the model degrades by
    // KEEPING targets (revalidate reports nothing) — probes are the
    // authoritative readback; hosts that care about deletion must wire
    // one (the platform glue always does).
    void set_probes(std::function<bool(const std::string&)> layer_exists,
                    std::function<bool(const std::string&)> layer_dirty,
                    std::function<std::optional<std::string>()>
                        native_current_layer);

    // -- active / selection --------------------------------------------------
    void set_active(const std::string& layer_id);  // "" clears
    const std::optional<std::string>& active_layer_id() const {
        return active_;
    }
    void note_selection(const std::string& layer_id);  // user gesture
    const std::optional<std::string>& selection_layer_id() const {
        return selection_;
    }
    // selection != tool write target → the presentation layer must show
    // the mismatch (select B must not silently keep writing A).
    bool selection_mismatch() const {
        return selection_.has_value() && tool_target_.has_value() &&
               *selection_ != *tool_target_;
    }

    // -- editing set (join order preserved) ------------------------------------
    bool start_editing(const std::string& layer_id);
    bool stop_editing(const std::string& layer_id);
    const std::vector<std::string>& editing_layer_ids() const {
        return editing_;
    }
    bool is_editing(const std::string& layer_id) const;

    // -- tool target ------------------------------------------------------------
    // Preflight fail-closed: digitizing/vertex tools may only write to a
    // layer with an open edit session that still exists.
    ToolArmReport arm_edit_tool(const std::string& layer_id);
    void disarm_tool();
    const std::optional<std::string>& tool_target_id() const {
        return tool_target_;
    }
    bool invariant_tool_target_in_editing_set() const {
        return !tool_target_.has_value() ||
               is_editing(*tool_target_) ||
               tool_target_->empty();
    }

    // -- runtime reconciliation ----------------------------------------------------
    // Drop everything referencing layers the runtime no longer has and
    // compare the native current layer with the domain active layer.
    RevalidationReport revalidate();

private:
    bool layer_exists_now(const std::string& layer_id) const;

    std::optional<std::string> active_;
    std::optional<std::string> selection_;
    std::optional<std::string> tool_target_;
    std::vector<std::string> editing_;  // join order
    std::function<bool(const std::string&)> layer_exists_;
    std::function<bool(const std::string&)> layer_dirty_;
    std::function<std::optional<std::string>()> native_current_layer_;
};

}  // namespace pwb::ui_composite
