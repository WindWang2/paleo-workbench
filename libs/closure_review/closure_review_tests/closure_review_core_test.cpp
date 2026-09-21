// closure_review core tests (line 09) — Qt-free, headless. Every rule runs
// against project JSON trees with the REAL .paleo.json section shapes (a
// full document is parsed from JSON text; the rest build the same tree
// structurally). The negative self-checks are in-band: broken projects must
// produce the specified issues and statuses, tampered inputs must fail the
// guards, and a simulated failed write must not leave a success receipt.

#include "closure_review_test.hpp"

#include <pwb/closure_review/project_review_actions.hpp>
#include <pwb/closure_review/report_export.hpp>
#include <pwb/closure_review/review_qc_core.hpp>
#include <pwb/closure_review/review_versioning.hpp>
#include <pwb/domain/json.hpp>

#include <cmath>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <limits>
#include <set>
#include <string>
#if defined(_WIN32)
#include <process.h>
inline int pwb_test_pid() { return _getpid(); }
#else
#include <unistd.h>
inline int pwb_test_pid() { return static_cast<int>(::getpid()); }
#endif

using namespace pwb;
using namespace pwb::closure_review;

namespace {

constexpr const char* kFixedNow = "2026-09-20T08:00:00";

// A realistic .paleo.json payload: the section names/shapes are the ones
// project/schema.cpp materializes and the Python model layer persists.
constexpr const char* kProjectJson = R"json({
  "version": "0.2.17a0",
  "schema_version": 2,
  "meta": {"name": "测试工区", "region": "蜀南", "project_root": "."},
  "paleomap_documents": [
    {
      "id": "map_broken",
      "name": "破碎草稿",
      "linked_target_horizon": "",
      "facies_polygons": [],
      "well_overlays": [],
      "line_features": [],
      "label_features": [],
      "map_crs": null,
      "view_state": {}
    },
    {
      "id": "map_clean",
      "name": "合格图件",
      "linked_target_horizon": "H2",
      "linked_contour_draft_id": "cdraft_1",
      "facies_polygons": [
        {"id": "f1", "facies_name": "浅水台地",
         "coordinates": [[100.0, 30.0], [102.0, 30.0], [102.0, 32.0],
                          [100.0, 32.0], [100.0, 30.0]]}
      ],
      "well_overlays": [{"well_id": "well_a"}],
      "line_features": [
        {"id": "c1", "role": "contour", "geometry":
          {"type": "LineString", "coordinates": [[100.0, 30.0], [101.0, 31.0]]}}
      ],
      "label_features": [],
      "map_crs": "EPSG:4326",
      "view_state": {}
    },
    {
      "id": "map_demo",
      "name": "演示草稿",
      "linked_target_horizon": "H3",
      "facies_polygons": [
        {"id": "d1", "facies_name": "深水盆地",
         "coordinates": [[100.0, 30.0], [102.0, 30.0], [102.0, 32.0],
                          [100.0, 32.0], [100.0, 30.0]]}
      ],
      "well_overlays": [{"well_id": "well_a"}],
      "line_features": [],
      "label_features": [],
      "map_crs": "EPSG:4326",
      "view_state": {"is_demo_draft": true}
    },
    {
      "id": "map_bowtie",
      "name": "自交图件",
      "linked_target_horizon": "H4",
      "facies_polygons": [
        {"id": "bt1", "facies_name": "蝴蝶相",
         "coordinates": [[0.0, 0.0], [10.0, 10.0], [10.0, 0.0], [0.0, 10.0],
                          [0.0, 0.0]]}
      ],
      "well_overlays": [{"well_id": "well_a"}],
      "line_features": [],
      "label_features": [],
      "map_crs": "EPSG:4326",
      "view_state": {}
    }
  ],
  "quality_reports": [],
  "version_sets": [],
  "compilation_runs": [
    {"id": "run_1", "name": "编译1", "target_horizon": "H2",
     "status": "review_required"}
  ],
  "well_tables": [
    {"id": "wtable_1", "name": "井表A", "target_horizon": "H2",
     "rows": [
       {"well_id": "well_a", "name": "井A", "x": 100.5, "y": 30.5,
        "qc_flag": "ok"},
       {"well_id": "well_b", "name": "井B", "x": 101.5, "y": 31.5,
        "qc_flag": "outlier", "qc_z_star": 2.9}
     ]}
  ],
  "contour_drafts": [
    {"id": "cdraft_1", "name": "等值线初稿", "target_horizon": "H2",
     "status": "editing", "segments": [{"level": 1.0}, {"level": 2.0}]}
  ],
  "user_vector_layers": [],
  "factor_map_tasks": [],
  "export_artifacts": []
})json";

