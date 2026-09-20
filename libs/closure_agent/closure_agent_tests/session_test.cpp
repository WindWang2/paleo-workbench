// closure_agent.session — the deterministic recorded-response e2e and the
// negative contract set:
//   plan -> tool call (real provider SDK) -> result -> audit receipt ->
//   checkpoint -> cancel (late result refused) -> recovery/resume,
// plus: unauthorized tool calls rejected, corrupted checkpoint rejected,
// duplicate receipts rejected, WRITE confirmation boundary.
#include "test_util.hpp"

#include <pwb/closure_agent/checkpoint.hpp>
#include <pwb/closure_agent/events.hpp>
#include <pwb/closure_agent/session.hpp>
#include <pwb/providers/builtin.hpp>
#include <pwb/providers/errors.hpp>
#include <pwb/providers/execution.hpp>

#include <algorithm>
#include <filesystem>
#include <fstream>
#include <set>

using namespace pwb::closure_agent;
namespace pp = pwb::providers;

namespace {

std::filesystem::path store_dir(const std::string& name) {
    return std::filesystem::temp_directory_path() /
           ("closure-agent-session-test-" + name);
}

struct Fixture {
    ActionRegistry registry;
    pp::ProviderRegistry providers;
    HarnessExecutor executor;
    SessionCheckpointStore store;
    AgentEventBus bus;
    std::vector<AgentEvent> events;
    NodeBindings bindings;
    long long turn_counter = 0;

    explicit Fixture(const std::string& dir_name, bool wipe = true)
        : executor(registry), store(store_dir(dir_name)) {
        if (wipe) {
            std::error_code ec;
            std::filesystem::remove_all(store_dir(dir_name), ec);
        }
        pp::register_builtin_providers(providers);
        register_actions();
        bus.subscribe([this](const AgentEvent& event) {
            events.push_back(event);
        });
        bindings.agent_actions = {
            {"data_agent", "data.discover_and_validate"},
            {"well_agent", "well.process_tops_and_curves"},
            {"seismic_agent", "seismic.extract_slices"},
            {"gis_agent", "gis.analyze_spatial_constraints"},
            {"carto_agent", "carto.generate_factor_surface"},
            {"viz_agent", "viz.compose_map_layout"},  // WRITE risk
            {"qa_agent", "qa.audit_and_verify"},
            {"result_agent", "result.package_and_report"},
        };
    }

    static Json factor_dataset() {
        Json dataset = Json::object();
        dataset["factor_name"] = "砂地比";
        dataset["unit"] = "1";
        dataset["target_horizon"] = "长8段";
        dataset["crs"] = "EPSG:4326";
        Json points = Json::array();
        for (const auto& [name, value] :
             std::vector<std::pair<const char*, double>>{
                 {"w1", 0.31}, {"w2", 0.42}, {"w3", 0.55},
                 {"w4", 0.38}, {"w5", 0.60}}) {
            Json point = Json::object();
            point["name"] = name;
            point["value"] = value;
            point["qc_flag"] = "ok";
            points.push_back(point);
        }
        dataset["points"] = points;
        return dataset;
    }

