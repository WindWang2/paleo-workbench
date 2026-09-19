#pragma once
// CONV-32 — CompilationInputSet (workflow/interpretation/compilation.py
// port, task I7): the pinned evidence input set for Phase 3 scientific
// runs (V9 ADR-7, goal §14). Phase 3 NEVER runs on "whatever is currently
// visible": the input set lists evidence selectors explicitly and freeze
// pins their versions. Persisted shape is document["compilation_input_sets"]
// (plain dict carrier, schema owned by this module — same split as the V5
// §45 mapping_workspace); the legacy workspace compilation_input_set dict
// stays as a compatibility view (legacy_view mirror).
//
// State machine: draft (entries add/remove) → frozen (versions pinned,
// inputs cannot drift). Freeze refuses any entry it cannot pin
// (missing/unregistered-version/unknown) — never enter a scientific run
// with a dark hole. Refusals roll back atomically (selector rewrites AND
// pins restore from the pre-freeze snapshot) and raise a ValueError-parity
// exception listing every refused entry.
//
// Seam mapping (Python duck-typed collaborators → ResolveContext):
//   Python `catalog=` (one object) splits into three C++ seams:
//     - catalog.resolve_version      → CatalogResolver (evidence version
//                                       lookups; nullopt == Python None)
//     - resolve_constraint_ref       → ConstraintResolver (constraint
//                                       freshness verdicts; typically
//                                       workflow_runtime::resolve_
//                                       constraint_ref over a repository)
//     - freeze FLOATING pin          → CatalogRepository* (current_
//                                       constraint_version; nullptr ==
//                                       Python catalog=None)
//   Python `workspace_state=`        → const WorkspaceView* (draft
//                                       membership; nullptr == None)
//   Python document                  → Json object view (factor_map_tasks
//                                       / prediction_tasks / user_vector_
//                                       layers / constraint_layers /
//                                       compilation_input_sets).
//
// Key order is Python dict insertion order — reproduced exactly via
// pwb::domain::Json (nlohmann::ordered_json).

#include <pwb/domain/ids.hpp>
#include <pwb/domain/json.hpp>
#include <pwb/workflow_graph/evidence.hpp>
#include <pwb/workflow_runtime/catalog_seam.hpp>

#include <functional>
#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace pwb::workflow_interpretation {

using domain::Json;
using workflow_graph::EvidenceResolution;

// Python ValueError — freeze refusals (double freeze / unpinnable
// entries). Message text is byte-identical to the Python raise.
struct CompilationValueError : std::runtime_error {
    using std::runtime_error::runtime_error;
    const char* python_class() const { return "ValueError"; }
};

// The seam bundle handed to create/validate/freeze. Python passes one
// catalog object; the C++ port splits it into the three access points
// those flows need (see header comment). Defaults reproduce
// catalog=None / workspace_state=None.
struct ResolveContext {
    // catalog.resolve_version(version_id) → {asset_id, name} | None.
    // nullopt == Python catalog=None (absent service); an engaged but
    // empty resolver is a PRESENT catalog that cannot resolve (MISSING,
    // not UNKNOWN) — the D8 distinction.
    std::optional<workflow_graph::CatalogResolver> catalog;
    // workspace_state membership/layers (nullptr == None).
    const workflow_graph::WorkspaceView* workspace = nullptr;
    // resolve_constraint_ref(document, ref) → {"status","detail"}.
    // Empty function is never called by the flows below unless constraint
    // selectors are resolved — install one (typically wrapping
    // workflow_runtime::resolve_constraint_ref) when they are.
    workflow_graph::ConstraintResolver constraint_resolver = {};
    // Constraint lifecycle repository — the freeze-time FLOATING pin seam
    // (Python's current_constraint_version(catalog, group_id)).
    // nullptr == Python catalog=None → pin_floating_constraints refuses.
    workflow_runtime::CatalogRepository* repository = nullptr;