domain::Json project_from_text() {
    return domain::Json::parse(kProjectJson, nullptr, true);
}

const domain::Json& report_issues(const domain::Json& report) {
    return report.at("issues");
}

bool has_issue_with_rule(const domain::Json& report, const std::string& rule) {
    for (const auto& issue : report_issues(report)) {
        if (issue.is_object() && issue.at("rule") == rule) {
            return true;
        }
    }
    return false;
}

// A clean, production map: everything the basic rules ask for is present.
void make_clean_map(domain::Json& root, const std::string& doc_id) {
    domain::Json doc = domain::Json::object();
    doc["id"] = doc_id;
    doc["name"] = "干净图件";
    doc["linked_target_horizon"] = "H9";
    doc["facies_polygons"] = domain::Json::array(
        {domain::Json{
            {"id", "f9"},
            {"coordinates",
             domain::Json::array({domain::Json::array({100.0, 30.0}),
                                  domain::Json::array({102.0, 30.0}),
                                  domain::Json::array({102.0, 32.0}),
                                  domain::Json::array({100.0, 32.0}),
                                  domain::Json::array({100.0, 30.0})})}}});
    doc["well_overlays"] =
        domain::Json::array({domain::Json{{"well_id", "w1"}}});
    doc["line_features"] = domain::Json::array({domain::Json{
        {"id", "c9"},
        {"role", "contour"},
        {"geometry",
         domain::Json{{"type", "LineString"},
                      {"coordinates",
                       domain::Json::array({domain::Json::array({100.0, 30.0}),
                                            domain::Json::array({101.0, 31.0})})}}}}});
    doc["label_features"] = domain::Json::array();
    doc["map_crs"] = "EPSG:4326";
    doc["view_state"] = domain::Json::object();
    root["paleomap_documents"].push_back(doc);
}

}  // namespace

// ---- broken project: every basic rule fires with the right severity ----

PWB_TEST(broken_project_qc_is_explained) {
    domain::Json root = project_from_text();
    auto result = run_map_qc_on_document(root, "map_broken", QcInputs{},
                                         nullptr, kFixedNow);
    CHECK(result.is_ok());
    const domain::Json report = result.value();
    CHECK_EQ(report.at("status").get<std::string>(), "error");
    CHECK(has_issue_with_rule(report, "target_horizon_present"));
    CHECK(has_issue_with_rule(report, "facies_polygons_present"));
    CHECK(has_issue_with_rule(report, "well_overlays_present"));
    CHECK(has_issue_with_rule(report, "contour_lines_present"));
    CHECK(has_issue_with_rule(report, "well_table_qc_clean"));

    // The flagged well sample locates spatially (ISS-QC-02): geometry +
    // centroid + ref.
    const domain::Json& issues = report_issues(report);
    bool saw_located_well_issue = false;
    for (const auto& issue : issues) {
        if (!issue.is_object() ||
            issue.at("rule") != "well_table_qc_clean") {
            continue;
        }
        CHECK(issue.contains("geometry"));
        CHECK(issue.at("geometry").at("type") == "Point");
        CHECK(issue.contains("centroid"));
        const auto& centroid = issue.at("centroid");
        CHECK(centroid.is_array() && centroid.size() == 2);
        CHECK(centroid[0].get<double>() == 101.5);
        CHECK(issue.at("ref") == "well_table:wtable_1/well_b");
        CHECK(issue.at("severity") == "warning");
        saw_located_well_issue = true;
    }
    CHECK(saw_located_well_issue);

    // V8 M11 honesty: basics all evaluated; extended + the cartographic
    // delegate accounting are skipped WITHOUT inputs / binding, each with
    // a visible reason. Always-evaluated: 6 basic + 6 extended;
    // skipped: out_of_bound / low_confidence / export_fallback +
    // cartographic_side_checks (composition_incomplete carries no
    // coverage entry — Python parity).
    const auto& rule_status = report.at("rule_status");
    CHECK(rule_status.at("target_horizon_present").at("evaluated") == true);
    CHECK(rule_status.at("out_of_bound_feature").at("evaluated") == false);
    CHECK(rule_status.at("out_of_bound_feature").at("reason") ==
          "未提供图幅范围（map_extent）");
    CHECK_EQ(report.at("coverage").at("evaluated").get<int>(), 12);
    CHECK_EQ(report.at("coverage").at("skipped").get<int>(), 4);

    // The report is stored on the document and bound to the active run.
    CHECK_EQ(root.at("quality_reports").size(), 1);
    CHECK(root.at("compilation_runs").back().contains(
        "active_quality_report_id"));
    CHECK(root.at("compilation_runs").back().at(
        "active_paleomap_document_id") == "map_broken");
}

