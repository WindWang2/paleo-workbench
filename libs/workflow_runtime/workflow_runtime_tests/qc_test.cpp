// CONV-33 route A1 — frozen-oracle replay test for the qc/map_qa_rules port.
//
// Replays libs/workflow_runtime_tests/fixtures/workflow_qc_oracle.json
// (frozen from the REAL Python implementation by
// tools/oracle/generate_workflow_qc_fixtures.py: paleo_workbench.workflow.qc
// + map_qa_rules, geoviz validate_ring and the geometry_operations.centroid
// facade included) through the C++ port and compares against the frozen
// expectation with semantic JSON equality plus raise parity. Scenario inputs
// are rebuilt independently on the C++ side; the fixture is the only shared
// artifact. Runtime stamping goes through an injected project::ModelClock
// seeded from the frozen clock state recorded per case.
//
// Beyond the replay: a comparator negative self-check (tampered expectations
// MUST fail) and C++-side seam checks for the parts Python's typed models
// cannot reach (QcProvenanceSink outcomes, the cartographic delegate
// forward, and the defensive Json-seam well-row branch).

#include <pwb/domain/json.hpp>
#include <pwb/project/version_models.hpp>
#include <pwb/workflow_runtime/map_qa_rules.hpp>
#include <pwb/workflow_runtime/qc.hpp>

#include <array>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <optional>
#include <string>
#include <vector>

