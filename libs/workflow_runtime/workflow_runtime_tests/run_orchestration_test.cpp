// Replay of tools/oracle/generate_run_orchestration_oracle.py —
// catalog/lifecycle.py shared run-orchestration skeleton parity.
#include <pwb/domain/json.hpp>
#include <pwb/workflow_runtime/run_orchestration.hpp>

#include <fstream>
#include <iostream>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

using pwb::domain::Json;
namespace wr = pwb::workflow_runtime;

namespace {

int g_checks = 0;
int g_failures = 0;

void check(bool ok, const std::string& label) {
    ++g_checks;
    if (!ok) {
        ++g_failures;
        std::cerr << "FAIL " << label << "\n";
    }
}

Json load(const char* path) {
    std::ifstream in(path);
    if (!in) throw std::runtime_error(std::string("cannot open ") + path);
    std::ostringstream ss;
    ss << in.rdbuf();
    return Json::parse(ss.str());
}

std::vector<std::string> str_list(const Json& j) {
    std::vector<std::string> out;
    for (const Json& e : j) out.push_back(e.get<std::string>());
    return out;
}

// Recording fake mirroring the generator's FakeCatalog — stores
// legacy-resource bridges and versions, throws on ops in raise_on.
class FakeCatalog : public wr::CatalogRepository {
public:
    std::vector<wr::RunRecord> runs_;
    std::map<std::string, wr::VersionRecord> legacy_;
    std::map<std::string, wr::VersionRecord> versions_;
    std::set<std::string> raise_on_;
    int next_run_ = 0;
    int next_version_ = 0;

    std::vector<wr::AssetRecord> list_assets() override { return {}; }
    std::optional<wr::AssetRecord> resolve_asset(
        const std::string&) override {
        return std::nullopt;
    }
    std::vector<wr::VersionRecord> list_versions(
        const std::string&) override {
        return {};
    }
    std::optional<wr::VersionRecord> resolve_version(
        const std::string& id) override {
        const auto it = versions_.find(id);
        return it != versions_.end() ? std::optional<wr::VersionRecord>(
                                           it->second)
                                     : std::nullopt;
    }
    std::vector<wr::RunRecord> list_runs() override {
        if (raise_on_.count("list_runs"))
            throw std::runtime_error("catalog down");
        return runs_;
    }
    std::optional<wr::RunRecord> resolve_run(
        const std::string&) override {
        return std::nullopt;
    }
    std::optional<wr::VersionRecord> resolve_legacy_resource(
        const std::string& rid) override {
        const auto it = legacy_.find(rid);
        return it != legacy_.end()
                   ? std::optional<wr::VersionRecord>(it->second)
                   : std::nullopt;
    }
    void set_run_ports(const std::string& run_id, const Json& in,
                       const Json& out) override {
        if (raise_on_.count("set_run_ports"))
            throw std::runtime_error("set_run_ports refused");
        port_calls_.push_back({run_id, in, out});
    }
    std::string register_run(
        const std::string& op,
        const std::vector<std::string>& inputs, const Json& params,
        const std::optional<std::string>& gen,
        const std::string& status,
        const std::optional<std::string>& domain_task_id,
        const std::optional<std::string>& snap,
        const std::optional<std::string>& actor) override {
        if (raise_on_.count("begin_run"))
            throw std::runtime_error("begin_run refused");
        wr::RunRecord r;
        const int run_n = ++next_run_;
        r.run_id = "run_" +
                   std::string(4 - std::to_string(run_n).size(), '0') +
                   std::to_string(run_n);
        r.operation = op;
        r.input_version_ids = inputs;
        r.parameters = params;
        r.generator_version = gen;
        r.domain_task_id = domain_task_id;
        r.input_snapshot_hash = snap;
        r.actor = actor;
        r.status = status;
        runs_.push_back(r);
        begin_kwargs_.push_back(params);
        return r.run_id;
    }
    wr::RegisteredAssetVersion register_result_asset(
        const std::string&, const std::string&, const std::string&,
        const Json&, const std::string&, const std::string&,
        const std::string&, const Json&) override {
        return {};
    }
    std::string register_version(
        const std::string&, const std::string&, const std::string&,
        const std::vector<std::string>&, const std::string&,
        const Json&) override {
        if (raise_on_.count("register_intermediate"))
            throw std::runtime_error("register_intermediate refused");
        const int ver_n = ++next_version_;
        return "ver_" +
               std::string(4 - std::to_string(ver_n).size(), '0') +
               std::to_string(ver_n);
    }
    void update_run_status(const std::string& run_id,
                           const std::string& status) override {
        if (raise_on_.count("complete_run"))
            throw std::runtime_error("complete_run refused");
        for (auto& r : runs_) {
            if (r.run_id == run_id) r.status = status;
        }
        status_calls_.push_back({run_id, status});
    }
    void attach_run_output(const std::string&,
                           const std::string&) override {}
    void set_current_version(const std::string&,
                             const std::string&) override {}
    std::optional<std::string> verify_integrity(
        const std::string&) override {
        return std::nullopt;
    }