PWB_TEST(clean_project_qc_passes_and_upserts_stably) {
    domain::Json root = project_from_text();
    // Flagged table only applies to matching horizon; H9 has no table.
    make_clean_map(root, "map_h9");

    auto first = run_map_qc_on_document(root, "map_h9", QcInputs{}, nullptr,
                                        kFixedNow);
    CHECK(first.is_ok());
    CHECK_EQ(first.value().at("status").get<std::string>(), "pass");
    CHECK_EQ(report_issues(first.value()).size(), 0);

    // Re-run: same linked map → same report object replaced (stable id),
    // the store does NOT inflate.
    const std::string stable_id =
        first.value().at("id").get<std::string>();
    auto second = run_map_qc_on_document(root, "map_h9", QcInputs{}, nullptr,
                                         kFixedNow);
    CHECK(second.is_ok());
    CHECK_EQ(second.value().at("id").get<std::string>(), stable_id);
    CHECK_EQ(root.at("quality_reports").size(), 1);

    // Self-check of the checker: a broken map STILL reports issues after
    // the clean one passed (per-map reports stay independent).
    auto broken = run_map_qc_on_document(root, "map_broken", QcInputs{},
                                         nullptr, kFixedNow);
    CHECK(broken.is_ok());
    CHECK_EQ(broken.value().at("status").get<std::string>(), "error");
    CHECK_EQ(root.at("quality_reports").size(), 2);
}

PWB_TEST(self_intersecting_facies_is_located) {
    domain::Json root = project_from_text();
    auto result = run_map_qc_on_document(root, "map_bowtie", QcInputs{},
                                         nullptr, kFixedNow);
    CHECK(result.is_ok());
    CHECK_EQ(result.value().at("status").get<std::string>(), "error");
    const domain::Json& issues = report_issues(result.value());
    bool saw = false;
    for (const auto& issue : issues) {
        if (!issue.is_object() ||
            issue.at("rule") != "facies_geometry_valid") {
            continue;
        }
        CHECK(issue.contains("geometry"));
        CHECK(issue.at("geometry").at("type") == "Polygon");
        CHECK(issue.contains("centroid"));
        // make_issue merges `extra` FLAT into the issue (Python
        // issue.update(extra) parity) — the code sits at the top level.
        CHECK(issue.at("code") == "self_intersection");
        CHECK(issue.at("feature_id") == "bt1");
        CHECK(issue.at("ref") == "map:map_bowtie/facies/bt1");
        saw = true;
    }
    CHECK(saw);
}

PWB_TEST(crs_and_renderer_rules_fire_on_real_sections) {
    domain::Json root = domain::Json::object();
    root["paleomap_documents"] = domain::Json::array();
    root["well_tables"] = domain::Json::array();
    root["user_vector_layers"] = domain::Json::array({
        domain::Json{{"id", "layer_a"},
                     {"name", "断层"},
                     {"crs", "EPSG:3857"},
                     {"features", domain::Json::array()}},
        domain::Json{{"id", "layer_b"},
                     {"name", "无CRS层"},
                     {"features", domain::Json::array()}},
    });
    domain::Json doc = domain::Json::object();
    doc["id"] = "map_crs";
    doc["name"] = "CRS图";
    doc["linked_target_horizon"] = "";
    doc["facies_polygons"] = domain::Json::array();
    doc["map_crs"] = "EPSG:4326";
    doc["view_state"] = domain::Json::object();
    root["paleomap_documents"].push_back(doc);

    auto result = run_map_qc_on_document(root, "map_crs", QcInputs{}, nullptr,
                                         kFixedNow);
    CHECK(result.is_ok());
    // error (mismatch) + warnings (undeclared) + presence warnings.
    CHECK_EQ(result.value().at("status").get<std::string>(), "error");
    CHECK(has_issue_with_rule(result.value(), "crs_mismatch"));
    CHECK(has_issue_with_rule(result.value(), "crs_undeclared"));

    // Categorized style missing a present class → renderer mismatch.
    root["paleomap_documents"][0]["facies_polygons"] =
        domain::Json::array({domain::Json{
            {"id", "f1"},
            {"facies_name", "泻湖"},
            {"coordinates",
             domain::Json::array({domain::Json::array({0.0, 0.0}),
                                  domain::Json::array({1.0, 0.0}),
                                  domain::Json::array({1.0, 1.0}),
                                  domain::Json::array({0.0, 1.0}),
                                  domain::Json::array({0.0, 0.0})})}}});
    root["paleomap_documents"][0]["facies_style"] = domain::Json{
        {"renderer", "categorized"},
        {"field", "facies_name"},
        {"categories",
         domain::Json::array({domain::Json::array({"浅水台地", 1})})}};
    auto mismatch = run_map_qc_on_document(root, "map_crs", QcInputs{},
                                           nullptr, kFixedNow);
    CHECK(mismatch.is_ok());
    CHECK(has_issue_with_rule(mismatch.value(), "class_renderer_mismatch"));
}

