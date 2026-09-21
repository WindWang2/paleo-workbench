// closure_review — the review/publish governance line (09) Qt-free cores.
//
// review_qc_core: workflow/qc.py + workflow/map_qa_rules.py parity over the
// portable project JSON tree (pwb::project::ProjectDocument::root()). Every
// rule reads the REAL sections the Python model layer persists
// (paleomap_documents / quality_reports / compilation_runs / well_tables /
// user_vector_layers / factor_map_tasks / contour_drafts / …); nothing is
// synthesized and a pass is never fabricated: rule_status/coverage record
// evaluated-vs-skipped with the skip reason (V8 M11 honesty contract).
//
// Geometry location reuses the migrated mapping kernels: self-intersection
// via ui_data_core::validate_ring (geoviz.validate_ring parity) and the
// locate point via mapping_kernel::ring_centroid (area-centroid with the
// degenerate vertex-mean fallback, V8 M4 parity).

#pragma once

#include "pwb/domain/errors.hpp"
#include "pwb/domain/json.hpp"

#include <functional>
#include <string>
#include <vector>

namespace pwb::closure_review {

// Ordered rule keys stored on QualityReport.rules (engine keys, not the
// Chinese chips) — workflow/qc.py BASIC_QC_RULES parity.
const std::vector<std::string>& basic_qc_rules();

// workflow/map_qa_rules.py EXTENDED_QC_RULES parity.
const std::vector<std::string>& extended_qc_rules();

// Python truthiness over JSON: null/false/empty-string/empty-array/empty
// object are falsy (issue.get(...) guards rely on this).
bool json_truthy(const domain::Json& value);

// qc.make_issue parity — builds one issue dict; geometry gains a centroid
// locate point ([x, y] or null) computed the V8 M4 way.
struct IssueSpec {
    std::string rule;
    std::string severity;
    std::string message;
    std::string feature_id;    // omitted when empty
    std::string feature_kind;  // omitted when empty
    domain::Json geometry;     // null → omitted
    std::string ref;           // omitted when empty
    domain::Json extra;        // object merged last, omitted when empty
};
domain::Json make_issue(const IssueSpec& spec);

// The locate point for one issue geometry: area centroid, vertex-mean
// fallback for degenerate rings, null for unlocatable shapes
// (workflow/qc.py _geometry_centroid parity).
domain::Json issue_locate_point(const domain::Json& geometry);

// _status_from_issues parity: error/critical → "error", warning → "warning",
// else "pass".
std::string status_from_issues(const domain::Json& issues);

// ---- project section readers -------------------------------------------------

// root["paleomap_documents"] as an array (missing → empty array).
domain::Json paleomap_documents_of(const domain::Json& root);

// The map document with this id, else nullptr.
const domain::Json* find_map_document(const domain::Json& root,
                                      const std::string& doc_id);

// workflow/qc.py active_quality_reports parity: the active compilation
// run's bound report when resolvable, else the last report per map.
domain::Json active_quality_reports_of(const domain::Json& root);

// ---- QC inputs + run ----------------------------------------------------------

// Optional inputs the extended rules consume. A null member leaves its
// rules SKIPPED with an explicit reason (extended_rule_coverage parity) —
// a skip never counts as a pass.
struct QcInputs {
    const domain::Json* map_extent = nullptr;         // [xmin,ymin,xmax,ymax]
    const domain::Json* fusion_confidence = nullptr;  // {min, mean, ...}
    const domain::Json* export_report = nullptr;      // engine/degraded report
    double confidence_threshold = 0.5;
};

// 编图侧检查委托 (workflow/map_qa_rules.py cartographic_issues parity): the
// review flow calls it beside the extended collectors. The bound delegate
// owns the mapping-side rule set (the mapping/compilation line may install
// a richer one); closure_review::geometry_cartographic_issues is the real
// default (document-geometry checks through the mapping kernels).
using CartographicQaDelegate = std::function<domain::Json(
    const domain::Json& project_root, const domain::Json& map_document)>;

// The real default delegate: per-facies ring cartography — unclosed
// exteriors, duplicate consecutive vertices, degenerate (zero-area) rings
// — every issue located by id/ref and geometry. Real checks over the
// document's own geometry (self-intersection is the basic pass's report);
// the mapping line may install a richer rule set through the same seam.
domain::Json geometry_cartographic_issues(const domain::Json& root,
                                          const domain::Json& map_document);

// collect_cartographic_qa_issues call shape: delegate issues, or an empty
// array when no delegate is bound (the caller records the skip honestly —
// the delegate itself is never stubbed).
domain::Json cartographic_issues(const domain::Json& root,
                                 const domain::Json& map_document,
                                 const CartographicQaDelegate* delegate);

// run_basic_qc + run_map_qc parity (one entry: the extended pass runs with
// the given inputs; basic rules always evaluate). Upserts the per-map
// report (stable id) into root["quality_reports"], binds the active
// compilation run, and returns the stored report. Unknown doc → NotFound.
domain::Result<domain::Json> run_map_qc_on_document(
    domain::Json& root, const std::string& doc_id, const QcInputs& inputs,
    const CartographicQaDelegate* cartographic, const std::string& iso_now,
    // BEGIN V14-COMPILATION-PUBLISH — optional QC provenance registrar
    // (the catalog DataRun registration Python performs in qc.py). Null
    // ⇒ the report keeps the honest provenance_registered=false marker;
    // a registrar that returns an empty id (registration failed) keeps it
    // false too — the flag never claims a run that does not exist.
    const std::function<std::string(const domain::Json& report)>* provenance =
        nullptr);
// END V14-COMPILATION-PUBLISH

}  // namespace pwb::closure_review