    struct PortCall {
        std::string run_id;
        Json input_ports;
        Json output_ports;
    };
    std::vector<PortCall> port_calls_;
    std::vector<std::pair<std::string, std::string>> status_calls_;
    std::vector<Json> begin_kwargs_;
};

wr::VersionRecord ver(const std::string& id, bool trashed = false) {
    wr::VersionRecord v;
    v.version_id = id;
    v.trashed = trashed;
    return v;
}

wr::RunRecord seed_run(const std::string& tid, const std::string& status,
                       std::vector<std::string> inputs,
                       std::vector<std::string> outputs) {
    wr::RunRecord r;
    r.run_id = "r_" + tid + "_" + status;
    r.domain_task_id = tid;
    r.status = status;
    r.input_version_ids = std::move(inputs);
    r.output_version_ids = std::move(outputs);
    return r;
}

void test_resolve_input_versions(const Json& exp) {
    FakeCatalog cat;
    cat.legacy_["res_a"] = ver("ver_a");
    cat.legacy_["res_b"] = ver("ver_b");
    const auto got = wr::resolve_input_versions(
        cat, {"res_a", "res_missing", "res_b"});
    check(Json(got) == exp["resolved"], "resolve_input_versions.resolved");
    check(Json(wr::resolve_input_versions(cat, {})) == exp["empty"],
          "resolve_input_versions.empty");
}

void test_fail_run(const Json& exp) {
    FakeCatalog cat;
    const std::string run_id = wr::begin_run(
        cat, wr::RunSpec{.operation = "op"});
    wr::fail_run(cat, run_id);
    check(cat.runs_.back().status ==
              exp["status_after"].get<std::string>(),
          "fail_run.status_after");
    check(cat.runs_.back().status == "failed", "fail_run.is_failed");

    FakeCatalog cat2;
    cat2.raise_on_.insert("complete_run");
    const std::string r2 =
        wr::begin_run(cat2, wr::RunSpec{.operation = "op"});
    wr::fail_run(cat2, r2);   // must not throw
    wr::fail_run(cat2, "");   // empty → early return (Python None)
    check(true, "fail_run.swallowed");
}

void test_annotate_output_port(const Json& exp) {
    FakeCatalog cat;
    wr::annotate_output_port(cat, "run_1", "ver_9", "primary");
    wr::annotate_output_port(cat, "", "ver_9", "primary");
    wr::annotate_output_port(cat, "run_1", "", "primary");
    check(cat.port_calls_.size() == 1, "annotate_output_port.one_call");
    check(cat.port_calls_[0].output_ports ==
              exp["calls"][0]["output_ports"],
          "annotate_output_port.payload");
    check(cat.port_calls_[0].input_ports.is_null(),
          "annotate_output_port.input_untouched");

    FakeCatalog cat2;
    cat2.raise_on_.insert("set_run_ports");
    wr::annotate_output_port(cat2, "run_1", "ver_9", "primary");
    check(true, "annotate_output_port.swallowed");
}

void test_annotate_input_ports(const Json& exp) {
    FakeCatalog cat;
    wr::annotate_input_ports(cat, "run_1", {"ver_a", "ver_b"}, "source",
                             "well", {"w1"});
    wr::annotate_input_ports(cat, "run_1", {}, "source");
    wr::annotate_input_ports(cat, "", {"ver_a"}, "source");
    check(cat.port_calls_.size() == 1, "annotate_input_ports.one_call");
    check(cat.port_calls_[0].input_ports ==
              exp["calls"][0]["input_ports"],
          "annotate_input_ports.payload");
    check(cat.port_calls_[0].output_ports.is_null(),
          "annotate_input_ports.output_untouched");

    FakeCatalog cat2;
    cat2.raise_on_.insert("set_run_ports");
    wr::annotate_input_ports(cat2, "run_1", {"ver_a"}, "source");
    check(true, "annotate_input_ports.swallowed");
}

void test_versions_for_domain_tasks(const Json& exp) {
    FakeCatalog cat;
    cat.runs_ = {
        seed_run("task_b", "complete", {"in_b"}, {"out_b"}),
        seed_run("task_a", "complete", {"in_a"}, {}),
        seed_run("task_a", "complete", {"in_a2"}, {"out_a2"}),
        seed_run("task_b", "failed", {"in_bx"}, {"out_bx"}),
        seed_run("task_b", "complete", {"in_b2"}, {"out_b2"}),
        seed_run("task_c", "complete", {"in_c"}, {"out_c"}),
    };
    cat.versions_["out_b"] = ver("out_b");
    cat.versions_["out_a2"] = ver("out_a2");
    cat.versions_["out_b2"] = ver("out_b2", true);
    cat.versions_["out_c"] = ver("out_c");
    const auto got = wr::versions_for_domain_tasks(
        {"task_a", "task_b", "task_c"}, cat);
    check(Json(got) == exp["resolved"], "vfdt.resolved");
    check(Json(wr::versions_for_domain_tasks({"task_a"}, cat)) ==
              exp["subset"],
          "vfdt.subset");
    check(Json(wr::versions_for_domain_tasks({}, cat)) == exp["empty"],
          "vfdt.empty");

    FakeCatalog boom;
    boom.raise_on_.insert("list_runs");
    std::string raised;
    try {
        wr::versions_for_domain_tasks({"task_a"}, boom);
    } catch (const std::exception& e) {
        raised = e.what();
    }
    check(raised == exp["boom"].get<std::string>(), "vfdt.propagates");
}

// register_factor_map_run skeleton exercised through the shared
// primitives — begin → register_version(intermediate) → complete, with
// fail_run compensation on registration failure.
void test_factor_map_skeleton(const Json& exp) {
    {
        FakeCatalog cat;
        cat.legacy_["res_a"] = ver("ver_res_a");
        auto inputs =
            wr::resolve_input_versions(cat, {"res_a", "res_missing"});
        std::set<std::string> seen(inputs.begin(), inputs.end());
        for (const std::string& vid : {"ver_res_a", "ver_extra"}) {
            if (!vid.empty() && !seen.count(vid)) {
                seen.insert(vid);
                inputs.push_back(vid);
            }
        }
        const std::string run_id = wr::begin_run(
            cat, wr::RunSpec{.operation = "factor_map",
                             .input_version_ids = inputs,
                             .parameters =
                                 {{"factor_type", "porosity"},
                                  {"target_horizon", "H1"},
                                  {"method", "idw"}},
                             .generator_version = "gen-v9",
                             .domain_task_id = "fmt_1",
                             .input_snapshot_hash = "snap123"});
        const std::string vid = cat.register_version(
            "asset", "payload", "intermediate", {}, run_id, Json::object());
        wr::complete_run(cat, run_id);
        const Json& e = exp["with_intermediate"];
        check(run_id == e["run_id"].get<std::string>(), "fmr.run_id");
        check(vid == e["version_id"].get<std::string>(), "fmr.version_id");
        check(cat.runs_.back().status == e["run_status"].get<std::string>(),
              "fmr.run_status");
        const Json begin_call = e["calls"][0]["kwargs"];
        check(cat.begin_kwargs_[0] == begin_call["parameters"],
              "fmr.parameters");
        check(Json(cat.runs_.back().input_version_ids) ==
                  begin_call["input_version_ids"],
              "fmr.input_version_ids");
        check(cat.runs_.back().domain_task_id ==
                  begin_call["domain_task_id"].get<std::string>(),
              "fmr.domain_task_id");
    }
    {
        // intermediate failure → run failed + re-raise.
        FakeCatalog cat;
        cat.raise_on_.insert("register_intermediate");
        const std::string run_id = wr::begin_run(
            cat, wr::RunSpec{.operation = "factor_map"});
        std::string raised;
        try {
            cat.register_version("asset", "p", "intermediate", {},
                                 run_id, Json::object());
            wr::complete_run(cat, run_id);
        } catch (const std::exception& e) {
            wr::fail_run(cat, run_id);
            raised = e.what();
        }
        const Json& e = exp["intermediate_failure"];
        check(raised == e["raised"].get<std::string>(), "fmr.fail.raised");
        check(cat.runs_.back().status == "failed",
              "fmr.fail.run_failed");
    }
    {
        // fail_run compensation itself throws → still re-raises original.
        FakeCatalog cat;
        cat.raise_on_.insert("register_intermediate");
        cat.raise_on_.insert("complete_run");
        const std::string run_id = wr::begin_run(
            cat, wr::RunSpec{.operation = "factor_map"});
        std::string raised;
        try {
            cat.register_version("asset", "p", "intermediate", {},
                                 run_id, Json::object());
            wr::complete_run(cat, run_id);
        } catch (const std::exception& e) {
            wr::fail_run(cat, run_id);
            raised = e.what();
        }
        check(raised ==
                  exp["fail_run_swallow"]["raised"].get<std::string>(),
              "fmr.fail_swallow.raised");
    }
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 2) {
        std::cerr << "usage: run_orchestration_test <fixture.json>\n";
        return 2;
    }
    const Json cases = load(argv[1]);
    test_resolve_input_versions(cases["resolve_input_versions"]);
    test_fail_run(cases["fail_run"]);
    test_annotate_output_port(cases["annotate_output_port"]);
    test_annotate_input_ports(cases["annotate_input_ports"]);
    test_versions_for_domain_tasks(cases["versions_for_domain_tasks"]);
    test_factor_map_skeleton(cases["factor_map_run"]);
    std::cout << "run_orchestration: " << g_checks << " checks, "
              << g_failures << " failure(s)\n";
    return g_failures == 0 ? 0 : 1;
}
