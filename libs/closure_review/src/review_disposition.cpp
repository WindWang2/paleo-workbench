#include "pwb/closure_review/review_disposition.hpp"

#include <pwb/domain/sha256.hpp>
#include <pwb/ui_review/qc_issue_rows.hpp>

#include <algorithm>
#include <map>

namespace pwb::closure_review {

namespace {

using domain::Json;

std::string field_string(const Json& object, const char* key) {
    if (!object.is_object()) {
        return {};
    }
    const auto it = object.find(key);
    return it != object.end() && it->is_string() ? it->get<std::string>()
                                                 : std::string();
}

// Canonical JSON (sorted object keys) so fingerprints survive reloads
// that re-order keys.
Json canonical(const Json& value) {
    if (value.is_object()) {
        std::map<std::string, Json> sorted;
        for (auto it = value.begin(); it != value.end(); ++it) {
            sorted.emplace(it.key(), canonical(it.value()));
        }
        Json out = Json::object();
        for (const auto& [key, entry] : sorted) {
            out[key] = entry;
        }
        return out;
    }
    if (value.is_array()) {
        Json out = Json::array();
        for (const auto& item : value) {
            out.push_back(canonical(item));
        }
        return out;
    }
    return value;
}

const Json* find_section(const Json& root, const char* name) {
    const auto it = root.find(name);
    return it != root.end() ? &*it : nullptr;
}

}  // namespace

const char* review_disposition_label(ReviewDisposition disposition) {
    switch (disposition) {
        case ReviewDisposition::Approved: return "通过";
        case ReviewDisposition::Rejected: return "未通过";
        case ReviewDisposition::Pending: return "待复核";
        case ReviewDisposition::NotExecuted: return "未执行";
        case ReviewDisposition::NotApplicable: return "不适用";
        case ReviewDisposition::Outdated: return "已过期";
    }
    return "待复核";  // unreachable, kept honest
}

std::optional<ReviewDisposition> review_disposition_from_string(
    const std::string& value) {
    if (value == "approved") return ReviewDisposition::Approved;
    if (value == "rejected") return ReviewDisposition::Rejected;
    if (value == "pending") return ReviewDisposition::Pending;
    if (value == "not_executed") return ReviewDisposition::NotExecuted;
    if (value == "not_applicable") return ReviewDisposition::NotApplicable;
    if (value == "outdated") return ReviewDisposition::Outdated;
    return std::nullopt;
}

std::string review_issue_key(const Json& issue) {
    // Canonical definition lives in ui_review (linked by every consumer —
    // the page and the persistence can never drift apart).
    return pwb::ui_review::qc_issue_key(issue);
}

std::vector<std::string> validate_review_record(
    const ReviewRecord& record) {
    std::vector<std::string> problems;
    if (record.issue_key.empty()) {
        problems.push_back("缺少问题标识");
    }
    if (record.reviewer_note.empty()) {
        // 复核备注必填 — accepting a difference without a reason is
        // exactly the failure mode F:78 forbids.
        problems.push_back("复核备注必填（接受差异必须说明理由）");
    }
    return problems;
}

Json review_record_to_json(const ReviewRecord& record) {
    Json json = Json::object();
    json["issue_key"] = record.issue_key;
    json["rule"] = record.rule;
    json["severity"] = record.severity;
    switch (record.disposition) {
        case ReviewDisposition::Approved: json["disposition"] = "approved"; break;
        case ReviewDisposition::Rejected: json["disposition"] = "rejected"; break;
        case ReviewDisposition::Pending: json["disposition"] = "pending"; break;
        case ReviewDisposition::NotExecuted: json["disposition"] = "not_executed"; break;
        case ReviewDisposition::NotApplicable: json["disposition"] = "not_applicable"; break;
        case ReviewDisposition::Outdated: json["disposition"] = "outdated"; break;
    }
    json["reviewer_note"] = record.reviewer_note;
    json["author"] = record.author;
    json["created_at"] = record.created_at;
    return json;
}

ReviewRecord review_record_from_json(const Json& json) {
    ReviewRecord record;
    if (!json.is_object()) {
        return record;
    }
    record.issue_key = field_string(json, "issue_key");
    record.rule = field_string(json, "rule");
    record.severity = field_string(json, "severity");
    const auto disposition =
        review_disposition_from_string(field_string(json, "disposition"));
    if (disposition.has_value()) {
        record.disposition = *disposition;
    }
    record.reviewer_note = field_string(json, "reviewer_note");
    record.author = field_string(json, "author");
    record.created_at = field_string(json, "created_at");
    return record;
}

std::vector<std::string> attach_review_record(Json& report,
                                              const ReviewRecord& record) {
    std::vector<std::string> problems = validate_review_record(record);
    if (!problems.empty()) {
        return problems;
    }
    if (!report.is_object()) {
        return {"报告不是对象"};
    }
    Json* records = nullptr;
    const auto it = report.find("review_records");
    if (it != report.end() && it->is_object()) {
        records = &*it;
    } else {
        report["review_records"] = Json::object();
        records = &report["review_records"];
    }
    (*records)[record.issue_key] = review_record_to_json(record);
    // The original verdict stays authoritative — this function never
    // touches report["status"] / report["issues"] (复核 ≠ 通过).
    return {};
}

std::vector<ReviewRecord> review_records_of(const Json& report) {
    std::vector<ReviewRecord> records;
    if (!report.is_object()) {
        return records;
    }
    const auto it = report.find("review_records");
    if (it == report.end() || !it->is_object()) {
        return records;
    }
    for (const auto& entry : it->items()) {
        records.push_back(review_record_from_json(entry.value()));
    }
    return records;
}

std::string qc_input_fingerprint(const Json& root, const Json& map_document,
                                 const QcInputs& inputs) {
    // The exact input set the collectors read: the map document entry,
    // the document sections the rule families consume, and the extended
    // inputs. Extend this list when a new collector reads a new section —
    // an input outside the fingerprint would make staleness a lie.
    Json bundle = Json::object();
    bundle["map_document"] = canonical(map_document);
    for (const char* section :
         {"correlation_interpretations", "prediction_tasks",
          "factor_map_tasks", "horizon_interpretations", "contour_drafts",
          "version_sets", "paleomap_documents", "stratigraphy",
          "wells", "resources"}) {
        const Json* value = find_section(root, section);
        if (value != nullptr) {
            bundle[section] = canonical(*value);
        }
    }
    bundle["map_extent"] =
        inputs.map_extent != nullptr ? canonical(*inputs.map_extent) : Json();
    bundle["fusion_confidence"] = inputs.fusion_confidence != nullptr
                                      ? canonical(*inputs.fusion_confidence)
                                      : Json();
    bundle["export_report"] = inputs.export_report != nullptr
                                  ? canonical(*inputs.export_report)
                                  : Json();
    bundle["confidence_threshold"] = inputs.confidence_threshold;

    const std::string dumped = canonical(bundle).dump();
    return domain::Sha256::of_bytes(dumped);
}

bool report_is_stale(const Json& report,
                     const std::string& current_fingerprint) {
    if (current_fingerprint.empty()) {
        return false;  // no evidence — never claim staleness
    }
    const auto it = report.find("input_fingerprint");
    if (it == report.end() || !it->is_string()) {
        return false;  // pre-M5 report without a stamp: honest unknown
    }
    return it->get<std::string>() != current_fingerprint;
}

}  // namespace pwb::closure_review
