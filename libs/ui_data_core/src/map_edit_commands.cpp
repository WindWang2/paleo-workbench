#include "pwb/ui_data_core/map_edit_commands.hpp"

#include "pwb/ui_data_core/json_util.hpp"

#include <stdexcept>
#include <utility>

namespace pwb::ui_data_core {

EditCommandStack::EditCommandStack(
    int max_depth, std::function<void(const EditCommand&)> on_push,
    std::function<void(const EditCommand&)> on_undo,
    std::function<void(const EditCommand&)> on_redo)
    : max_depth_(max_depth),
      on_push_(std::move(on_push)),
      on_undo_(std::move(on_undo)),
      on_redo_(std::move(on_redo)) {
    if (max_depth < 1) {
        throw std::invalid_argument("max_depth must be >= 1");
    }
}

void EditCommandStack::push(std::shared_ptr<EditCommand> command) {
    command->apply();
    undo_.push_back(std::move(command));
    if (static_cast<int>(undo_.size()) > max_depth_) {
        undo_.pop_front();
        overflowed_ = true;
    }
    redo_.clear();
    if (on_push_) {
        on_push_(*undo_.back());
    }
}

bool EditCommandStack::undo() {
    if (undo_.empty()) {
        return false;
    }
    auto command = std::move(undo_.back());
    undo_.pop_back();
    command->revert();
    redo_.push_back(command);
    if (on_undo_) {
        on_undo_(*command);
    }
    return true;
}

bool EditCommandStack::redo() {
    if (redo_.empty()) {
        return false;
    }
    auto command = std::move(redo_.back());
    redo_.pop_back();
    command->apply();
    undo_.push_back(command);
    if (on_redo_) {
        on_redo_(*command);
    }
    return true;
}

void EditCommandStack::clear() {
    undo_.clear();
    redo_.clear();
    overflowed_ = false;
}

}  // namespace pwb::ui_data_core
