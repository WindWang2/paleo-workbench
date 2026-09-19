// workflow_engine.lifecycle — the CONV-32 store-driven lifecycle engine
// (RunEngine) replayed against the frozen Python oracle
// (workflow_engine_lifecycle_oracle.json, generated from the REAL
// paleo_workbench.workflow.dag.engine WorkflowEngine by
// tools/oracle/generate_workflow_engine_lifecycle_fixtures.py).
//
// Every case reconstructs the exact Python scenario in C++: the same specs,
// the same scripted executor results, the same deterministic seams (ticking
// clock 1000.0 +0.5, fixed run-id pool, recorded backoff waits, frozen
// receipt environment) and a real WorkflowRunStore in a fresh tmpdir. The
// frozen timestamps pin not just values but the exact save/clock call ORDER
// of the engine; the receipts, cache identities (sha256) and every state
// transition are compared field-by-field via json_semantic_diff.

#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <functional>
#include <map>
#include <memory>
#include <sstream>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/workflow_engine/run_engine.hpp>

using pwb::domain::Json;
using pwb::workflow_engine::ActionInfo;
using pwb::workflow_engine::ActionResultView;
using pwb::workflow_engine::CancelToken;
using pwb::workflow_engine::CheckpointFailed;
using pwb::workflow_engine::EnvironmentIdentity;
using pwb::workflow_engine::EnvironmentProvider;
using pwb::workflow_engine::IActionCatalog;
using pwb::workflow_engine::RunContext;
using pwb::workflow_engine::RunEngine;
using pwb::workflow_engine::RunFunctionMap;
using pwb::workflow_engine::RunOptions;

namespace spec_ns = pwb::workflow_spec;

namespace {

int g_checks = 0;
int g_failures = 0;
int g_negatives = 0;

void check(bool ok, const std::string& what) {
    ++g_checks;
    if (!ok) {
        ++g_failures;
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
    }
}

Json load_fixture(const std::string& path) {
    std::ifstream stream(path, std::ios::binary);
    if (!stream.good()) {
        std::fprintf(stderr, "FAIL cannot open fixture %s\n", path.c_str());
        std::exit(1);
    }
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    return Json::parse(buffer.str());
}

// nlohmann parses non-negative JSON integers as number_unsigned while C++
// int fields project as number_integer, and json_semantic_diff treats the
// two kinds as different. Python has one int type — normalize both sides.
Json normalize_int_kinds(const Json& value) {
    if (value.is_object()) {
        Json out = Json::object();
        for (const auto& [key, item] : value.items()) {
            out[key] = normalize_int_kinds(item);
        }
        return out;
    }
    if (value.is_array()) {
        Json out = Json::array();
        for (const auto& item : value) out.push_back(normalize_int_kinds(item));
        return out;
    }
    if (value.is_number_integer() && !value.is_number_unsigned()) {
        const long long raw = value.get<long long>();
        if (raw >= 0) return Json(static_cast<std::uint64_t>(raw));
    }
    return value;
}

void expect_json(const std::string& what, const Json& actual,
                 const Json& expected) {
    const auto diff =
        pwb::domain::json_semantic_diff(normalize_int_kinds(actual),
                                        normalize_int_kinds(expected));
    check(diff.equal,
          what + (diff.equal ? "" : " — " + diff.path + ": " + diff.reason));
}

// ------------------------------------------------------------- seams --

struct TickingClock {
    double value = 1000.0;
    double operator()() {
        const double now = value;
        value += 0.5;
        return now;
    }
};

struct WaitRecorder {
    std::vector<double> waits;
    void operator()(const CancelToken&, double seconds) { waits.push_back(seconds); }
};

class FakeCatalog : public IActionCatalog {
public:
    std::map<std::string, ActionInfo> actions;
    std::optional<ActionInfo> get(const std::string& id) const override {
        const auto it = actions.find(id);
        return it == actions.end() ? std::nullopt : std::optional(it->second);
    }
    std::vector<std::string> ids() const override {
        std::vector<std::string> out;
        for (const auto& [id, info] : actions) out.push_back(id);
        return out;
    }
};

using Fallback = std::function<ActionResultView(const Json&)>;

struct Scripted {
    std::vector<ActionResultView> queue;
    Fallback fallback;
    ActionResultView run(const Json& bound) {
        if (!queue.empty()) {
            const ActionResultView front = queue.front();
            queue.erase(queue.begin());
            return front;
        }
        if (fallback) return fallback(bound);
        return ActionResultView{};  // plain success {} (Python default)
    }
};

std::string rid(int n) {  // Python: f"r{n:015d}" — 16 chars
    char buffer[24];
    std::snprintf(buffer, sizeof(buffer), "r%015d", n);
    return buffer;
}

std::filesystem::path make_tmpdir() {
    std::string pattern = "/tmp/pwb-wf-life-cpp-XXXXXX";
    if (char* dir = mkdtemp(pattern.data()); dir != nullptr) return dir;
    std::perror("mkdtemp");
    std::exit(1);
}

// ----------------------------------------------------------- harness --

struct Harness {
    std::filesystem::path tmp;
    std::shared_ptr<TickingClock> clock = std::make_shared<TickingClock>();
    std::shared_ptr<WaitRecorder> waiter = std::make_shared<WaitRecorder>();
    std::unique_ptr<pwb::workflow_engine::WorkflowRunStore> store;
    FakeCatalog catalog;
    RunFunctionMap functions;
    std::vector<Json> calls;
    EnvironmentProvider env;
    std::vector<std::string> ids;
    std::size_t id_pos = 0;
    std::unique_ptr<RunEngine> engine;

