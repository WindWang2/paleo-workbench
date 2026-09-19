#pragma once
// CONV-32 — constraint products (workflow/interpretation/constraint_product.py
// port): the read-only domain projection of one constraint group. Identity =
// ConstraintLayers.id (same id the constraint_versions commit/version chain
// uses); payload authority = the live document; maturity/staleness come from
// the catalog seam. This module also owns the two convergences the Python
// side enforces:
//
//   * dual ConstraintKind convergence — the GEOLOGICAL 10-state vocabulary
//     (mapping_workspace/layer_roles.ConstraintKind) is canonical and maps
//     uniquely through CONSTRAINT_INTERPOLATION_ROLE onto the ENGINE 5-state
//     vocabulary (constraint_capabilities.ConstraintKind); the same-named
//     enums are never passed through raw (baseline P1-4);
//   * CRS discipline — declared-and-different CRSs raise (never silently
//     mixed coordinates); undeclared sides get honest notes, never guesses.
//
// Seam mapping (Python duck-typed objects -> Json views of the document):
//   document.constraint_layers -> {"constraint_layers": [group, …]}
//   group                     -> {"id", "name", "target_horizon", "crs",
//                                "lines": [line, …]}
//   line                      -> {"id", "name", "role", "active",
//                                "target_horizon", "coordinates",
//                                "properties"?: dict}
//   catalog                   -> workflow_runtime::CatalogRepository
//                                (nullptr = Python catalog=None: no version
//                                chain, maturity stays draft).
#include <pwb/domain/json.hpp>

#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

namespace pwb::workflow_runtime {
class CatalogRepository;
}  // namespace pwb::workflow_runtime

namespace pwb::workflow_interpretation {

using domain::Json;

// ---- geo vocabulary (layer_roles.ConstraintKind, 10 states) --------------

// strip().lower() in the vocabulary -> the canonical kind value, else
// nullopt (unknown is never guessed).
[[nodiscard]] std::optional<std::string> constraint_kind_from_value(
    const std::string& text);

// CONSTRAINT_INTERPOLATION_ROLE: kind -> "direction" | "boundary" | "break".
[[nodiscard]] std::optional<std::string> interpolation_role_for_kind(
    const std::string& kind);

// Geological constraint kind -> engine constraint kind (unique mapping via
// the interpolation role; unknown -> nullopt, never guessed). All 10 geo
// kinds map to a non-null engine kind.
[[nodiscard]] std::optional<std::string> to_engine_kind(
    const std::string& geo_kind);

// ---- CRS discipline (baseline P1-3) ---------------------------------------

// Python ValueError parity.
struct ConstraintCrsError : std::invalid_argument {
    using std::invalid_argument::invalid_argument;
    const char* python_class() const { return "ValueError"; }
};

// Declared-and-different CRSs -> ConstraintCrsError (mixed coordinates are
// never silently mixed); any undeclared side -> honest note; equal -> "".
[[nodiscard]] std::string assert_constraints_crs_compatible(
    const std::optional<std::string>& factor_crs,
    const std::optional<std::string>& constraint_crs,
    const std::string& context = "");

// ---- projection ------------------------------------------------------------

struct ConstraintLineSummary {
    std::string line_id;
    std::string name;
    std::string role;            // engine role (break/direction/boundary/…)
    std::string geo_kind;        // geological kind ("" = unlabelled/invalid)
    bool active = true;          // source default
    long long n_points = 0;      // len(coordinates) — ALL points
    double strength = 1.0;       // default 1.0 (declared below)
    bool strength_declared = false;
    std::string confidence = "unknown";  // unknown | low | medium | high
    std::string content_fingerprint;

    // Keys: line_id, name, role, geo_kind, active, n_points, strength,
    // strength_declared, confidence, content_fingerprint.
    [[nodiscard]] Json to_dict() const;
};

struct ConstraintProduct {
    std::string constraint_id;   // = group.id (commit/version-chain identity)
    std::string name;
    std::string target_horizon;
    std::vector<std::string> kinds;        // valid geo kinds, encounter order
    std::vector<std::string> engine_kinds; // per line: role map first, then
                                           // geo-kind map; insertion order
    std::string crs;
    bool crs_declared = false;
    std::vector<ConstraintLineSummary> lines;
    long long n_active = 0;
    std::string committed_version_id;      // "" = never committed -> draft
    std::string committed_content_hash;
    std::string content_hash;              // live content (incl. uncommitted)
    std::string maturity = "draft";        // draft | committed
    std::string staleness;                 // resolve_constraint_ref vocabulary
    std::string staleness_detail;          // "" = 未评估; also
                                           // "uncommitted" for never-committed
                                           // groups with content
    std::string source = "user";           // user | imported | derived
    std::string validity;                  // honest note ("" = no finding)

    [[nodiscard]] bool has_uncommitted_edits() const;

    // Keys: constraint_id, name, target_horizon, kinds, engine_kinds, crs,
    // crs_declared, lines, n_active, committed_version_id,
    // committed_content_hash, content_hash, maturity, staleness,
    // staleness_detail, source, validity.
    [[nodiscard]] Json to_dict() const;
};

// Document constraint group -> ConstraintProduct (read-only projection).
// catalog == nullptr mirrors Python catalog=None: no version chain is
// consulted and maturity stays draft.
[[nodiscard]] ConstraintProduct constraint_product_for_group(
    const Json& document, const Json& group,
    const pwb::workflow_runtime::CatalogRepository* catalog = nullptr);

[[nodiscard]] std::vector<ConstraintProduct>
constraint_products_for_document(
    const Json& document,
    const pwb::workflow_runtime::CatalogRepository* catalog = nullptr);

}  // namespace pwb::workflow_interpretation
