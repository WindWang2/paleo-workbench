#include "pwb/ui_review/review_core.hpp"

#include "pwb/ui_review/tokens.hpp"

namespace pwb::ui_review {

namespace {

const domain::Json* member(const domain::Json& obj, const char* key) {
    if (!obj.is_object()) {
        return nullptr;
    }
    const auto it = obj.find(key);
    return it != obj.end() ? &*it : nullptr;
}

std::string str_member(const domain::Json& obj, const char* key) {
    const domain::Json* m = member(obj, key);
    return (m != nullptr && m->is_string()) ? m->get<std::string>() : "";
}

std::string join(const std::vector<std::string>& items,
                 const std::string& sep) {
    std::string out;
    for (const auto& item : items) {
        if (!out.empty()) {
            out += sep;
        }
        out += item;
    }
    return out;
}

}  // namespace

std::string review_config_text() {
    return "当前内置规则：\n" + join(tokens::default_qc_rules(), " · ") +
           "\n\n规则编辑器将在后续版本提供。";
}

std::string review_report_filename(const domain::Json& report) {
    std::string stem = str_member(report, "linked_map_document_id");
    if (stem.empty()) {
        stem = str_member(report, "id");
    }
    return "qc_" + stem + ".json";
}

std::optional<domain::Json>
review_finalize_target(const domain::Json& reports,
                       const domain::Json& docs) {
    if (!docs.is_array() || docs.empty()) {
        return std::nullopt;
    }
    if (reports.is_array() && !reports.empty()) {
        const std::string linked =
            str_member(reports.front(), "linked_map_document_id");
        for (const auto& doc : docs) {
            if (str_member(doc, "id") == linked) {
                return doc;
            }
        }
    }
    return docs.back();
}

std::string review_run_done_text(int ran) {
    return "已检查 " + std::to_string(ran) + " 幅图件";
}

std::string review_finalize_done_text(const std::string& doc_name,
                                      const domain::Json& version_set) {
    long long snapshots = 0;
    const domain::Json* snap = member(version_set, "snapshots");
    if (snap != nullptr && snap->is_array()) {
        snapshots = static_cast<long long>(snap->size());
    }
    return "已定稿图件「" + doc_name + "」\nVersionSet: " +
           str_member(version_set, "name") + "\n状态: " +
           str_member(version_set, "status") + " · 快照数: " +
           std::to_string(snapshots);
}

}  // namespace pwb::ui_review
