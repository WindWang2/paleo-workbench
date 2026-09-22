// cartographic_qa — C++ port of paleo_workbench/mapping/cartographic_qa.py
// (V7 §14 cartographic QA rule set). Line anchors refer to the frozen
// Python source:
//   CARTOGRAPHIC_QA_RULES        L60    15 rule ids, order = summary order
//   _RuleStats                   L99    evaluated/skipped/notes accounting
//   _crs_issues                  L169   crs_invalid + unit_unknown
//   _geometry_issues             L242   geometry_invalid (bounded builtin
//                                       validator, engine label "host")
//   _outside_extent_issues       L322   layer_outside_extent
//   _stale_issues                L396   stale_input (precomputed summary
//                                       only — see CartographicQaOptions)
//   _missing_source_issues       L452   missing_source
//   _renderer_domain_issues      L580   renderer_domain_mismatch (spec
//                                       registry seam — see options)
//   _legend_issues               L689   legend_empty
//   _furniture_issues            L740   core_furniture_missing
//   _confidence_issues           L792   low_confidence
//   _fallback_renderer_issues    L856   fallback_renderer
//   _maturity_issues             L906   unpublished_data_in_export
//   _style_binding_issues        L994   style_binding_unknown (the V2
//                                       symbol registry is THIS lib —
//                                       geological_symbols::symbol_by_id)
//   _raster_range_issues         L1071  raster_range_invalid (reuses
//                                       cartography::ScalarStyleSpec)
//   _factor_group_issues         L1142  broken_factor_group
//   collect_cartographic_qa      L1215  issues + per-rule summary
//   issues_for_interactive_hub   L1305  bbox/layer_id localization adapter
//
// INPUTS (Python kwargs parity): the collector consumes the existing
// workflow_runtime::CartographicQaInputs facts struct — the SAME struct the
// CartographicQaDelegate seam (map_qa_rules.hpp L66-77, the L446 thin
// delegate) already declares, so collect_cartographic_qa_issues() can be
// bound as the delegate verbatim. Honest degradation is preserved: a rule
// whose inputs are absent records evaluated-vs-skipped with a note, never
// a fabricated pass.
//
// NOT PORTED (documented): the inline fallback in _stale_issues that builds
// a StaleSummary through mapping_workspace.MappingDependencyService — the
// service is not ported (workflow_runtime/staleness.hpp documents the same
// seam). Without inputs.stale_summary the rule skips with an explicit note.
//
// Qt-free, Python-free.
#pragma once

#include <pwb/domain/json.hpp>
#include <pwb/workflow_runtime/map_qa_rules.hpp>

#include <functional>
#include <optional>
#include <string>
#include <vector>

namespace pwb::cartography {

using Json = pwb::domain::Json;

// CARTOGRAPHIC_QA_RULES (cartographic_qa.py L60-76; order preserved — the
// summary dict iterates this list).
const std::vector<std::string>& cartographic_qa_rules();

// DEFAULT_CONFIDENCE_THRESHOLD (L78).
inline constexpr double kDefaultConfidenceThreshold = 0.5;

// ---------------------------------------------------------------------------
// Supplementary seams
// ---------------------------------------------------------------------------

// geometry_operations.ValidityResult parity for the geometry_invalid engine
// seam: `engine` is disclosed verbatim in the issue message + extra (Python
// uses "qgis"/"shapely-fallback"; the builtin bounded validator reports
// "host" — the facade's own label for non-GEOS host math).
struct GeometryValidity {
    bool valid = true;
    std::string reason;          // "" when valid (Python `reason or 'invalid'`)
    std::string engine = "host";
};

// The builtin geometry engine: a bounded pure-C++ GeoJSON validity check —
// Point/LineString/Polygon + Multi* + GeometryCollection. Rings must be
// closed, carry >=4 positions, have non-zero signed area, and contain no
// self-intersections (the geoviz _segments_properly_intersect predicate:
// proper crossings + collinear overlaps) nor non-adjacent duplicate
// vertices — the invalid classes shapely is_valid flags for the geometry
// shapes this app actually stores. Returns a verdict for every GeoJSON
// type; a nullopt return is reserved for INJECTED validators that cannot
// adjudicate (Python's RuntimeError "no validation engine" path).
std::optional<GeometryValidity> validate_geojson_geometry(
    const Json& geometry);

// Facts the Python module resolves by *import* and that no project section
// can supply honestly. Every member has an honest default: unbound → the
// dependent rule skips with a note (never guessed).
struct CartographicQaOptions {
    // role value -> GeologicalLayerSpec dict — the ui_composite spec
    // registry mirror (callers build it once via
    // ui_composite::geological_layer_specs() + GeologicalLayerSpec::to_dict();
    // cartography cannot link ui_composite — ui_workstation already depends
    // on cartography). Absent role key ⇔ Python spec_for_role KeyError.
    // nullptr → renderer_domain_mismatch skips with an explicit note.
    const Json* role_specs = nullptr;

    // geometry_operations.validate engine seam. nullopt return ⇔ the Python
    // RuntimeError "validate requires the qgis bridge or shapely" path —
    // the feature is skipped, not failed. Empty function → the builtin
    // validate_geojson_geometry.
    std::function<std::optional<GeometryValidity>(const Json& geometry)>
        validate_geometry;
};

// ---------------------------------------------------------------------------
// Public API (collect_cartographic_qa L1215)
// ---------------------------------------------------------------------------

struct CartographicQaReport {
    Json issues;   // array of make_issue dicts
    Json summary;  // {rule_id: {"evaluated", "skipped", "notes"}}
};

// Evaluate every §14 rule. `project` is the ProjectDocument root tree;
// `inputs` is the workflow_runtime::CartographicQaInputs facts struct
// (snapshot/capability/stale_summary/catalog/confidence_threshold — the
// Python kwargs verbatim).
CartographicQaReport collect_cartographic_qa(
    const Json& project,
    const workflow_runtime::CartographicQaInputs& inputs = {},
    const CartographicQaOptions& options = {});

// collect_cartographic_qa_issues (L1254): the list-only twin — same rules,
// same honesty; the signature IS workflow_runtime::CartographicQaDelegate-
// compatible so the app can install it directly:
//   CartographicQaDelegate d = &pwb::cartography::collect_cartographic_qa_issues;
// (with options captured in a lambda when a spec registry is available).
Json collect_cartographic_qa_issues(
    const Json& project,
    const workflow_runtime::CartographicQaInputs& inputs = {},
    const CartographicQaOptions& options = {});

// cartographic_rule_summary (L1330): only the evaluated/skipped summary.
Json cartographic_rule_summary(
    const Json& project,
    const workflow_runtime::CartographicQaInputs& inputs = {},
    const CartographicQaOptions& options = {});

// issues_for_interactive_hub (L1305): issues + "bbox" (geometry bbox, else
// centroid ±1) and "layer_id" (ref/layer fallback) adapter fields.
Json issues_for_interactive_hub(
    const Json& project,
    const workflow_runtime::CartographicQaInputs& inputs = {},
    const CartographicQaOptions& options = {});

}  // namespace pwb::cartography
