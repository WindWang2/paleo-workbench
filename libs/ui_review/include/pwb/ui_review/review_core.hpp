#pragma once

// UI-11 — review_export_page.py Qt-free semantics: the QC-run/export/
// finalize flow texts and the workflow seams (run_map_qc /
// active_quality_reports / export_quality_report_json /
// finalize_map_version / default_export_dir / project views) — every one
// a deferred subsystem call, plain DTOs only. The action-header state
// projection and result-summary counts are owned by UI-06
// (ui_pages_data::qc_summary) and are NOT redeclared here.

#include "pwb/domain/errors.hpp"
#include "pwb/domain/json.hpp"

#include <optional>
#include <string>
#include <vector>

namespace pwb::ui_review {

// NOTE — the action-header state projection and the result-summary counts
// are NOT re-declared here: UI-06 already owns them in
// pwb::ui_pages_data::qc_summary (resolve_action_header / summarize_qc /
// derive_rule_result via ui_data_core). This header keeps only what UI-06
// lacks: the flow texts and the workflow seams.

// ---- flow texts ---------------------------------------------------------------
// _on_config: "当前内置规则：\n{DEFAULT_QC_RULES joined ' · '}\n\n
// 规则编辑器将在后续版本提供。"
std::string review_config_text();

// export_report suggested name: "qc_{linked_map_document_id or id}.json".
std::string review_report_filename(const domain::Json& report);

// finalize_version doc pick: the doc whose id matches
// reports[0].linked_map_document_id, else docs[-1]; nullopt when empty.
std::optional<domain::Json>
review_finalize_target(const domain::Json& reports,
                       const domain::Json& docs);

// "已检查 {ran} 幅图件"
std::string review_run_done_text(int ran);
// "已定稿图件「{doc}」\nVersionSet: {name}\n状态: {status} · 快照数: {n}"
std::string review_finalize_done_text(const std::string& doc_name,
                                      const domain::Json& version_set);

// ---- workflow seams -----------------------------------------------------------
// run_map_qc / active_quality_reports / export_quality_report_json /
// finalize_map_version / default_export_dir + the project views the page
// re-reads (paleomap_documents / export_artifacts). All plain DTOs; the
// binding lives in the integration slice.
class IReviewActions {
public:
    virtual ~IReviewActions() = default;

    // active_quality_reports(project) → [QualityReport dict]
    virtual domain::Json active_quality_reports() = 0;
    // run_map_qc(project, doc_id) — one call per paleomap document.
    virtual domain::DataError run_map_qc(const std::string& doc_id) = 0;
    // export_quality_report_json(report, path, project=..., register=bound).
    virtual domain::DataError
    export_report_json(const domain::Json& report,
                       const std::string& path) = 0;
    // finalize_map_version(project, doc_id, note="审核页专家定稿",
    // operator="expert", require_qc_pass=False) → VersionSet dict.
    virtual domain::Result<domain::Json>
    finalize_map_version(const std::string& doc_id) = 0;
    // default_export_dir(project_path).
    virtual std::string default_export_dir() = 0;
    // project.paleomap_documents → [doc dict]
    virtual domain::Json paleomap_documents() = 0;
    // project.export_artifacts → [artifact dict]
    virtual domain::Json export_artifacts() = 0;
};

}  // namespace pwb::ui_review
