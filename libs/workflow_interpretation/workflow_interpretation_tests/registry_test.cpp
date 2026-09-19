// CONV-32 workflow_interpretation registry oracle replay test.
//
// Replays libs/workflow_interpretation/workflow_interpretation_tests/fixtures/
// workflow_interpretation_registry_oracle.json (frozen from the REAL Python
// implementation — paleo_workbench/workflow/constraint_capabilities.py +
// workflow/interpretation/algorithm_registry.py — by
// tools/oracle/generate_workflow_interpretation_registry_fixtures.py)
// through the C++ port and compares against the frozen expectation:
// semantic JSON equality plus raise parity (python_class + message; the
// str(KeyError(...)) double-quoted form is recomputed and verified too).
//
// Exception-type notes (the frozen headers declare messages, not Python
// exception types):
//  * KeyError parity  — capabilities_for_method throws std::out_of_range
//    (chosen KeyError analog; verified by message + the frozen str() form).
//  * ValueError parity — constraint_kind_from / canonical_algorithm_id
//    throw std::invalid_argument. canonical_algorithm_id actually throws
//    AlgorithmValueError, a std::invalid_argument subclass with
//    python_class() == "ValueError" that lives in algorithm_registry.cpp
//    (the frozen header does not export it); it is caught here by base.
//  * ConstraintViolationError is the frozen-header ValueError subclass
//    (std::runtime_error base) with method/unsupported/ignored attributes.
//
// Includes three comparator NEGATIVE SELF-CHECKS: frozen expectations are
// tampered with in memory and the comparator must flag every one — a green
// replay then proves the comparisons can actually fail.

#include <pwb/domain/json.hpp>
#include <pwb/workflow_interpretation/algorithm_registry.hpp>
#include <pwb/workflow_interpretation/constraint_capabilities.hpp>

#include <algorithm>
#include <cstdio>
#include <fstream>
#include <set>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace {

using pwb::domain::Json;
using pwb::workflow_interpretation::AlgorithmSpec;
using pwb::workflow_interpretation::ConstraintApplication;
using pwb::workflow_interpretation::ConstraintKind;
using pwb::workflow_interpretation::ConstraintSupport;
using pwb::workflow_interpretation::ConstraintViolationError;
using pwb::workflow_interpretation::algorithms;
using pwb::workflow_interpretation::canonical_algorithm_id;
using pwb::workflow_interpretation::capabilities_for_method;
using pwb::workflow_interpretation::capability_matrix;
using pwb::workflow_interpretation::constraint_kind_from;
using pwb::workflow_interpretation::display_label;
using pwb::workflow_interpretation::evaluate_request;
using pwb::workflow_interpretation::get_algorithm;
using pwb::workflow_interpretation::interpolation_algorithm_labels;
using pwb::workflow_interpretation::register_algorithm;
using pwb::workflow_interpretation::to_string;
using pwb::workflow_interpretation::ui_interpolation_methods;

int g_failures = 0;
int g_checks = 0;

constexpr ConstraintKind kKinds[] = {
    pwb::workflow_interpretation::ConstraintKind::BOUNDARY_MASK,
    pwb::workflow_interpretation::ConstraintKind::BARRIER,
    pwb::workflow_interpretation::ConstraintKind::DIRECTION,
    pwb::workflow_interpretation::ConstraintKind::ANISOTROPY,
    pwb::workflow_interpretation::ConstraintKind::TREND,
};

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

// Compare after a dump/parse round-trip so int/unsigned spellings collapse
// exactly like Python's JSON serialization did for the frozen side.
bool json_eq(const Json& got, const Json& expect) {
    return pwb::domain::json_semantically_equal(Json::parse(got.dump()),
                                                expect);
}

bool compare(const std::string& id, const Json& got, const Json& expect,
             bool quiet) {
    if (json_eq(got, expect)) return true;
    if (!quiet) {
        const auto diff = pwb::domain::json_semantic_diff(
            Json::parse(got.dump()), expect);
        std::printf("FAIL %s at %s: %s\n  got:    %s\n  expect: %s\n",
                    id.c_str(), diff.path.c_str(), diff.reason.c_str(),
                    got.dump().c_str(), expect.dump().c_str());
        ++g_failures;
    }
    return false;
}

// ------------------------------------------------------------- raise parity

// python_class + message + the str() form Python would print. str() of a
// KeyError with one string argument reprs the message (it contains single
// quotes and no double quotes, so Python double-quotes it); every other
// exception prints the message verbatim.
Json raise_json(const std::exception& exc, const char* python_class) {
    const std::string message = exc.what();
    Json out = Json::object();
    out["python_class"] = python_class;
    out["message"] = message;
    out["str"] = std::string(python_class) == "KeyError"
                     ? "\"" + message + "\""
                     : message;
    return out;
}