PWB_TEST(active_reports_prefer_run_binding_then_last_per_map) {
    domain::Json root = project_from_text();
    CHECK(active_quality_reports_of(root).empty());

    run_map_qc_on_document(root, "map_broken", QcInputs{}, nullptr,
                           kFixedNow);
    // The active run bound map_broken's report → exactly that one.
    domain::Json active = active_quality_reports_of(root);
    CHECK_EQ(active.size(), 1);
    CHECK(active[0].at("linked_map_document_id") == "map_broken");

    // Without a run binding, the last report per map surfaces.
    root["compilation_runs"] = domain::Json::array();
    run_map_qc_on_document(root, "map_clean", QcInputs{}, nullptr,
                           kFixedNow);
    active = active_quality_reports_of(root);
    CHECK_EQ(active.size(), 2);
    std::set<std::string> maps;
    for (const auto& report : active) {
        maps.insert(report.at("linked_map_document_id")
                        .get<std::string>());
    }
    CHECK(maps.count("map_broken") == 1);
    CHECK(maps.count("map_clean") == 1);
}

PWB_TEST(out_of_bound_uses_view_state_extent) {
    domain::Json root = project_from_text();
    root["paleomap_documents"][1]["view_state"]["extent"] =
        domain::Json::array({0.0, 0.0, 1.0, 1.0});
    auto result = run_map_qc_on_document(root, "map_clean", QcInputs{},
                                         nullptr, kFixedNow);
    CHECK(result.is_ok());
    CHECK(has_issue_with_rule(result.value(), "out_of_bound_feature"));
    // Python parity: the coverage map keys on the map_extent ARGUMENT —
    // the view_state fallback still emits issues but records the rule as
    // skipped-with-reason (the argument was never provided).
    const auto& rule_status = result.value().at("rule_status");
    CHECK(rule_status.at("out_of_bound_feature").at("evaluated") == false);
    CHECK(rule_status.at("out_of_bound_feature").at("reason") ==
          "未提供图幅范围（map_extent）");

    // With the argument provided the rule evaluates (and still reports).
    const domain::Json extent =
        domain::Json::array({0.0, 0.0, 1.0, 1.0});
    QcInputs with_extent;
    with_extent.map_extent = &extent;
    auto argued = run_map_qc_on_document(root, "map_clean", with_extent,
                                         nullptr, kFixedNow);
    CHECK(argued.is_ok());
    CHECK(has_issue_with_rule(argued.value(), "out_of_bound_feature"));
    CHECK(argued.value().at("rule_status").at("out_of_bound_feature")
              .at("evaluated") == true);
}

// ---- export: atomic write + honest failures + artifact registration ----

