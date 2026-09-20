#include "pwb/closure_review/project_review_actions.hpp"

namespace pwb::closure_review {

namespace {

domain::DataError unbound_error() {
    return domain::DataError(domain::ErrorCode::InvalidArgument,
                             "未绑定工程");
}

}  // namespace

ProjectReviewActions::ProjectReviewActions(Delegates delegates)
    : delegates_(std::move(delegates)) {}

domain::Json* ProjectReviewActions::document() {
    return delegates_.document != nullptr ? delegates_.document() : nullptr;
}

std::string ProjectReviewActions::iso_now() {
    if (delegates_.clock != nullptr) {
        const std::string fixed = delegates_.clock();
        if (!fixed.empty()) {
            return fixed;
        }
    }
    return domain::now_iso8601();
}

const CartographicQaDelegate*
ProjectReviewActions::cartographic_delegate() {
    if (delegates_.cartographic != nullptr) {
        return delegates_.cartographic();
    }
    return delegates_.document != nullptr ? &default_cartographic_
                                          : nullptr;
}

domain::Json ProjectReviewActions::active_quality_reports() {
    domain::Json* doc = document();
    if (doc == nullptr) {
        return domain::Json::array();
    }
    return active_quality_reports_of(*doc);
}

domain::DataError ProjectReviewActions::run_map_qc(
    const std::string& doc_id) {
    domain::Json* doc = document();
    if (doc == nullptr) {
        return unbound_error();
    }
    const QcInputs inputs = delegates_.qc_inputs != nullptr
                                ? delegates_.qc_inputs()
                                : QcInputs{};
    auto result = run_map_qc_on_document(
        *doc, doc_id, inputs, cartographic_delegate(), iso_now());
    if (!result.is_ok()) {
        return result.error();
    }
    if (delegates_.save != nullptr) {
        if (const domain::DataError save_error = delegates_.save();
            !save_error.ok()) {
            return save_error;
        }
    }
    // Domain convention: a default DataError carries Unknown — success
    // must be constructed explicitly (see errors.hpp).
    return domain::DataError(domain::ErrorCode::Ok, "");
}

domain::DataError ProjectReviewActions::export_report_json(
    const domain::Json& report, const std::string& path) {
    domain::Json* doc = document();
    if (doc == nullptr) {
        return unbound_error();
    }
    const domain::DataError error = export_quality_report_json(
        *doc, report, std::filesystem::path(path), iso_now());
    if (!error.ok()) {
        return error;
    }
    if (delegates_.save != nullptr) {
        if (const domain::DataError save_error = delegates_.save();
            !save_error.ok()) {
            return save_error;
        }
    }
    // Domain convention: a default DataError carries Unknown — success
    // must be constructed explicitly (see errors.hpp).
    return domain::DataError(domain::ErrorCode::Ok, "");
}

domain::Result<domain::Json>
ProjectReviewActions::finalize_map_version(const std::string& doc_id) {
    domain::Json* doc = document();
    if (doc == nullptr) {
        return unbound_error();
    }
    // review_export_page.py finalize_map_version signature parity:
    // note="审核页专家定稿", operator="expert", require_qc_pass=False.
    auto result = finalize_map_version_on_document(
        *doc, doc_id, "审核页专家定稿", "expert", /*require_qc_pass=*/false,
        iso_now());
    if (!result.is_ok()) {
        return result;
    }
    if (delegates_.save != nullptr) {
        if (const domain::DataError save_error = delegates_.save();
            !save_error.ok()) {
            return save_error;
        }
    }
    return result;
}

std::string ProjectReviewActions::default_export_dir() {
    std::filesystem::path project;
    if (delegates_.project_file != nullptr) {
        project = delegates_.project_file();
    }
    if (project.empty()) {
        return closure_review::default_export_dir(nullptr).string();
    }
    return closure_review::default_export_dir(&project).string();
}

domain::Json ProjectReviewActions::paleomap_documents() {
    domain::Json* doc = document();
    if (doc == nullptr) {
        return domain::Json::array();
    }
    return paleomap_documents_of(*doc);
}

domain::Json ProjectReviewActions::export_artifacts() {
    domain::Json* doc = document();
    if (doc == nullptr) {
        return domain::Json::array();
    }
    const auto it = doc->find("export_artifacts");
    if (it == doc->end() || !it->is_array()) {
        return domain::Json::array();
    }
    return *it;
}

}  // namespace pwb::closure_review