Json eval_app_json(const ConstraintApplication& app) {
    Json labels = Json::array();
    // One named set — taking begin()/end() on two separate temporaries would
    // pair iterators from different objects.
    const std::set<std::string> label_set = app.diagnostics_labels();
    std::vector<std::string> sorted(label_set.begin(), label_set.end());
    std::sort(sorted.begin(), sorted.end());
    for (const std::string& label : sorted) labels.push_back(label);
    Json out = Json::object();
    out["result"] = app.as_dict();
    out["honest"] = app.honest();
    out["diagnostics_labels"] = labels;
    return out;
}

Json run_evaluate(const Json& input) {
    std::vector<std::string> requested;
    for (const Json& kind : input.at("requested")) {
        requested.push_back(kind.get<std::string>());
    }
    try {
        return eval_app_json(evaluate_request(
            input.at("method").get<std::string>(), requested,
            input.value("strict", false)));
    } catch (const ConstraintViolationError& exc) {
        Json raise = raise_json(exc, "ConstraintViolationError");
        raise["method"] = exc.method;
        raise["unsupported"] = exc.unsupported;
        raise["ignored"] = exc.ignored;
        return Json{{"raise", raise}};
    } catch (const std::invalid_argument& exc) {
        // ValueError parity: "'<v>' is not a valid ConstraintKind".
        return Json{{"raise", raise_json(exc, "ValueError")}};
    } catch (const std::out_of_range& exc) {
        // KeyError parity: unknown interpolation method (repr of the
        // ORIGINAL argument + sorted known list).
        return Json{{"raise", raise_json(exc, "KeyError")}};
    }
}

// --------------------------------------------------------------- dispatchers