    void register_actions() {
        auto simple = [&](const std::string& id, ActionRisk risk,
                          ActionHandler handler) {
            ActionSpec spec;
            spec.action_id = id;
            spec.description = "session e2e action " + id;
            spec.risk = risk;
            spec.handler = std::move(handler);
            registry.register_spec(spec);
        };
        simple("data.discover_and_validate", ActionRisk::Read,
               [](void*, const Json& parameters) {
                   return Json{{"assets", 12},
                               {"target_horizon", parameters.value("target_horizon", "")}};
               });
        simple("well.process_tops_and_curves", ActionRisk::Compute,
               [](void*, const Json&) {
                   return Json{{"tops", Json::array({"长8顶", "长7底"})},
                               {"curves", Json::array({"GR", "DTW"})}};
               });
        simple("seismic.extract_slices", ActionRisk::Compute,
               [](void*, const Json&) { return Json{{"slices", 4}}; });
        simple("gis.analyze_spatial_constraints", ActionRisk::Compute,
               [](void*, const Json&) { return Json{{"barriers", 3}}; });
        // Real provider SDK consumption: the plan's compute step drives the
        // builtin geology.factor_stats through the guarded pipeline.
        simple("carto.generate_factor_surface", ActionRisk::Compute,
               [](void* ctx, const Json& parameters) {
                   auto* context = static_cast<ActionContext*>(ctx);
                   const auto* providers =
                       reinterpret_cast<const pp::ProviderRegistry*>(
                           context->extras["provider_registry"].get<long long>());
                   pp::ProviderInputs inputs;
                   pp::TypedInput dataset;
                   dataset.type_name = "GeologicalFactorDataset";
                   dataset.payload = parameters["dataset"];
                   inputs.set("dataset", std::move(dataset));
                   pp::ProviderContext provider_context =
                       context->provider_context();
                   provider_context.work_dir =
                       std::filesystem::temp_directory_path().string() +
                       "/closure-agent-session-work";
                   const pp::ProviderResult result = pp::execute_provider(
                       *providers, "geology.factor_stats", inputs,
                       Json::object(), &provider_context, nullptr);
                   Json payload = Json::object();
                   Json artifacts = Json::array();
                   for (const auto& artifact : result.artifacts) {
                       artifacts.push_back(artifact.to_json());
                   }
                   payload["artifacts"] = artifacts;
                   payload["factor"] = parameters["dataset"]["factor_name"];
                   return payload;
               });
        simple("viz.compose_map_layout", ActionRisk::Write,
               [](void*, const Json&) {
                   Json document = Json::object();
                   Json layers = Json::array();
                   Json layer = Json::object();
                   layer["id"] = "factor-grid";
                   layer["name"] = "砂地比网格";
                   layer["visible"] = true;
                   layer["features"] = Json::array({Json("p1")});
                   layers.push_back(layer);
                   document["layers"] = layers;
                   document["extent"] =
                       std::vector<double>{106.0, 35.0, 108.0, 37.0};
                   document["crs"] = "EPSG:4326";
                   return Json{{"map_document", document}};
               });
        simple("qa.audit_and_verify", ActionRisk::Compute,
               [](void*, const Json&) {
                   Json grid = Json::array();
                   for (const double v : {0.31, 0.42, 0.55, 0.38, 0.60, 0.47}) {
                       grid.push_back(v);
                   }
                   return Json{{"values", grid}, {"qc", "pass"}};
               });
        simple("result.package_and_report", ActionRisk::Compute,
               [](void*, const Json&) {
                   return Json{{"report", "executed"},
                               {"lineage", Json::array({"discover", "carto"})}};
               });
    }

    SessionConfig make_config() {
        SessionConfig config;
        config.registry = &registry;
        config.executor = &executor;
        config.checkpoints = &store;
        config.events = &bus;
        config.bindings = bindings;
        config.context_initializer = [this](ActionContext& context) {
            context.extras["provider_registry"] =
                reinterpret_cast<long long>(&providers);
        };
        config.turn_id_generator = [this] {
            return "turn-" + std::to_string(++turn_counter);
        };
        return config;
    }
};

}  // namespace