PWB_TEST(export_writes_parseable_json_and_registers_artifact) {
    domain::Json root = project_from_text();
    run_map_qc_on_document(root, "map_broken", QcInputs{}, nullptr,
                           kFixedNow);
    const domain::Json report =
        active_quality_reports_of(root).front();

    const std::filesystem::path out_dir =
        std::filesystem::temp_directory_path() /
        ("pwb09_export_" + std::to_string(pwb_test_pid()));
    std::filesystem::create_directories(out_dir);
    const auto out_path = out_dir / "qc_map_broken.json";

    const domain::DataError error = export_quality_report_json(
        root, report, out_path, kFixedNow);
    CHECK(error.ok());
    CHECK(std::filesystem::exists(out_path));

    // The delivered file parses and carries the report identity.
    std::ifstream in(out_path);
    const std::string text((std::istreambuf_iterator<char>(in)),
                           std::istreambuf_iterator<char>());
    const domain::Json parsed = domain::Json::parse(text, nullptr, true);
    CHECK(parsed.at("id") == report.at("id"));
    CHECK(parsed.at("linked_map_document_id") == "map_broken");

    // The artifact record landed with the right shape (record_export
    // parity: linked map first, format qc_json, source = report id).
    CHECK_EQ(root.at("export_artifacts").size(), 1);
    const auto& artifact = root.at("export_artifacts")[0];
    CHECK(artifact.at("linked_id") == "map_broken");
    CHECK_EQ(artifact.at("format").get<std::string>(), "qc_json");
    CHECK(artifact.at("output_path") == out_path.string());
    CHECK(artifact.at("source_task_ids") ==
          domain::Json::array({report.at("id")}));

    std::filesystem::remove_all(out_dir);
}

PWB_TEST(export_failure_leaves_no_success_receipt) {
    domain::Json root = project_from_text();

    // Destination under a FILE path: the parent "directory" cannot be
    // created — the write must fail and append NO artifact.
    const std::filesystem::path block =
        std::filesystem::temp_directory_path() /
        ("pwb09_block_" + std::to_string(pwb_test_pid()));
    std::filesystem::create_directories(block);
    std::ofstream(block / "as_file") << "x";
    const auto out_path = block / "as_file" / "nested" / "qc.json";

    const domain::DataError error =
        export_quality_report_json(root, domain::Json{{"id", "qc_x"}},
                                   out_path, kFixedNow);
    CHECK(!error.ok());
    CHECK_EQ(root.contains("export_artifacts")
                 ? root.at("export_artifacts").size()
                 : 0,
             0);
    CHECK(!std::filesystem::exists(out_path));
    std::filesystem::remove_all(block);
}

PWB_TEST(non_finite_floats_normalize_to_null) {
    // Build an issue payload carrying NaN/Inf (e.g. from a corrupt grid
    // statistic) — the exported file must still parse strictly.
    domain::Json report = domain::Json{
        {"id", "qc_nan"},
        {"linked_map_document_id", "map_nan"},
        {"issues",
         domain::Json::array({domain::Json{
             {"rule", "low_confidence"},
             {"severity", "warning"},
             {"message", "m"},
             {"extra",
              domain::Json{{"confidence_min", std::nan("")},
                           {"confidence_mean",
                            std::numeric_limits<double>::infinity()}}}}})}};
    const std::filesystem::path out_dir =
        std::filesystem::temp_directory_path() /
        ("pwb09_nan_" + std::to_string(pwb_test_pid()));
    const auto out_path = out_dir / "qc_nan.json";
    domain::Json sink_root = domain::Json::object();
    const domain::DataError error =
        export_quality_report_json(sink_root, report, out_path, kFixedNow);
    CHECK(error.ok());
    CHECK_EQ(sink_root.at("export_artifacts").size(), 1);
    std::ifstream in(out_path);
    const std::string text((std::istreambuf_iterator<char>(in)),
                           std::istreambuf_iterator<char>());
    CHECK(text.find("NaN") == std::string::npos);
    CHECK(text.find("Infinity") == std::string::npos);
    const domain::Json parsed = domain::Json::parse(text, nullptr, true);
    CHECK(parsed.at("issues")[0].at("extra").at("confidence_min").is_null());
    std::filesystem::remove_all(out_dir);
}

// ---- finalize: guards, supersede, snapshot, run bookkeeping ----

PWB_TEST(demo_draft_refuses_finalize) {
    domain::Json root = project_from_text();
    auto result = finalize_map_version_on_document(
        root, "map_demo", "note", "expert", false, kFixedNow);
    CHECK(!result.is_ok());
    CHECK(result.error().message.find("演示草稿") != std::string::npos);
    CHECK(root.at("version_sets").empty());
}

PWB_TEST(require_qc_pass_blocks_on_error_report) {
    domain::Json root = project_from_text();
    run_map_qc_on_document(root, "map_broken", QcInputs{}, nullptr,
                           kFixedNow);
    auto result = finalize_map_version_on_document(
        root, "map_broken", "", "expert", /*require_qc_pass=*/true,
        kFixedNow);
    CHECK(!result.is_ok());
    CHECK(result.error().message.find("质检未通过") != std::string::npos);

    // And with require_qc_pass on an UNCHECKED map the gate refuses too.
    auto unchecked = finalize_map_version_on_document(
        root, "map_clean", "", "expert", /*require_qc_pass=*/true,
        kFixedNow);
    CHECK(!unchecked.is_ok());
    CHECK(unchecked.error().message.find("先运行质检") != std::string::npos);
}

