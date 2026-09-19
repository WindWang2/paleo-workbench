// workflow_engine.receipt_plan_view — CONV-32 execution receipts + plan
// views vs the frozen Python oracle (workflow_receipt_plan_view_oracle.json,
// generated from the REAL dag/receipt.py + dag/plan_view.py by
// tools/oracle/generate_workflow_receipt_plan_view_fixtures.py with the
// environment/clock seams frozen). Covers: to_dict key order + rounding,
// degraded reasons, version-id collection (dedupe keep-first), output
// redaction, from_dict coercions (defaults + null tolerance), plan views
// (mixed run, checklist edges, from_summary with/without spec, order
// restore, empty spec, state labels incl. the graceful unknown-state
// divergence) and the full symbol map. In-test negative self-checks tamper
// frozen expectations and require the comparator to catch them.

#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <optional>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/workflow_engine/plan_view.hpp>
#include <pwb/workflow_engine/receipt.hpp>

using pwb::domain::Json;
namespace we = pwb::workflow_engine;
namespace ws = pwb::workflow_spec;

namespace {

int g_checks = 0;
int g_negative_checks = 0;
int g_failures = 0;

void check(bool ok, const std::string& what) {
    if (ok) {
        ++g_checks;
        return;
    }
    ++g_failures;
    std::fprintf(stderr, "FAIL %s\n", what.c_str());
}

Json load_fixture(int argc, char** argv) {
    const char* path = argc > 1 ? argv[1]
                                : "workflow_receipt_plan_view_oracle.json";
    std::ifstream stream(path, std::ios::binary);
    if (!stream.good()) {
        std::fprintf(stderr, "FAIL cannot open %s\n", path);
        std::exit(1);
    }
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    return Json::parse(buffer.str());
}

// Type-sensitive comparison with Python json semantics: int vs float is a
// KIND difference (1 != 1.0), signed vs unsigned integers are one kind
// (the fixture parse and the C++ producers may differ in signedness),
// floats compare exactly (both sides serialise through the same shortest
// round-trip decimal). Objects compare by key SET here; key ORDER is
// asserted separately below.
std::string value_diff(const Json& left, const Json& right,
                       const std::string& path) {
    if (left.is_number() && right.is_number()) {
        if (left.is_number_float() != right.is_number_float()) {
            return path + ": number kind differs (int vs float): "
                + left.dump() + " vs " + right.dump();
        }
        if (left == right) return "";
        return path + ": number value differs: " + left.dump() + " vs "
            + right.dump();
    }
    if (left.type() != right.type()) {
        return path + ": type differs: " + left.dump() + " vs " + right.dump();
    }
    if (left.is_object()) {
        if (left.size() != right.size()) {
            return path + ": object size differs: "
                + std::to_string(left.size()) + " vs "
                + std::to_string(right.size());
        }
        for (auto it = left.begin(); it != left.end(); ++it) {
            if (!right.contains(it.key())) {
                return path + "." + it.key() + ": missing on right";
            }
            const std::string diff =
                value_diff(it.value(), right.at(it.key()),
                           path + "." + it.key());
            if (!diff.empty()) return diff;
        }
        for (auto it = right.begin(); it != right.end(); ++it) {
            if (!left.contains(it.key())) {
                return path + "." + it.key() + ": missing on left";
            }
        }
        return "";
    }
    if (left.is_array()) {
        if (left.size() != right.size()) {
            return path + ": array length differs: "
                + std::to_string(left.size()) + " vs "
                + std::to_string(right.size());
        }
        for (std::size_t i = 0; i < left.size(); ++i) {
            const std::string diff = value_diff(
                left[i], right[i], path + "[" + std::to_string(i) + "]");
            if (!diff.empty()) return diff;
        }
        return "";
    }
    if (left == right) return "";
    return path + ": value differs: " + left.dump() + " vs " + right.dump();
}

// Insertion-order comparison (both sides are ordered_json: the fixture
// keeps the Python dict order, the C++ to_dict emits the frozen member
// order). Only objects carry a key order; array element order recurses
// pairwise; leaves are value-typed and already covered by value_diff (the
// strict type() check there would false-fire on C++ int vs
// fixture-parsed unsigned).
bool key_order_equal(const Json& left, const Json& right) {
    if (left.is_object() && right.is_object()) {
        auto li = left.begin();
        auto ri = right.begin();
        for (; li != left.end() && ri != right.end(); ++li, ++ri) {
            if (li.key() != ri.key()) return false;
            if (!key_order_equal(li.value(), ri.value())) return false;
        }
        return li == left.end() && ri == right.end();
    }
    if (left.is_array() && right.is_array()) {
        if (left.size() != right.size()) return false;
        for (std::size_t i = 0; i < left.size(); ++i) {
            if (!key_order_equal(left[i], right[i])) return false;
        }
    }
    return true;
}

void expect_exact(const Json& got, const Json& want, const std::string& label) {
    const std::string diff = value_diff(got, want, "$");
    check(diff.empty(), label + (diff.empty() ? "" : " | " + diff));
    check(key_order_equal(got, want), label + " | key order mismatch");
}

Json str_array(const std::vector<std::string>& values) {
    Json array = Json::array();
    for (const std::string& value : values) array.push_back(value);
    return array;
}

// A healthy comparator must reject tampered expectations; each call proves
// one tamper is caught (value diff OR key-order diff fires).
void negative_self_check(const Json& got, const Json& tampered,
                         const std::string& label) {
    const bool values_equal = value_diff(got, tampered, "$").empty();
    const bool order_equal = key_order_equal(got, tampered);
    check(!values_equal || !order_equal, label + ": tamper must be detected");
    ++g_negative_checks;
}

const we::EnvironmentProvider frozen_env = [] {
    return we::EnvironmentIdentity{"3.11.9", "Linux-6.9.0-x86_64", "8.0.0"};
};
const we::Clock frozen_clock = [] { return 1700000000.0; };

// ------------------------------------------------------------- receipt ---

// Cases 1-6; returns the case-1 produced dict for the tamper self-checks.
Json receipt_checks(const Json& fixture) {
    // Environment seam layout.
    {
        const we::EnvironmentIdentity env = frozen_env();
        expect_exact(env.to_dict(), fixture["frozen_environment"],
                     "environment_identity to_dict");
    }

    // 1 — succeeded node, full to_dict.
    Json got1;
    {
        we::ActionResultView result;
        result.status = "success";
        result.outputs = Json{{"count", 3},
                              {"path", "/tmp/x"},
                              {"flag", true},
                              {"none", nullptr}};
        result.metrics = Json{
            {"provenance", Json{{"provider_id", "contour"},
                                {"provider_version", "2.1"},
                                {"run_id", "cat-7"}}},
            {"rows", 42}};
        result.verification = Json{{"checks", 2}, {"passed", 2}};
        result.elapsed_ms = 1234.5678;
        we::BuildReceiptArgs args;
        args.node_id = "interp";
        args.workflow_run_id = "run-42";
        args.action_id = "map.interpolate_idw";
        args.action_version = "1.2.0";
        args.description = "克里金插值";
        args.parameters = Json{{"method", "idw"}, {"power", 2.0}};
        args.input_version_ids = {"dv-a", "dv-b"};
        args.estimated_resources = Json{{"cpu_seconds", 1.5}};
        args.resource_category = "compute";
        args.started_at = 1699999999.5;
        got1 = we::build_receipt(result, args, frozen_env, frozen_clock).to_dict();
        expect_exact(got1, fixture["succeeded_to_dict"],
                     "case1 succeeded to_dict");
    }

    // 2 — degraded reasons.
    {
        we::ActionResultView result;
        result.status = "degraded";
        result.warnings = {"低精度插值", "边缘裁剪"};
        result.elapsed_ms = 10.0;
        we::BuildReceiptArgs args;
        args.node_id = "n2";
        args.action_id = "qc.check";
        args.action_version = "0.3";
        args.description = "质检";
        expect_exact(
            we::build_receipt(result, args, frozen_env, frozen_clock).to_dict(),
            fixture["degraded"]["with_warnings"],
            "case2 degraded with warnings");

        we::ActionResultView quiet;
        quiet.status = "degraded";
        const Json quiet_dict =
            we::build_receipt(quiet, we::BuildReceiptArgs{}, frozen_env,
                              frozen_clock)
                .to_dict();
        check(quiet_dict["degraded_reason"]
                  == fixture["degraded"]["empty_warnings"]["degraded_reason"],
              "case2 empty-warnings degraded_reason");
        check(quiet_dict["status"]
                  == fixture["degraded"]["empty_warnings"]["status"],
              "case2 empty-warnings status");
    }

    // 3 — empty outputs.
    {
        we::ActionResultView result;
        result.elapsed_ms = 0.5;
        we::BuildReceiptArgs args;
        args.node_id = "n";
        const Json dict =
            we::build_receipt(result, args, frozen_env, frozen_clock).to_dict();
        expect_exact(dict["outputs_summary"],
                     fixture["empty_outputs"]["outputs_summary"],
                     "case3 outputs_summary");
        expect_exact(dict["output_version_ids"],
                     fixture["empty_outputs"]["output_version_ids"],
                     "case3 output_version_ids");
    }

    // 4 — version id collection: dedupe keep-first, artifacts ->
    // version_ids -> singular; plain-string artifact versions do not count.
    {
        Json outputs;
        outputs["artifacts"] = Json::array({
            Json{{"version", Json{{"version_id", "v1"}}}},
            Json{{"version", "v1"}},
            Json{{"version", Json{{"version_id", "v2"}}}},
        });
        outputs["version_ids"] = Json::array({"v2", "v3"});
        outputs["version_id"] = "v4";
        expect_exact(str_array(we::collect_output_version_ids(outputs)),
                     fixture["version_ids_dedupe"], "case4 version ids");
    }

    // 5 — output redaction + in-process handles + array/scalar pass-through.
    {
        Json redaction;
        redaction["artifacts"] = Json::array({1, 2, 3, 4, 5});
        redaction["rows"] = Json{{"a", 1}, {"b", 2}};
        redaction["flag"] = true;
        expect_exact(we::summarize_outputs(redaction),
                     fixture["summarize"]["redaction"], "case5 redaction");

        Json handles;
        handles["values"] = Json::array({1, 2});
        handles["map_document"] = Json{{"z", 1}};
        handles["document"] = "doc";
        handles["composition"] = 7;
        expect_exact(we::summarize_outputs(handles),
                     fixture["summarize"]["in_process_handles"],
                     "case5 in-process handles");

        Json scalars;
        scalars["stops"] = Json::array({1, 2, 3});
        scalars["ratio"] = 0.25;
        scalars["empty"] = "";
        scalars["zero"] = 0;
        scalars["none"] = nullptr;
        scalars["txt"] = "ok";
        expect_exact(we::summarize_outputs(scalars),
                     fixture["summarize"]["arrays_and_scalars"],
                     "case5 arrays and scalars");
    }

    // 6 — from_dict round-trip, {} defaults, null tolerance.
    {
        expect_exact(we::ExecutionReceipt::from_dict(
                         fixture["succeeded_to_dict"])
                         .to_dict(),
                     fixture["from_dict"]["roundtrip"], "case6 roundtrip");
        expect_exact(
            we::ExecutionReceipt::from_dict(Json::object()).to_dict(),
            fixture["from_dict"]["defaults"], "case6 defaults");
        const Json nulls = Json{
            {"node_id", nullptr},
            {"workflow_run_id", nullptr},
            {"provider_id", nullptr},
            {"provider_version", nullptr},
            {"resource_category", nullptr},
            {"parameters", nullptr},
            {"estimated_resources", nullptr},
            {"input_version_ids", nullptr},
            {"output_version_ids", nullptr},
            {"outputs_summary", nullptr},
            {"verification", nullptr},
            {"qc_metrics", nullptr},
            {"warnings", nullptr},
            {"started_at", nullptr},
            {"finished_at", nullptr},
            {"degraded_reason", nullptr},
            {"error", nullptr},
            {"cache_identity", nullptr},
            {"environment", nullptr},
            {"action_id", nullptr},
            {"status", nullptr},
        };
        expect_exact(we::ExecutionReceipt::from_dict(nulls).to_dict(),
                     fixture["from_dict"]["null_tolerance"],
                     "case6 null tolerance");
    }

    return got1;
}

// ----------------------------------------------------------- plan view ---

ws::WorkflowSpec litho_spec() {
    ws::WorkflowSpec spec;
    spec.workflow_id = "wf.litho";
    spec.name = "岩性制图";
    ws::NodeSpec a;
    a.node_id = "a";
    a.action_id = "qc.validate_inputs";
    a.description = "输入检查";
    ws::NodeSpec b;
    b.node_id = "b";
    b.action_id = "map.interpolate_idw";
    b.description = "插值";
    b.depends_on = {"a"};
    ws::NodeSpec c;
    c.node_id = "c";
    c.action_id = "map.render_composition";
    c.description = "编图";
    c.depends_on = {"b"};
    spec.nodes = {std::move(a), std::move(b), std::move(c)};
    return spec;
}

ws::NodeRun node_run(const std::string& id, ws::NodeState state) {
    ws::NodeRun run;
    run.node_id = id;
    run.state = state;
    return run;
}

ws::WorkflowRun make_run(const ws::WorkflowSpec& spec, ws::RunState state,
                         std::vector<std::pair<std::string, ws::NodeRun>> runs) {
    ws::WorkflowRun run;
    run.run_id = "run-0";
    run.workflow = spec;
    run.state = state;
    run.node_runs = std::move(runs);
    return run;
}

// Cases 7-13; returns the case-7 produced dict for the tamper self-checks.
Json plan_view_checks(const Json& fixture) {
    const ws::WorkflowSpec spec = litho_spec();

    // 7 — mixed run: succeeded/running/pending -> ✓●○, progress 0.333,
    // current 插值, running row detail "33%".
    Json got7;
    {
        ws::NodeRun a = node_run("a", ws::NodeState::succeeded);
        a.receipt = Json{{"status", "degraded"}};
        const ws::WorkflowRun run = make_run(
            spec, ws::RunState::running,
            {{"a", std::move(a)},
             {"b", node_run("b", ws::NodeState::running)},
             {"c", node_run("c", ws::NodeState::pending)}});
        got7 = we::WorkflowPlanView::from_run(run).to_dict();
        expect_exact(got7, fixture["plan_mixed_run"]["from_run"],
                     "case7 from_run");
        expect_exact(we::WorkflowPlanView::from_spec(spec).to_dict(),
                     fixture["plan_mixed_run"]["from_spec"],
                     "case7 from_spec");
    }

    // 8 — checklist edges: skipped condition vs upstream failure, details
    // verbatim; from_cache row; failed run label.
    {
        ws::WorkflowSpec spec8;
        spec8.workflow_id = "wf.litho8";
        spec8.name = "岩性制图";
        ws::NodeSpec a;
        a.node_id = "a";
        a.action_id = "qc.validate_inputs";
        a.description = "输入检查";
        ws::NodeSpec b;
        b.node_id = "b";
        b.action_id = "map.interpolate_idw";
        b.description = "插值";
        b.depends_on = {"a"};
        ws::NodeSpec c;
        c.node_id = "c";
        c.action_id = "qc.check_condition";
        c.description = "质检";
        c.depends_on = {"a"};
        ws::NodeSpec d;
        d.node_id = "d";
        d.action_id = "io.export_map";
        d.description = "导出";
        d.depends_on = {"b"};
        spec8.nodes = {std::move(a), std::move(b), std::move(c), std::move(d)};

        ws::NodeRun sa = node_run("a", ws::NodeState::succeeded);
        sa.from_cache = true;
        sa.receipt = Json{{"status", "success"}};
        ws::NodeRun fb = node_run("b", ws::NodeState::failed);
        fb.error = "插值失败";
        ws::NodeRun sc = node_run("c", ws::NodeState::skipped);
        sc.skip_reason = "条件未满足";
        ws::NodeRun sd = node_run("d", ws::NodeState::skipped);
        sd.skip_reason = "upstream b failed";
        const ws::WorkflowRun run = make_run(
            spec8, ws::RunState::failed,
            {{"a", std::move(sa)},
             {"b", std::move(fb)},
             {"c", std::move(sc)},
             {"d", std::move(sd)}});
        expect_exact(we::WorkflowPlanView::from_run(run).to_dict(),
                     fixture["checklist_edges"], "case8 checklist edges");
    }

    // 9 — from_summary with and without the spec.
    {
        const Json summary = Json{
            {"workflow_id", "wf.litho"},
            {"name", "岩性制图"},
            {"state", "interrupted"},
            {"progress", 0.5},
            {"nodes",
             Json{
                 {"a", Json{{"state", "succeeded"},
                            {"from_cache", true},
                            {"receipt_status", "success"}}},
                 {"b", Json{{"state", "running"}, {"label", "自定义标签"}}},
                 {"x", Json{{"state", "pending"}, {"label", "幽灵节点"}}},
             }},
        };
        expect_exact(we::WorkflowPlanView::from_summary(summary, &spec).to_dict(),
                     fixture["from_summary"]["with_spec"],
                     "case9 from_summary with spec");
        expect_exact(we::WorkflowPlanView::from_summary(summary).to_dict(),
                     fixture["from_summary"]["without_spec"],
                     "case9 from_summary without spec");
    }

    // 10 — ordering restore: node_runs inserted reversed, items land back
    // in spec node order after the stable sort.
    {
        const ws::WorkflowRun run = make_run(
            spec, ws::RunState::running,
            {{"c", node_run("c", ws::NodeState::succeeded)},
             {"b", node_run("b", ws::NodeState::running)},
             {"a", node_run("a", ws::NodeState::succeeded)}});
        expect_exact(we::WorkflowPlanView::from_run(run).to_dict(),
                     fixture["ordering_restore"], "case10 ordering restore");
    }

    // 11 — empty spec.
    {
        ws::WorkflowSpec empty;
        empty.workflow_id = "wf.empty";
        empty.name = "空工作流";
        expect_exact(we::WorkflowPlanView::from_spec(empty).to_dict(),
                     fixture["empty_spec"], "case11 empty spec");
    }

    // 12 — run-state labels + graceful unknown-state passthrough (Python
    // raises ValueError, frozen beside the graceful value).
    {
        const Json& labels = fixture["state_labels"]["labels"];
        for (auto it = labels.begin(); it != labels.end(); ++it) {
            we::WorkflowPlanView view;
            view.workflow_id = "w";
            view.name = "n";
            view.state = it.key();
            check(view.state_label() == it.value().get<std::string>(),
                  "case12 state_label '" + it.key() + "'");
        }
        const Json& unknown = fixture["state_labels"]["unknown_state"];
        we::WorkflowPlanView view;
        view.workflow_id = "w";
        view.name = "n";
        view.state = "paused";
        check(view.state_label() == unknown["graceful"].get<std::string>(),
              "case12 unknown state graceful passthrough");
        check(unknown["python_raises"].is_string(),
              "case12 python error frozen");
        check(view.to_dict()["state_label"] == "paused",
              "case12 to_dict survives unknown state");
    }

    // 13 — the full node-state symbol map.
    {
        const std::vector<std::pair<std::string, ws::NodeState>> states = {
            {"pending", ws::NodeState::pending},
            {"running", ws::NodeState::running},
            {"succeeded", ws::NodeState::succeeded},
            {"failed", ws::NodeState::failed},
            {"cancelled", ws::NodeState::cancelled},
            {"skipped", ws::NodeState::skipped},
            {"unavailable", ws::NodeState::unavailable},
        };
        for (const auto& [name, state] : states) {
            we::PlanItem item;
            item.node_id = "n";
            item.label = "行";
            item.state = state;
            expect_exact(item.to_dict(), fixture["symbols"][name],
                         "case13 symbol " + name);
        }
    }

    return got7;
}

// ------------------------------------------------- negative self-checks ---

void negative_self_checks(const Json& fixture, const Json& got1,
                          const Json& got7) {
    // Value tamper: duration_ms nudged by 1ms.
    {
        Json tampered = got1;
        tampered["duration_ms"] = 1234.569;
        negative_self_check(got1, tampered,
                            "negative duration_ms value tamper");
    }
    // Nested value tamper: the running row's symbol flipped.
    {
        Json tampered = got7;
        tampered["items"][1]["symbol"] = "○";
        negative_self_check(got7, tampered, "negative symbol value tamper");
    }
    // Kind tamper: int attempt vs float 1.0 (Python json 1 != 1.0).
    {
        Json tampered = got1;
        tampered["attempt"] = 1.0;
        negative_self_check(got1, tampered, "negative attempt int/float tamper");
    }
    // Key-order tamper: values identical, schema_version/node_id swapped.
    {
        Json tampered = Json::object();
        std::optional<Json> stash;
        for (const auto& [key, value] : fixture["succeeded_to_dict"].items()) {
            if (key == "schema_version") {
                stash = value;
                continue;
            }
            if (key == "node_id") {
                tampered["node_id"] = value;
                if (stash.has_value()) tampered["schema_version"] = *stash;
                continue;
            }
            tampered[key] = value;
        }
        check(stash.has_value(), "negative key-order tamper rebuilt");
        negative_self_check(got1, tampered, "negative key order tamper");
    }
}

}  // namespace

int main(int argc, char** argv) {
    const Json fixture = load_fixture(argc, argv);
    const Json got1 = receipt_checks(fixture);
    const Json got7 = plan_view_checks(fixture);
    negative_self_checks(fixture, got1, got7);

    if (g_failures == 0) {
        std::printf("ALL %d CHECKS PASSED (+%d negative self-checks)\n",
                    g_checks, g_negative_checks);
        return 0;
    }
    std::printf("FAIL: %d check(s) failed (%d passed, +%d negative "
                "self-checks)\n",
                g_failures, g_checks, g_negative_checks);
    return 1;
}
