// map_edit_commands.py port — the undo/redo command stack for the mapping
// editor. Commands own std::function apply-callbacks; the scene supplies
// them. ``do()`` maps to apply() (``do`` is a C++ keyword); ``undo()`` maps
// to revert().
#pragma once

#include "pwb/ui_data_core/json_util.hpp"
#include "pwb/ui_data_core/map_edit_geometry.hpp"

#include <deque>
#include <functional>
#include <memory>
#include <string>
#include <utility>
#include <vector>

namespace pwb::ui_data_core {

class EditCommand {
public:
    virtual ~EditCommand() = default;
    virtual void apply() = 0;   // Python do()
    virtual void revert() = 0;  // Python undo()
};

// MoveCommand — translate one or more features by (dx, dy).
class MoveCommand : public EditCommand {
public:
    MoveCommand(std::vector<std::string> feature_ids, double dx, double dy,
                std::function<void(const std::string&, double, double)>
                    apply_move)
        : feature_ids_(std::move(feature_ids)),
          dx_(dx),
          dy_(dy),
          apply_move_(std::move(apply_move)) {}

    void apply() override {
        for (const auto& fid : feature_ids_) {
            apply_move_(fid, dx_, dy_);
        }
    }
    void revert() override {
        for (const auto& fid : feature_ids_) {
            apply_move_(fid, -dx_, -dy_);
        }
    }

private:
    std::vector<std::string> feature_ids_;
    double dx_;
    double dy_;
    std::function<void(const std::string&, double, double)> apply_move_;
};

// VertexEditCommand — replace a feature's coordinate ring
// (set / insert / delete vertex).
class VertexEditCommand : public EditCommand {
public:
    VertexEditCommand(
        std::string feature_id, MapRing old_coordinates,
        MapRing new_coordinates,
        std::function<void(const std::string&, const MapRing&)>
            apply_coordinates)
        : feature_id_(std::move(feature_id)),
          old_coordinates_(std::move(old_coordinates)),
          new_coordinates_(std::move(new_coordinates)),
          apply_coordinates_(std::move(apply_coordinates)) {}

    void apply() override { apply_coordinates_(feature_id_, new_coordinates_); }
    void revert() override {
        apply_coordinates_(feature_id_, old_coordinates_);
    }

private:
    std::string feature_id_;
    MapRing old_coordinates_;
    MapRing new_coordinates_;
    std::function<void(const std::string&, const MapRing&)>
        apply_coordinates_;
};

// RingEditCommand — replace one addressed ring without flattening sibling
// holes/parts.
class RingEditCommand : public EditCommand {
public:
    RingEditCommand(
        std::string feature_id, int part_index, int ring_index,
        MapRing old_coordinates, MapRing new_coordinates,
        std::function<void(const std::string&, int, int, const MapRing&)>
            apply_ring)
        : feature_id_(std::move(feature_id)),
          part_index_(part_index),
          ring_index_(ring_index),
          old_coordinates_(std::move(old_coordinates)),
          new_coordinates_(std::move(new_coordinates)),
          apply_ring_(std::move(apply_ring)) {}

    void apply() override {
        apply_ring_(feature_id_, part_index_, ring_index_, new_coordinates_);
    }
    void revert() override {
        apply_ring_(feature_id_, part_index_, ring_index_, old_coordinates_);
    }

private:
    std::string feature_id_;
    int part_index_;
    int ring_index_;
    MapRing old_coordinates_;
    MapRing new_coordinates_;
    std::function<void(const std::string&, int, int, const MapRing&)>
        apply_ring_;
};

// CreateFeatureCommand — add a feature from a normalized record; undo
// removes it by id.
class CreateFeatureCommand : public EditCommand {
public:
    CreateFeatureCommand(
        domain::Json record,
        std::function<void(const domain::Json&)> add_feature,
        std::function<void(const std::string&)> remove_feature)
        : record_(std::move(record)),
          feature_id_(record_.is_object()
                          ? json_get_string(record_, "id")
                          : std::string{}),
          add_feature_(std::move(add_feature)),
          remove_feature_(std::move(remove_feature)) {}

    void apply() override { add_feature_(record_); }
    void revert() override { remove_feature_(feature_id_); }

private:
    domain::Json record_;
    std::string feature_id_;
    std::function<void(const domain::Json&)> add_feature_;
    std::function<void(const std::string&)> remove_feature_;
};

// PropertyChangeCommand — change a scalar property (name/text) on a
// feature.
class PropertyChangeCommand : public EditCommand {
public:
    PropertyChangeCommand(
        std::string feature_id, std::string key, domain::Json old_value,
        domain::Json new_value,
        std::function<void(const std::string&, const std::string&,
                           const domain::Json&)>
            apply_property)
        : feature_id_(std::move(feature_id)),
          key_(std::move(key)),
          old_value_(std::move(old_value)),
          new_value_(std::move(new_value)),
          apply_property_(std::move(apply_property)) {}