PWB_TEST(finalize_publishes_traceable_state) {
    domain::Json root = project_from_text();
    run_map_qc_on_document(root, "map_clean", QcInputs{}, nullptr,
                           kFixedNow);

    auto result = finalize_map_version_on_document(
        root, "map_clean", "专家复核通过", "expert", false, kFixedNow);
    CHECK(result.is_ok());
    const domain::Json vset = result.value();
    CHECK_EQ(vset.at("status").get<std::string>(), "final");
    CHECK_EQ(vset.at("target_horizon").get<std::string>(), "H2");
    CHECK_EQ(vset.at("snapshots").size(), 1);
    const auto& snap = vset.at("snapshots")[0];
    CHECK(snap.at("map_document_id") == "map_clean");
    CHECK_EQ(snap.at("facies_count").get<int>(), 1);
    CHECK_EQ(snap.at("contour_segment_count").get<int>(), 2);
    // The H2 well table carries one flagged sample (outlier) → the report
    // is a warning, and the snapshot records that status honestly.
    CHECK_EQ(snap.at("qc_status").get<std::string>(), "warning");
    CHECK(snap.at("quality_report_id") ==
          root.at("quality_reports")[0].at("id"));
    CHECK(!snap.at("content_fingerprint").get<std::string>().empty());
    CHECK_EQ(snap.at("created_by").get<std::string>(), "expert");

    // Contour draft went final; the run went export_ready.
    CHECK_EQ(root.at("contour_drafts")[0].at("status").get<std::string>(),
             "final");
    CHECK_EQ(root.at("compilation_runs").back().at("status")
                 .get<std::string>(),
             "export_ready");
    CHECK(root.at("compilation_runs").back().at(
        "active_paleomap_document_id") == "map_clean");

    // Fingerprint tamper self-check: same content → same fingerprint;
    // changed geometry → different fingerprint. Re-finalizing SUPERSEDES
    // the prior final and creates a fresh set per finalize (versioning.py
    // parity — _version_set_for_horizon skips superseded sets), so each
    // returned set carries exactly its own new snapshot.
    const std::string fp =
        snap.at("content_fingerprint").get<std::string>();
    auto again = finalize_map_version_on_document(
        root, "map_clean", "复核定稿", "expert2", false, kFixedNow);
    CHECK(again.is_ok());
    CHECK_EQ(again.value().at("snapshots").size(), 1);
    CHECK(again.value().at("snapshots")[0].at("content_fingerprint") == fp);
    CHECK_EQ(again.value().at("snapshots")[0].at("created_by")
                 .get<std::string>(),
             "expert2");
    root["paleomap_documents"][1]["facies_polygons"][0]["coordinates"][0] =
        domain::Json::array({100.5, 30.5});
    auto changed = finalize_map_version_on_document(
        root, "map_clean", "改图再定稿", "expert", false, kFixedNow);
    CHECK(changed.is_ok());
    CHECK_EQ(changed.value().at("snapshots").size(), 1);
    CHECK(changed.value().at("snapshots")[0].at("content_fingerprint") != fp);

    // History: three finalization rounds → two superseded sets + one final.
    int finals = 0;
    int superseded = 0;
    for (const auto& vs : root.at("version_sets")) {
        if (vs.at("status") == "final") ++finals;
        if (vs.at("status") == "superseded") ++superseded;
    }
    CHECK_EQ(finals, 1);
    CHECK_EQ(superseded, 2);
}

