// ProjectReviewActions — the real ui_review::IReviewActions backend
// (review_export_page.py parity): every page action consumes the LIVE
// project document through injected delegates, so the page never needs to
// know where the document lives (PwbDataStore in the platform app, a test
// fixture in tests). A delegate resolving to nullptr is the honest
// "未绑定工程" state; a failed save surfaces as an error — a mutation is
// only acked once it persisted.

#pragma once

#include "pwb/closure_review/report_export.hpp"
#include "pwb/closure_review/review_qc_core.hpp"
#include "pwb/closure_review/review_versioning.hpp"
#include "pwb/domain/diagnostics.hpp"
#include "pwb/ui_review/review_core.hpp"

#include <filesystem>
#include <functional>

namespace pwb::closure_review {

class ProjectReviewActions final : public ui_review::IReviewActions {
public:
    struct Delegates {
        // The live document root; nullptr = no project bound.
        std::function<domain::Json*()> document;
        // The project file path (empty = none) for default_export_dir.
        std::function<std::filesystem::path()> project_file;
        // Persist the mutated document. Returning an error fails the
        // action — the in-memory mutation alone is never a success.
        std::function<domain::DataError()> save;
        // QC inputs provider (map_extent / fusion_confidence /
        // export_report may come from session state); default = none, the
        // extended rules then report their skips honestly.
        std::function<QcInputs()> qc_inputs;
        // 编图侧检查委托 binding (see review_qc_core.hpp). Null → the
        // cartographic rules are skipped with reason, never faked.
        std::function<const CartographicQaDelegate*()> cartographic;
        // Clock injection for tests (empty → now_iso8601()).
        std::function<std::string()> clock;
    };

    explicit ProjectReviewActions(Delegates delegates);

    // ---- ui_review::IReviewActions ----------------------------------------
    domain::Json active_quality_reports() override;
    domain::DataError run_map_qc(const std::string& doc_id) override;
    domain::DataError
    export_report_json(const domain::Json& report,
                       const std::string& path) override;
    domain::Result<domain::Json>
    finalize_map_version(const std::string& doc_id) override;
    std::string default_export_dir() override;
    domain::Json paleomap_documents() override;
    domain::Json export_artifacts() override;

private:
    domain::Json* document();
    std::string iso_now();
    const CartographicQaDelegate* cartographic_delegate();

    Delegates delegates_;
    CartographicQaDelegate default_cartographic_ =
        &geometry_cartographic_issues;
};

}  // namespace pwb::closure_review
