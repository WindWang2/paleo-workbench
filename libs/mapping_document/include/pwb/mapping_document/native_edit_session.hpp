// Native edit session controller (CONV-27d).
//
// Port of paleo_workbench/mapping/native_edit_session.py — the HOST side of
// the native (QGIS-mirror) editing lifecycle, one instance per workbench.
// Once edit authority migrates to QGIS, the host is the SYNCHRONIZER: mirror
// layers enter the native edit buffer through the bridge's startEditing();
// vertex tools edit the mirror directly; the host truth (the committed vector
// layer state) only consumes the committed* delta after a successful commit
// (apply_committed_delta). During the session the host truth is untouched —
// a crash with uncommitted edits loses them (volatile session, no sidecar),
// by design.
//
// The three-gate structure:
//   * before entering: open()'s gate (role/maturity/group-lock — the host's
//     single gate point) + the CRS front gate (session set); a rejection
//     never calls startEditing();
//   * during editing: no defense (the native buffer is free);
//   * before commit: commit_all() judges the whole set (gate re-check +
//     zero topology errors — geometry is READ BACK from the mirror, the edit
//     buffer is the fact); any rejection keeps the whole set in session.
//
// Save = whole-set all-or-nothing: every layer commits → every delta is
// written back → ledger alignment per layer (host's on_committed) → the
// suppression window closes.
//
// Pure logic: no Qt. The bridge is the abstract NativeEditBridgeStack seam
// (the C++ shape of Python's duck-typed stack; D-27d-03); the committed-delta
// consumer is the ICommittedDeltaSink seam (D-27d-04 — the minimal faithful
// projection of the Python controller's layer usage, so hosts adapt their own
// vector-layer type with a one-line forward). Single-threaded by contract.
#pragma once

#include <pwb/domain/json.hpp>
#include <pwb/mapping_document/document_io.hpp>
#include <pwb/mapping_document/edit_gesture_manager.hpp>
#include <pwb/mapping_document/edit_session_set.hpp>

#include <cstdint>
#include <functional>
#include <map>
#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace pwb::mapping_document {

using Json = pwb::domain::Json;

// ---------------------------------------------------------------------------
// Bridge seam — the duck-typed QGIS bridge stack surface (D-27d-03)
// ---------------------------------------------------------------------------

// Error-string convention: "" = success, anything else is a bridge error
// message (surfaced verbatim to the caller, like the Python `str(err or "")`
// plumbing). Capability surfaces that an OLD bridge lacks are virtual with
// "unsupported" defaults so the honest-degradation paths trigger naturally.
class NativeEditBridgeStack {
public:
    virtual ~NativeEditBridgeStack() = default;

    // Legacy-bridge adapter hook: an adapter over a pre-M1 bridge (no mirror
    // edit sessions at all) returns false so open() refuses with the same
    // honest message Python produced for a duck-typed stack missing the
    // native edit face.
    virtual bool supports_native_editing() const { return true; }

    // -- M1 native edit face (the four core operations) ---------------------
    virtual std::string start_mirror_layer_editing(const std::string& doc_id) = 0;
    virtual std::string commit_mirror_layer(const std::string& doc_id) = 0;
    virtual std::string roll_back_mirror_layer(const std::string& doc_id) = 0;
    // Returns {"exists": bool, "features": [...]}. `limit` 0 = no limit
    // (the snapshot-capture call passes 0, mirroring the Python signature).
    virtual Json mirror_features_json(const std::string& doc_id, int limit = 0) = 0;

    // -- capability surfaces (absent on old bridges → default = unsupported)

    // set_committed_callback(canvas_address, fn): the bridge invokes the
    // callback synchronously during commit with (doc_id, delta_json). The
    // default no-op mirrors "set_committed_callback unavailable".
    virtual void set_committed_callback(
        std::uintptr_t /*canvas_address*/,
        const std::function<void(const std::string&, const Json&)>& /*callback*/) {}

    // Mirror attribute-write op (edit-period attribute edits / facies swap).
    virtual bool has_attribute_write() const { return false; }
    virtual std::string set_mirror_feature_attributes(
        const std::string& /*doc_id*/, const Json& /*feature_ids*/,
        const Json& /*values*/) {
        return "unsupported";
    }

    // Dirty probe into the native buffer. nullopt = no query surface
    // (unknown — never guessed).
    virtual std::optional<bool> mirror_layer_dirty(const std::string& /*doc_id*/) {
        return std::nullopt;
    }

    // Restore-one-macro snapshot surface (compensation path). The snapshot
    // payload is whatever mirror_features_json(id, 0) returned.
    virtual bool has_restore_snapshot() const { return false; }
    virtual std::string restore_mirror_snapshot(const std::string& /*doc_id*/,
                                                const Json& /*snapshot*/) {
        return "unsupported";
    }

