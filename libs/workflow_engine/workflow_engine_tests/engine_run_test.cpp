// workflow_engine.run — C++ in-memory DAG engine vs the frozen Python
// oracle (workflow_engine_oracle.json, generated from the REAL
// implementations by tools/oracle/generate_workflow_engine_fixtures.py).
// Covers: topological order, failure short-circuit (frozen validate
// message), cooperative cancel (inside op + pre-cancelled), per-node
// stdout-level logs, $ref binding (incl. frozen BindingError message) and
// the frozen validation problem lists.

#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/mapping/interpolator.hpp>
#include <pwb/workflow_engine/engine.hpp>
#include <pwb/workflow_engine/ops.hpp>

using pwb::domain::Json;
namespace we = pwb::workflow_engine;
using we::CancelToken;
using we::Engine;
using we::NodeRegistry;
using we::NodeSpec;
using we::NodeState;
using we::RunState;
using we::ValidationError;
using we::WorkflowSpec;
using we::WorkflowRun;

namespace {

int g_failures = 0;

void check(bool ok, const std::string& what) {
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

Json load_fixture() {
    std::ifstream stream(PWB_ENGINE_FIXTURE, std::ios::binary);
    if (!stream.good()) {
        std::fprintf(stderr, "FAIL cannot open %s\n", PWB_ENGINE_FIXTURE);
        std::exit(1);
    }
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    return Json::parse(buffer.str());
}

// Log sink that keeps every line for assertions.
struct LogCapture {
    std::vector<std::string> lines;
    we::LogSink sink() {
        return [this](const std::string& line) { lines.push_back(line); };
    }
    bool contains(const std::string& needle) const {
        for (const std::string& line : lines) {
            if (line.find(needle) != std::string::npos) return true;
        }
        return false;
    }
    std::size_t first_index(const std::string& needle) const {
        for (std::size_t i = 0; i < lines.size(); ++i) {
            if (lines[i].find(needle) != std::string::npos) return i;
        }
        return lines.size();
    }
};

NodeRegistry make_registry() {
    NodeRegistry registry;
    we::register_builtin_ops(registry);
    we::register_mapping_ops(registry);
    registry.register_op(
        "test.fail",
        [](const Json&, const CancelToken&) -> we::NodeResult {
            throw std::runtime_error("boom");
        });
    return registry;
}

NodeSpec node(const std::string& id, const std::string& op,
              std::vector<std::string> deps = {}, Json params = Json::object()) {
    NodeSpec spec;
    spec.node_id = id;
    spec.op = op;
    spec.depends_on = std::move(deps);
    spec.params = std::move(params);
    return spec;
}

WorkflowSpec make_spec(const std::string& workflow_id,
                       std::vector<NodeSpec> nodes) {
    WorkflowSpec spec;
    spec.workflow_id = workflow_id;
    spec.nodes = std::move(nodes);
    return spec;
}

void check_close(const Json& got, const Json& want, double tol,
                 const std::string& label) {
    if (got.is_null() && want.is_null()) return;
    if (!got.is_number() || !want.is_number()) {
        check(false, label + ": type/null mismatch");
        return;
    }
    const double diff = std::fabs(got.get<double>() - want.get<double>());
    check(diff <= tol,
          label + ": diff " + std::to_string(diff) + " > " + std::to_string(tol));
}

// Nested grid rows (NaN → null on both sides).
void check_grid_rows(const Json& got_rows, const Json& want_rows, double tol,
                     const std::string& label) {
    check(got_rows.size() == want_rows.size(), label + ": row count");
    std::size_t cells = 0;
    for (std::size_t i = 0; i < got_rows.size() && i < want_rows.size(); ++i) {
        const Json& got_row = got_rows[i];
        const Json& want_row = want_rows[i];
        check(got_row.size() == want_row.size(), label + ": col count");
        for (std::size_t j = 0; j < got_row.size() && j < want_row.size(); ++j) {
            check_close(got_row[j], want_row[j], tol,
                        label + " cell[" + std::to_string(i) + "]["
                            + std::to_string(j) + "]");
            ++cells;
        }
    }
    check(cells > 0, label + ": non-empty grid");
}

// Flat coordinate axes (1-D arrays).
void check_axis(const Json& got, const Json& want, double tol,
                const std::string& label) {
    check(got.is_array() && want.is_array(), label + ": arrays");
    check(got.size() == want.size(), label + ": length");
    for (std::size_t i = 0; i < got.size() && i < want.size(); ++i) {
        check_close(got[i], want[i], tol,
                    label + "[" + std::to_string(i) + "]");
    }
}

void compare_extract_outputs(const we::NodeRun& extract, const Json& want) {
    check(extract.state == NodeState::succeeded, "extract node succeeded");
    const Json& out = extract.outputs;
    check(out["factor_name"] == want["factor_name"], "extract factor_name");
    check(out["unit"] == want["unit"], "extract unit (FACTOR_DEFAULTS)");
    check(out["target_horizon"] == want["target_horizon"], "extract horizon");
    check(out["crs"] == want["crs"], "extract crs");
    check(out["point_count"] == want["point_count"], "extract point_count");
    const Json& rows = want["points"];
    const Json& got = out["points"];
    check(got.size() == rows.size(), "extract points count");
    for (std::size_t i = 0; i < got.size() && i < rows.size(); ++i) {
        check_close(got[i][0], rows[i][0], 1e-12, "extract point x");
        check_close(got[i][1], rows[i][1], 1e-12, "extract point y");
        check_close(got[i][2], rows[i][2], 1e-12, "extract point value");
        check(got[i][3] == rows[i][3], "extract point qc_flag");
    }
    const Json& diag = want["diagnostics"];
    check(out["diagnostics"]["coordinate_key_families_used"]
              == diag["coordinate_key_families_used"],
          "extract coordinate families");
    check(out["diagnostics"]["skipped_missing_coordinates"]
              == diag["skipped_missing_coordinates"],
          "extract skipped_missing");
    check(out["diagnostics"]["skipped_invalid_coordinates"]
              == diag["skipped_invalid_coordinates"],
          "extract skipped_invalid");
    check(out["diagnostics"]["derived_points"] == diag["derived_points"],
          "extract derived_points");
}

void run_chain_case(const Json& fixture, const Json& case_json,
                    NodeRegistry& registry) {
    const std::string id = case_json["id"].get<std::string>();
    const Json& idw_options = case_json["idw_options"];
    Json extract_params = {
        {"records", fixture["records"]},
        {"factor_name", fixture["factor_name"]},
        {"target_horizon", case_json["extract_options"]["target_horizon"]},
        {"crs", case_json["extract_options"]["crs"]},
    };
    Json idw_params = {
        {"samples", Json{{"$ref", "extract"}, {"key", "points"}}},
        {"grid_n", idw_options["grid_n"]},
        {"power", idw_options["power"]},
        // Python interpolate_factor resolves the distance policy against the
        // DATASET crs — the chain wires it from the extract node output.
        {"crs", Json{{"$ref", "extract"}, {"key", "crs"}}},
    };
    check(idw_options["dataset_crs"] == case_json["extract_options"]["crs"],
          id + ": fixture dataset_crs consistent");
    if (!idw_options["max_neighbors"].is_null()) {
        idw_params["max_neighbors"] = idw_options["max_neighbors"];
    }
    const WorkflowSpec spec = make_spec(
        "conv07." + id,
        {node("extract", "map.extract_factors", {}, extract_params),
         node("idw", "map.interpolate_idw", {"extract"}, idw_params),
         node("post", "test.noop", {"idw"})});

    LogCapture logs;
    Engine engine(registry, logs.sink());
    const WorkflowRun run = engine.run(spec);

    check(run.state == RunState::completed, id + ": run completed");
    const we::NodeRun* extract = run.find("extract");
    const we::NodeRun* idw = run.find("idw");
    const we::NodeRun* post = run.find("post");
    check(extract != nullptr && extract->state == NodeState::succeeded,
          id + ": extract succeeded");
    check(idw != nullptr && idw->state == NodeState::succeeded,
          id + ": idw succeeded");
    check(post != nullptr && post->state == NodeState::succeeded,
          id + ": post succeeded");

    // extract node output vs the frozen REAL Python extract_factors result.
    compare_extract_outputs(*extract, case_json["extract"]);

    // idw node output vs the frozen REAL Python interpolate_factor chain.
    const Json& out = idw->outputs;
    check(out["algorithm_id"] == "idw", id + ": algorithm_id");
    check(out["n_samples"] == case_json["n_samples"], id + ": n_samples");
    check(out["grid_n"] == case_json["idw_options"]["grid_n"],
          id + ": output grid_n");
    check_grid_rows(out["grid_z"], case_json["grid_z"], 1e-6, id + " grid_z");
    check_axis(out["grid_x"], case_json["grid_x"], 1e-12, id + " grid_x");
    check_axis(out["grid_y"], case_json["grid_y"], 1e-12, id + " grid_y");
    check_close(out["statistics"]["min"], case_json["statistics"]["min"],
                1e-9, id + " statistics min");
    check_close(out["statistics"]["max"], case_json["statistics"]["max"],
                1e-9, id + " statistics max");
    check_close(out["statistics"]["mean"], case_json["statistics"]["mean"],
                1e-9, id + " statistics mean");
    check_close(out["statistics"]["std"], case_json["statistics"]["std"],
                1e-9, id + " statistics std");
    check(out["statistics"]["valid_count"]
              == case_json["statistics"]["valid_count"],
          id + " statistics valid_count");
    check(out["statistics"]["total_count"]
              == case_json["statistics"]["total_count"],
          id + " statistics total_count");
    check(out["distance_policy"] == case_json["distance_policy"],
          id + ": distance_policy");
    check(out["distance_policy_annotation"]
              == case_json["distance_policy_annotation"],
          id + ": distance_policy_annotation");

    // The engine materialises a typed FactorGrid payload (user-flow
    // deliverable), not just the JSON projection.
    check(idw->payload.has_value(), id + ": payload present");
    const auto* grid = std::any_cast<pwb::mapping::FactorGrid>(&idw->payload);
    check(grid != nullptr, id + ": typed FactorGrid payload");
    if (grid != nullptr) {
        check(grid->grid_n == case_json["idw_options"]["grid_n"].get<int>(),
              id + ": payload grid_n");
        check(grid->grid_z.size()
                  == static_cast<std::size_t>(grid->grid_n)
                         * static_cast<std::size_t>(grid->grid_n),
              id + ": payload grid_z size");
        check(grid->n_samples == case_json["n_samples"].get<int>(),
              id + ": payload n_samples");
    }

    // stdout-level logs: run start/end plus a running line per node.
    check(logs.contains("run conv07." + id + ": start (3 nodes)"),
          id + ": run start log");
    check(logs.contains("node extract (op=map.extract_factors): running"),
          id + ": extract running log");
    check(logs.contains("node idw (op=map.interpolate_idw): running"),
          id + ": idw running log");
    check(logs.contains("node post (op=test.noop): running"),
          id + ": post running log");
    check(logs.contains(": succeeded in "), id + ": succeeded logs");
    check(logs.contains("run conv07." + id + ": completed"),
          id + ": run completed log");
}

void oracle_chain_cases(const Json& fixture, NodeRegistry& registry) {
    for (const Json& case_json : fixture["cases"]) {
        run_chain_case(fixture, case_json, registry);
    }
}

void linear_chain_order_and_logs(NodeRegistry& registry) {
    LogCapture logs;
    Engine engine(registry, logs.sink());
    const WorkflowRun run = engine.run(make_spec(
        "conv07.linear",
        {node("a", "test.noop"), node("b", "test.noop", {"a"}),
         node("c", "test.noop", {"b"})}));
    check(run.state == RunState::completed, "linear run completed");
    for (const we::NodeRun& nr : run.node_runs) {
        check(nr.state == NodeState::succeeded, "linear " + nr.node_id);
        check(nr.attempt == 1, "linear attempt");
        check(nr.started_at > 0.0 && nr.finished_at >= nr.started_at,
              "linear timestamps");
        check(nr.error.empty() && nr.skip_reason.empty(),
              "linear no error/skip_reason");
    }
    const std::size_t a = logs.first_index("node a (op=test.noop): running");
    const std::size_t b = logs.first_index("node b (op=test.noop): running");
    const std::size_t c = logs.first_index("node c (op=test.noop): running");
    check(a < b && b < c && c < logs.lines.size(),
          "linear topological execution order a<b<c");
    check(logs.contains("run conv07.linear: start (3 nodes)"),
          "linear start log");
    check(logs.contains("run conv07.linear: completed"),
          "linear completed log");
    check(logs.contains("node a (op=test.noop): succeeded in "),
          "linear succeeded log");
}

void diamond_completes(NodeRegistry& registry) {
    Engine engine(registry);
    const WorkflowRun run = engine.run(make_spec(
        "conv07.diamond",
        {node("a", "test.noop"), node("b", "test.noop", {"a"}),
         node("c", "test.noop", {"a"}), node("d", "test.noop", {"b", "c"})}));
    check(run.state == RunState::completed, "diamond completed");
    for (const we::NodeRun& nr : run.node_runs) {
        check(nr.state == NodeState::succeeded, "diamond " + nr.node_id);
    }
}

// The oracle failure chain: extract succeeds with 0 points → idw fails with
// the frozen Python validate() message → post is skipped → run FAILED.
void failure_short_circuit_frozen_message(const Json& fixture,
                                          NodeRegistry& registry) {
    LogCapture logs;
    Engine engine(registry, logs.sink());
    const WorkflowSpec spec = make_spec(
        "conv07.fail",
        {node("extract", "map.extract_factors", {},
              Json{{"records", fixture["failure"]["records"]},
                   {"factor_name", fixture["factor_name"]},
                   {"target_horizon", "H1"}}),
         node("idw", "map.interpolate_idw", {"extract"},
              Json{{"samples",
                    Json{{"$ref", "extract"}, {"key", "points"}}},
                   {"grid_n", 8}}),
         node("post", "test.noop", {"idw"})});
    const WorkflowRun run = engine.run(spec);
    check(run.state == RunState::failed, "failure run failed");
    check(run.find("extract")->state == NodeState::succeeded,
          "failure extract succeeded with 0 points");
    check(run.find("extract")->outputs["point_count"]
              == fixture["failure"]["point_count"],
          "failure extract point_count 0");
    check(run.find("idw")->state == NodeState::failed, "failure idw failed");
    check(fixture["failure"]["message"].get<std::string>()
              == run.find("idw")->error,
          "failure idw error == frozen Python validate message");
    check(run.find("post")->state == NodeState::skipped, "failure post skipped");
    check(run.find("post")->skip_reason == "upstream idw failed",
          "failure post skip_reason");
    check(logs.contains("node idw (op=map.interpolate_idw): failed: "),
          "failure idw log line");
    check(logs.contains("node post: skipped (upstream idw failed)"),
          "failure post log line");
    check(logs.contains("run conv07.fail: failed"), "failure run log");
}

void op_failure_short_circuit(NodeRegistry& registry) {
    Engine engine(registry);
    const WorkflowRun run = engine.run(make_spec(
        "conv07.boom",
        {node("a", "test.noop"), node("b", "test.fail", {"a"}),
         node("c", "test.noop", {"b"}), node("d", "test.noop", {"b"})}));
    check(run.state == RunState::failed, "boom run failed");
    check(run.find("a")->state == NodeState::succeeded, "boom a succeeded");
    check(run.find("b")->state == NodeState::failed, "boom b failed");
    check(run.find("b")->error == "boom", "boom b error");
    check(run.find("c")->state == NodeState::skipped, "boom c skipped");
    check(run.find("d")->state == NodeState::skipped, "boom d skipped");
}

// Cooperative cancel while an op runs: the op polls the token (honest
// checkpoint, ADR-2 style), the engine lands b CANCELLED, the still-pending
// c CANCELLED ("cancelled at b") and a stays SUCCEEDED. A LOCAL registry
// keeps the capturing lambda's lifetime scoped to this test.
void cancel_inside_op(NodeRegistry& registry) {
    NodeRegistry local = make_registry();
    std::atomic<bool> started{false};
    local.register_op(
        "test.block",
        [&](const Json&, const CancelToken& token) -> we::NodeResult {
            started.store(true);
            while (!token.is_cancelled()) {
                std::this_thread::sleep_for(std::chrono::milliseconds(1));
            }
            token.throw_if_cancelled();
            return {};
        });
    LogCapture logs;
    Engine engine(local, logs.sink());
    const WorkflowSpec spec = make_spec(
        "conv07.cancel",
        {node("a", "test.noop"), node("b", "test.block", {"a"}),
         node("c", "test.noop", {"b"})});
    CancelToken token;
    WorkflowRun run;
    std::thread driver([&] { run = engine.run(spec, token); });
    for (int i = 0; !started.load() && i < 5000; ++i) {
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    check(started.load(), "cancel: block op started");
    token.cancel();
    driver.join();
    check(run.state == RunState::cancelled, "cancel run cancelled");
    check(run.find("a")->state == NodeState::succeeded,
          "cancel a stays succeeded");
    check(run.find("b")->state == NodeState::cancelled, "cancel b cancelled");
    check(run.find("b")->error == "cancelled: workflow run cancelled",
          "cancel b error");
    check(run.find("c")->state == NodeState::cancelled, "cancel c cancelled");
    check(run.find("c")->error == "cancelled at b", "cancel c error");
    check(!logs.contains("node c (op=test.noop): running"),
          "cancel c never ran");
    check(logs.contains("run conv07.cancel: cancelled"),
          "cancel run log");
}

// A pre-cancelled token runs nothing: every node lands CANCELLED.
void pre_cancelled_token(NodeRegistry& registry) {
    LogCapture logs;
    Engine engine(registry, logs.sink());
    CancelToken token;
    token.cancel();
    const WorkflowRun run = engine.run(
        make_spec("conv07.precancel",
                  {node("a", "test.noop"), node("b", "test.noop", {"a"})}),
        token);
    check(run.state == RunState::cancelled, "precancel run cancelled");
    check(run.find("a")->state == NodeState::cancelled, "precancel a");
    check(run.find("b")->state == NodeState::cancelled, "precancel b");
    check(run.find("a")->error == "run cancelled", "precancel a error");
    check(!logs.contains(": running"), "precancel: no node ran");
}

// Frozen validation problem lists (real Python validate_workflow_spec).
void validation_against_frozen_messages(const Json& fixture) {
    const Json& frozen = fixture["validation"];
    NodeRegistry registry = make_registry();
    const std::vector<std::pair<std::string, WorkflowSpec>> cases = {
        {"cycle_two", make_spec("t.spec", {node("a", "test.noop", {"b"}),
                                          node("b", "test.noop", {"a"})})},
        {"cycle_three", make_spec("t.spec", {node("a", "test.noop", {"c"}),
                                             node("b", "test.noop", {"a"}),
                                             node("c", "test.noop", {"b"})})},
        {"missing_dependency", make_spec("t.spec", {node("a", "test.noop", {"ghost"})})},
        {"unknown_action", make_spec("t.spec", {node("a", "ghost.op")})},
        {"self_dependency", make_spec("t.spec", {node("a", "test.noop", {"a"})})},
        {"ref_not_in_depends_on",
         make_spec("t.spec", {node("a", "test.noop"),
                              node("b", "map.extract_factors", {},
                                   Json{{"samples", Json{{"$ref", "a"},
                                                         {"key", "points"}}}})})},
        {"ref_unknown_node",
         make_spec("t.spec", {node("a", "test.noop", {},
                                   Json{{"up", Json{{"$ref", "ghost"}}}})})},
        {"ref_key_not_string",
         make_spec("t.spec", {node("a", "test.noop"),
                              node("b", "map.extract_factors", {"a"},
                                   Json{{"samples", Json{{"$ref", "a"},
                                                         {"key", 3}}}})})},
        {"bad_node_id", make_spec("t.spec", {node("Big", "test.noop")})},
        {"empty_workflow", make_spec("t.spec", {})},
    };
    for (const auto& [name, spec] : cases) {
        const std::vector<std::string> problems =
            we::validate_spec(spec, registry);
        const Json& want = frozen[name];
        check(problems.size() == want.size(),
              name + ": problem count " + std::to_string(problems.size()));
        for (std::size_t i = 0; i < problems.size() && i < want.size(); ++i) {
            check(problems[i] == want[i].get<std::string>(),
                  name + ": problem[" + std::to_string(i) + "] '" + problems[i]
                      + "'");
        }
    }
    // duplicate_node: Python appends a dict-collapse artifact
    // ("dependency cycle among nodes []") after the duplicate problem; the
    // C++ subset reproduces the duplicate problem itself (07-decisions D2).
    {
        const std::vector<std::string> problems = we::validate_spec(
            make_spec("t.spec", {node("a", "test.noop"),
                                 node("a", "map.extract_factors")}),
            registry);
        check(problems.size() == 1, "duplicate: single problem");
        check(!problems.empty()
                  && problems[0] == frozen["duplicate_node"][0].get<std::string>(),
              "duplicate: frozen message");
    }

    // Engine.run refuses an invalid spec before anything executes.
    LogCapture logs;
    Engine engine(registry, logs.sink());
    bool threw = false;
    try {
        engine.run(make_spec("t.spec",
                             {node("a", "test.noop", {"b"}),
                              node("b", "test.noop", {"a"})}));
    } catch (const ValidationError& exc) {
        threw = true;
        check(exc.problems.size() == 1, "engine validation problems");
        check(std::string(exc.what()).find(
                  "workflow 't.spec' invalid: dependency cycle among nodes")
                  == 0,
              "engine validation message prefix");
    }
    check(threw, "engine.run throws ValidationError on cycle");
    check(logs.lines.empty(), "engine.run refused spec before any log");
}

// Runtime $ref binding failure → node FAILED with the frozen Python
// BindingError message (never a silent partial binding).
void runtime_binding_frozen_messages(const Json& fixture, NodeRegistry& registry) {
    Engine engine(registry);
    const WorkflowRun run = engine.run(make_spec(
        "conv07.bindfail",
        {node("a", "test.noop"),
         node("b", "test.noop", {"a"},
              Json{{"v", Json{{"$ref", "a"}, {"key", "nope"}}}})}));
    check(run.state == RunState::failed, "bindfail run failed");
    check(run.find("a")->state == NodeState::succeeded, "bindfail a");
    check(run.find("b")->state == NodeState::failed, "bindfail b failed");
    check(fixture["runtime_binding"]["ref_missing_key"].get<std::string>()
              == run.find("b")->error,
          "bindfail frozen BindingError message");
}

// Surface coverage beyond the chain tests: WorkflowSpec::from_json (the
// JSON spec entry), the frozen "no resolved output yet" binding message
// (a succeeded node with EMPTY outputs is unresolved — Python's results
// view behaves the same) and the idw op's option parsing (search_radius,
// null value → NaN → filtered from n_samples).
void additional_surface_coverage(const Json& fixture, NodeRegistry& registry) {
    // from_json → run round-trip (spec JSON is the host-facing surface).
    {
        const Json spec_json = Json{
            {"workflow_id", "conv07.fromjson"},
            {"nodes", Json::array({
                Json{{"node_id", "a"}, {"op", "test.noop"}},
                Json{{"node_id", "b"},
                     {"op", "test.noop"},
                     {"depends_on", Json::array({"a"})}},
            })}};
        const WorkflowSpec spec = WorkflowSpec::from_json(spec_json);
        Engine engine(registry);
        const WorkflowRun run = engine.run(spec);
        check(run.state == RunState::completed, "from_json run completed");
        check(run.find("a")->state == NodeState::succeeded
                  && run.find("b")->state == NodeState::succeeded,
              "from_json nodes succeeded");

        bool threw = false;
        try {
            WorkflowSpec::from_json(Json{{"workflow_id", "t"}});
        } catch (const std::invalid_argument&) {
            threw = true;
        }
        check(threw, "from_json missing nodes throws");
    }

    // $ref to a succeeded-but-empty node: frozen Python BindingError text.
    {
        NodeRegistry local = make_registry();
        local.register_op(
            "test.empty",
            [](const Json&, const CancelToken&) -> we::NodeResult {
                return {};
            });
        Engine engine(local);
        const WorkflowRun run = engine.run(make_spec(
            "conv07.emptyref",
            {node("ghost", "test.empty"),
             node("b", "test.noop", {"ghost"},
                  Json{{"v", Json{{"$ref", "ghost"}}}})}));
        check(run.state == RunState::failed, "emptyref run failed");
        check(run.find("ghost")->state == NodeState::succeeded,
              "emptyref ghost succeeded with empty outputs");
        check(fixture["runtime_binding"]["ref_unresolved_node"]
                  .get<std::string>()
              == run.find("b")->error,
          "emptyref frozen BindingError message");
    }

    // Whole-output $ref (no key): the bound value is the full outputs doc.
    {
        Engine engine(registry);
        const WorkflowRun run = engine.run(make_spec(
            "conv07.wholeref",
            {node("a", "test.noop"),
             node("b", "test.noop", {"a"},
                  Json{{"up", Json{{"$ref", "a"}}}})}));
        check(run.state == RunState::completed, "wholeref run completed");
        check(run.find("b")->outputs["ok"] == true,
              "wholeref b succeeded with bound outputs");
    }

    // Direct op invocation: option parsing paths the chain cases don't hit.
    {
        const we::NodeFunction* idw = registry.find("map.interpolate_idw");
        check(idw != nullptr, "idw op registered");
        if (idw != nullptr) {
            CancelToken token;
            // One null value → NaN → filtered by valid_points (n_samples 3).
            Json samples = Json::array();
            samples.push_back(Json::array({0.0, 0.0, 1.0}));
            samples.push_back(Json::array({0.4, 0.1, 1.2}));
            samples.push_back(Json::array({0.2, 0.5, nullptr}));
            samples.push_back(Json::array({20.0, 20.0, 9.0}));
            Json params = Json::object();
            params["samples"] = samples;
            params["grid_n"] = 8;
            params["search_radius"] = 2.0;
            const we::NodeResult radius = (*idw)(params, token);
            check(radius.outputs["n_samples"] == 3,
                  "idw op: null value filtered, search_radius parsed");
            // Radius pruning: near the (0,0)/(0.4,0.1)/(20,20) samples the
            // grid is finite, the far majority of the padded extent is NaN.
            const int valid = radius.outputs["statistics"]["valid_count"]
                                  .get<int>();
            check(valid > 0 && valid < 64,
                  "idw op: search_radius prunes far cells (valid " + std::to_string(valid)
                      + " of 64)");
            const auto* grid =
                std::any_cast<pwb::mapping::FactorGrid>(&radius.payload);
            check(grid != nullptr && grid->search_radius.has_value()
                      && *grid->search_radius == 2.0,
                  "idw op: typed payload carries search_radius");
        }
    }
}

}  // namespace

int main() {
    const Json fixture = load_fixture();
    NodeRegistry registry = make_registry();

    oracle_chain_cases(fixture, registry);
    linear_chain_order_and_logs(registry);
    diamond_completes(registry);
    failure_short_circuit_frozen_message(fixture, registry);
    op_failure_short_circuit(registry);
    cancel_inside_op(registry);
    pre_cancelled_token(registry);
    validation_against_frozen_messages(fixture);
    runtime_binding_frozen_messages(fixture, registry);
    additional_surface_coverage(fixture, registry);

    std::printf("%s: workflow_engine.run (%d failure(s))\n",
                g_failures == 0 ? "PASS" : "FAIL", g_failures);
    return g_failures == 0 ? 0 : 1;
}
