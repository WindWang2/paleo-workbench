// CONV-06 acceptance test: reconciles the C++ workflow_spec port against the
// Python oracle fixture frozen by tools/oracle/generate_workflow_spec_fixtures.py.
// Every expectation (problem messages in full-list order, round-trip JSON,
// canonical hashes, resolved bindings) was computed by running the real
// paleo_workbench modules. Registered as ctest "workflow_spec.validate".
#include <fstream>
#include <iostream>
#include <optional>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/workflow_spec/model.hpp>
#include <pwb/workflow_spec/validation.hpp>

#ifndef PWB_WORKFLOW_SPEC_FIXTURE
#error "PWB_WORKFLOW_SPEC_FIXTURE must point at workflow_spec_oracle.json"
#endif

namespace {

int g_failures = 0;
int g_checks = 0;

void check(bool ok, const std::string& context, const std::string& detail) {
    ++g_checks;
    if (!ok) {
        ++g_failures;
        std::cerr << "FAIL " << context << (detail.empty() ? "" : ": " + detail)
                  << "\n";
    }
}

void check_json_equal(const pwb::domain::Json& expected,
                      const pwb::domain::Json& actual,
                      const std::string& context) {
    // Byte-level dump comparison pins the Python to_dict KEY ORDER too
    // (D3 byte-for-byte layout promise); == alone is key-order-insensitive.
    check(expected.dump() == actual.dump(), context,
          "expected " + expected.dump() + ", got " + actual.dump());
}

void check_strings(const std::vector<std::string>& expected,
                   const std::vector<std::string>& actual,
                   const std::string& context) {
    bool equal = expected.size() == actual.size();
    if (equal) {
        for (std::size_t i = 0; i < expected.size(); ++i) {
            if (expected[i] != actual[i]) {
                equal = false;
                break;
            }
        }
    }
    if (!equal) {
        std::string detail = "expected [";
        for (const auto& p : expected) detail += p + " | ";
        detail += "] got [";
        for (const auto& p : actual) detail += p + " | ";
        detail += "]";
        check(false, context, detail);
    } else {
        check(true, context, "");
    }
}

pwb::workflow_spec::ActionCatalog
catalog_from_json(const pwb::domain::Json& map) {
    pwb::workflow_spec::ActionCatalog catalog;
    for (const auto& [action_id, risk] : map.items()) {
        catalog.emplace(action_id, risk.get<std::string>());
    }
    return catalog;
}

}  // namespace