    void apply() override {
        apply_property_(feature_id_, key_, new_value_);
    }
    void revert() override {
        apply_property_(feature_id_, key_, old_value_);
    }

private:
    std::string feature_id_;
    std::string key_;
    domain::Json old_value_;
    domain::Json new_value_;
    std::function<void(const std::string&, const std::string&,
                       const domain::Json&)>
        apply_property_;
};

// DeleteFeatureCommand — remove a feature; undo restores it from the
// stored record.
class DeleteFeatureCommand : public EditCommand {
public:
    DeleteFeatureCommand(
        domain::Json record,
        std::function<void(const domain::Json&)> add_feature,
        std::function<void(const std::string&)> remove_feature)
        : record_(std::move(record)),
          feature_id_(record_.is_object()
                          ? json_get_string(record_, "id")
                          : std::string{}),
          add_feature_(std::move(add_feature)),
          remove_feature_(std::move(remove_feature)) {}

    void apply() override { remove_feature_(feature_id_); }
    void revert() override { add_feature_(record_); }

private:
    domain::Json record_;
    std::string feature_id_;
    std::function<void(const domain::Json&)> add_feature_;
    std::function<void(const std::string&)> remove_feature_;
};

// BatchVertexEditCommand — coordinate updates to multiple features as one
// undo step.
class BatchVertexEditCommand : public EditCommand {
public:
    struct Change {
        std::string feature_id;
        MapRing old_coordinates;
        MapRing new_coordinates;
    };

    BatchVertexEditCommand(
        std::vector<Change> changes,
        std::function<void(const std::string&, const MapRing&)>
            apply_coordinates)
        : changes_(std::move(changes)),
          apply_coordinates_(std::move(apply_coordinates)) {}

    void apply() override {
        for (const auto& change : changes_) {
            apply_coordinates_(change.feature_id, change.new_coordinates);
        }
    }
    void revert() override {
        for (const auto& change : changes_) {
            apply_coordinates_(change.feature_id, change.old_coordinates);
        }
    }

private:
    std::vector<Change> changes_;
    std::function<void(const std::string&, const MapRing&)>
        apply_coordinates_;
};

// CompositeCommand — child commands as a single undo/redo unit.
class CompositeCommand : public EditCommand {
public:
    explicit CompositeCommand(std::vector<std::shared_ptr<EditCommand>> commands)
        : commands_(std::move(commands)) {}

    void apply() override {
        for (const auto& cmd : commands_) {
            cmd->apply();
        }
    }
    void revert() override {
        for (auto it = commands_.rbegin(); it != commands_.rend(); ++it) {
            (*it)->revert();
        }
    }

private:
    std::vector<std::shared_ptr<EditCommand>> commands_;
};

// EditCommandStack — linear undo/redo stack with a maximum depth.
class EditCommandStack {
public:
    explicit EditCommandStack(
        int max_depth = 50,
        std::function<void(const EditCommand&)> on_push = nullptr,
        std::function<void(const EditCommand&)> on_undo = nullptr,
        std::function<void(const EditCommand&)> on_redo = nullptr);

    int max_depth() const { return max_depth_; }
    // Whether the depth cap has dropped commands since the last clear —
    // undoing everything can then no longer return to the baseline, so a
    // dirty flag derived from can_undo() must stay dirty (#894-3).
    bool overflowed() const { return overflowed_; }

    void push(std::shared_ptr<EditCommand> command);
    bool undo();
    bool redo();
    bool can_undo() const { return !undo_.empty(); }
    bool can_redo() const { return !redo_.empty(); }
    std::size_t undo_depth() const { return undo_.size(); }
    std::size_t redo_depth() const { return redo_.size(); }
    void clear();

private:
    int max_depth_;
    std::deque<std::shared_ptr<EditCommand>> undo_;
    std::deque<std::shared_ptr<EditCommand>> redo_;
    bool overflowed_ = false;
    std::function<void(const EditCommand&)> on_push_;
    std::function<void(const EditCommand&)> on_undo_;
    std::function<void(const EditCommand&)> on_redo_;
};

}  // namespace pwb::ui_data_core