    // Gesture macros on the mirror undo stack (bridge begin/endEditCommand).
    virtual std::string undo_mirror_edit(const std::string& /*doc_id*/) {
        return "unsupported";
    }
    virtual std::string redo_mirror_edit(const std::string& /*doc_id*/) {
        return "unsupported";
    }
};

// ---------------------------------------------------------------------------
// Committed-delta sink — the host truth's write-back seam (D-27d-04)
// ---------------------------------------------------------------------------

// The minimal faithful projection of the Python controller's layer usage:
// identity + display name + CRS + apply_committed_delta. Hosts adapt their
// vector-layer type (ui_composite::VectorLayer already has the delta method).
class ICommittedDeltaSink {
public:
    virtual ~ICommittedDeltaSink() = default;
    virtual const std::string& id() const = 0;
    // Display name used in rejection messages. An EMPTY name is treated as
    // absent — the controller falls back to the layer id (the C++ contract
    // for Python `getattr(layer, 'name', layer_id)`; hosts may simply return
    // the id when they have no display name).
    virtual const std::string& name() const = 0;
    virtual const std::string& crs() const = 0;
    // Absorbs one native commit delta (irreversible — the mirror already
    // committed; same semantics as the host commit path).
    virtual void apply_committed_delta(const Json& delta,
                                       const std::string& session_id,
                                       const std::string& source_tool,
                                       const Json& gestures) = 0;
};

// ---------------------------------------------------------------------------
// Commit gates
// ---------------------------------------------------------------------------

// Role/maturity/group-lock host gate (single gate point).
using EditGate = std::function<std::pair<bool, std::string>(const std::string&)>;

// Topology commit gate (M4): the bridge-checker path takes priority when the
// checker can drive the stack's run_geometry_checks; otherwise the controller
// falls back to per-layer validate_records over the read-back features.
class ICommitTopologyGate {
public:
    virtual ~ICommitTopologyGate() = default;
    virtual bool enabled() const = 0;
    struct RunResult {
        bool available = false;  // false = fall back to validate_records
        std::vector<Json> issues;
    };
    // Issues are objects carrying at least {layer_id, feature_id, message}.
    virtual RunResult run_for_commit(NativeEditBridgeStack& stack,
                                     std::uintptr_t canvas,
                                     const std::vector<std::string>& layer_ids) {
        (void)stack;
        (void)canvas;
        (void)layer_ids;
        return {};
    }
    // Fallback validator over normalized read-back records.
    virtual std::vector<Json> validate_records(
        const std::string& layer_id, const std::vector<Json>& records) = 0;
    // Record the per-layer issue count on the layer model (host display).
    virtual void record_validation(const std::string& layer_id,
                                   std::size_t issue_count) = 0;
};

// Geological invariant gate (geotopo Ticket 4): records → violation objects
// {layer_id, code, message, severity}; "error" blocks the whole set,
// "warning" passes (the host reports them separately).
using GeologyGate = std::function<std::vector<Json>(
    const std::map<std::string, std::vector<Json>>& records)>;

using OnCommitted = std::function<void(const ICommittedDeltaSink&)>;

// ---------------------------------------------------------------------------
// Controller
// ---------------------------------------------------------------------------

class NativeEditSessionController {
public:
    // Owns a private session set (the Python process-singleton shape; the
    // "one edit session per workbench at a time" constraint lives in the
    // owner's scope).
    NativeEditSessionController();
    // Shares an externally owned set (multi-workbench hosts / tests).
    explicit NativeEditSessionController(EditSessionSet& session_set);
    // Id generator for the compensation gesture id (D-27d-08; defaults to a
    // deterministic counter).
    explicit NativeEditSessionController(FeatureIdGenerator ids);

    NativeEditSessionController(const NativeEditSessionController&) = delete;
    NativeEditSessionController& operator=(const NativeEditSessionController&) = delete;

    // -- capability & state -------------------------------------------------

    // bridge_supports(stack) parity: delegates to the stack's
    // supports_native_editing() (legacy adapters return false) so call sites
    // read the same as Python and tests can assert the probe contract.
    static bool bridge_supports(const NativeEditBridgeStack& stack);

    bool is_open(const std::string& layer_id) const;
    std::vector<std::string> session_layer_ids() const;
    NativeEditBridgeStack* stack_for(const std::string& layer_id);

    EditSessionSet& session_set() { return *session_set_ptr_; }
    EditGestureManager& gestures() { return gestures_; }

    // -- lifecycle ----------------------------------------------------------