    explicit Harness(const Json& meta_env, std::vector<std::string> run_ids)
        : tmp(make_tmpdir()), ids(std::move(run_ids)) {
        using pwb::workflow_engine::WorkflowRunStore;
        store = std::make_unique<WorkflowRunStore>(
            tmp, [clock = clock.get()] { return (*clock)(); });
        EnvironmentIdentity identity{meta_env.at("python").get<std::string>(),
                                     meta_env.at("platform").get<std::string>(),
                                     meta_env.at("workbench").get<std::string>()};
        env = [identity] { return identity; };
    }

    void add_action(const std::string& id, bool cacheable = false) {
        ActionInfo info;
        info.action_id = id;
        info.cacheable = cacheable;
        info.description = id + " action";
        catalog.actions[id] = info;
    }

    void script(const std::string& id, std::vector<ActionResultView> queue,
                Fallback fallback = nullptr) {
        auto scripted = std::make_shared<Scripted>();
        scripted->queue = std::move(queue);
        scripted->fallback = std::move(fallback);
        functions[id] = [id, calls = &calls, scripted](const Json& bound,
                                                       const CancelToken&) {
            calls->push_back(Json{{"action", id}, {"params", bound}});
            return scripted->run(bound);
        };
    }

    void build() {
        engine = std::make_unique<RunEngine>(
            catalog, functions, *store,
            [clock = clock.get()] { return (*clock)(); },
            [waiter = waiter.get()](const CancelToken& token, double seconds) {
                (*waiter)(token, seconds);
            },
            env, nullptr,
            [this] {
                return id_pos < ids.size() ? ids[id_pos++]
                                           : std::string("ffff000000000000");
            });
    }

