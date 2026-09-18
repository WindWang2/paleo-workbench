#pragma once

// C++ port of paleo_workbench/workflow/interpretation/evidence.py (CONV-25).
// Typed evidence selectors ("factor:t1:ver_x") and the resolution contract
// that turns them into usable/unusable verdicts with provenance.
//
// Document seams (per ledgers/25-decisions.md):
//   - catalog version resolution  -> CatalogResolver callback
//   - document JSON view          -> Json object passed by the caller
//   - workspace membership        -> WorkspaceView callbacks
//   - constraint verdict          -> ConstraintResolver callback
//
// Qt-free, Python-free.

#include <pwb/domain/json.hpp>
#include <pwb/workflow_graph/graph.hpp>

#include <functional>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

namespace pwb::workflow_graph {

using pwb::domain::Json;

// Python ValueError — parse/format failures and repr-style messages.
struct EvidenceValueError : std::runtime_error {
    using std::runtime_error::runtime_error;
    const char* python_class() const { return "ValueError"; }
};

enum class EvidenceKind {
    Phase1Draft,
    Factor,
    Prediction,
    ConstraintGroup,
    CatalogVersion,
};

enum class EvidenceStatus {
    Resolved,
    Floating,
    Unpinned,
    Stale,
    Missing,
    Unknown,
};

const char* evidence_kind_value(EvidenceKind kind);
const char* evidence_status_value(EvidenceStatus status);
std::optional<EvidenceKind> evidence_kind_for_prefix(
    const std::string& prefix);

struct EvidenceSelector {
    EvidenceKind kind;
    std::string ref_id;
    std::string version_id;  // "" == None
    bool floating = false;

    // str(selector) — Python EvidenceSelector.__str__.
    std::string str() const;
};

EvidenceSelector parse_evidence_selector(const std::string& value);
std::string format_evidence_selector(
    EvidenceKind kind,
    const std::string& ref_id,
    const std::string& version_id = "",
    bool floating = false);
bool looks_like_version_id(const std::string& ref);

struct EvidenceResolution {
    EvidenceSelector selector;
    EvidenceStatus status = EvidenceStatus::Unknown;
    std::string pinned_version_id;  // "" == None
    std::string asset_id;           // "" == None
    std::string display;
    std::string detail;
    Json quality = Json::object();

    bool is_usable() const;
    Json to_dict() const;
};

// --- documented seams -------------------------------------------------------

// catalog.resolve_version(version_id) -> {asset_id, name} | None.
// Return std::nullopt for "not found". Throwing is also tolerated — the
// port wraps calls exactly where Python's _resolve_version swallows errors,
// but returning nullopt is the preferred contract.
struct VersionInfo {
    std::string asset_id;
    std::string name;
};
using CatalogResolver =
    std::function<std::optional<VersionInfo>(const std::string& version_id)>;

// workspace.membership(layer_id) -> {source_version_id} | None, and
// workspace.layers_with_role(role) -> [layer_id, ...] in workspace order.
struct WorkspaceMembership {
    std::string source_version_id;
};
struct WorkspaceView {
    std::function<std::optional<WorkspaceMembership>(const std::string&)>
        membership;
    std::function<std::vector<std::string>(const std::string&)>
        layers_with_role;
};

// resolve_constraint_ref(document, catalog, ref) -> {"status","detail"}.
// Throwing maps to status=unknown (mirroring the Python except-clause).
using ConstraintResolver =
    std::function<Json(const Json& document, const std::string& ref)>;

// resolve_evidence(document, value, catalog=..., workspace_state=...)
// `catalog` present-but-failing and absent are distinct states (D8).
EvidenceResolution resolve_evidence(
    const Json& document,
    const EvidenceSelector& selector,
    const std::optional<CatalogResolver>& catalog = std::nullopt,
    const WorkspaceView* workspace = nullptr,
    const ConstraintResolver& constraint_resolver = {});

// Parse-then-resolve convenience for raw selector strings / bare ids.
EvidenceResolution resolve_evidence(
    const Json& document,
    const std::string& value,
    const std::optional<CatalogResolver>& catalog = std::nullopt,
    const WorkspaceView* workspace = nullptr,
    const ConstraintResolver& constraint_resolver = {});

// available_evidence(document, workspace_state=...) — note that Python
// resolves drafts without a catalog, so pinned drafts land on UNKNOWN.
std::vector<EvidenceResolution> available_evidence(
    const Json& document,
    const WorkspaceView* workspace = nullptr,
    const ConstraintResolver& constraint_resolver = {});

}  // namespace pwb::workflow_graph