    // Convenience factory bundling the repository-backed defaults:
    // catalog over repository->resolve_version, constraint verdicts via
    // workflow_runtime::resolve_constraint_ref(document, repository, ref),
    // pin seam on the repository. repository == nullptr reproduces
    // Python's catalog=None exactly (absent catalog + null repo).
    static ResolveContext for_repository(
        workflow_runtime::CatalogRepository* repository);
};

// One evidence entry of an input set (selector + the honest resolution
// snapshot recorded at add time).
struct CompilationInputSetEntry {
    std::string selector;
    std::string label;
    std::string evidence_kind;
    // Version pinned at freeze (RESOLVED/STALE entries); "" before freeze.
    std::string pinned_version_id;
    std::string resolved_asset_id;
    std::string added_at;
    std::string added_by;
    std::string note;
    // Resolution status at add time (evidence.EvidenceStatus value
    // vocabulary; a snapshot — never updated afterwards).
    std::string status_at_add;

    // Keys exactly: selector, label, evidence_kind, pinned_version_id,
    // resolved_asset_id, added_at, added_by, note, status_at_add.
    [[nodiscard]] Json to_dict() const;
    // str(data.get(key) or "") coercions for every field.
    static CompilationInputSetEntry from_dict(const Json& data);
};

// One compilation input set (goal §14: base interpretation + factor
// versions + constraint versions + evidence versions + configuration).
struct CompilationInputSet {
    std::string id;
    std::string name;
    std::vector<CompilationInputSetEntry> entries;
    std::string created_at;
    std::string created_by;
    // Algorithm recommendation record (method + rationale; manual picks
    // live in manual_overrides). Json objects, key order preserved.
    Json recommendation = Json::object();
    Json manual_overrides = Json::object();
    Json configuration = Json::object();
    bool frozen = false;
    std::string frozen_at;
    int schema_version = 1;

    // -- views ------------------------------------------------------------
    // First exact-selector match, else nullptr.
    [[nodiscard]] const CompilationInputSetEntry* entry_for_selector(
        const std::string& selector) const;
    [[nodiscard]] std::vector<std::string> selectors() const;
    // Compatibility view: {label or selector → selector} in entry
    // insertion order. (Python returns a dict — duplicate labels would
    // collapse last-wins; the C++ pair vector keeps every entry. No
    // Python observable depends on that collapse.)
    [[nodiscard]] std::vector<std::pair<std::string, std::string>>
    legacy_view() const;

    // -- serialization ----------------------------------------------------
    // Keys exactly: id, name, entries[], created_at, created_by,
    // recommendation, manual_overrides, configuration, frozen, frozen_at,
    // schema_version.
    [[nodiscard]] Json to_dict() const;
    static CompilationInputSet from_dict(const Json& data);
};

// The honest result of one input-set validation.
struct CompilationValidation {
    std::string input_set_id;
    std::vector<EvidenceResolution> resolutions;
    // ready = all usable (RESOLVED/FLOATING/STALE); degraded = any
    // UNPINNED; blocked = any MISSING/UNKNOWN.
    std::string verdict;  // "ready" | "degraded" | "blocked"
    std::string detail;

    // Raw selectors of the resolutions starting with "factor:".
    [[nodiscard]] std::vector<std::string> factor_selectors() const;
    // Keys exactly: input_set_id, verdict, detail,
    // entries[resolutions' to_dict…].
    [[nodiscard]] Json to_dict() const;
};

// uuid4().hex[:12] producer for set ids ("ciset_" prefix is added here).
using IdGen = std::function<std::string()>;

// Create an input set from evidence selectors (the honest resolution
// snapshot rides on every entry — never guessed). Malformed selectors
// propagate workflow_graph::EvidenceValueError (Python ValueError).
// id = set_id (when non-empty) or "ciset_" + idgen() / domain::make_id.
// Default name: 综合编图输入集（{N} 项证据）(fullwidth parens).
[[nodiscard]] CompilationInputSet create_input_set(
    const Json& document,
    const std::vector<std::string>& selectors,
    const ResolveContext& ctx = {},
    const std::string& name = "",
    const std::string& created_by = "",
    const std::string& set_id = "",
    const std::string& now = "",
    const IdGen& idgen = {});

