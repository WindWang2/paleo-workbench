#include <pwb/mapping_document/edit_gesture_manager.hpp>

#include <algorithm>

namespace pwb::mapping_document {

GestureRecord EditGestureManager::finish(std::string gesture_id,
                                         std::string undo_text,
                                         const std::vector<std::string>& layer_ids) {
    std::vector<std::string> ordered;
    ordered.reserve(layer_ids.size());
    for (const std::string& layer_id : layer_ids) {
        if (std::find(ordered.begin(), ordered.end(), layer_id) == ordered.end()) {
            ordered.push_back(layer_id);
        }
    }
    GestureRecord record{std::move(gesture_id), std::move(undo_text),
                         std::move(ordered), false};
    gestures_.push_back(record);
    return record;
}

const GestureRecord* EditGestureManager::find(const std::string& gesture_id) const {
    for (auto it = gestures_.rbegin(); it != gestures_.rend(); ++it) {
        if (it->gesture_id == gesture_id) return &*it;
    }
    return nullptr;
}

GestureRecord* EditGestureManager::find(const std::string& gesture_id) {
    return const_cast<GestureRecord*>(
        static_cast<const EditGestureManager*>(this)->find(gesture_id));
}

void EditGestureManager::replace(const GestureRecord& record) {
    for (GestureRecord& existing : gestures_) {
        if (existing.gesture_id == record.gesture_id) {
            existing = record;
            return;
        }
    }
}

std::vector<std::string> EditGestureManager::undo_plan() const {
    for (auto it = gestures_.rbegin(); it != gestures_.rend(); ++it) {
        if (!it->undone) {
            return {it->layer_ids.rbegin(), it->layer_ids.rend()};
        }
    }
    return {};
}

void EditGestureManager::mark_undone(const std::string& gesture_id) {
    GestureRecord* record = find(gesture_id);
    if (record == nullptr || record->undone) return;
    GestureRecord updated = *record;
    updated.undone = true;
    replace(updated);
    redo_queue_.push_back(gesture_id);
}

std::vector<std::string> EditGestureManager::redo_plan() {
    while (!redo_queue_.empty()) {
        const GestureRecord* record = find(redo_queue_.back());
        if (record != nullptr && record->undone) {
            return record->layer_ids;
        }
        redo_queue_.pop_back();
    }
    return {};
}

void EditGestureManager::mark_redone(const std::string& gesture_id) {
    GestureRecord* record = find(gesture_id);
    if (record == nullptr || !record->undone) return;
    GestureRecord updated = *record;
    updated.undone = false;
    replace(updated);
    // Whole-queue erase vs Python list.remove (first occurrence): equivalent
    // because mark_undone's idempotence guard keeps at most one queue entry
    // per gesture id.
    std::erase(redo_queue_, gesture_id);
}

std::string EditGestureManager::current_gesture_id() {
    for (auto it = gestures_.rbegin(); it != gestures_.rend(); ++it) {
        if (!it->undone) return it->gesture_id;
    }
    while (!redo_queue_.empty()) {
        const GestureRecord* record = find(redo_queue_.back());
        if (record != nullptr && record->undone) return record->gesture_id;
        redo_queue_.pop_back();
    }
    return "";
}

void EditGestureManager::clear() {
    gestures_.clear();
    redo_queue_.clear();
}

Json EditGestureManager::audit_records() const {
    Json out = Json::array();
    for (const GestureRecord& record : gestures_) {
        Json entry = Json::object();
        entry["gesture_id"] = record.gesture_id;
        entry["undo_text"] = record.undo_text;
        entry["layer_ids"] = record.layer_ids;
        out.push_back(std::move(entry));
    }
    return out;
}

}  // namespace pwb::mapping_document