int main() {
    std::ifstream fixture_file(PWB_WORKFLOW_SPEC_FIXTURE);
    if (!fixture_file) {
        std::cerr << "FAIL cannot open fixture " << PWB_WORKFLOW_SPEC_FIXTURE
                  << "\n";
        return 2;
    }
    pwb::domain::Json fixture;
    try {
        fixture_file >> fixture;
    } catch (const std::exception& ex) {
        std::cerr << "FAIL fixture is not valid JSON: " << ex.what() << "\n";
        return 2;
    }

    const auto& meta = fixture.at("python");
    check(meta.at("workflow_schema_version").get<std::string>() ==
              std::string(pwb::workflow_spec::kWorkflowSchemaVersion),
          "schema_version constant", "");

    // ------------------------------------------------------ valid_specs --
    for (const auto& case_json : fixture.at("valid_specs")) {
        const std::string name = case_json.at("name").get<std::string>();
        const std::string context = "valid_specs/" + name;
        try {
            const auto spec = pwb::workflow_spec::WorkflowSpec::from_dict(
                case_json.at("spec"));
            const auto catalog =
                catalog_from_json(case_json.at("registry"));
            const auto problems =
                pwb::workflow_spec::validate_workflow_spec(spec, catalog);
            check_strings({}, problems, context);
            check_json_equal(case_json.at("reserialized"), spec.to_dict(),
                             context + "/roundtrip");
            check(case_json.at("spec_hash").get<std::string>() ==
                      spec.spec_hash(),
                  context + "/spec_hash",
                  "expected " +
                      case_json.at("spec_hash").get<std::string>() + " got " +
                      spec.spec_hash());
        } catch (const std::exception& ex) {
            check(false, context, std::string("threw: ") + ex.what());
        }
    }

    // ----------------------------------------------------- invalid_specs --
    for (const auto& case_json : fixture.at("invalid_specs")) {
        const std::string name = case_json.at("name").get<std::string>();
        const std::string context = "invalid_specs/" + name;
        try {
            const auto spec = pwb::workflow_spec::WorkflowSpec::from_dict(
                case_json.at("spec"));
            const auto catalog =
                catalog_from_json(case_json.at("registry"));
            const auto problems =
                pwb::workflow_spec::validate_workflow_spec(spec, catalog);
            std::vector<std::string> expected;
            for (const auto& problem : case_json.at("problems")) {
                expected.push_back(problem.get<std::string>());
            }
            check_strings(expected, problems, context);
        } catch (const std::exception& ex) {
            check(false, context, std::string("threw: ") + ex.what());
        }
    }

    // ---------------------------------------------------- condition_trees --
    for (const auto& case_json : fixture.at("condition_trees")) {
        const std::string context =
            "condition_trees/" +
            case_json.at("name").get<std::string>();
        const auto condition = pwb::workflow_spec::NodeCondition::from_dict(
            case_json.at("condition"));
        // from_dict(to_dict()) must round-trip the frozen shape first.
        check_json_equal(case_json.at("condition"), condition.to_dict(),
                         context + "/roundtrip");
        std::vector<std::string> expected;
        for (const auto& problem : case_json.at("problems")) {
            expected.push_back(problem.get<std::string>());
        }
        check_strings(
            expected,
            pwb::workflow_spec::validate_condition_tree(condition), context);
    }

    // ------------------------------------------------------ slot_bindings --
    for (const auto& case_json : fixture.at("slot_bindings")) {
        const std::string context =
            "slot_bindings/" + case_json.at("name").get<std::string>();
        const auto spec = pwb::workflow_spec::WorkflowSpec::from_dict(
            case_json.at("spec"));
        const auto materialized = pwb::workflow_spec::materialize_slot_defaults(
            spec, case_json.at("slot_values"));
        check_json_equal(case_json.at("materialized"), materialized,
                         context + "/materialized");
        std::vector<std::string> expected;
        for (const auto& problem : case_json.at("problems")) {
            expected.push_back(problem.get<std::string>());
        }
        check_strings(expected,
                      pwb::workflow_spec::slot_schema_problems(spec,
                                                               materialized),
                      context);
    }

    // ------------------------------------------------------------- resolve --
    for (const auto& case_json : fixture.at("resolve")) {
        const std::string context =
            "resolve/" + case_json.at("name").get<std::string>();
        pwb::workflow_spec::BindEnv env;
        env.slot_values = case_json.at("slot_values");
        for (const auto& [node_id, outputs] :
             case_json.at("results").items()) {
            env.results.emplace(node_id, outputs);
        }
        for (const auto& [key, value] : case_json.at("context").items()) {
            env.context_values.emplace(key, value);
        }
        std::optional<std::string> error;
        pwb::domain::Json resolved{nullptr};
        try {
            resolved = pwb::workflow_spec::resolve_value(case_json.at("value"),
                                                         env);
        } catch (const pwb::workflow_spec::BindingError& ex) {
            error = ex.what();
        } catch (const std::exception& ex) {
            check(false, context,
                  std::string("unexpected exception: ") + ex.what());
            continue;
        }
        const bool has_error = case_json.at("error").is_string();
        check(has_error == error.has_value(), context + "/error_kind",
              error.value_or(""));
        if (has_error && error.has_value()) {
            check(case_json.at("error").get<std::string>() == *error,
                  context + "/error_text", *error);
        } else if (!has_error) {
            check_json_equal(case_json.at("resolved"), resolved,
                             context + "/resolved");
        }
    }

    // ------------------------------------------------------- canonical_hash --
    for (const auto& case_json : fixture.at("canonical_hash")) {
        const std::string context =
            "canonical_hash/" + case_json.at("name").get<std::string>();
        const std::string hash = pwb::workflow_spec::canonical_hash(
            case_json.at("value"));
        check(case_json.at("hash").get<std::string>() == hash,
              context, "got " + hash);
    }

    // --------------------------------------------------------- run_roundtrip --
    for (const auto& case_json : fixture.at("run_roundtrip")) {
        const std::string context =
            "run_roundtrip/" + case_json.at("name").get<std::string>();
        try {
            const auto run = pwb::workflow_spec::WorkflowRun::from_dict(
                case_json.at("run"));
            check_json_equal(case_json.at("reserialized"), run.to_dict(),
                             context + "/roundtrip");
        } catch (const std::exception& ex) {
            check(false, context, std::string("threw: ") + ex.what());
        }
    }

    // -------------------------------------------------------- from_dict_error --
    // Python raises (KeyError/ValueError/TypeError); the port must throw too
    // (exception text is not frozen — D5 maps the types).
    for (const auto& case_json : fixture.at("from_dict_error")) {
        const std::string context =
            "from_dict_error/" + case_json.at("name").get<std::string>();
        bool threw = false;
        try {
            if (case_json.at("spec").contains("node_id")) {
                static_cast<void>(
                    pwb::workflow_spec::NodeRun::from_dict(
                        case_json.at("spec")));
            } else if (case_json.at("spec").contains("run_id")) {
                static_cast<void>(
                    pwb::workflow_spec::WorkflowRun::from_dict(
                        case_json.at("spec")));
            } else {
                static_cast<void>(
                    pwb::workflow_spec::WorkflowSpec::from_dict(
                        case_json.at("spec")));
            }
        } catch (const std::exception&) {
            threw = true;
        }
        check(threw, context, "expected a throw, got success");
    }

    // ------------------------------------------ create_run / model helpers --
    // Smoke coverage for the run factory (07 will consume it): the explicit
    // overload is fully deterministic.
    {
        pwb::workflow_spec::WorkflowSpec spec;
        spec.workflow_id = "wf.create";
        spec.name = "create";
        spec.nodes.push_back({});
        spec.nodes.back().node_id = "a";
        spec.nodes.back().action_id = "a.compute";
        spec.nodes.push_back({});
        spec.nodes.back().node_id = "b";
        spec.nodes.back().action_id = "b.compute";
        const auto run = pwb::workflow_spec::create_run(
            spec, pwb::domain::Json::object({{"factor", "GR"}}), "runid0001",
            1758144000.0);
        check(run.run_id == "runid0001", "create_run/run_id", "");
        check(run.node_runs.size() == 2 && run.node_runs[0].first == "a" &&
                  run.node_runs[1].first == "b",
              "create_run/node_runs order", "");
        check(run.node_runs[0].second.state ==
                      pwb::workflow_spec::NodeState::pending,
              "create_run/pending", "");
        check(run.created_at == pwb::domain::Json(1758144000.0) &&
                  run.updated_at == run.created_at,
              "create_run/timestamps", "");
        check(run.spec_hash.has_value() &&
                  *run.spec_hash == spec.spec_hash(),
              "create_run/spec_hash", "");
        check(run.slot_values == pwb::domain::Json::object(
                                     {{"factor", "GR"}}),
              "create_run/slot_values", "");
        // Terminal-state predicate parity with TERMINAL_NODE_STATES.
        using pwb::workflow_spec::NodeState;
        check(pwb::workflow_spec::is_terminal_node_state(NodeState::succeeded) &&
                  pwb::workflow_spec::is_terminal_node_state(NodeState::failed) &&
                  pwb::workflow_spec::is_terminal_node_state(
                      NodeState::cancelled) &&
                  pwb::workflow_spec::is_terminal_node_state(
                      NodeState::skipped) &&
                  pwb::workflow_spec::is_terminal_node_state(
                      NodeState::unavailable) &&
                  !pwb::workflow_spec::is_terminal_node_state(
                      NodeState::pending) &&
                  !pwb::workflow_spec::is_terminal_node_state(
                      NodeState::running),
              "is_terminal_node_state", "");
        // WorkflowSpec::node hit + miss.
        check(spec.node("b").action_id == "b.compute", "node()/hit", "");
        bool threw = false;
        try {
            static_cast<void>(spec.node("ghost"));
        } catch (const pwb::workflow_spec::ModelError&) {
            threw = true;
        }
        check(threw, "node()/miss throws", "");
    }

    std::cout << "workflow_spec.validate: " << g_checks
              << " checks, " << g_failures << " failures\n";
    return g_failures == 0 ? 0 : 1;
}
