// M5 — 问题级人工复核状态机 core battery (closure_review.review_disposition).

#include <pwb/closure_review/review_disposition.hpp>
#include <pwb/closure_review/review_qc_core.hpp>

#include "closure_review_test.hpp"

using pwb::closure_review::ReviewDisposition;
using pwb::closure_review::ReviewRecord;
using pwb::domain::Json;

namespace {

Json make_issue(const char* rule, const char* feature) {
    return Json{{"rule", rule}, {"severity", "error"},
                {"message", "msg"}, {"feature_id", feature}};
}

Json make_report() {
    return Json{{"id", "qc1"}, {"status", "error"},
                {"issues", Json::array({make_issue("rule.a", "f1")})}};
}

}  // namespace

PWB_TEST(disposition_vocabulary_roundtrip) {
    using pwb::closure_review::review_disposition_from_string;
    using pwb::closure_review::review_disposition_label;
    CHECK(review_disposition_from_string("approved") ==
          ReviewDisposition::Approved);
    CHECK(review_disposition_from_string("rejected") ==
          ReviewDisposition::Rejected);
    CHECK(review_disposition_from_string("pending") ==
          ReviewDisposition::Pending);
    CHECK(review_disposition_from_string("not_executed") ==
          ReviewDisposition::NotExecuted);
    CHECK(review_disposition_from_string("not_applicable") ==
          ReviewDisposition::NotApplicable);
    CHECK(review_disposition_from_string("outdated") ==
          ReviewDisposition::Outdated);
    CHECK(!review_disposition_from_string("pass").has_value());
    CHECK(std::string(review_disposition_label(ReviewDisposition::Outdated))
              .find("过期") != std::string::npos);
}

PWB_TEST(issue_key_stable_and_distinct) {
    using pwb::closure_review::review_issue_key;
    const Json issue = make_issue("rule.a", "f1");
    CHECK(review_issue_key(issue) == "rule.a|f1");
    // Same rule, different feature → different key.
    CHECK(review_issue_key(make_issue("rule.a", "f2")) != "rule.a|f1");
    // Feature missing → ref fallback stays addressable.
    Json no_feature = Json{{"rule", "rule.a"}, {"ref", "r9"}};
    CHECK(review_issue_key(no_feature) == "rule.a|r9");
}

PWB_TEST(note_is_mandatory) {
    ReviewRecord record;
    record.issue_key = "rule.a|f1";
    record.disposition = ReviewDisposition::NotApplicable;  // 接受差异
    CHECK(!pwb::closure_review::validate_review_record(record).empty());
    record.reviewer_note = "与区域背景一致，接受差异";
    CHECK(pwb::closure_review::validate_review_record(record).empty());
}

PWB_TEST(attach_never_rewrites_original_verdict) {
    Json report = make_report();
    const std::string status_before = report["status"].get<std::string>();
    const std::string issue_before = report["issues"].dump();

    ReviewRecord record;
    record.issue_key = "rule.a|f1";
    record.rule = "rule.a";
    record.severity = "error";
    record.disposition = ReviewDisposition::Approved;  // 人工认可
    record.reviewer_note = "专家确认";
    record.created_at = "2026-09-22T00:00:00";
    CHECK(pwb::closure_review::attach_review_record(report, record).empty());

    // 复核 ≠ 通过: original status and issues byte-identical.
    CHECK(report["status"].get<std::string>() == status_before);
    CHECK(report["issues"].dump() == issue_before);
    const auto records = pwb::closure_review::review_records_of(report);
    CHECK(records.size() == 1);
    CHECK(records.front().disposition == ReviewDisposition::Approved);
    CHECK(records.front().severity == "error");
}

PWB_TEST(attach_rejects_empty_note) {
    Json report = make_report();
    ReviewRecord record;
    record.issue_key = "rule.a|f1";
    record.disposition = ReviewDisposition::Approved;
    CHECK(!pwb::closure_review::attach_review_record(report, record).empty());
    CHECK(pwb::closure_review::review_records_of(report).empty());
}

PWB_TEST(records_survive_the_qc_upsert) {
    // A re-run replaces the report (upsert by linked_map_document_id)
    // but carries review_records over — human work is never dropped.
    Json root = Json::object();
    root["paleomap_documents"] = Json::array(
        {Json{{"id", "doc1"}, {"name", "图1"}, {"layers", Json::array()}}});
    root["quality_reports"] = Json::array();

    const auto first = pwb::closure_review::run_map_qc_on_document(
        root, "doc1", pwb::closure_review::QcInputs{}, nullptr,
        "2026-09-22T10:00:00", nullptr);
    CHECK(first.is_ok());

    Json* report = &root["quality_reports"].at(0);
    const std::string fingerprint =
        report->value("input_fingerprint", std::string());
    CHECK(!fingerprint.empty());

    ReviewRecord record;
    record.issue_key = "rule|feature";
    record.rule = "rule";
    record.severity = "warning";
    record.disposition = ReviewDisposition::NotApplicable;
    record.reviewer_note = "理由";
    record.created_at = "2026-09-22T10:05:00";
    CHECK(pwb::closure_review::attach_review_record(*report, record).empty());

    // Re-run without input changes: record carried over, same fingerprint.
    const auto second = pwb::closure_review::run_map_qc_on_document(
        root, "doc1", pwb::closure_review::QcInputs{}, nullptr,
        "2026-09-22T11:00:00", nullptr);
    CHECK(second.is_ok());
    CHECK(root["quality_reports"].size() == 1);
    const auto carried =
        pwb::closure_review::review_records_of(root["quality_reports"].at(0));
    CHECK(carried.size() == 1);
    CHECK(carried.front().reviewer_note == "理由");
    CHECK(root["quality_reports"]
              .at(0)
              .value("input_fingerprint", std::string()) == fingerprint);

    // Input change → the stamped fingerprint mismatches → 已过期.
    root["paleomap_documents"] = Json::array(
        {Json{{"id", "doc1"},
              {"name", "图1-改"},
              {"layers", Json::array()}}});
    const Json& doc = root["paleomap_documents"].at(0);
    const std::string current =
        pwb::closure_review::qc_input_fingerprint(root, doc, {});
    CHECK(current != fingerprint);
    CHECK(pwb::closure_review::report_is_stale(root["quality_reports"].at(0),
                                               current));
    // A re-run stamps the new inputs → fresh again (and the human record
    // is still there — 复核记录可重开和追溯).
    const auto third = pwb::closure_review::run_map_qc_on_document(
        root, "doc1", pwb::closure_review::QcInputs{}, nullptr,
        "2026-09-22T12:00:00", nullptr);
    CHECK(third.is_ok());
    CHECK(!pwb::closure_review::report_is_stale(
        root["quality_reports"].at(0), current));
    CHECK(pwb::closure_review::review_records_of(root["quality_reports"].at(0))
              .size() == 1);
    // Missing stamp (pre-M5 report) → honest unknown, never stale.
    Json legacy = Json{{"id", "qc-old"}};
    CHECK(!pwb::closure_review::report_is_stale(legacy, current));
}

int main() {
    return ::pwb_test::run_all();
}