    Json calls_json() const { return Json(std::vector<Json>(calls)); }
    Json calls_json_from(std::size_t offset) const {
        return Json(std::vector<Json>(calls.begin() + static_cast<long>(offset),
                                      calls.end()));
    }
};

// --------------------------------------------------------- projections --

Json proj_node(const spec_ns::NodeRun& nr) {
    Json in_ids = Json::array();
    for (const auto& id : nr.input_version_ids) in_ids.push_back(id);
    Json out_ids = Json::array();
    for (const auto& id : nr.output_version_ids) out_ids.push_back(id);
    return Json{
        {"state", spec_ns::to_string(nr.state)},
        {"attempt", nr.attempt},
        {"action_status", nr.action_status ? Json(*nr.action_status) : Json(nullptr)},
        {"from_cache", nr.from_cache},
        {"parameters", nr.parameters},
        {"input_version_ids", in_ids},
        {"cache_identity", nr.cache_identity ? Json(*nr.cache_identity) : Json(nullptr)},
        {"output_version_ids", out_ids},
        {"outputs", nr.outputs},
        {"receipt", nr.receipt ? *nr.receipt : Json(nullptr)},
        {"skip_reason", nr.skip_reason ? Json(*nr.skip_reason) : Json(nullptr)},
        {"error", nr.error ? Json(*nr.error) : Json(nullptr)},
        {"started_at", nr.started_at},
        {"finished_at", nr.finished_at},
    };
}

Json proj_run(const spec_ns::WorkflowRun& run) {
    Json nodes = Json::object();
    for (const auto& [id, nr] : run.node_runs) nodes[id] = proj_node(nr);
    return Json{
        {"run_id", run.run_id},
        {"state", spec_ns::to_string(run.state)},
        {"parent_run_id", run.parent_run_id ? Json(*run.parent_run_id) : Json(nullptr)},
        {"project_name", run.project_name ? Json(*run.project_name) : Json(nullptr)},
        {"project_path", run.project_path ? Json(*run.project_path) : Json(nullptr)},
        {"spec_hash", run.spec_hash ? Json(*run.spec_hash) : Json(nullptr)},
        {"slot_values", run.slot_values},
        {"created_at", run.created_at},
        {"updated_at", run.updated_at},
        {"node_runs", nodes},
    };
}

// -------------------------------------------------------------- specs --

spec_ns::WorkflowSpec chain_spec() {
    spec_ns::WorkflowSpec spec;
    spec.workflow_id = "wf.chain";
    spec.name = "Chain";
    spec_ns::NodeSpec a;
    a.node_id = "a";
    a.action_id = "t.compute";
    a.parameters = Json{{"factor", Json{{"$slot", "factor"}}}};
    spec_ns::NodeSpec b;
    b.node_id = "b";
    b.action_id = "t.compute";
    b.parameters = Json{{"up", Json{{"$ref", "a"}, {"key", "factor"}}}};
    b.depends_on = {"a"};
    spec.nodes = {a, b};
    spec_ns::SlotSpec slot;
    slot.name = "factor";
    slot.schema = Json{{"type", "string"}};
    spec.slots = {slot};
    return spec;
}

RunContext make_ctx(const std::string& path,
                    const Json& identity = Json(nullptr)) {
    RunContext ctx;
    ctx.workspace_id = "ws-1";
    ctx.project_path = path;
    ctx.project_identity = identity;
    return ctx;
}

// -------------------------------------------------------- result views --

ActionResultView ok_view(const Json& outputs, double elapsed = 12.5,
                         const std::string& status = "success") {
    ActionResultView view;
    view.status = status;
    view.outputs = outputs;
    view.elapsed_ms = elapsed;
    return view;
}

ActionResultView a_view(const Json& factor) {
    return ok_view(Json{{"factor", factor}, {"version_ids", Json::array({"v-a-1"})}});
}

ActionResultView b_view() {
    return ok_view(Json{{"report", "done"}, {"version_ids", Json::array({"v-b-1"})}},
                   7.25);
}

ActionResultView rejected_view(const std::string& error, double elapsed) {
    ActionResultView view;
    view.status = "rejected";
    view.error = error;
    view.elapsed_ms = elapsed;
    return view;
}

Fallback compute_fallback() {
    return [](const Json& bound) {
        if (bound.contains("factor")) return a_view(bound.at("factor"));
        return b_view();
    };
}

void script_chain(Harness& h) {
    h.add_action("t.compute");
    h.script("t.compute", {}, compute_fallback());
}

// --------------------------------------------------------------- cases --

void case_run_complete_chain(const Json& fixture, const Json& env) {
    Harness h(env, {rid(101), rid(102)});
    script_chain(h);
    h.build();
    RunContext ctx = make_ctx("/proj/one", Json("proj-identity-1"));
    auto run = h.engine->create_run(chain_spec(), Json{{"factor", "porosity"}}, &ctx);
    const spec_ns::WorkflowRun final_run = h.engine->run(run.run_id, &ctx);
    expect_json("case1.run", proj_run(final_run), fixture.at("run"));
    expect_json("case1.calls", h.calls_json(), fixture.at("calls"));
}

void case_static_validation(const Json& fixture, const Json& env) {
    Harness h(env, {rid(201)});
    script_chain(h);
    h.build();
    spec_ns::WorkflowSpec bad;
    bad.workflow_id = "wf.bad";
    bad.name = "Bad";
    spec_ns::NodeSpec a;
    a.node_id = "a";
    a.action_id = "ghost.op";
    bad.nodes = {a};
    try {
        h.engine->create_run(bad, Json::object(), nullptr);
        check(false, "case2 must raise WorkflowValidationError");
    } catch (const pwb::workflow_engine::WorkflowValidationError& exc) {
        expect_json("case2.error",
                    Json{{"type", "WorkflowValidationError"},
                         {"message", std::string(exc.what())},
                         {"problems", Json(exc.problems)}},
                    fixture.at("error"));
    }
    expect_json("case2.calls", h.calls_json(), fixture.at("calls"));
}

void case_slot_schema(const Json& fixture, const Json& env) {
    Harness h(env, {rid(301)});
    script_chain(h);
    h.build();
    try {
        h.engine->create_run(chain_spec(), Json::object(), nullptr);
        check(false, "case3 must raise WorkflowValidationError");
    } catch (const pwb::workflow_engine::WorkflowValidationError& exc) {
        expect_json("case3.error",
                    Json{{"type", "WorkflowValidationError"},
                         {"message", std::string(exc.what())},
                         {"problems", Json(exc.problems)}},
                    fixture.at("error"));
    }
}

void case_crash_resume(const Json& fixture, const Json& env) {
    Harness h(env, {rid(401), rid(402)});
    script_chain(h);
    h.build();
    RunContext ctx = make_ctx("/proj/one");
    auto run = h.engine->create_run(chain_spec(), Json{{"factor", "porosity"}}, &ctx);
    // Fabricate the crashed checkpoint: a finished, b torn mid-RUNNING
    // (mirrors the generator tick-for-tick: 3 clock stamps + save).
    auto crashed = h.store->load(run.run_id);
    crashed.state = spec_ns::RunState::running;
    auto* a = crashed.find_node_run("a");
    a->state = spec_ns::NodeState::succeeded;
    a->attempt = 1;
    a->action_status = "success";
    a->parameters = Json{{"factor", "porosity"}};
    a->outputs = Json{{"factor", "porosity"}, {"version_ids", Json::array({"v-a-1"})}};
    a->output_version_ids = {"v-a-1"};
    a->started_at = Json((*h.clock)());
    a->finished_at = Json((*h.clock)());
    auto* b = crashed.find_node_run("b");
    b->state = spec_ns::NodeState::running;
    b->attempt = 1;
    b->started_at = Json((*h.clock)());
    h.store->save(crashed);
    const spec_ns::WorkflowRun resumed = h.engine->resume(run.run_id, &ctx);
    expect_json("case4.run", proj_run(resumed), fixture.at("run"));
    expect_json("case4.calls", h.calls_json(), fixture.at("calls"));
}

void case_failure_no_revival(const Json& fixture, const Json& env) {
    Harness h(env, {rid(501), rid(502)});
    h.add_action("t.compute");
    h.add_action("t.fail");
    h.script("t.compute", {}, compute_fallback());
    ActionResultView boom;
    boom.status = "failed";
    boom.error = "engine exploded";
    boom.elapsed_ms = 3.0;
    h.script("t.fail", {boom});
    spec_ns::WorkflowSpec spec;
    spec.workflow_id = "wf.fail";
    spec.name = "Fail";
    spec_ns::NodeSpec a;
    a.node_id = "a";
    a.action_id = "t.compute";
    a.parameters = Json{{"factor", Json{{"$slot", "factor"}}}};
    spec_ns::NodeSpec b;
    b.node_id = "b";
    b.action_id = "t.fail";
    b.depends_on = {"a"};
    spec_ns::NodeSpec c;
    c.node_id = "c";
    c.action_id = "t.compute";
    c.parameters = Json{{"mode", "report"}};
    c.depends_on = {"b"};
    spec.nodes = {a, b, c};
    spec_ns::SlotSpec slot;
    slot.name = "factor";
    slot.schema = Json{{"type", "string"}};
    spec.slots = {slot};
    h.build();
    RunContext ctx = make_ctx("/proj/one");
    auto run = h.engine->create_run(spec, Json{{"factor", "porosity"}}, &ctx);
    const auto failed = h.engine->run(run.run_id, &ctx);
    check(failed.state == spec_ns::RunState::failed, "case5 run fails");
    const Json before = proj_run(h.store->load(run.run_id));
    const auto revived = h.engine->resume(run.run_id, &ctx);
    check(revived.state == spec_ns::RunState::failed, "case5 resume stays failed");
    const Json after = proj_run(h.store->load(run.run_id));
    expect_json("case5.after_failure", before, fixture.at("after_failure"));
    expect_json("case5.after_resume", after, fixture.at("after_resume"));
    expect_json("case5.calls", h.calls_json(), fixture.at("calls"));
}

void case_rerun_carry_all(const Json& fixture, const Json& env) {
    Harness h(env, {rid(601), rid(602)});
    script_chain(h);
    h.build();
    RunContext ctx = make_ctx("/proj/one");
    auto first = h.engine->create_run(chain_spec(), Json{{"factor", "porosity"}}, &ctx);
    h.engine->run(first.run_id, &ctx);
    const std::size_t calls_before = h.calls.size();
    auto rerun = h.engine->rerun(first.run_id);
    check(h.calls.size() == calls_before, "case6 carry-over rerun executes nothing");
    expect_json("case6.run", proj_run(rerun), fixture.at("run"));
    expect_json("case6.calls", h.calls_json_from(calls_before), fixture.at("calls"));
    expect_json("case6.first_run_id", Json(first.run_id), fixture.at("first_run_id"));
}

void case_rerun_slot_override(const Json& fixture, const Json& env) {
    Harness h(env, {rid(701), rid(702)});
    script_chain(h);
    h.build();
    RunContext ctx = make_ctx("/proj/one");
    auto first = h.engine->create_run(chain_spec(), Json{{"factor", "porosity"}}, &ctx);
    h.engine->run(first.run_id, &ctx);
    const std::size_t calls_before = h.calls.size();
    auto rerun = h.engine->rerun(first.run_id, {}, Json{{"factor", "silt"}}, &ctx);
    check(h.calls.size() == calls_before + 2, "case7 changed identity re-executes");
    expect_json("case7.run", proj_run(rerun), fixture.at("run"));
    expect_json("case7.calls", h.calls_json_from(calls_before), fixture.at("calls"));
}

void case_rerun_from_b(const Json& fixture, const Json& env) {
    Harness h(env, {rid(801), rid(802)});
    script_chain(h);
    h.build();
    RunContext ctx = make_ctx("/proj/one");
    auto first = h.engine->create_run(chain_spec(), Json{{"factor", "porosity"}}, &ctx);
    h.engine->run(first.run_id, &ctx);
    const std::size_t calls_before = h.calls.size();
    auto rerun = h.engine->rerun(first.run_id, {"b"}, Json::object(), &ctx);
    check(h.calls.size() == calls_before + 1, "case8 only b re-executes");
    expect_json("case8.run", proj_run(rerun), fixture.at("run"));
    expect_json("case8.calls", h.calls_json_from(calls_before), fixture.at("calls"));
}

spec_ns::WorkflowSpec condition_spec(int value) {
    spec_ns::WorkflowSpec spec;
    spec.workflow_id = "wf.cond";
    spec.name = "Cond";
    spec_ns::NodeCondition condition;
    condition.kind = "node_output_equals";
    condition.node = "a";
    condition.key = "flag";
    condition.value = value;
    spec_ns::NodeSpec c;  // listed FIRST: the condition must wait for a
    c.node_id = "c";
    c.action_id = "t.compute";
    c.condition = condition;
    spec_ns::NodeSpec a;
    a.node_id = "a";
    a.action_id = "t.compute";
    spec.nodes = {c, a};
    return spec;
}

void case_conditions(const Json& fixture, const Json& env) {
    {  // 42 != 7 -> "condition false"
        Harness h(env, {rid(901), rid(902)});
        auto counter = std::make_shared<int>(0);
        h.add_action("t.compute");
        h.script("t.compute", {}, [counter](const Json&) {
            if (++(*counter) == 1) {
                return ok_view(Json{{"flag", 42}, {"version_ids", Json::array({"v-a-9"})}});
            }
            return ok_view(Json{{"ran", true}}, 2.0);
        });
        h.build();
        RunContext ctx = make_ctx("/proj/one");
        auto run = h.engine->create_run(condition_spec(7), Json::object(), &ctx);
        const auto final_run = h.engine->run(run.run_id, &ctx);
        expect_json("case9.condition_false", proj_run(final_run),
                    fixture.at("condition_false"));
    }
    {  // flag == 42 -> waits for a, then executes
        Harness h(env, {rid(911), rid(912)});
        auto counter = std::make_shared<int>(0);
        h.add_action("t.compute");
        h.script("t.compute", {}, [counter](const Json&) {
            if (++(*counter) == 1) {
                return ok_view(Json{{"flag", 42}, {"version_ids", Json::array({"v-a-9"})}});
            }
            return ok_view(Json{{"ran", true}}, 2.0);
        });
        h.build();
        RunContext ctx = make_ctx("/proj/one");
        auto run = h.engine->create_run(condition_spec(42), Json::object(), &ctx);
        const auto final_run = h.engine->run(run.run_id, &ctx);
        expect_json("case9.condition_true", proj_run(final_run),
                    fixture.at("condition_true"));
    }
}

void case_retry_resource_shed(const Json& fixture, const Json& env) {
    Harness h(env, {rid(1001)});
    h.add_action("t.compute");
    h.script("t.compute",
             {rejected_view("ResourceExhausted: cpu: busy", 1.0),
              rejected_view("ResourceExhausted: cpu: busy", 1.0),
              rejected_view("ResourceExhausted: cpu: busy", 1.0)});
    spec_ns::WorkflowSpec spec;
    spec.workflow_id = "wf.retry";
    spec.name = "Retry";
    spec_ns::NodeSpec r;
    r.node_id = "r";
    r.action_id = "t.compute";
    r.retry.max_attempts = 3;
    r.retry.backoff_seconds = 0.05;
    spec.nodes = {r};
    h.build();
    RunContext ctx = make_ctx("/proj/one");
    auto run = h.engine->create_run(spec, Json::object(), &ctx);
    const auto final_run = h.engine->run(run.run_id, &ctx);
    expect_json("case10.run", proj_run(final_run), fixture.at("run"));
    expect_json("case10.calls", h.calls_json(), fixture.at("calls"));
    Json waits = Json::array();
    for (const double w : h.waiter->waits) waits.push_back(w);
    expect_json("case10.waits", waits, fixture.at("waits"));
}

void case_plain_rejection(const Json& fixture, const Json& env) {
    Harness h(env, {rid(1101)});
    h.add_action("t.compute");
    h.script("t.compute",
             {rejected_view("invalid context: session expired", 1.0),
              rejected_view("invalid context: session expired", 1.0)});
    spec_ns::WorkflowSpec spec;
    spec.workflow_id = "wf.reject";
    spec.name = "Reject";
    spec_ns::NodeSpec r;
    r.node_id = "r";
    r.action_id = "t.compute";
    r.retry.max_attempts = 3;
    spec.nodes = {r};
    h.build();
    RunContext ctx = make_ctx("/proj/one");
    auto run = h.engine->create_run(spec, Json::object(), &ctx);
    const auto final_run = h.engine->run(run.run_id, &ctx);
    check(final_run.find_node_run("r")->attempt == 1,
          "case11 plain rejections never retry");
    expect_json("case11.run", proj_run(final_run), fixture.at("run"));
    expect_json("case11.calls", h.calls_json(), fixture.at("calls"));
    Json waits = Json::array();
    for (const double w : h.waiter->waits) waits.push_back(w);
    expect_json("case11.waits", waits, fixture.at("waits"));
}

void case_unavailable(const Json& fixture, const Json& env) {
    Harness h(env, {rid(1201)});
    h.add_action("t.compute");
    h.add_action("t.unavail");
    h.script("t.compute", {}, compute_fallback());
    ActionResultView unavail;
    unavail.status = "unavailable";
    unavail.error = "backend not installed";
    unavail.elapsed_ms = 1.0;
    h.script("t.unavail", {unavail});
    spec_ns::WorkflowSpec spec;
    spec.workflow_id = "wf.unavail";
    spec.name = "Unavail";
    spec_ns::NodeSpec a;
    a.node_id = "a";
    a.action_id = "t.compute";
    a.parameters = Json{{"factor", Json{{"$slot", "factor"}}}};
    spec_ns::NodeSpec b;
    b.node_id = "b";
    b.action_id = "t.unavail";
    b.depends_on = {"a"};
    spec_ns::NodeSpec c;
    c.node_id = "c";
    c.action_id = "t.compute";
    c.depends_on = {"b"};
    spec.nodes = {a, b, c};
    spec_ns::SlotSpec slot;
    slot.name = "factor";
    slot.schema = Json{{"type", "string"}};
    spec.slots = {slot};
    h.build();
    RunContext ctx = make_ctx("/proj/one");
    auto run = h.engine->create_run(spec, Json{{"factor", "porosity"}}, &ctx);
    const auto final_run = h.engine->run(run.run_id, &ctx);
    check(final_run.find_node_run("c")->skip_reason.value_or("") ==
              "upstream b unavailable", "case12 dependent skip reason");
    expect_json("case12.run", proj_run(final_run), fixture.at("run"));
    expect_json("case12.calls", h.calls_json(), fixture.at("calls"));
}

void case_cancel_mid_run(const Json& fixture, const Json& env) {
    Harness h(env, {rid(1301)});
    h.add_action("t.compute");
    h.add_action("t.stop");
    h.script("t.compute", {}, compute_fallback());
    ActionResultView stopped;
    stopped.status = "cancelled";
    stopped.error = "user pressed stop";
    stopped.elapsed_ms = 5.0;
    h.script("t.stop", {stopped});
    spec_ns::WorkflowSpec spec;
    spec.workflow_id = "wf.cancel";
    spec.name = "Cancel";
    spec_ns::NodeSpec a;
    a.node_id = "a";
    a.action_id = "t.compute";
    a.parameters = Json{{"factor", Json{{"$slot", "factor"}}}};
    spec_ns::NodeSpec b;
    b.node_id = "b";
    b.action_id = "t.stop";
    b.depends_on = {"a"};
    spec_ns::NodeSpec c;
    c.node_id = "c";
    c.action_id = "t.compute";
    c.depends_on = {"b"};
    spec.nodes = {a, b, c};
    spec_ns::SlotSpec slot;
    slot.name = "factor";
    slot.schema = Json{{"type", "string"}};
    spec.slots = {slot};
    h.build();
    RunContext ctx = make_ctx("/proj/one");
    auto run = h.engine->create_run(spec, Json{{"factor", "porosity"}}, &ctx);
    const auto cancelled = h.engine->run(run.run_id, &ctx);
    const Json first = proj_run(cancelled);
    const auto second = h.engine->run(run.run_id, &ctx);  // early return
    expect_json("case13.first", first, fixture.at("first"));
    expect_json("case13.second", proj_run(second), fixture.at("second"));
    expect_json("case13.calls", h.calls_json(), fixture.at("calls"));
}

void case_cancel_no_active(const Json& fixture, const Json& env) {
    Harness h(env, {rid(1401)});
    h.add_action("t.compute");
    h.script("t.compute", {});
    spec_ns::WorkflowSpec spec;
    spec.workflow_id = "wf.solo";
    spec.name = "Solo";
    spec_ns::NodeSpec solo;
    solo.node_id = "solo";
    solo.action_id = "t.compute";
    spec.nodes = {solo};
    h.build();
    RunContext ctx = make_ctx("/proj/one");
    auto run = h.engine->create_run(spec, Json::object(), &ctx);
    h.engine->run(run.run_id, &ctx);
    check(h.engine->cancel("no-such-run") == fixture.at("cancel_unknown").get<bool>(),
          "case14 cancel unknown run");
    check(h.engine->cancel(run.run_id) == fixture.at("cancel_finished").get<bool>(),
          "case14 cancel finished run");
}

void case_checkpoint_failure(const Json& fixture, const Json& env) {
    Harness h(env, {rid(1501), rid(1502)});
    script_chain(h);
    h.build();
    RunContext ctx = make_ctx("/proj/one");
    auto run = h.engine->create_run(chain_spec(), Json{{"factor", "porosity"}}, &ctx);
    const std::string run_id = run.run_id;
    RunOptions opts;
    opts.on_update = [&h](const spec_ns::WorkflowRun&) {
        std::error_code ec;
        std::filesystem::permissions(
            h.tmp, std::filesystem::perms::owner_read | std::filesystem::perms::owner_exec,
            std::filesystem::perm_options::replace, ec);  // next save must fail
    };
    std::string raised = "none";
    try {
        h.engine->run(run_id, &ctx, opts);
    } catch (const CheckpointFailed&) {
        raised = "CheckpointFailed";
    } catch (...) {
        raised = "other-exception";
    }
    std::error_code ec;
    std::filesystem::permissions(h.tmp, std::filesystem::perms::owner_all,
                                 std::filesystem::perm_options::replace, ec);
    check(raised == fixture.at("exception").get<std::string>(),
          "case15 raises CheckpointFailed (got " + raised + ")");
    const Json persisted = proj_run(h.store->load(run_id));
    expect_json("case15.after_failure", persisted, fixture.at("after_failure"));
    const auto resumed = h.engine->resume(run_id, &ctx);
    check(resumed.state == spec_ns::RunState::completed, "case15 resume completes");
    expect_json("case15.after_resume", proj_run(resumed), fixture.at("after_resume"));
    expect_json("case15.calls", h.calls_json(), fixture.at("calls"));
}

void case_project_guard(const Json& fixture, const Json& env) {
    Harness h(env, {rid(1601), rid(1602)});
    h.add_action("t.compute");
    h.script("t.compute", {});  // no node ever executes under the guard
    spec_ns::WorkflowSpec spec;
    spec.workflow_id = "wf.guard";
    spec.name = "Guard";
    spec_ns::NodeSpec a;
    a.node_id = "a";
    a.action_id = "t.compute";
    spec_ns::NodeSpec b;
    b.node_id = "b";
    b.action_id = "t.compute";
    b.depends_on = {"a"};
    spec.nodes = {a, b};
    h.build();
    RunContext one = make_ctx("/proj/one", Json("proj-live"));
    RunContext two = make_ctx("/proj/two", Json("proj-live"));
    auto run = h.engine->create_run(spec, Json::object(), &one);

    Json mismatch;
    try {
        h.engine->run(run.run_id, &two);
        check(false, "case16 run mismatch must raise");
    } catch (const pwb::workflow_engine::WorkflowValidationError& exc) {
        mismatch = Json{{"type", "WorkflowValidationError"},
                        {"message", std::string(exc.what())},
                        {"problems", Json(exc.problems)}};
    }
    expect_json("case16.run_mismatch", mismatch, fixture.at("run_mismatch"));

    Json rerun_error;
    try {
        h.engine->rerun(run.run_id, {}, Json::object(), &two);
        check(false, "case16 rerun mismatch must raise");
    } catch (const pwb::workflow_engine::WorkflowValidationError& exc) {
        rerun_error = Json{{"type", "WorkflowValidationError"},
                           {"message", std::string(exc.what())},
                           {"problems", Json(exc.problems)}};
    }
    expect_json("case16.rerun_mismatch", rerun_error, fixture.at("rerun_mismatch"));

    RunOptions switch_opts;
    switch_opts.project_probe = [] { return Json("other-project"); };
    const auto switched = h.engine->run(run.run_id, &one, switch_opts);
    expect_json("case16.probe_switch", proj_run(switched), fixture.at("probe_switch"));

    RunOptions raise_opts;
    raise_opts.project_probe = []() -> Json {
        throw std::runtime_error("probe blew up");
    };
    const auto probe_raised = h.engine->run(run.run_id, &one, raise_opts);
    expect_json("case16.probe_raise", proj_run(probe_raised), fixture.at("probe_raise"));
}

void case_degraded(const Json& fixture, const Json& env) {
    Harness h(env, {rid(1701)});
    h.add_action("t.compute");
    ActionResultView degraded;
    degraded.status = "degraded";
    degraded.outputs = Json{{"grid", "ok"}, {"version_ids", Json::array({"v-d-1"})}};
    degraded.warnings = {"low coverage", "sparse wells"};
    degraded.elapsed_ms = 12.5;
    h.script("t.compute", {degraded});
    spec_ns::WorkflowSpec spec;
    spec.workflow_id = "wf.degraded";
    spec.name = "Degraded";
    spec_ns::NodeSpec d;
    d.node_id = "d";
    d.action_id = "t.compute";
    spec.nodes = {d};
    h.build();
    RunContext ctx = make_ctx("/proj/one");
    auto run = h.engine->create_run(spec, Json::object(), &ctx);
    const auto final_run = h.engine->run(run.run_id, &ctx);
    check(final_run.state == spec_ns::RunState::completed, "case17 run completes");
    check(final_run.find_node_run("d")->action_status.value_or("") == "degraded",
          "case17 action_status degraded");
    expect_json("case17.run", proj_run(final_run), fixture.at("run"));
    expect_json("case17.calls", h.calls_json(), fixture.at("calls"));
}

void case_context_unavailable(const Json& fixture, const Json& env) {
    Harness h(env, {rid(1801)});
    h.add_action("t.compute");
    h.script("t.compute", {});
    spec_ns::WorkflowSpec spec;
    spec.workflow_id = "wf.ctx";
    spec.name = "Ctx";
    spec_ns::NodeSpec n;
    n.node_id = "n";
    n.action_id = "t.compute";
    n.parameters = Json{{"well", Json{{"$context", "active_well_id"}}}};
    spec_ns::NodeSpec d;
    d.node_id = "d";
    d.action_id = "t.compute";
    d.depends_on = {"n"};
    spec.nodes = {n, d};
    h.build();
    RunContext ctx = make_ctx("/proj/one");  // no active_well_id in the session
    auto run = h.engine->create_run(spec, Json::object(), &ctx);
    const auto final_run = h.engine->run(run.run_id, &ctx);
    check(final_run.state == spec_ns::RunState::failed, "case18 run fails");
    expect_json("case18.run", proj_run(final_run), fixture.at("run"));
    expect_json("case18.calls", h.calls_json(), fixture.at("calls"));
}

void case_double_run_guard(const Json& fixture, const Json& env) {
    Harness h(env, {rid(1901), rid(1902)});
    script_chain(h);
    h.build();
    RunContext ctx = make_ctx("/proj/one");
    auto run = h.engine->create_run(chain_spec(), Json{{"factor", "porosity"}}, &ctx);
    Json nested;
    RunOptions opts;
    opts.on_update = [&h, &run_id = run.run_id, &ctx, &nested](const spec_ns::WorkflowRun&) {
        try {
            h.engine->run(run_id, &ctx);  // re-entrant: must refuse
        } catch (const pwb::workflow_engine::WorkflowValidationError& exc) {
            nested = Json{{"type", "WorkflowValidationError"},
                          {"message", std::string(exc.what())},
                          {"problems", Json(exc.problems)}};
        }
    };
    const auto final_run = h.engine->run(run.run_id, &ctx, opts);
    check(!nested.is_null(), "case19 re-entrant run raised");
    expect_json("case19.nested_error", nested, fixture.at("nested_error"));
    expect_json("case19.run", proj_run(final_run), fixture.at("run"));
}

void case_cache_reuse_new_run(const Json& fixture, const Json& env) {
    Harness h(env, {rid(2001), rid(2002)});
    h.add_action("t.compute");
    h.add_action("t.cacheable", /*cacheable=*/true);
    h.script("t.cacheable", {}, [](const Json&) {
        return ok_view(Json{{"factor", "porosity"},
                            {"version_ids", Json::array({"v-a-1"})}});
    });
    h.script("t.compute", {}, [](const Json&) { return b_view(); });
    spec_ns::WorkflowSpec spec;
    spec.workflow_id = "wf.cache";
    spec.name = "Cache";
    spec_ns::NodeSpec a;
    a.node_id = "a";
    a.action_id = "t.cacheable";
    a.parameters = Json{{"factor", Json{{"$slot", "factor"}}}};
    spec_ns::NodeSpec b;
    b.node_id = "b";
    b.action_id = "t.compute";
    b.depends_on = {"a"};
    spec.nodes = {a, b};
    spec_ns::SlotSpec slot;
    slot.name = "factor";
    slot.schema = Json{{"type", "string"}};
    spec.slots = {slot};
    h.build();
    RunContext ctx = make_ctx("/proj/one");
    auto first = h.engine->create_run(spec, Json{{"factor", "porosity"}}, &ctx);
    h.engine->run(first.run_id, &ctx);
    const std::size_t calls_after_first = h.calls.size();
    auto second = h.engine->create_run(spec, Json{{"factor", "porosity"}}, &ctx);
    const auto final_run = h.engine->run(second.run_id, &ctx);
    check(final_run.find_node_run("a")->from_cache, "case20 a reused from cache");
    check(h.calls.size() == calls_after_first + 1, "case20 only b executed");
    expect_json("case20.run", proj_run(final_run), fixture.at("run"));
    expect_json("case20.calls", h.calls_json_from(calls_after_first),
                fixture.at("calls"));
}

}  // namespace