// Resolve every entry (honest verdict: ready/degraded/blocked). Entries
// with a pinned_version_id validate against the version-rewritten
// selector (the in-selector version IS the pin).
[[nodiscard]] CompilationValidation validate_input_set(
    const CompilationInputSet& input_set, const Json& document,
    const ResolveContext& ctx = {});

// Python _selector_with_version — write the pinned version back into the
// selector string (factor/prediction/constraint_group vocabulary).
// Constraint pins rewrite to the group-resolved EXPLICIT selector (freeze
// already expanded floating entries into per-group pins — never produces
// an unparsable constraints::<ver> shape). All other kinds: selector
// unchanged.
[[nodiscard]] std::string selector_with_version(
    const std::string& selector, const std::string& version_id);

// Freeze: pin every resolvable entry's version; anything unpinnable →
// CompilationValueError (python_class() == "ValueError"). Pins:
//   RESOLVED/STALE → resolution.pinned_version_id + selector rewritten to
//     the explicit versioned form (applied only when it differs AND
//     parses);
//   FLOATING (constraints:current) → only when EXACTLY ONE constraint
//     group has a commit: pin that group's version and rewrite the
//     selector to explicit constraints:<group>:<ver>; multiple committed
//     groups → refusal (pinning one leaves dark holes for the rest);
//   UNPINNED/MISSING/UNKNOWN → refusal with status + detail.
// Refusals restore EVERY entry from the pre-freeze snapshot (selector AND
// pin — atomic) before raising. Success: frozen = true, frozen_at = now.
CompilationInputSet& freeze_input_set(CompilationInputSet& input_set,
                                      const Json& document,
                                      const ResolveContext& ctx = {},
                                      const std::string& now = "");

// Python _pin_floating_constraints — constraints:current →
// (group_id, version_id). Only when EXACTLY ONE constraint group has a
// committed version; zero or multiple groups → nullopt (multiple →
// pinning any one leaves dark holes). repository == nullptr → nullopt;
// any repository error → nullopt (query failure = unpinnable).
[[nodiscard]] std::optional<std::pair<std::string, std::string>>
pin_floating_constraints(
    const Json& document,
    workflow_runtime::CatalogRepository* repository);

// -- persistence helpers ----------------------------------------------------

// Write into document["compilation_input_sets"] (additive dict carrier).
// active=true marks the payload active and deactivates every existing
// record; an id match replaces in place, otherwise the payload appends.
void persist_input_set(Json& document, const CompilationInputSet& input_set,
                       bool active = true);

// The document's active input set (nullopt when none; legacy projects
// only carry the legacy dict view).
[[nodiscard]] std::optional<CompilationInputSet> active_input_set(
    const Json& document);

[[nodiscard]] std::vector<CompilationInputSet> input_sets_for_document(
    const Json& document);

// The SINGLE consumption adapter for the compilation input set (R2-F1):
// the active structured set's legacy_view() when non-empty; else the
// workspace legacy compilation_input_set dict ({str(k): str(v)}); else
// empty. fusion/staleness/validation all read the evidence set through
// this function — the two carriers never act independently.
// (Python returns dict[str, str]; the C++ pair vector preserves the
// Python 3.7+ dict insertion order of both carriers.)
[[nodiscard]] std::vector<std::pair<std::string, std::string>> evidence_view(
    const Json& document, const Json* workspace_state = nullptr);

// First-structuring migration from the legacy view (R2-F9: the migration
// belongs to the domain layer, not the UI). Builds a shell set (name
// 综合编图输入集), one entry per parseable legacy (label → selector) with
// evidence_kind + added_by recorded (status_at_add stays ""), persists it
// and returns it. Unparseable selectors are skipped; ANY failure →
// nullopt (migration must never block the legacy view path).
[[nodiscard]] std::optional<CompilationInputSet>
create_input_set_shell_from_legacy(Json& document,
                                   const Json& workspace_state,
                                   const std::string& created_by = "",
                                   const IdGen& idgen = {});

}  // namespace pwb::workflow_interpretation