PWB_TEST(finalize_supersedes_prior_final_for_same_horizon) {
    domain::Json root = domain::Json::object();
    root["paleomap_documents"] = domain::Json::array();
    root["quality_reports"] = domain::Json::array();
    root["version_sets"] = domain::Json::array();
    root["compilation_runs"] = domain::Json::array();
    root["well_tables"] = domain::Json::array();
    root["contour_drafts"] = domain::Json::array();
    make_clean_map(root, "map_a");
    make_clean_map(root, "map_b");
    root["paleomap_documents"][1]["linked_target_horizon"] = "H9";

    auto first = finalize_map_version_on_document(root, "map_a", "", "e1",
                                                  false, kFixedNow);
    CHECK(first.is_ok());
    auto second = finalize_map_version_on_document(root, "map_b", "", "e2",
                                                   false, kFixedNow);
    CHECK(second.is_ok());
    // Same horizon → exactly one final (the newest); the older is kept as
    // superseded (history preserved).
    int finals = 0;
    int superseded = 0;
    for (const auto& vs : root.at("version_sets")) {
        if (vs.at("status") == "final") {
            ++finals;
            CHECK(vs.at("snapshots")[0].at("map_document_id") == "map_b");
            CHECK(vs.at("finalized_by") == "e2");
        }
        if (vs.at("status") == "superseded") {
            ++superseded;
        }
    }
    CHECK_EQ(finals, 1);
    CHECK_EQ(superseded, 1);
}

PWB_TEST(unknown_document_is_not_found_everywhere) {
    domain::Json root = project_from_text();
    auto qc = run_map_qc_on_document(root, "map_nope", QcInputs{}, nullptr,
                                     kFixedNow);
    CHECK(!qc.is_ok());
    auto fin = finalize_map_version_on_document(root, "map_nope", "", "e",
                                                false, kFixedNow);
    CHECK(!fin.is_ok());
    CHECK(active_quality_reports_of(root).empty());
}

// ---- cartographic delegation ----

PWB_TEST(cartographic_delegate_runs_and_skips_honestly) {
    domain::Json root = project_from_text();

    // No delegate: the delegation returns an empty list (the caller's
    // coverage records the skip) — never fabricated issues.
    const domain::Json* doc =
        find_map_document(root, "map_bowtie");
    CHECK(doc != nullptr);
    CHECK(cartographic_issues(root, *doc, nullptr).empty());

    // The real default delegate: mapping-kernel-backed geometry checks.
    const CartographicQaDelegate delegate = &geometry_cartographic_issues;

    // Wired into run_map_qc via the delegate parameter: a ring with a
    // duplicate consecutive vertex surfaces the cartographic issue WITH
    // location (the basic pass does not own that shape).
    root["paleomap_documents"][3]["facies_polygons"][0]["coordinates"] =
        domain::Json::array({domain::Json::array({0.0, 0.0}),
                             domain::Json::array({0.0, 0.0}),
                             domain::Json::array({1.0, 0.0}),
                             domain::Json::array({1.0, 1.0}),
                             domain::Json::array({0.0, 0.0})});
    auto result = run_map_qc_on_document(root, "map_bowtie", QcInputs{},
                                         &delegate, kFixedNow);
    CHECK(result.is_ok());
    bool saw_duplicate_vertices = false;
    for (const auto& issue : report_issues(result.value())) {
        const std::string rule = issue.at("rule").get<std::string>();
        if (rule == "cartographic_duplicate_vertices") {
            saw_duplicate_vertices = true;
            CHECK(issue.at("feature_kind") == "facies");
            CHECK(issue.at("feature_id") == "bt1");
            CHECK(issue.at("ref") == "map:map_bowtie/facies/bt1");
        }
    }
    CHECK(saw_duplicate_vertices);
}

// ---- ProjectReviewActions (the real IReviewActions backend) ----

namespace {

struct ActionsHarness {
    domain::Json document;
    std::filesystem::path project_file;
    int save_calls = 0;
    // Explicit Ok default: a default-constructed DataError carries
    // Unknown (NOT ok) — see errors.hpp.
    domain::DataError next_save_error =
        domain::DataError(domain::ErrorCode::Ok, "");

    ProjectReviewActions::Delegates delegates() {
        ProjectReviewActions::Delegates d;
        d.document = [this]() -> domain::Json* { return &document; };
        d.project_file = [this]() { return project_file; };
        d.save = [this]() -> domain::DataError {
            ++save_calls;
            return next_save_error;
        };
        d.clock = []() { return std::string(kFixedNow); };
        d.cartographic = []() -> const CartographicQaDelegate* {
            return nullptr;
        };
        return d;
    }
};

}  // namespace

// A fresh backend object per call site — tests never share backend state.
namespace {
ProjectReviewActions actions_for(ActionsHarness& harness) {
    return ProjectReviewActions(harness.delegates());
}
}  // namespace