    // Enter a native edit session. gate(layer_id) → (allowed, reason): a
    // rejection never starts editing. Join semantics: with a session set
    // already open, a gate-passing layer with a matching CRS JOINS the set
    // (growth, never replacement); a CRS mismatch leaves that layer out with
    // an honest message (same-session layers must share the CRS).
    //
    // Lifetime contract (D-27d-09): the controller stores non-owning
    // stack/layer pointers for the whole session — the caller must keep both
    // objects alive until the layer's session leaves the controller
    // (commit_all / rollback). The bridge callback registered on the stack
    // captures `this`; destroy the controller BEFORE the stack (or stop the
    // bridge) — Python's stack held a strong reference to the bound method,
    // so this ordering is the C++ stand-in for that guarantee.
    std::pair<bool, std::string> open(NativeEditBridgeStack& stack,
                                      ICommittedDeltaSink& layer,
                                      const EditGate& gate,
                                      std::uintptr_t canvas_address = 0);

    // Roll back to the session-open snapshot baseline (volatile session:
    // rollBack resets the mirror content; the host ledger stays frozen at
    // the baseline → no republish needed).
    std::pair<bool, std::string> rollback(const std::string& layer_id);

    // -- committed deltas (write-back channel) ------------------------------

    // Bridge committed-callback collection point (triggered synchronously
    // during commit). delta_json may arrive as an object or a JSON string;
    // unparsable input is dropped with a warning diagnostic (never throws).
    void handle_committed(const std::string& doc_id, const Json& delta_json);

    // -- read-back (the edit buffer is the fact) ----------------------------

    // Current mirror features including uncommitted buffer edits — the
    // topology gate's verification input. Normalized to
    // [{feature_id, geometry, attributes}]; parse failures / missing mirror
    // → empty vector.
    std::vector<Json> readback_features(NativeEditBridgeStack& stack,
                                        const std::string& layer_id) const;

    // -- attribute writes (the only native edit-period attribute channel) ---

    static bool supports_attribute_write(const NativeEditBridgeStack& stack);

    // Edits attributes in the mirror buffer (one undoable macro; lands with
    // the commit). The host must NOT open a parallel session while the
    // native buffer owns edit authority — facies swaps and the like route
    // here, sharing the vertex-edit undo/commit semantics.
    std::pair<bool, std::string> set_feature_attributes(
        const std::string& layer_id, const std::vector<std::string>& feature_ids,
        const Json& attributes);

    // Uncommitted native-buffer changes; nullopt = the bridge has no query
    // surface or the probe failed (unknown, not guessed). Never throws.
    std::optional<bool> pending_changes(const std::string& layer_id);

    // -- save: whole-set all-or-nothing --------------------------------------

    // Commits the session set: gates first, then per-layer commit + delta
    // write-back + ledger alignment (on_committed). ANY failure keeps the
    // whole set in session: the failed layer X keeps its session (the QGIS
    // commit failed with the buffer intact — retry after the fix); layers
    // after X roll back; already-committed layers are compensated from the
    // pre-commit snapshots (reopen + restore as one undoable macro — the
    // Ctrl+Z escape hatch, D9).
    std::pair<bool, std::string> commit_all(const EditGate& gate,
                                            ICommitTopologyGate* topology,
                                            const GeologyGate& geology = nullptr,
                                            const OnCommitted& on_committed = nullptr);

    // Compensation-recovery events (read-only; diagnostics/audit).
    const std::vector<std::string>& compensations() const { return compensations_; }

    // -- gestures (host plan for the bridge-side undo/redo macros) ----------

    // Whole-gesture undo: per-layer undo in REVERSE plan order (in-layer =
    // the QGIS undo-stack macro). A partial failure does NOT mark the
    // gesture done (half-way failure semantics — the next attempt retries
    // the same plan).
    bool undo_gesture();
    bool redo_gesture();

    // Diagnostics channel (warnings, e.g. unparsable commit deltas).
    std::vector<std::string> warnings() const { return warnings_; }

private:
    struct Session {
        NativeEditBridgeStack* stack = nullptr;
        ICommittedDeltaSink* layer = nullptr;
        std::uintptr_t canvas = 0;
    };

    std::vector<Json> topology_gate_issues(ICommitTopologyGate& topology);

    // Returns the ids successfully compensated.
    std::vector<std::string> compensate_committed(
        const std::vector<std::pair<std::string, Session>>& committed,
        const std::map<std::string, Json>& snapshots);

    EditSessionSet* session_set_ptr_ = nullptr;
    EditSessionSet owned_session_set_;
    EditGestureManager gestures_;
    // Session registry keyed by layer id. Iteration MUST follow the session
    // JOIN order (the Python dict's insertion order: the active layer is the
    // first session; commits, gate re-checks, topology fallback and
    // session_layer_ids all consume that order), so `session_order_` carries
    // the sequence and the map is lookup-only.
    std::map<std::string, Session> sessions_;       // layer_id → session
    std::vector<std::string> session_order_;
    std::map<std::string, Json> pending_commits_;   // doc_id → committed delta
    std::vector<std::string> compensations_;
    FeatureIdGenerator ids_;
    std::vector<std::string> warnings_;
};

}  // namespace pwb::mapping_document