namespace {

using pwb::domain::Json;
using pwb::workflow_runtime::CartographicQaDelegate;
using pwb::workflow_runtime::CartographicQaInputs;
using pwb::workflow_runtime::MapQcInputs;
using pwb::workflow_runtime::QcIssueFields;
using pwb::workflow_runtime::QcProvenanceSink;
using pwb::workflow_runtime::QcRunDeps;
using pwb::workflow_runtime::QcRunRegistration;

int failures = 0;
int checks = 0;

Json read_fixture(const char* path) {
    std::ifstream in(path);
    if (!in) {
        throw std::runtime_error(std::string("cannot open fixture: ") + path);
    }
    Json data;
    try {
        in >> data;
    } catch (const std::exception& exc) {
        throw std::runtime_error(std::string("fixture parse error: ") +
                                 exc.what());
    }
    return data;
}

bool equals(const Json& left, const Json& right) {
    return pwb::domain::json_semantically_equal(left, right);
}

void report_mismatch(const std::string& id, const Json& got,
                     const Json& expect) {
    const auto diff = pwb::domain::json_semantic_diff(got, expect);
    std::printf("FAIL %s at %s: %s\n  got:    %s\n  expect: %s\n",
                id.c_str(), diff.path.c_str(), diff.reason.c_str(),
                got.dump().c_str(), expect.dump().c_str());
    ++failures;
}

// The frozen expectations went through Python's JSON serialization;
// normalize the computed side the same way (int/unsigned and float
// spellings collapse exactly like Python's json round-trip).
void compare(const std::string& id, const Json& got_in, const Json& expect) {
    ++checks;
    if (expect.contains("raise")) {
        if (got_in.contains("raise") && got_in.at("raise") == expect.at("raise")) {
            return;
        }
        report_mismatch(id, got_in, expect);
        return;
    }
    if (got_in.contains("raise")) {
        report_mismatch(id, got_in, expect);
        return;
    }
    const Json got = Json::parse(got_in.dump());
    if (!equals(got, expect.at("result"))) {
        report_mismatch(id, got, expect.at("result"));
    }
}

// The qc.py / map_qa_rules.py public surface raises exactly one exception
// class (ValueError for unknown map documents); the port throws
// std::invalid_argument with the identical message.
Json raise_payload(const std::exception& exc) {
    return Json{{"raise",
                 Json{{"python_class", "ValueError"},
                      {"message", exc.what()}}}};
}

// --------------------------------------------------------- frozen clock --

struct FrozenClockState {
    std::string now_iso;
    std::vector<std::string> ids;
    std::size_t next_id = 0;
};

pwb::project::ModelClock make_clock(FrozenClockState& state) {
    pwb::project::ModelClock clock;
    clock.now_iso = [&state] { return state.now_iso; };
    clock.make_id = [&state](std::string_view prefix) {
        if (state.next_id < state.ids.size()) {
            return state.ids[state.next_id++];
        }
        return std::string(prefix) + "_frozen_unexpected";
    };
    return clock;
}

FrozenClockState clock_from_input(const Json& input) {
    FrozenClockState state;
    if (input.contains("clock") && input.at("clock").is_object()) {
        const Json& clock = input.at("clock");
        if (const auto it = clock.find("now_iso");
            it != clock.end() && it->is_string()) {
            state.now_iso = it->get<std::string>();
        }
        if (const auto it = clock.find("ids");
            it != clock.end() && it->is_array()) {
            for (const Json& id : *it) {
                if (id.is_string()) {
                    state.ids.push_back(id.get<std::string>());
                }
            }
        }
    }
    return state;
}

// ----------------------------------------------------------- input views --

MapQcInputs parse_map_qc_inputs(const Json& inputs) {
    MapQcInputs result;
    if (!inputs.is_object()) {
        return result;
    }
    if (const auto it = inputs.find("map_extent");
        it != inputs.end() && it->is_array() && it->size() == 4) {
        std::array<double, 4> extent{};
        bool ok = true;
        for (std::size_t i = 0; i < 4; ++i) {
            if (!(*it)[i].is_number()) {
                ok = false;
                break;
            }
            extent[i] = (*it)[i].get<double>();
        }
        if (ok) {
            result.map_extent = extent;
        }
    }
    if (const auto it = inputs.find("fusion_confidence");
        it != inputs.end() && !it->is_null()) {
        result.fusion_confidence = *it;
    }
    if (const auto it = inputs.find("confidence_threshold");
        it != inputs.end() && it->is_number()) {
        result.confidence_threshold = it->get<double>();
    }
    if (const auto it = inputs.find("export_report");
        it != inputs.end() && !it->is_null()) {
        result.export_report = *it;
    }
    return result;
}

QcIssueFields parse_issue_fields(const Json& fields) {
    QcIssueFields result;
    if (!fields.is_object()) {
        return result;
    }
    if (const auto it = fields.find("feature_id");
        it != fields.end() && it->is_string()) {
        result.feature_id = it->get<std::string>();
    }
    if (const auto it = fields.find("feature_kind");
        it != fields.end() && it->is_string()) {
        result.feature_kind = it->get<std::string>();
    }
    if (const auto it = fields.find("ref");
        it != fields.end() && it->is_string()) {
        result.ref = it->get<std::string>();
    }
    if (const auto it = fields.find("geometry");
        it != fields.end() && !it->is_null()) {
        result.geometry = *it;
    }
    if (const auto it = fields.find("extra");
        it != fields.end() && it->is_object() && !it->empty()) {
        result.extra = *it;
    }
    return result;
}

// ------------------------------------------------------------- dispatch --

void dispatch_case(const std::string& id, const std::string& fn,
                   const Json& input, const Json& expect) {
    if (fn == "qc.make_issue") {
        const Json& fields =
            input.contains("fields") ? input.at("fields") : Json(nullptr);
        compare(id,
                pwb::workflow_runtime::make_issue(
                    input.at("rule").get<std::string>(),
                    input.at("severity").get<std::string>(),
                    input.at("message").get<std::string>(),
                    parse_issue_fields(fields)),
                expect);
        return;
    }
    if (fn == "qc.spatial_issues") {
        const Json issues =
            input.contains("issues") ? input.at("issues") : Json(nullptr);
        compare(id, pwb::workflow_runtime::spatial_issues(issues), expect);
        return;
    }
    if (fn == "qc.issue_layer_geojson") {
        std::optional<pwb::project::QualityReport> report;
        if (input.at("report").is_object()) {
            report = pwb::project::QualityReport::from_dict(
                input.at("report"));
        }
        std::optional<std::string> map_document_id;
        if (input.at("map_document_id").is_string()) {
            map_document_id = input.at("map_document_id").get<std::string>();
        }
        compare(id,
                pwb::workflow_runtime::issue_layer_geojson(report,
                                                           map_document_id),
                expect);
        return;
    }
    if (fn == "qc.active_quality_reports") {
        Json out = Json::array();
        for (const auto& report : pwb::workflow_runtime::
                 active_quality_reports(input.at("project"))) {
            out.push_back(report.to_dict());
        }
        compare(id, out, expect);
        return;
    }
    if (fn == "qc.run_basic_qc") {
        Json project = input.at("project");
        FrozenClockState clock_state = clock_from_input(input);
        QcRunDeps deps;
        deps.clock = make_clock(clock_state);
        try {
            const auto report = pwb::workflow_runtime::run_basic_qc(
                project, input.at("map_document_id").get<std::string>(),
                input.at("bind_active_run").get<bool>(), deps);
            compare(id,
                    Json{{"report", report.to_dict()}, {"project", project}},
                    expect);
        } catch (const std::exception& exc) {
            compare(id, raise_payload(exc), expect);
        }
        return;
    }
    if (fn == "qc.run_map_qc") {
        Json project = input.at("project");
        FrozenClockState clock_state = clock_from_input(input);
        QcRunDeps deps;
        deps.clock = make_clock(clock_state);
        const MapQcInputs inputs = parse_map_qc_inputs(
            input.contains("inputs") ? input.at("inputs") : Json(nullptr));
        try {
            const auto report = pwb::workflow_runtime::run_map_qc(
                project, input.at("map_document_id").get<std::string>(),
                input.at("bind_active_run").get<bool>(), inputs, deps);
            compare(id,
                    Json{{"report", report.to_dict()}, {"project", project}},
                    expect);
        } catch (const std::exception& exc) {
            compare(id, raise_payload(exc), expect);
        }
        return;
    }
    if (fn == "mapqa.collect_extended_qc_issues") {
        const MapQcInputs inputs = parse_map_qc_inputs(
            input.contains("inputs") ? input.at("inputs") : Json(nullptr));
        compare(id,
                pwb::workflow_runtime::collect_extended_qc_issues(
                    input.at("project"), input.at("document"), inputs),
                expect);
        return;
    }
    if (fn == "mapqa.extended_rule_coverage") {
        const MapQcInputs inputs = parse_map_qc_inputs(
            input.contains("inputs") ? input.at("inputs") : Json(nullptr));
        compare(id, pwb::workflow_runtime::extended_rule_coverage(inputs),
                expect);
        return;
    }
    if (fn == "mapqa.composition_qa_issues") {
        compare(id,
                pwb::workflow_runtime::composition_qa_issues(
                    input.at("composition")),
                expect);
        return;
    }
    std::printf("FAIL %s: unknown fn %s\n", id.c_str(), fn.c_str());
    ++failures;
}

// ------------------------------------------------ comparator negative check

void comparator_self_check(const Json& fixture) {
    // Tamper three output fields of a real frozen case in memory and prove
    // the comparison FAILS for each (fixture integrity guard).
    const Json* target = nullptr;
    for (const Json& item : fixture.at("cases")) {
        if (item.at("id").get<std::string>() == "mapqc.all_skip_inputs") {
            target = &item;
            break;
        }
    }
    if (target == nullptr) {
        std::printf("FAIL comparator self-check: case not found\n");
        ++failures;
        return;
    }
    Json project = target->at("input").at("project");
    FrozenClockState clock_state = clock_from_input(target->at("input"));
    QcRunDeps deps;
    deps.clock = make_clock(clock_state);
    const auto report = pwb::workflow_runtime::run_map_qc(
        project, target->at("input").at("map_document_id").get<std::string>(),
        target->at("input").at("bind_active_run").get<bool>(),
        parse_map_qc_inputs(target->at("input").at("inputs")), deps);
    const Json got = Json::parse(
        Json{{"report", report.to_dict()}, {"project", project}}.dump());

    const Json& frozen =
        target->at("expect").at("result").at("report");
    int caught = 0;
    const int expected_caught = 3;

    {  // 1) status tampered
        Json tampered = frozen;
        tampered["status"] = "pass";
        if (equals(got.at("report"), tampered)) {
            std::printf("FAIL comparator self-check: status tamper not caught\n");
            ++failures;
        } else {
            ++caught;
        }
    }
    {  // 2) coverage skipped tampered (int)
        Json tampered = frozen;
        tampered["coverage"]["skipped"] = 1;
        if (equals(got.at("report"), tampered)) {
            std::printf("FAIL comparator self-check: coverage tamper not caught\n");
            ++failures;
        } else {
            ++caught;
        }
    }
    {  // 3) one issue message tampered (verbatim Chinese message guard)
        Json tampered = frozen;
        tampered["issues"][3]["message"] = "篡改的消息";
        if (equals(got.at("report"), tampered)) {
            std::printf("FAIL comparator self-check: message tamper not caught\n");
            ++failures;
        } else {
            ++caught;
        }
    }
    if (caught == expected_caught) {
        std::printf("comparator self-check: OK (%d tampers caught)\n", caught);
    }
}

// ------------------------------------------------------ C++-only seam checks

class RecordingSink final : public QcProvenanceSink {
public:
    struct Call {
        std::string name;
        std::vector<std::string> source_task_ids;
        std::string domain_task_id;
        Json parameters;
        Json report_json;
    };
    std::vector<Call> calls;
    bool succeed = true;
    bool throw_on_call = false;