int main() {
    const std::string query =
        "对长东区块做砂地比单因素编图，目标层位长8段";

    // ---- e2e: plan -> confirmation -> tools -> results -> audit -------------
    std::string session_id;
    std::size_t receipt_count = 0;
    {
        Fixture fixture("e2e");
        SessionConfig config = fixture.make_config();
        AgentSession session(config);
        session_id = session.session_id();

        const SessionTurn turn =
            session.submit(query, Json{{"dataset", Fixture::factor_dataset()}});
        // WRITE-bearing plan stops at the confirmation boundary.
        check(session.state() == SessionState::AwaitingConfirmation,
              "write-bearing plan stops at the confirmation boundary");
        check(turn.status == "awaiting_confirmation",
              "turn status awaiting_confirmation");
        check(turn.intent.factor_type == "sand_ratio", "intent factor extracted");
        check(turn.intent.target_horizon == "目标层位长8段",
              "oracle horizon extracted");
        check(session.receipts().empty(), "no receipts before the grant");
        // Partial grant does not run the plan.
        check(session.confirm_write({}).status == "awaiting_confirmation",
              "partial grant keeps the confirmation boundary");
        check(session.confirm_write({"viz.compose_map_layout"}).status ==
                  "completed",
              "granted plan runs to completion");
        check(session.state() == SessionState::Completed, "session completed");
        check(session.receipts().size() == 7, "one receipt per completed node");
        receipt_count = session.receipts().size();
        std::set<std::string> ids;
        for (const auto& receipt : session.receipts()) ids.insert(receipt.receipt_id);
        check(ids.size() == receipt_count, "receipt ids unique");
        const SessionTurn& done = *session.current_turn();
        check(done.deliverable.is_object() && done.deliverable.contains("report"),
              "deliverable extracted from the result node");
        bool saw_factor_artifacts = false;
        for (const auto& node : done.plan.nodes) {
            if (node.id == "task_carto_generate" && node.result.is_object()) {
                const auto outputs = node.result.find("outputs");
                saw_factor_artifacts = outputs != node.result.end() &&
                                       outputs->contains("artifacts") &&
                                       (*outputs)["artifacts"].is_array() &&
                                       (*outputs)["artifacts"].size() == 1;
            }
        }
        check(saw_factor_artifacts,
              "cartography step executed the REAL factor-stats provider");
        // Events: ordered state machine trace.
        std::vector<std::string> types;
        for (const auto& event : fixture.events) types.push_back(event.type);
        check(std::find(types.begin(), types.end(),
                        "session.confirmation_required") != types.end(),
              "confirmation event published");
        check(std::count(types.begin(), types.end(), "session.receipt_issued") == 7,
              "receipt events published");
        check(std::count(types.begin(), types.end(),
                         "session.checkpoint_written") >= 1,
              "checkpoint events published");
    }

    // ---- recovery: a fresh session rebuilds from the checkpoint -------------
    {
        Fixture fixture("e2e", /*wipe=*/false);
        fixture.turn_counter = 1000;
        SessionConfig config = fixture.make_config();
        AgentSession session(config);
        const SessionTurn recovered = session.recover(session_id);
        check(recovered.status == "completed", "recovered terminal status");
        check(session.receipts().size() == receipt_count,
              "receipts restored from the checkpoint");
        bool duplicate_refused = false;
        try {
            session.apply_receipt(session.receipts().front());
        } catch (const DuplicateReceiptError&) {
            duplicate_refused = true;
        }
        check(duplicate_refused, "duplicate receipt refused");
        check(session.resume().status == "completed",
              "resume on a finished plan keeps the terminal state");
    }

    // ---- rejection of unauthorized write plans ------------------------------
    {
        Fixture fixture("neg-write");
        SessionConfig config = fixture.make_config();
        AgentSession session(config);
        session.submit("把图层导出为高精SVG和PDF截图");
        check(session.state() == SessionState::AwaitingConfirmation,
              "write plan requires explicit grant");
        const SessionTurn rejected = session.reject_write();
        check(rejected.status == "rejected", "user rejection is terminal");
        check(session.receipts().empty(), "rejected write plan produced no receipts");
    }

    // ---- cancel + late result refusal ---------------------------------------
    {
        Fixture fixture("cancel");
        // The cartography step arms the token mid-handler; its result arrives
        // after cancellation and must NOT resurrect the turn.
        ActionSpec canceller =
            *fixture.registry.find("carto.generate_factor_surface");
        canceller.handler = [](void* ctx, const Json&) {
            static_cast<ActionContext*>(ctx)->cancel->cancel();
            return Json{{"artifacts", Json::array()}, {"factor", "砂地比"}};
        };
        fixture.registry.register_spec(canceller, true);
        SessionConfig config = fixture.make_config();
        AgentSession session(config);
        session.submit("对比XX井和YY井的砂组顶面并生成单因素图");
        check(session.state() == SessionState::AwaitingConfirmation,
              "plan reaches the confirmation boundary before cancel");
        const SessionTurn turn = session.confirm_write({"viz.compose_map_layout"});
        check(turn.status == "cancelled", "turn cancelled after late result");
        check(session.state() == SessionState::Cancelled, "session cancelled");
        for (const auto& node : turn.plan.nodes) {
            if (node.id == "task_carto_generate") {
                check(node.status == TaskStatus::Skipped &&
                          node.error.value_or("").find("late result") !=
                              std::string::npos,
                      "late result recorded as skipped, never completed");
            }
            check(node.status != TaskStatus::Running, "no node left running");
        }
        check(turn.deliverable.is_null(), "cancelled turn has no deliverable");
    }

    // ---- corrupted checkpoint is rejected, never faked ----------------------
    {
        Fixture fixture("corrupt");
        SessionConfig config = fixture.make_config();
        AgentSession session(config);
        session.submit(query, Json{{"dataset", Fixture::factor_dataset()}});
        session.confirm_write({"viz.compose_map_layout"});
        const std::string sid = session.session_id();
        const std::filesystem::path path =
            store_dir("corrupt") / (sid + ".json");
        std::error_code ec;
        check(std::filesystem::exists(path, ec), "checkpoint file exists");
        // Tamper: flip a byte inside the payload region.
        std::ifstream in(path, std::ios::binary);
        std::string body((std::istreambuf_iterator<char>(in)),
                         std::istreambuf_iterator<char>());
        in.close();
        const auto pos = body.find("executed");
        check(pos != std::string::npos, "tamper target found");
        if (pos != std::string::npos) body[pos] = 'X';
        std::ofstream out(path, std::ios::binary | std::ios::trunc);
        out.write(body.data(), static_cast<std::streamsize>(body.size()));
        out.close();
        bool corrupt_refused = false;
        const std::string message = expect_throw([&] {
            AgentSession restored(fixture.make_config());
            restored.recover(sid);
        });
        corrupt_refused = message.find("corrupted") != std::string::npos ||
                          message.find("mismatch") != std::string::npos;
        check(corrupt_refused,
              "tampered checkpoint rejected (checksum mismatch): " + message);
    }

    // ---- interrupted plan (iteration budget) -> recover -> resume -----------
    {
        Fixture fixture("resume", /*wipe=*/true);
        fixture.turn_counter = 2000;
        SessionConfig config = fixture.make_config();
        config.max_iterations = 1;  // deterministic interruption: one batch
        AgentSession session(config);
        const SessionTurn interrupted_turn = session.submit(
            query, Json{{"dataset", Fixture::factor_dataset()}});
        check(session.state() == SessionState::AwaitingConfirmation,
              "interruptible plan reaches the confirmation boundary");
        const SessionTurn granted = session.confirm_write({"viz.compose_map_layout"});
        check(granted.status == "failed", "iteration budget exhaustion fails honestly");
        check(granted.error.value_or("").find("did not finish") != std::string::npos,
              "interrupted error text");
        check(session.receipts().size() == 1,
              "the first ready node is audited (one ready batch)");
        for (const auto& node : granted.plan.nodes) {
            if (node.id == "task_result_delivery") {
                check(node.status == TaskStatus::Pending,
                      "unfinished suffix stays PENDING (resume-able)");
            }
        }
        const std::string sid = session.session_id();

        // A NEW session (restart simulation) recovers the PENDING suffix.
        Fixture restored_fixture("resume", /*wipe=*/false);
        restored_fixture.turn_counter = 3000;
        SessionConfig restored_config = restored_fixture.make_config();
        AgentSession restored(restored_config);
        const SessionTurn recovered = restored.recover(sid);
        check(recovered.status == "failed", "recovered interrupted status");
        check(restored.receipts().size() == 1, "receipt history restored");
        std::size_t completed_before = 0;
        for (const auto& node : recovered.plan.nodes) {
            if (node.status == TaskStatus::Completed) ++completed_before;
        }
        check(completed_before == 1, "completed prefix restored");
        // Resume finishes the pending suffix (carto -> viz -> qa -> result).
        const SessionTurn resumed = restored.resume();
        check(resumed.status == "completed", "resumed plan completed");
        check(restored.receipts().size() == 7, "resumed suffix audited");
        check(restored.current_turn()->deliverable.contains("report"),
              "resumed deliverable extracted");
    }

    // ---- a genuinely FAILED step never auto-retries on resume ---------------
    {
        Fixture fixture("failed-step", /*wipe=*/true);
        ActionSpec broken = *fixture.registry.find("carto.generate_factor_surface");
        broken.handler = [](void*, const Json&) -> Json {
            throw std::runtime_error("provider kernel exploded");
        };
        fixture.registry.register_spec(broken, true);
        SessionConfig config = fixture.make_config();
        AgentSession session(config);
        session.submit(query, Json{{"dataset", Fixture::factor_dataset()}});
        check(session.state() == SessionState::AwaitingConfirmation,
              "broken-handler plan reaches the confirmation boundary");
        const SessionTurn failed_turn =
            session.confirm_write({"viz.compose_map_layout"});
        check(failed_turn.status == "failed", "interrupted turn failed");
        check(session.receipts().size() == 3,
              "only the completed prefix is audited");
        const std::string sid = session.session_id();

        Fixture restored_fixture("failed-step", /*wipe=*/false);
        // NOTE: the restored fixture's carto handler is the WORKING one, but
        // resume must not silently retry a FAILED step — the turn stays
        // failed until an explicit rerun (fail-closed recovery contract).
        AgentSession restored(restored_fixture.make_config());
        restored.recover(sid);
        const SessionTurn resumed = restored.resume();
        check(resumed.status == "failed",
              "failed step is not silently retried by resume");
    }

    // ---- checkpoint persistence failure is fatal, never fake-completed ------
    {
        Fixture fixture("ckpt-fail");
        // A store rooted under a regular file can never persist: every
        // checkpoint_now() throws, and the turn must land failed.
        std::filesystem::path blocker = std::filesystem::temp_directory_path() /
                                        "closure-agent-ckpt-blocker";
        std::filesystem::remove_all(blocker);
        { std::ofstream out(blocker); out << "not a directory"; }
        SessionCheckpointStore unwritable(blocker);
        SessionConfig config = fixture.make_config();
        config.checkpoints = &unwritable;
        AgentSession session(config);
        session.submit(query);
        check(session.state() == SessionState::AwaitingConfirmation,
              "checkpoint-failure plan reaches the confirmation boundary");
        const SessionTurn turn = session.confirm_write({"viz.compose_map_layout"});
        check(turn.status == "failed",
              "checkpoint failure fails the turn (never completed)");
        check(session.state() == SessionState::Failed,
              "checkpoint failure terminal state is failed");
        check(turn.error.value_or("").find("checkpoint persistence failed") !=
                  std::string::npos,
              "checkpoint failure error text");
        // The pre-failure prefix is still audited (receipts exist) but the
        // turn never scores completed and exposes no deliverable: without a
        // terminal checkpoint there is no recoverable success.
        check(session.receipts().size() >= 1,
              "completed prefix still audited before the failure");
        check(turn.deliverable.is_null(),
              "failed turn exposes no deliverable");
        std::error_code ec;
        std::filesystem::remove_all(blocker, ec);
    }

    // ---- resume never resurrects a user-rejected turn ------------------------
    {
        Fixture fixture("neg-write");
        SessionConfig config = fixture.make_config();
        AgentSession session(config);
        session.submit("把图层导出为高精SVG和PDF截图");
        check(session.reject_write().status == "rejected", "rejected terminal");
        const SessionTurn& after = session.resume();
        check(after.status == "rejected",
              "resume does not resurrect a rejected turn");
        check(session.receipts().empty(),
              "rejected turn still has no receipts after resume attempt");
    }

    return test_exit("closure_agent.session");
}
