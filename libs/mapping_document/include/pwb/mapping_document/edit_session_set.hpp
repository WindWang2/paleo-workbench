// Edit session layer set (CONV-27d).
//
// Port of paleo_workbench/mapping/edit_session_set.py — the set of layers the
// current edit session touches: entering edit = {active layer}; when a
// gesture spills into neighbouring layers (vertex "all layers" mode,
// topology point-spread targets) they join through a gate re-check — accepted
// automatically, rejected layers stay out with a status-bar reason
// (decision #1283).
//
// The whole set forms the mirror REPUBLISH SUPPRESSION WINDOW: data-delta
// republishes for in-set layers are short-circuited while editing happens on
// the mirror layers themselves; out-of-set layers keep publishing (no-op
// style-drift self-heal keeps working there). Data ledgers freeze during the
// session; style validation keeps running; after commit the ledger alignment
// jumps straight to the new baseline.
//
// The CRS is frozen when the session opens (decision #1285: CRS cannot change
// during an edit session); field-schema changes on in-set layers are rejected
// (save/rollback first); out-of-set layers are unrestricted.
//
// Pure logic: no Qt. Single-threaded by contract.
//
// Lifetime contract (replaces Python's weakref binding, D-27d-02): the
// publisher stack is bound as a non-owning identity pointer. The caller must
// keep the stack object alive while the session is open; close() / a discard
// that empties the set unbind. The conservative window query never
// short-circuits for an unbound or different stack — a session without a
// known edit target suppresses nothing.
#pragma once

#include <functional>
#include <string>
#include <utility>
#include <vector>

namespace pwb::mapping_document {

// The verdict of one neighbour-layer join re-check (reason feeds the status
// bar on rejection).
struct JoinDecision {
    std::string layer_id;
    bool accepted = false;
    std::string reason;

    bool operator==(const JoinDecision&) const = default;
};

class EditSessionSet {
public:
    // Host gate for join re-checks: (allowed, reason) per layer id.
    // Absent gate = everything passes (pure geometry spillover).
    using Gate = std::function<std::pair<bool, std::string>(const std::string&)>;

    // Opens the session: set = {active layer}, freezes the session CRS and
    // binds the publish target stack (identity only).
    void open(const std::string& layer_id, const std::string& crs = "",
              const void* stack = nullptr);

    // Neighbour-layer join re-check (call when a gesture spills over):
    // gate-passing layers join the set automatically with the frozen CRS.
    std::vector<JoinDecision> request_join(const std::vector<std::string>& layer_ids,
                                           const Gate& gate = nullptr);

    // Closes the session (after commit/rollback): resets the set and frozen
    // state, returns the layers that were in it (insertion order).
    std::vector<std::string> close();

    // Removes one layer (QGIS per-layer rollback semantics); an emptied set
    // closes the session (CRS unbound, stack unbound).
    void discard(const std::string& layer_id);

    bool contains(const std::string& layer_id) const;

    // Ordered set (insertion order; first element = the active layer).
    const std::vector<std::string>& layer_ids() const { return layers_; }

    bool is_open() const { return !layers_.empty(); }

    // The CRS frozen at session open (immutable during the session).
    const std::string& frozen_crs() const { return frozen_crs_; }

    // Suppression-window query: returns the set when the session is bound to
    // exactly this publish stack, else empty. An unbound session never
    // short-circuits any publish (conservative: no edit target = no window).
    std::vector<std::string> active_layer_ids(const void* stack) const;

    // Change mutexes: CRS is frozen while a session is open; field-schema
    // changes are rejected for in-set layers. Python parity for both
    // messages (exact strings, including the full-width punctuation).
    std::pair<bool, std::string> allows_crs_change() const;
    std::pair<bool, std::string> allows_schema_change(
        const std::string& layer_id) const;

private:
    std::vector<std::string> layers_;  // insertion order, first = active
    std::string frozen_crs_;
    const void* stack_ref_ = nullptr;  // non-owning identity (D-27d-02)
};

}  // namespace pwb::mapping_document