    std::optional<QcRunRegistration> register_qc_run(
        const std::string& name,
        const std::vector<std::string>& source_task_ids,
        const std::string& domain_task_id, const Json& parameters,
        const Json& report_json) override {
        if (throw_on_call) {
            throw std::runtime_error("sink exploded");
        }
        calls.push_back(Call{name, source_task_ids, domain_task_id,
                            parameters, report_json});
        if (!succeed) {
            return std::nullopt;
        }
        return QcRunRegistration{"run_new", "ver_new"};
    }
};

void seam_self_checks() {
    // A minimal project: one document with a linked prediction task.
    Json project = Json::parse(R"({
      "meta": {"name": "seam", "created_at": "t0", "updated_at": "t0"},
      "paleomap_documents": [
        {"id": "map_s", "name": "缝检查图", "linked_target_horizon": "H1",
         "linked_prediction_task_id": "pred_9"}
      ],
      "quality_reports": [],
      "compilation_runs": [
        {"id": "run_s", "name": "R", "target_horizon": "H1", "status": "draft",
         "workflow_steps": [], "active_factor_map_task_ids": [],
         "active_prediction_task_id": null, "active_paleomap_document_id": null,
         "active_quality_report_id": null, "export_artifact_ids": [],
         "created_at": "t0", "updated_at": "t0"}
      ]
    })");
    FrozenClockState clock_state;
    clock_state.now_iso = "2026-01-01T00:00:00+00:00";
    clock_state.ids = {"qc_seam01"};
    QcRunDeps deps;
    deps.clock = make_clock(clock_state);

