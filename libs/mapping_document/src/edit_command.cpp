#include <pwb/mapping_document/edit_command.hpp>

#include <algorithm>
#include <stdexcept>
#include <utility>

namespace pwb::mapping_document {

void GroupCommand::apply() {
    for (const auto& command : nested_) command->apply();
}

void GroupCommand::revert() {
    for (auto it = nested_.rbegin(); it != nested_.rend(); ++it) (*it)->revert();
}

bool CommandStack::undo() {
    if (undo_.empty()) return false;
    run(undo_, redo_, true);
    return true;
}

bool CommandStack::redo() {
    if (redo_.empty()) return false;
    run(redo_, undo_, false);
    return true;
}

void CommandStack::run(std::vector<std::unique_ptr<DocumentCommand>>& from,
                       std::vector<std::unique_ptr<DocumentCommand>>& to,
                       bool undo_move) {
    std::unique_ptr<DocumentCommand> command = std::move(from.back());
    from.pop_back();
    if (undo_move) {
        command->revert();
    } else {
        command->apply();
    }
    to.push_back(std::move(command));
    ++revision_;
    if (observer_) {
        // A group touches every kind its nested commands touch: notify per
        // nested command in travel order (reverse for undo).
        if (auto* group = dynamic_cast<GroupCommand*>(to.back().get())) {
            if (undo_move) {
                for (auto it = group->nested().rbegin();
                     it != group->nested().rend(); ++it) {
                    notify(**it, true);
                }
            } else {
                for (const auto& nested_command : group->nested()) {
                    notify(*nested_command, false);
                }
            }
        } else {
            notify(*to.back(), undo_move);
        }
    }
}

void CommandStack::notify(const DocumentCommand& command, bool undo) {
    try {
        observer_(command, undo);
    } catch (...) {
        // Observer failures must never corrupt the history transition
        // (see the contract in edit_command.hpp).
    }
}

void CommandStack::clear_history() {
    undo_.clear();
    redo_.clear();
    open_group_.reset();
}

void CommandStack::execute(std::unique_ptr<DocumentCommand> command) {
    if (!command) return;
    // Python `_execute`: apply first; a raising apply leaves stacks and
    // revision untouched and the command never enters history.
    command->apply();
    command->set_id(next_id_++);
    redo_.clear();
    revision_++;
    if (observer_) observer_(*command, false);
    if (open_group_) {
        open_group_->nested.push_back(std::move(command));
        return;
    }
    undo_.push_back(std::move(command));
}

void CommandStack::begin_group(const std::string& label) {
    if (open_group_) {
        throw std::logic_error("a command group is already open");
    }
    open_group_ = std::make_unique<Group>();
    open_group_->label = label;
}

void CommandStack::end_group() {
    if (!open_group_) {
        throw std::logic_error("no command group is open");
    }
    if (open_group_->nested.empty()) {
        open_group_.reset();  // nothing recorded: no history entry, no revision bump
        return;
    }
    auto group = std::make_unique<GroupCommand>(
        open_group_->label, RevisionKind::kLayout, std::move(open_group_->nested));
    group->set_id(next_id_++);
    undo_.push_back(std::move(group));
    open_group_.reset();
    // Nested commands already bumped the revision and invalidated redo; the
    // group entry itself adds nothing further.
}

void CommandStack::rollback_group() {
    if (!open_group_) {
        throw std::logic_error("no command group is open");
    }
    auto& nested = open_group_->nested;
    for (auto it = nested.rbegin(); it != nested.rend(); ++it) {
        (*it)->revert();
        notify(**it, true);
    }
    nested.clear();
    open_group_.reset();
    // The document changed and changed back: consumers must refresh.
    ++revision_;
}

std::vector<const DocumentCommand*> CommandStack::undo_stack() const {
    std::vector<const DocumentCommand*> out;
    out.reserve(undo_.size());
    for (const auto& command : undo_) out.push_back(command.get());
    return out;
}

std::vector<const DocumentCommand*> CommandStack::redo_stack() const {
    std::vector<const DocumentCommand*> out;
    out.reserve(redo_.size());
    for (const auto& command : redo_) out.push_back(command.get());
    return out;
}

}  // namespace pwb::mapping_document
