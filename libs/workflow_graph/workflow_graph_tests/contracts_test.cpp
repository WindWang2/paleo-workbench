// CONV-25 oracle replay: drives every frozen case in
// fixtures/workflow_graph_oracle.json through the C++ port and compares
// against the real-Python expectation (result or raise{class,message}).

#include <pwb/domain/json.hpp>
#include <pwb/workflow_graph/evidence.hpp>
#include <pwb/workflow_graph/graph.hpp>

#include <cstdio>
#include <fstream>
#include <map>
#include <set>
#include <sstream>
#include <string>
#include <vector>

using pwb::domain::Json;
using namespace pwb::workflow_graph;

namespace {

int g_checks = 0;
int g_failures = 0;

void check(bool ok, const std::string& id, const std::string& what) {
    ++g_checks;
    if (!ok) {
        ++g_failures;
        std::printf("FAIL %s: %s\n", id.c_str(), what.c_str());
    }
}

Json read_fixture(const char* path) {
    std::ifstream in(path);
    std::stringstream ss;
    ss << in.rdbuf();
    return Json::parse(ss.str());
}

// Ordered, type-strict comparison (#1344):
//  * Json is ordered_json — to_dict key order is contractual (D5), so
//    object keys must match IN ORDER, not just as a set;
//  * int vs float slips must fail (dump->parse->== treats 1 == 1.0);
//  * int vs unsigned collapses (Python has no unsigned);
//  * dump/parse still normalises representations.
bool semantically_equal(const Json& a, const Json& b) {
    const Json an = Json::parse(a.dump());
    const Json bn = Json::parse(b.dump());
    if (an.is_object() && bn.is_object()) {
        if (an.size() != bn.size()) return false;
        auto ia = an.items().begin();
        auto ib = bn.items().begin();
        for (; ia != an.items().end(); ++ia, ++ib) {
            if (ia.key() != ib.key()) return false;
            if (!semantically_equal(ia.value(), ib.value())) return false;
        }
        return true;
    }
    if (an.is_array() && bn.is_array()) {
        if (an.size() != bn.size()) return false;
        for (std::size_t i = 0; i < an.size(); ++i)
            if (!semantically_equal(an.at(i), bn.at(i))) return false;
        return true;
    }
    if (an.is_number() && bn.is_number())
        return an.is_number_float() == bn.is_number_float() && an == bn;
    return an == bn;
}

// Python str() on a Json scalar (fixture inputs may carry null/int values).
std::string jstr_scalar(const Json& v) {
    if (v.is_null()) return "";
    if (v.is_string()) return v.get<std::string>();
    if (v.is_boolean()) return v.get<bool>() ? "True" : "False";
    if (v.is_number_integer()) return std::to_string(v.get<long long>());
    if (v.is_number_unsigned())
        return std::to_string(v.get<unsigned long long>());
    if (v.is_number_float()) return v.dump();
    return v.dump();
}

// Python `str(x or "")` — truthiness gate first, then str().
std::string jstr_or_empty(const Json& v) {
    if (v.is_null()) return "";
    if (v.is_boolean()) return v.get<bool>() ? "True" : "";
    if (v.is_number())
        return v.get<double>() == 0.0 ? "" : jstr_scalar(v);
    if (v.is_string()) return v.get<std::string>();
    if ((v.is_array() || v.is_object()) && v.empty()) return "";
    return jstr_scalar(v);
}

// list(x or []) semantics for fixture iterables (#1344): arrays keep
// elements, strings iterate CHARACTERS, dicts iterate KEYS, a truthy
// non-iterable scalar raises TypeError (as Python does inside rebuild).
std::vector<std::string> str_list(const Json& v) {
    std::vector<std::string> out;
    if (v.is_array()) {
        for (const auto& e : v) out.push_back(jstr_scalar(e));
    } else if (v.is_string()) {
        const std::string& sv = v.get_ref<const std::string&>();
        for (std::size_t i = 0; i < sv.size();) {
            const unsigned char c = sv[i];
            const std::size_t len =
                c < 0x80 ? 1 : c < 0xE0 ? 2 : c < 0xF0 ? 3 : 4;
            out.push_back(sv.substr(i, len));
            i += len;
        }
    } else if (v.is_object()) {
        for (const auto& [k, _] : v.items()) out.push_back(k);
    } else if (!v.is_null() &&
               !(v.is_boolean() && !v.get<bool>()) &&
               !(v.is_number() && v.get<double>() == 0.0)) {
        throw WorkflowTypeError("fixture str_list: non-iterable value");
    }
    return out;
}

std::optional<std::string> opt_str(const Json& obj, const char* key) {
    if (!obj.is_object() || !obj.contains(key) || obj.at(key).is_null())
        return std::nullopt;
    return jstr_scalar(obj.at(key));  // tolerate non-string fixture values
}

std::vector<DataVersionRef> versions_of(const Json& in) {
    std::vector<DataVersionRef> out;
    for (const auto& v : in.at("versions")) {
        DataVersionRef r;
        r.version_id = v.value("version_id", "");
        r.asset_id = v.value("asset_id", "");
        r.name = v.value("name", "");
        r.producing_run_id = opt_str(v, "producing_run_id");
        out.push_back(std::move(r));
    }
    return out;
}

std::vector<DataRunRef> runs_of(const Json& in) {
    std::vector<DataRunRef> out;
    for (const auto& v : in.at("runs")) {
        DataRunRef r;
        r.run_id = v.value("run_id", "");
        r.operation = v.value("operation", "");
        r.input_version_ids = str_list(v.value("input_version_ids", Json()));
        r.output_version_ids =
            str_list(v.value("output_version_ids", Json()));
        r.parameters =
            v.contains("parameters") ? v.at("parameters") : Json::object();
        r.generator_version = opt_str(v, "generator_version");
        r.status = v.value("status", "running");
        r.started_at = opt_str(v, "started_at");
        r.finished_at = opt_str(v, "finished_at");
        r.domain_task_id = opt_str(v, "domain_task_id");
        r.input_snapshot_hash = opt_str(v, "input_snapshot_hash");
        out.push_back(std::move(r));
    }
    return out;
}

DependencyGraph graph_of(const Json& in) {
    return DependencyGraph::from_listings(versions_of(in), runs_of(in));
}

Json ordered_pairs(
    const std::vector<std::pair<std::string, std::string>>& t) {
    Json out = Json::object();
    for (const auto& [k, v] : t) out[k] = v;
    return out;
}

Json ordered_lists(
    const std::vector<std::pair<std::string, std::vector<std::string>>>& t) {
    Json out = Json::object();
    for (const auto& [k, v] : t) out[k] = v;
    return out;
}

Json run_ids_of(const std::vector<const DataRunRef*>& runs) {
    Json out = Json::array();
    for (const auto* r : runs) out.push_back(r->run_id);
    return out;
}

// freeze_graph() — the generator's index snapshot shape.
Json freeze_graph(const DependencyGraph& g) {
    Json edges = Json::array();
    for (const auto& e : g.edges())
        edges.push_back(Json::array({e.source_version_id, e.run_id,
                                     e.target_version_id, e.operation}));
    Json cycles = Json::array();
    for (const auto& n : g.cycles()) cycles.push_back(n);
    return Json{{"producing_run", ordered_pairs(g.producing_run())},
                {"consumers", ordered_lists(g.consumers())},
                {"run_inputs", ordered_lists(g.run_inputs())},
                {"run_outputs", ordered_lists(g.run_outputs())},
                {"version_asset", ordered_pairs(g.version_asset())},
                {"asset_versions", ordered_lists(g.asset_versions())},
                {"domain_task_runs",
                 ordered_lists(g.domain_task_runs())},
                {"edges", edges},
                {"cycle_nodes", cycles},
                {"has_cycle", g.has_cycle()}};
}

// --- evidence seams ---------------------------------------------------------

// catalog: null -> absent; {"raise":true} -> resolver that throws;
// {"resolve":{vid:{asset_id,name}}} -> lookup (missing -> nullopt).
std::optional<CatalogResolver> catalog_of(const Json& spec) {
    if (spec.is_null()) return std::nullopt;
    if (spec.value("raise", false)) {
        return CatalogResolver(
            [](const std::string&) -> std::optional<VersionInfo> {
                throw std::runtime_error("catalog backend error");
            });
    }
    const Json table = spec.value("resolve", Json::object());
    return CatalogResolver(
        [table](const std::string& vid) -> std::optional<VersionInfo> {
            if (!table.is_object() || !table.contains(vid)) return std::nullopt;
            const Json& row = table.at(vid);
            return VersionInfo{row.value("asset_id", ""),
                               row.value("name", "")};
        });
}

// workspace: null -> nullptr; {"membership":{lid:{source_version_id}},
// "roles":{initial_facies_draft:[ids]}}.
struct WsHolder {
    WorkspaceView view;
    bool present = false;
};

WsHolder workspace_of(const Json& spec) {
    WsHolder h;
    if (spec.is_null()) return h;
    h.present = true;
    const Json mem = spec.value("membership", Json::object());
    const Json roles = spec.value("roles", Json::object());
    h.view.membership = [mem](const std::string& lid)
        -> std::optional<WorkspaceMembership> {
        if (!mem.is_object() || !mem.contains(lid)) return std::nullopt;
        // str(getattr(m, "source_version_id", "") or "") — falsy values
        // collapse to "" (#1339 fixtures may carry 0/false/null).
        return WorkspaceMembership{jstr_or_empty(
            mem.at(lid).value("source_version_id", Json()))};
    };
    h.view.layers_with_role =
        [roles](const std::string& role) -> std::vector<std::string> {
        if (!roles.is_object() || !roles.contains(role)) return {};
        return str_list(roles.at(role));
    };
    return h;
}

// verdict: {"status","detail"} -> canned verdict; {"raise":msg} -> throw;
// {"absent":true} -> EMPTY resolver (Python's missing-import state -> the
// port raises EvidenceImportError, not a swallowed bad_function_call).
// Non-dict verdicts pass through verbatim — verdict.get then raises
// AttributeError in the port exactly as in Python (#1344).
ConstraintResolver constraint_of(const Json& verdict) {
    if (verdict.is_null() ||
        (verdict.is_object() && verdict.value("absent", false)))
        return ConstraintResolver{};
    if (verdict.is_object() && verdict.contains("verbatim")) {
        const Json raw = verdict.at("verbatim");
        return ConstraintResolver([raw](const Json&, const std::string&) {
            return raw;
        });
    }
    if (verdict.contains("raise")) {
        const std::string msg = verdict.at("raise").get<std::string>();
        return ConstraintResolver(
            [msg](const Json&, const std::string&) -> Json {
                throw std::runtime_error(msg);
            });
    }
    return ConstraintResolver([verdict](const Json&, const std::string&) {
        return verdict;
    });
}

EvidenceKind kind_of(const std::string& s) {
    if (s == "phase1_draft") return EvidenceKind::Phase1Draft;
    if (s == "factor") return EvidenceKind::Factor;
    if (s == "prediction") return EvidenceKind::Prediction;
    if (s == "constraint_group") return EvidenceKind::ConstraintGroup;
    if (s == "catalog_version") return EvidenceKind::CatalogVersion;
    // Python EvidenceKind(s) raises ValueError on unknown kind — the oracle
    // would have frozen a raise; silently mapping to CatalogVersion hid it
    // (#1344).
    throw EvidenceValueError("unknown evidence kind: '" + s + "'");
}

// --- case execution ---------------------------------------------------------

Json exec_case(const Json& c) {
    const std::string fn = c.at("fn").get<std::string>();
    const Json& in = c.at("input");

    if (fn == "graph_rebuild") {
        return freeze_graph(graph_of(in));
    }
    if (fn == "graph_rebuild_twice") {
        // rebuild() must fully reset prior state — a DependencyGraph object
        // is reusable in Python (#1344). Optional versions2/runs2 swap in a
        // second listing set for the second rebuild.
        DependencyGraph g;
        g.rebuild(versions_of(in), runs_of(in));
        const Json in2{{"versions", in.value("versions2", in.at("versions"))},
                       {"runs", in.value("runs2", in.at("runs"))}};
        g.rebuild(versions_of(in2), runs_of(in2));
        return freeze_graph(g);
    }
    if (fn == "direct_downstream") {
        const auto g = graph_of(in);
        return run_ids_of(
            g.direct_downstream_runs(in.at("version_id").get<std::string>()));
    }
    if (fn == "transitive_runs") {
        const auto g = graph_of(in);
        const std::size_t cap =
            in.value("max_nodes", Json(100000)).get<std::size_t>();
        return run_ids_of(g.transitive_downstream_runs(
            str_list(in.at("version_ids")), cap));
    }
    if (fn == "transitive_versions") {
        const auto g = graph_of(in);
        Json out = Json::array();
        for (const auto& v : g.transitive_downstream_versions(
                 str_list(in.at("version_ids"))))
            out.push_back(v);
        return out;
    }
    if (fn == "latest_run") {
        const auto g = graph_of(in);
        const auto* r =
            g.latest_run_for_domain_task(in.at("task_id").get<std::string>());
        return r ? Json(r->run_id) : Json(nullptr);
    }
    if (fn == "asset_id_for") {
        const auto g = graph_of(in);
        const auto a =
            g.asset_id_for(in.at("version_id").get<std::string>());
        return a ? Json(*a) : Json(nullptr);
    }
    if (fn == "find_reuse_run") {
        const auto g = graph_of(in);
        const Json& q = in.at("query");
        const auto* r = g.find_reuse_run(
            q.at("operation").get<std::string>(),
            str_list(q.value("input_version_ids", Json::array())),
            opt_str(q, "generator_version"),
            opt_str(q, "input_snapshot_hash"),
            q.value("parameters", Json(nullptr)),
            q.value("require_outputs", true));
        return r ? Json(r->run_id) : Json(nullptr);
    }
    if (fn == "topological_runs") {
        const auto g = graph_of(in);
        std::optional<std::map<std::string, std::set<std::string>>> tc;
        if (in.contains("task_consumers") &&
            in.at("task_consumers").is_object()) {
            std::map<std::string, std::set<std::string>> m;
            for (const auto& [k, v] : in.at("task_consumers").items()) {
                const auto lst = str_list(v);
                m[k] = std::set<std::string>(lst.begin(), lst.end());
            }
            tc = std::move(m);
        }
        return run_ids_of(
            g.topological_runs(str_list(in.at("run_ids")), tc));
    }
    if (fn == "parse_selector") {
        const auto sel =
            parse_evidence_selector(jstr_or_empty(in.at("value")));
        return Json{{"kind", evidence_kind_value(sel.kind)},
                    {"ref_id", sel.ref_id},
                    {"version_id", sel.version_id},
                    {"floating", sel.floating},
                    {"raw", sel.str()}};
    }
    if (fn == "format_selector") {
        return Json(format_evidence_selector(
            kind_of(in.at("kind").get<std::string>()),
            jstr_or_empty(in.at("ref_id")),
            jstr_or_empty(in.value("version_id", Json())),
            in.value("floating", false)));
    }
    if (fn == "resolve") {
        auto ws = workspace_of(in.at("workspace"));
        return resolve_evidence(
                   in.at("document"), jstr_or_empty(in.at("value")),
                   catalog_of(in.at("catalog")),
                   ws.present ? &ws.view : nullptr,
                   constraint_of(in.at("verdict")))
            .to_dict();
    }
    if (fn == "resolve_selector_obj") {
        const EvidenceSelector sel{
            kind_of(in.at("kind").get<std::string>()),
            in.at("ref_id").get<std::string>(),
            opt_str(in, "version_id").value_or(""),
            in.value("floating", false)};
        return resolve_evidence(in.contains("document") ? in.at("document")
                                                        : Json::object(),
                                sel, catalog_of(in.at("catalog")))
            .to_dict();
    }
    if (fn == "available_evidence") {
        auto ws = workspace_of(in.at("workspace"));
        Json out = Json::array();
        for (const auto& r : available_evidence(
                 in.at("document"), ws.present ? &ws.view : nullptr,
                 constraint_of(in.value("verdict", Json(nullptr)))))
            out.push_back(r.to_dict());
        return out;
    }
    throw std::runtime_error("unknown fn: " + fn);
}

std::string raise_class_of(const std::exception& e) {
    if (dynamic_cast<const DependencyGraphError*>(&e))
        return "DependencyGraphError";
    if (dynamic_cast<const EvidenceValueError*>(&e)) return "ValueError";
    if (dynamic_cast<const EvidenceImportError*>(&e)) return "ImportError";
    if (dynamic_cast<const EvidenceAttributeError*>(&e))
        return "AttributeError";
    if (dynamic_cast<const WorkflowTypeError*>(&e)) return "TypeError";
    return "std::exception";
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 2) {
        std::fprintf(stderr, "usage: %s <fixture.json>\n", argv[0]);
        return 2;
    }
    const Json fixture = read_fixture(argv[1]);
    int total = 0;
    for (const auto& c : fixture.at("cases")) {
        ++total;
        const std::string id = c.at("id").get<std::string>();
        const Json& expect = c.at("expect");
        if (expect.contains("raise")) {
            const Json& re = expect.at("raise");
            try {
                const Json got = exec_case(c);
                check(false, id,
                      "expected raise " +
                          re.at("python_class").get<std::string>() +
                          ", got result " + got.dump().substr(0, 120));
            } catch (const std::exception& e) {
                check(raise_class_of(e) ==
                          re.at("python_class").get<std::string>(),
                      id, std::string("raise class mismatch: ") + e.what());
                // "*" masks messages that embed environment-dependent text
                // (e.g. ImportError's module path) — #1344.
                const Json msg = re.at("message");
                if (msg != Json("*"))
                    check(std::string(e.what()) == msg.get<std::string>(),
                          id, std::string("message mismatch: ") + e.what());
            }
            continue;
        }
        try {
            Json got = exec_case(c);
            Json exp = expect.at("result");
            // "cycle_nodes": "*" — membership is traversal-order dependent
            // for >=3-node cycles (Python iterates a hash-ordered set); the
            // freeze asserts has_cycle + non-emptiness only (#1342).
            if (exp.is_object() && exp.value("cycle_nodes", Json()) ==
                                       Json("*")) {
                check(got.is_object() &&
                          got.value("cycle_nodes", Json::array()).is_array() &&
                          !got.at("cycle_nodes").empty(),
                      id, "cycle_nodes expected nonempty");
                got["cycle_nodes"] = "*";
            }
            if (!semantically_equal(got, exp)) {
                check(false, id,
                      "result mismatch\n  got:    " + got.dump() +
                          "\n  expect: " + exp.dump());
            }
        } catch (const std::exception& e) {
            check(false, id,
                  std::string("unexpected raise: ") + e.what());
        }
    }
    std::printf("%d cases, %d checks, %d failures\n", total, g_checks,
                g_failures);
    return g_failures == 0 ? 0 : 1;
}