    // 1) successful registration flips provenance_registered and feeds the
    //    seam the Python call-site payload (name/task ids/parameters), with
    //    the serialized report still carrying provenance_registered=false
    //    (Python dumps the temp file before flipping the flag).
    {
        RecordingSink sink;
        QcRunDeps with_sink = deps;
        with_sink.provenance_sink = &sink;
        const auto report = pwb::workflow_runtime::run_basic_qc(
            project, "map_s", true, with_sink);
        ++checks;
        if (!report.provenance_registered || sink.calls.size() != 1) {
            std::printf("FAIL seam: registration outcome not visible\n");
            ++failures;
        } else {
            const RecordingSink::Call& call = sink.calls.front();
            const bool payload_ok =
                call.name == "QC 缝检查图" &&
                call.source_task_ids ==
                    std::vector<std::string>{"map_s"} &&
                call.domain_task_id == "pred_9" &&
                call.parameters ==
                    Json{{"map_document_id", "map_s"},
                         {"qc_status", report.status}} &&
                call.report_json.at("id") == report.id &&
                call.report_json.at("provenance_registered") == false;
            if (!payload_ok) {
                std::printf("FAIL seam: registration payload mismatch\n");
                ++failures;
            }
        }
    }

    // 2) run_qc None (nullopt) keeps the report visibly unregistered.
    {
        RecordingSink sink;
        sink.succeed = false;
        QcRunDeps with_sink = deps;
        with_sink.provenance_sink = &sink;
        const auto report = pwb::workflow_runtime::run_basic_qc(
            project, "map_s", true, with_sink);
        ++checks;
        if (report.provenance_registered) {
            std::printf("FAIL seam: nullopt registration must stay false\n");
            ++failures;
        }
    }