bool dispatch(const std::string& id, const std::string& fn,
              const Json& input, const Json& expect, bool quiet) {
    if (fn == "capabilities_resolve") {
        Json results = Json::array();
        for (const Json& method : input.at("methods")) {
            const auto caps =
                capabilities_for_method(method.get<std::string>());
            results.push_back(Json{{"method", caps.method},
                                   {"label", caps.label}});
        }
        return compare(id, Json{{"results", results}}, expect, quiet);
    }
    if (fn == "capabilities_for") {
        Json got;
        try {
            const auto caps =
                capabilities_for_method(input.at("method").get<std::string>());
            Json for_kind = Json::object();
            for (const ConstraintKind kind : kKinds) {
                const ConstraintSupport cs = caps.for_kind(kind);
                for_kind[to_string(kind)] =
                    Json::array({to_string(cs.level), cs.note});
            }
            got = Json{{"result",
                        Json{{"method", caps.method},
                             {"label", caps.label},
                             {"prerequisites", caps.prerequisites},
                             {"for_kind", for_kind}}}};
        } catch (const std::out_of_range& exc) {
            got = Json{{"raise", raise_json(exc, "KeyError")}};
        }
        return compare(id, got, expect, quiet);
    }
    if (fn == "evaluate_request") {
        return compare(id, run_evaluate(input), expect, quiet);
    }
    if (fn == "evaluate_request_two") {
        const bool ok1 = compare(id + ".ok", run_evaluate(input.at("ok")),
                                 expect.at("ok"), quiet);
        const bool ok2 = compare(id + ".invalid",
                                 run_evaluate(input.at("invalid")),
                                 expect.at("invalid"), quiet);
        return ok1 && ok2;
    }
    if (fn == "algorithm_to_dict") {
        const AlgorithmSpec* spec =
            get_algorithm(input.at("algorithm_id").get<std::string>());
        return compare(
            id, Json{{"result", spec != nullptr ? spec->to_dict() : Json()}},
            expect, quiet);
    }
    if (fn == "algorithm_constraint_support") {
        const AlgorithmSpec* spec =
            get_algorithm(input.at("algorithm_id").get<std::string>());
        Json result = Json::object();
        for (const Json& kind : input.at("kinds")) {
            const ConstraintSupport cs = spec->constraint_support(
                constraint_kind_from(kind.get<std::string>()));
            result[kind.get<std::string>()] =
                Json::array({to_string(cs.level), cs.note});
        }
        return compare(id, Json{{"result", result}}, expect, quiet);
    }
    if (fn == "canonical_algorithm_id") {
        Json outcomes = Json::array();
        for (const Json& ref : input.at("refs")) {
            try {
                outcomes.push_back(
                    Json{{"ok", canonical_algorithm_id(ref.get<std::string>())}});
            } catch (const std::invalid_argument& exc) {
                // AlgorithmValueError (python_class()=="ValueError") is
                // defined in algorithm_registry.cpp; caught by base here.
                outcomes.push_back(Json{{"raise", raise_json(exc, "ValueError")}});
            }
        }
        return compare(id, Json{{"outcomes", outcomes}}, expect, quiet);
    }
    if (fn == "get_algorithm") {
        Json results = Json::array();
        for (const Json& ref : input.at("refs")) {
            const AlgorithmSpec* spec = get_algorithm(ref.get<std::string>());
            if (spec != nullptr) {
                results.push_back(Json{{"algorithm_id", spec->algorithm_id},
                                       {"family", spec->family}});
            } else {
                results.push_back(Json());
            }
        }
        return compare(id, Json{{"results", results}}, expect, quiet);
    }
    if (fn == "ui_lists") {
        Json got = Json::object();
        got["methods"] = ui_interpolation_methods();
        Json labels = Json::object();
        for (const auto& [label, algorithm] : interpolation_algorithm_labels()) {
            labels[label] = algorithm;
        }
        got["labels"] = labels;
        // ALGORITHMS membership: the frozen header exposes
        // std::map<std::string, AlgorithmSpec> (key-sorted), while Python
        // froze dict insertion order. No Python observable depends on that
        // order (alias rebuild is collision-free; UI lists derive from
        // UI_INTERPOLATION_METHODS), so both sides are sorted here and
        // compared order-insensitively.
        Json want = expect.at("algorithm_ids");
        std::vector<std::string> expected_ids(want.begin(), want.end());
        std::sort(expected_ids.begin(), expected_ids.end());
        Json sorted_expect = expect;
        sorted_expect["algorithm_ids"] = expected_ids;
        std::vector<std::string> have;
        for (const auto& [algorithm_id, spec] : algorithms()) {
            have.push_back(algorithm_id);
        }
        std::sort(have.begin(), have.end());
        got["algorithm_ids"] = have;
        return compare(id, got, sorted_expect, quiet);
    }
    if (fn == "display_label") {
        Json results = Json::array();
        for (const Json& ref : input.at("refs")) {
            results.push_back(display_label(ref.get<std::string>()));
        }
        return compare(id, Json{{"results", results}}, expect, quiet);
    }
    if (fn == "register_semantics") {
        // Mirrors the generator script exactly: register, resolve both
        // aliases, replace with disjoint aliases, prove the stale alias is
        // gone and the size did not grow. Mutates the global registry (the
        // later cases only exercise the capabilities matrix, never
        // ALGORITHMS).
        std::vector<std::string> steps;
        steps.push_back("size_before=" + std::to_string(algorithms().size()));
        AlgorithmSpec spec;
        spec.algorithm_id = "test.custom";
        spec.family = "interpolation";
        spec.display_label = "测试替换";
        spec.aliases = {"custom thing", "替换前"};
        register_algorithm(spec);
        steps.push_back("canonical[Custom Thing]=" +
                        canonical_algorithm_id("Custom Thing"));
        steps.push_back("canonical[替换前]=" +
                        canonical_algorithm_id("替换前"));
        steps.push_back("size_after_register=" +
                        std::to_string(algorithms().size()));
        AlgorithmSpec replacement;
        replacement.algorithm_id = "test.custom";
        replacement.family = "interpolation";
        replacement.display_label = "测试替换2";
        replacement.aliases = {"替换后"};
        register_algorithm(replacement);
        try {
            steps.push_back("canonical[custom thing]=" +
                            canonical_algorithm_id("custom thing"));
        } catch (const std::invalid_argument& exc) {
            steps.push_back("canonical[custom thing]=ValueError:" +
                            std::string(exc.what()));
        }
        steps.push_back("canonical[替换后]=" +
                        canonical_algorithm_id("替换后"));
        steps.push_back("size_after_replace=" +
                        std::to_string(algorithms().size()));
        return compare(id, Json{{"steps", steps}}, expect, quiet);
    }
    if (fn == "capability_matrix") {
        const Json matrix = capability_matrix();
        Json key_order = Json::array();
        for (auto it = matrix.begin(); it != matrix.end(); ++it) {
            key_order.push_back(it.key());
        }
        Json idw_constraints_order = Json::array();
        const Json& idw_row = matrix.at("idw").at("constraints");
        for (auto it = idw_row.begin(); it != idw_row.end(); ++it) {
            idw_constraints_order.push_back(it.key());
        }
        return compare(id,
                       Json{{"matrix", matrix},
                            {"key_order", key_order},
                            {"idw_constraints_order", idw_constraints_order}},
                       expect, quiet);
    }
    std::printf("FAIL %s: unknown fn '%s'\n", id.c_str(), fn.c_str());
    ++g_failures;
    return false;
}

// -------------------------------------------- acceptance closure (no fixture)

