// V14-COMPILATION-PUBLISH — the QC provenance registrar seam.
//
// The report's provenance_registered marker must flip ONLY when a real
// DataRun registration happened (H14: never claim a run that does not
// exist). Pinned cases:
//   * no registrar bound      → false (Python get_catalog() → None);
//   * registrar returns ""    → false (registration failed);
//   * registrar returns an id → true, and the id rides the report;
//   * a registrar that throws must not fail the QC run itself.

#include "closure_review_test.hpp"

#include <pwb/closure_review/project_review_actions.hpp>
#include <pwb/closure_review/review_qc_core.hpp>
#include <pwb/domain/json.hpp>

#include <stdexcept>
#include <string>

using namespace pwb;
using namespace pwb::closure_review;

namespace {

constexpr const char* kFixedNow = "2026-09-21T00:00:00";

constexpr const char* kProjectJson = R"json({
  "version": "0.2.17a0",
  "schema_version": 2,
  "meta": {"name": "溯源测试工区", "region": "蜀南", "project_root": "."},
  "paleomap_documents": [
    {
      "id": "map_ok",
      "name": "测试图",
      "crs": "EPSG:4326",
      "layers": [
        {"id": "lyr_1", "name": "相带", "layer_type": "polygon", "visible": true}
      ]
    }
  ],
  "compilation_input_sets": [],
  "map_products": [],
  "quality_reports": []
})json";

domain::Json parse_project() { return domain::Json::parse(kProjectJson); }

domain::Json run_qc(domain::Json& project, const std::string& doc_id,
                    const std::function<std::string(const domain::Json&)>* registrar) {
    const auto result = run_map_qc_on_document(project, doc_id, QcInputs{}, nullptr,
                                               kFixedNow, registrar);
    CHECK(result.is_ok());
    if (!result.is_ok()) return domain::Json::object();
    return result.value();
}

PWB_TEST(no_registrar_keeps_false) {
    domain::Json project = parse_project();
    const domain::Json report = run_qc(project, "map_ok", nullptr);
    CHECK(report.value("provenance_registered", true) == false);
    CHECK(!report.contains("provenance_run_id"));
}

PWB_TEST(failing_registrar_keeps_false) {
    domain::Json project = parse_project();
    const std::function<std::string(const domain::Json&)> failing =
        [](const domain::Json&) -> std::string { return {}; };
    const domain::Json report = run_qc(project, "map_ok", &failing);
    CHECK(report.value("provenance_registered", true) == false);
    CHECK(!report.contains("provenance_run_id"));
}

PWB_TEST(successful_registrar_flips_true) {
    domain::Json project = parse_project();
    const std::function<std::string(const domain::Json&)> ok =
        [](const domain::Json& report) -> std::string {
            // The registrar receives the report being stored (Python's
            // run_qc passes the serialized report).
            return "run_" + report.value("id", std::string("unknown"));
        };
    const domain::Json report = run_qc(project, "map_ok", &ok);
    CHECK(report.value("provenance_registered", false) == true);
    CHECK_EQ(report.value("provenance_run_id", std::string()),
             "run_" + report.value("id", std::string()));
    // The stored report (root section) carries the same marker.
    const domain::Json& reports = project.at("quality_reports");
    CHECK(reports.is_array() && reports.size() == 1);
    CHECK(reports[0].value("provenance_registered", false) == true);
    CHECK_EQ(reports[0].value("provenance_run_id", std::string()),
             reports[0].value("id", std::string()).empty()
                 ? std::string()
                 : "run_" + reports[0].value("id", std::string()));
}

PWB_TEST(throwing_registrar_does_not_fail_the_run) {
    domain::Json project = parse_project();
    const std::function<std::string(const domain::Json&)> throwing =
        [](const domain::Json&) -> std::string {
            throw std::runtime_error("catalog unavailable");
        };
    const domain::Json report = run_qc(project, "map_ok", &throwing);
    CHECK(report.value("provenance_registered", true) == false);
    CHECK(report.contains("id"));
}

PWB_TEST(project_review_actions_honours_the_delegate) {
    domain::Json project = parse_project();
    ProjectReviewActions::Delegates delegates;
    delegates.document = [&project]() -> domain::Json* { return &project; };
    delegates.clock = [] { return std::string(kFixedNow); };
    int calls = 0;
    delegates.provenance = [&calls](const domain::Json&) -> std::string {
        ++calls;
        return "run_probe";
    };
    ProjectReviewActions actions(std::move(delegates));
    const auto error = actions.run_map_qc("map_ok");
    CHECK(error.ok());
    CHECK_EQ(static_cast<long long>(calls), 1);
    const domain::Json& reports = project.at("quality_reports");
    CHECK(reports.is_array() && !reports.empty());
    CHECK(reports.back().value("provenance_registered", false) == true);
    CHECK_EQ(reports.back().value("provenance_run_id", std::string()),
             std::string("run_probe"));
}

}  // namespace

int main() { return pwb_test::run_all(); }