    // 3) a throwing sink must not fail the QC run (Python broad except).
    {
        RecordingSink sink;
        sink.throw_on_call = true;
        QcRunDeps with_sink = deps;
        with_sink.provenance_sink = &sink;
        bool threw = false;
        try {
            const auto report = pwb::workflow_runtime::run_basic_qc(
                project, "map_s", true, with_sink);
            threw = report.provenance_registered;
        } catch (...) {
            threw = true;
        }
        ++checks;
        if (threw) {
            std::printf("FAIL seam: sink exception escaped or flagged true\n");
            ++failures;
        }
    }

    // 4) defensive Json-seam branch: a well row without x/y degrades to a
    //    non-spatial issue (unreachable from Python's typed models).
    {
        Json seam_project = Json::parse(R"({
          "meta": {"name": "row"},
          "paleomap_documents": [
            {"id": "map_r", "name": "行检查", "linked_target_horizon": "H1"}
          ],
          "well_tables": [
            {"id": "wt_r", "name": "表", "target_horizon": "H1",
             "rows": [{"well_id": "well_x", "name": "W-X", "qc_flag": "outlier"}]}
          ]
        })");
        const Json issues = pwb::workflow_runtime::collect_extended_qc_issues(
            seam_project, seam_project["paleomap_documents"][0], MapQcInputs{});
        (void)issues;
        const Json basic = pwb::workflow_runtime::spatial_issues(
            seam_project);  // no-op shape check for null tolerance
        (void)basic;
        Json row_project = seam_project;
        // run_basic_qc freezes the row issue without geometry/centroid.
        FrozenClockState row_clock;
        row_clock.now_iso = "2026-01-01T00:00:00+00:00";
        row_clock.ids = {"qc_row01"};
        QcRunDeps row_deps;
        row_deps.clock = make_clock(row_clock);
        const auto report = pwb::workflow_runtime::run_basic_qc(
            row_project, "map_r", false, row_deps);
        ++checks;
        const Json* row_issue = nullptr;
        for (const Json& issue : report.issues) {
            if (issue.value("rule", "") == "well_table_qc_clean") {
                row_issue = &issue;
            }
        }
        if (row_issue == nullptr || row_issue->contains("geometry") ||
            row_issue->contains("centroid") ||
            row_issue->at("message") != "井点 W-X 质控=outlier") {
            std::printf("FAIL seam: malformed row did not degrade to a "
                        "non-spatial issue\n");
            ++failures;
        }
    }

    // 5) cartographic_issues forwards project + inputs to the delegate
    //    verbatim (D7 thin delegate).
    {
        const Json project_view = Json{{"meta", Json{{"name", "cart"}}}};
        CartographicQaInputs inputs;
        inputs.snapshot = Json{{"v", 7}};
        inputs.confidence_threshold = 0.9;
        bool forwarded = false;
        CartographicQaDelegate delegate =
            [&](const Json& p, const CartographicQaInputs& in) -> Json {
            forwarded = p == project_view && in.snapshot == inputs.snapshot &&
                        in.confidence_threshold == 0.9;
            return Json::array({Json{{"rule", "delegate_marker"}}});
        };
        const Json out = pwb::workflow_runtime::cartographic_issues(
            project_view, inputs, delegate);
        ++checks;
        if (!forwarded || out.size() != 1 ||
            out[0].at("rule") != "delegate_marker") {
            std::printf("FAIL seam: cartographic delegate not forwarded\n");
            ++failures;
        }
    }
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 2) {
        std::fprintf(stderr, "usage: %s <fixture.json>\n", argv[0]);
        return 2;
    }
    const Json fixture = read_fixture(argv[1]);
    int total = 0;
    for (const Json& item : fixture.at("cases")) {
        ++total;
        dispatch_case(item.at("id").get<std::string>(),
                      item.at("fn").get<std::string>(), item.at("input"),
                      item.at("expect"));
    }
    comparator_self_check(fixture);
    seam_self_checks();
    if (failures != 0) {
        std::printf("%d/%d cases FAILED (%d checks)\n", failures, total,
                    checks);
        return 1;
    }
    std::printf("all %d cases passed (%d checks)\n", total, checks);
    return 0;
}