PWB_TEST(actions_backend_closes_the_loop) {
    ActionsHarness harness;
    harness.document = project_from_text();
    const std::filesystem::path work =
        std::filesystem::temp_directory_path() /
        ("pwb09_actions_" + std::to_string(::getpid()));
    std::filesystem::create_directories(work);
    // A real .paleo.json-shaped project file path → exports land in the
    // sibling project.artifacts/exports directory (artifact_dir_for parity).
    harness.project_file = work / "project.paleo.json";
    { std::ofstream touch(harness.project_file); }

    ProjectReviewActions actions = actions_for(harness);
    ui_review::IReviewActions* acts = &actions;

    // Page flow: paleomap_documents → run QC per doc → reports appear →
    // finalize → artifacts traceable.
    const domain::Json docs = acts->paleomap_documents();
    CHECK_EQ(docs.size(), 4);
    CHECK_EQ(acts->active_quality_reports().size(), 0);

    CHECK(acts->run_map_qc("map_broken").ok());
    CHECK_EQ(harness.save_calls, 1);
    CHECK_EQ(acts->active_quality_reports().size(), 1);

    // Export through the page's path (report → file → artifact → traceable
    // after "reopen": the document tree carries the record). The page's
    // suggested directory IS default_export_dir — exercise that seam.
    const domain::Json report =
        acts->active_quality_reports().front();
    const auto out_path =
        std::filesystem::path(acts->default_export_dir()) / "qc_broken.json";
    CHECK(acts->export_report_json(report, out_path.string()).ok());
    CHECK_EQ(acts->export_artifacts().size(), 1);
    CHECK(std::filesystem::exists(out_path));

    // Finalize the clean map through the backend.
    CHECK(acts->run_map_qc("map_clean").ok());
    auto fin = acts->finalize_map_version("map_clean");
    CHECK(fin.is_ok());
    CHECK_EQ(fin.value().at("status").get<std::string>(), "final");

    // default_export_dir parity: <sibling project.artifacts>/exports.
    CHECK_EQ(acts->default_export_dir(),
             (work / "project.artifacts" / "exports").string());

    std::filesystem::remove_all(work);
}

PWB_TEST(save_failure_is_not_a_success_receipt) {
    ActionsHarness harness;
    harness.document = project_from_text();
    harness.next_save_error = domain::DataError(
        domain::ErrorCode::IoError, "short write (simulated disk full)");

    ProjectReviewActions actions = actions_for(harness);
    ui_review::IReviewActions* acts = &actions;
    const domain::DataError error = acts->run_map_qc("map_broken");
    CHECK(!error.ok());
    CHECK(error.message.find("disk full") != std::string::npos);
    CHECK_EQ(harness.save_calls, 1);
    // The mutation happened in memory but the action was NOT acked —
    // the caller sees the error and may retry after freeing space.
    auto fin = acts->finalize_map_version("map_clean");
    CHECK(!fin.is_ok());
    CHECK(fin.error().message.find("disk full") != std::string::npos);
}

PWB_TEST(unbound_document_states_are_honest) {
    ProjectReviewActions::Delegates d;
    d.document = []() -> domain::Json* { return nullptr; };
    d.project_file = []() { return std::filesystem::path(); };
    ProjectReviewActions actions(std::move(d));

    CHECK_EQ(actions.paleomap_documents().size(), 0);
    CHECK_EQ(actions.active_quality_reports().size(), 0);
    CHECK_EQ(actions.export_artifacts().size(), 0);
    CHECK(!actions.run_map_qc("map_x").ok());
    CHECK(!actions.finalize_map_version("map_x").is_ok());
    // The page renders its own 未绑定工程 guard off this state.
}

PWB_TEST(review_finalize_target_picks_linked_doc) {
    // review_core glue through the backend-shaped DTOs: the finalize target
    // prefers reports[0].linked_map_document_id, else the LAST doc.
    const domain::Json reports = domain::Json::array(
        {domain::Json{{"id", "qc1"}, {"linked_map_document_id", "map_c"}}});
    const domain::Json docs =
        domain::Json::array({domain::Json{{"id", "map_a"}},
                             domain::Json{{"id", "map_b"}},
                             domain::Json{{"id", "map_c"}}});
    const auto target = ui_review::review_finalize_target(reports, docs);
    CHECK(target.has_value());
    CHECK((*target)["id"] == "map_c");
    const auto fallback = ui_review::review_finalize_target(
        domain::Json::array({domain::Json{{"id", "qc9"}}}), docs);
    CHECK(fallback.has_value());
    CHECK((*fallback)["id"] == "map_c");
}

int main() { return pwb_test::run_all(); }
