// Stable command model + shared command history (CONV-27).
//
// Port of the *behavior* of paleo_workbench/mapping/composer/components.py
// `_CompositionCommand` + `CompositionEditSession` history machinery,
// factored so both the composition session and the map-document session
// share one stack. Decision D-27-02: pure C++ instead of QUndoStack — the
// data-kernel library is Qt-free, and the Python contract (redo cleared on
// every new command, revision bumped on every apply/undo/redo, closure-free
// revert) does not match QUndoStack macro semantics. Hosts that need a
// QUndoStack can adapt through this facade.
//
// Exception safety: execute() applies the command BEFORE it enters any
// history; a throwing apply leaves the stacks, the revision and the open
// group exactly as they were (mirrors Python `_execute`, where a raising
// apply skips the push). apply/revert of an already-executed command only
// shuffle captured values.
#pragma once

#include <functional>
#include <memory>
#include <string>
#include <vector>

namespace pwb::mapping_document {

// Which document-level revision counter a command invalidates (the
// composition session uses only `layout`; the map-document session splits
// data/style/layout per the unified dirty-state contract).
enum class RevisionKind { kData, kStyle, kLayout };

class DocumentCommand {
public:
    virtual ~DocumentCommand() = default;

    // Applied exactly once by CommandStack::execute before the command can
    // ever be redone.
    virtual void apply() = 0;
    virtual void revert() = 0;
    virtual const std::string& label() const = 0;
    virtual RevisionKind revision_kind() const = 0;

    // Stable id: 1-based, assigned by the stack at execution time in
    // execution order. Python has no ids (its commands are closures); this
    // is the C++ observability contract the oracle freezes.
    long long id() const { return id_; }
    void set_id(long long id) { id_ = id; }

private:
    long long id_ = 0;
};

// One reversible document mutation assembled from captured before/after
// values — the C++ shape of Python's `_CompositionCommand(label, apply,
// revert)` closures. The session builds these; nothing outside the sessions
// needs to.
class LambdaCommand final : public DocumentCommand {
public:
    using Fn = std::function<void()>;

    LambdaCommand(std::string label, RevisionKind kind, Fn apply_fn, Fn revert_fn)
        : label_(std::move(label)), kind_(kind), apply_fn_(std::move(apply_fn)),
          revert_fn_(std::move(revert_fn)) {}

    void apply() override { apply_fn_(); }
    void revert() override { revert_fn_(); }
    const std::string& label() const override { return label_; }
    RevisionKind revision_kind() const override { return kind_; }

private:
    std::string label_;
    RevisionKind kind_;
    Fn apply_fn_;
    Fn revert_fn_;
};

// A recorded group of commands undone/redone as one unit (the session-level
// shape of the gesture macros): apply = nested in order, revert = nested in
// reverse. `label` is the group label, not any nested label.
class GroupCommand final : public DocumentCommand {
public:
    GroupCommand(std::string label, RevisionKind kind,
                 std::vector<std::unique_ptr<DocumentCommand>> nested)
        : label_(std::move(label)), kind_(kind), nested_(std::move(nested)) {}

    void apply() override;
    void revert() override;
    const std::string& label() const override { return label_; }
    RevisionKind revision_kind() const override { return kind_; }
    std::size_t size() const { return nested_.size(); }
    // Exposed so the stack can notify the observer per nested command
    // (a mixed-kind group invalidates every kind it touches).
    const std::vector<std::unique_ptr<DocumentCommand>>& nested() const {
        return nested_;
    }

private:
    std::string label_;
    RevisionKind kind_;
    std::vector<std::unique_ptr<DocumentCommand>> nested_;
};

// Undo/redo history shared by both edit sessions. Single-threaded by
// contract: the owning session serializes all access (no internal locks).
//
// The observer must not throw; it runs inside history transitions where a
// throw would leave a half-applied state. A throwing observer is swallowed
// by the stack to protect the invariant.
//
// Grouping protocol (the session-level analog of the gesture plan/mark
// contract): begin_group → commands accumulate into the open group (the
// redo stack is invalidated by the FIRST nested command, matching the
// "new edit clears redo" rule) → end_group pushes one history entry, or
// rollback_group reverts the partial edits in reverse and discards the
// group. Rollback bumps the revision: the document changed and changed
// back, so stale-cache consumers must still be notified. clear_history
// with an open group discards the group record without reverting (the
// session-level analog of the gesture history reset on commit) — the
// partial edits stay in the document deliberately.
class CommandStack {
public:
    // Invoked after every successful apply (execute), undo and redo with the
    // command and whether it moved backwards. Sessions hook the per-kind
    // revision counters here.
    using Observer = std::function<void(const DocumentCommand&, bool undo)>;

    bool can_undo() const { return !undo_.empty(); }
    bool can_redo() const { return !redo_.empty(); }
    bool undo();
    bool redo();
    void clear_history();

    long long revision() const { return revision_; }

    void execute(std::unique_ptr<DocumentCommand> command);

    void begin_group(const std::string& label);
    bool group_open() const { return open_group_ != nullptr; }
    void end_group();
    void rollback_group();

    void set_observer(Observer observer) { observer_ = std::move(observer); }

    // Read-only history views (diagnostics / oracle).
    std::vector<const DocumentCommand*> undo_stack() const;
    std::vector<const DocumentCommand*> redo_stack() const;

private:
    void run(std::vector<std::unique_ptr<DocumentCommand>>& from,
             std::vector<std::unique_ptr<DocumentCommand>>& to, bool undo);
    void notify(const DocumentCommand& command, bool undo);

    struct Group {
        std::string label;
        std::vector<std::unique_ptr<DocumentCommand>> nested;
    };

    std::vector<std::unique_ptr<DocumentCommand>> undo_;
    std::vector<std::unique_ptr<DocumentCommand>> redo_;
    std::unique_ptr<Group> open_group_;
    long long revision_ = 0;
    long long next_id_ = 1;
    Observer observer_;
};

}  // namespace pwb::mapping_document