// Python evaluate_request never populates ConstraintApplication::ignored,
// so honest()'s negative branch is only reachable by direct construction —
// exercised here against the Python semantics
// (not (set(ignored) - set(diagnostics_labels()))).
void honest_closure() {
    ++g_checks;
    ConstraintApplication app;
    app.method = "idw";
    app.ignored = {"trend", "barrier"};
    app.diagnostics = {
        "trend:partial:note",
        "barrier:unsupported:IDW 反距离加权 ignores barrier — the surface "
        "will NOT reflect this constraint"};
    const std::set<std::string> labels = app.diagnostics_labels();
    const bool honest_covered = app.honest();  // both ignored labelled
    app.diagnostics.pop_back();                // barrier now uncovered
    const bool honest_uncovered = app.honest();
    app.diagnostics.clear();
    const bool honest_silent = app.honest();   // everything dropped silently
    const bool labels_ok = labels.size() == 2 && labels.count("trend") == 1 &&
                           labels.count("barrier") == 1;
    if (!honest_covered || honest_uncovered || honest_silent || !labels_ok) {
        std::printf("FAIL honest closure: covered=%d uncovered=%d silent=%d "
                    "labels_ok=%d\n",
                    honest_covered ? 1 : 0, honest_uncovered ? 1 : 0,
                    honest_silent ? 1 : 0, labels_ok ? 1 : 0);
        ++g_failures;
        return;
    }
    std::printf("honest()/diagnostics_labels closure: OK\n");
}

// --------------------------------------------------- comparator negative run

// Tamper one frozen expectation in memory; the dispatcher must report a
// mismatch (quiet — the mismatch itself is the expected outcome).
Json& json_pointer_get(Json& root, const std::vector<std::string>& tokens) {
    Json* cur = &root;
    for (const std::string& token : tokens) {
        if (cur->is_array()) {
            cur = &(*cur)[static_cast<std::size_t>(std::stoul(token))];
        } else {
            cur = &(*cur)[token];
        }
    }
    return *cur;
}

std::vector<std::string> split_pointer(const std::string& json_pointer) {
    std::vector<std::string> tokens;
    std::string rest = json_pointer;
    while (!rest.empty()) {
        const std::size_t slash = rest.find('/');
        if (slash == std::string::npos) {
            tokens.push_back(rest);
            break;
        }
        tokens.push_back(rest.substr(0, slash));
        rest = rest.substr(slash + 1);
    }
    return tokens;
}

bool negative_tamper(const Json& fixture, const std::string& case_id,
                     const std::string& json_pointer,
                     const Json& tampered_value) {
    for (const Json& cs : fixture.at("cases")) {
        if (cs.at("id").get<std::string>() != case_id) continue;
        Json mutated = cs;
        json_pointer_get(mutated.at("expect"), split_pointer(json_pointer)) =
            tampered_value;
        const bool caught = !dispatch(case_id + ".tampered",
                                      cs.at("fn").get<std::string>(),
                                      cs.at("input"), mutated.at("expect"),
                                      /*quiet=*/true);
        if (!caught) {
            std::printf("FAIL negative self-check: tamper of %s at %s was "
                        "NOT caught\n",
                        case_id.c_str(), json_pointer.c_str());
            ++g_failures;
        }
        return caught;
    }
    std::printf("FAIL negative self-check: case %s not found\n",
                case_id.c_str());
    ++g_failures;
    return false;
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 2) {
        std::fprintf(stderr, "usage: %s <fixture.json>\n", argv[0]);
        return 2;
    }
    const Json fixture = read_fixture(argv[1]);

    int cases = 0;
    for (const Json& cs : fixture.at("cases")) {
        ++cases;
        ++g_checks;
        dispatch(cs.at("id").get<std::string>(),
                 cs.at("fn").get<std::string>(), cs.at("input"),
                 cs.at("expect"), /*quiet=*/false);
    }

    honest_closure();

    int negatives = 0;
    if (negative_tamper(
            fixture, "case04_kriging_unsupported_diagnostics",
            "result/constraint_diagnostics/0",
            Json("barrier:unsupported:TAMPERED ignores barrier — the surface "
                 "will NOT reflect this constraint"))) {
        ++negatives;
    }
    if (negative_tamper(fixture, "case14_to_dict_factor_fusion",
                        "result/produces_uncertainty", Json(false))) {
        ++negatives;
    }
    if (negative_tamper(fixture, "case02_keyerror_message", "raise/str",
                        Json("unknown interpolation method 'nope'; TAMPERED"))) {
        ++negatives;
    }

    if (g_failures != 0) {
        std::printf("%d/%d checks FAILED (%d fixture cases)\n", g_failures,
                    g_checks, cases);
        return 1;
    }
    std::printf("ALL %d CHECKS PASSED (+%d negative self-checks)\n", g_checks,
                negatives);
    return 0;
}
