// Edit gesture manager (CONV-27d).
//
// Port of paleo_workbench/mapping/edit_gesture_manager.py — the gesture level
// of the two-level undo (host side): the host records "gesture → ordered
// affected layer ids"; undoing a whole gesture walks the layers in REVERSE
// order, redoing walks them forward (per-layer, the bridge undo stack holds
// one macro per layer per gesture, begun/ended by the bridge's
// begin/endEditCommand). Gesture boundaries = mouse release / command
// confirmation (bridge-side edit_gesture callback).
//
// The gesture records double as the audit source (gesture id, affected layer
// sequence, macro text). Pure logic: no Qt, no bridge.
//
// Single-threaded by contract (the owning workbench serializes access).
#pragma once

#include <pwb/domain/json.hpp>

#include <string>
#include <vector>

namespace pwb::mapping_document {

using Json = pwb::domain::Json;

struct GestureRecord {
    std::string gesture_id;
    std::string undo_text;
    std::vector<std::string> layer_ids;
    bool undone = false;

    bool operator==(const GestureRecord&) const = default;
};

class EditGestureManager {
public:
    // Records one finished gesture (layer sequence de-duplicated, order
    // preserved — first occurrence wins, exactly like the Python loop).
    GestureRecord finish(std::string gesture_id, std::string undo_text,
                         const std::vector<std::string>& layer_ids);

    // The most recent not-yet-undone gesture's layer sequence, REVERSED
    // (whole-gesture undo = reverse-order per-layer undo). Empty = nothing
    // to undo.
    std::vector<std::string> undo_plan() const;

    void mark_undone(const std::string& gesture_id);

    // The most recent undone gesture's layer sequence, in FORWARD order.
    // Stale redo-queue ids (never marked, or re-done) are popped.
    std::vector<std::string> redo_plan();

    void mark_redone(const std::string& gesture_id);

    // The gesture id the undo/redo plans resolve to ("" = none). Same
    // source as the plans: the latest open (not undone) gesture, else the
    // redo queue head.
    std::string current_gesture_id();

    // Gesture history is voided after commit/rollback (the same semantics
    // as QGIS clearing the undo stack on commit).
    void clear();

    // The gesture audit stream: [{gesture_id, undo_text, layer_ids}].
    Json audit_records() const;

    std::size_t size() const { return gestures_.size(); }

private:
    const GestureRecord* find(const std::string& gesture_id) const;
    GestureRecord* find(const std::string& gesture_id);
    void replace(const GestureRecord& record);

    std::vector<GestureRecord> gestures_;
    // Ids of undone gestures, most recently undone first (LIFO redo).
    std::vector<std::string> redo_queue_;
};

}  // namespace pwb::mapping_document