int main(int argc, char** argv) {
    const std::string fixture_path =
        argc > 1 ? argv[1]
                 : "libs/workflow_engine/workflow_engine_tests/fixtures/"
                   "workflow_engine_lifecycle_oracle.json";
    const Json doc = load_fixture(fixture_path);
    const Json& env = doc.at("meta").at("environment");
    const Json& cases = doc.at("cases");

    case_run_complete_chain(cases.at("run_complete_chain"), env);
    case_static_validation(cases.at("static_validation_unknown_action"), env);
    case_slot_schema(cases.at("slot_schema_missing_required"), env);
    case_crash_resume(cases.at("crash_resume_completes"), env);
    case_failure_no_revival(cases.at("failure_no_resume_revival"), env);
    case_rerun_carry_all(cases.at("rerun_carry_all"), env);
    case_rerun_slot_override(cases.at("rerun_slot_override_miss"), env);
    case_rerun_from_b(cases.at("rerun_from_b"), env);
    case_conditions(cases.at("conditions"), env);
    case_retry_resource_shed(cases.at("retry_resource_shed"), env);
    case_plain_rejection(cases.at("plain_rejection"), env);
    case_unavailable(cases.at("unavailable"), env);
    case_cancel_mid_run(cases.at("cancel_mid_run"), env);
    case_cancel_no_active(cases.at("cancel_no_active"), env);
    case_checkpoint_failure(cases.at("checkpoint_failure"), env);
    case_project_guard(cases.at("project_guard"), env);
    case_degraded(cases.at("degraded"), env);
    case_context_unavailable(cases.at("context_unavailable"), env);
    case_double_run_guard(cases.at("double_run_guard"), env);
    case_cache_reuse_new_run(cases.at("cache_reuse_new_run"), env);

    // Negative self-checks: tampered expectations MUST compare unequal
    // (proves the comparisons above are not vacuous).
    {
        Json expected = cases.at("run_complete_chain").at("run");
        Json actual = expected;  // shape stand-in via copy then re-tamper below
        Json tampered = expected;
        tampered["state"] = "failed";
        check(!pwb::domain::json_semantic_diff(actual, tampered).equal,
              "negative: tampered run state must differ");
        ++g_negatives;
        tampered = expected;
        tampered["node_runs"]["a"]["attempt"] = 99;
        check(!pwb::domain::json_semantic_diff(actual, tampered).equal,
              "negative: tampered attempt must differ");
        ++g_negatives;
        Json msg = cases.at("project_guard").at("run_mismatch");
        Json tampered_msg = msg;
        tampered_msg["message"] = "workflow 'wf.guard' invalid: tampered";
        check(!pwb::domain::json_semantic_diff(msg, tampered_msg).equal,
              "negative: tampered guard message must differ");
        ++g_negatives;
    }

    if (g_failures != 0) {
        std::fprintf(stderr, "FAILED: %d of %d checks\n", g_failures, g_checks);
        return 1;
    }
    std::printf("ALL %d CHECKS PASSED (+%d negative self-checks)\n", g_checks,
                g_negatives);
    return 0;
}
