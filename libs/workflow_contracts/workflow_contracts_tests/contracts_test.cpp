// CONV-23 oracle conformance runner — replays every frozen case in
// workflow_contract_oracle.json against the C++ workflow contract layer.
// Conventions match prediction.contracts / geomodel.contracts: dispatch by
// "fn", semantic JSON equality (dump/parse normalized both sides), raises
// assert exception class + exact message.

#include <cstdio>
#include <fstream>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/workflow_contracts/models.hpp>
#include <pwb/workflow_contracts/readiness.hpp>
#include <pwb/workflow_contracts/registry.hpp>
#include <pwb/workflow_contracts/report.hpp>

using pwb::domain::Json;
namespace wc = pwb::workflow_contracts;

int g_failures = 0;
int g_checks = 0;

void check(bool ok, const std::string& what) {
    ++g_checks;
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

// Python has one int type: normalize number kinds on both sides before
// comparing (int-vs-float stays a real difference).
Json norm(const Json& v) { return Json::parse(v.dump()); }

bool sem_eq(const Json& a, const Json& b) {
    return pwb::domain::json_semantically_equal(norm(a), norm(b));
}

std::string raise_class(const std::exception& e) {
    if (dynamic_cast<const std::invalid_argument*>(&e))
        return "ValueError";
    if (dynamic_cast<const std::out_of_range*>(&e)) return "IndexError";
    if (dynamic_cast<const std::runtime_error*>(&e)) return "RuntimeError";
    return "Exception";
}

// ---------------------------------------------------------------------------
// fn implementations
// ---------------------------------------------------------------------------

Json ids_of(const std::vector<const wc::DomainWorkflowContract*>& v) {
    Json out = Json::array();
    for (const auto* c : v) out.push_back(c->id);
    return out;
}

class StubProbe final : public wc::ProductionModelProbe {
public:
    explicit StubProbe(std::string mode) : mode_(std::move(mode)) {}
    std::optional<Json>
    find_production_model(const std::string&) const override {
        if (mode_ == "model") return Json{{"asset_id", "m1"}};
        if (mode_ == "none") return std::nullopt;
        throw std::runtime_error("store exploded");
    }

private:
    std::string mode_;
};

const wc::ProductionModelProbe* probe_for(const Json& input,
                                        StubProbe& holder) {
    const std::string mode = input.value("probe", std::string("model"));
    if (mode == "unset") return nullptr;  // svc is None path
    holder = StubProbe(mode);
    return &holder;
}

Json run_case(const Json& c) {
    const std::string fn = c.at("fn").get<std::string>();
    const Json& input = c.at("input");
    const wc::WorkflowContractRegistry& reg = wc::get_default_registry();

    if (fn == "contract_dump") {
        const auto* ctr =
            reg.get_contract(input.at("id").get<std::string>());
        return ctr ? ctr->model_dump() : Json(nullptr);
    }
    if (fn == "completeness") {
        const auto* ctr =
            reg.get_contract(input.at("id").get<std::string>());
        return ctr ? ctr->completeness() : Json(nullptr);
    }
    if (fn == "list_contracts") {
        Json out = Json::array();
        for (const auto& x : reg.list_contracts()) out.push_back(x.id);
        return out;
    }
    if (fn == "get_contract") {
        const auto* ctr =
            reg.get_contract(input.at("id").get<std::string>());
        return ctr ? ctr->model_dump() : Json(nullptr);
    }
    if (fn == "contracts_by_category")
        return ids_of(reg.contracts_by_category(
            input.at("category").get<std::string>()));
    if (fn == "upstream")
        return ids_of(reg.upstream(input.at("id").get<std::string>()));
    if (fn == "downstream")
        return ids_of(reg.downstream(input.at("id").get<std::string>()));
    if (fn == "all_expert_questions") {
        Json out = Json::array();
        for (const auto* q : reg.all_expert_questions())
            out.push_back(q->id);
        return out;
    }
    if (fn == "p0_ids") {
        Json out = Json::array();
        for (const auto& s : wc::WorkflowContractRegistry::p0_ids())
            out.push_back(s);
        return out;
    }
    if (fn == "validation_issues") {
        Json out = Json::array();
        for (const auto& s : reg.validation_issues()) out.push_back(s);
        return out;
    }
    if (fn == "duplicate_registry") {
        std::vector<wc::DomainWorkflowContract> two;
        wc::DomainWorkflowContract a, b;
        a.id = "dup";
        a.name = "dup";
        b.id = "dup";
        b.name = "dup";
        two.push_back(a);
        two.push_back(b);
        wc::WorkflowContractRegistry bad(std::move(two));
        return Json(nullptr);  // never reached — ctor throws
    }
    if (fn == "custom_registry") {
        std::vector<wc::DomainWorkflowContract> cs;
        for (const auto& spec : input.at("contracts"))
            cs.push_back(wc::DomainWorkflowContract::from_json(spec));
        wc::WorkflowContractRegistry r(std::move(cs));
        Json out = Json::array();
        for (const auto& s : r.validation_issues()) out.push_back(s);
        return out;
    }
    if (fn == "readiness") {
        StubProbe holder("model");
        const auto project =
            wc::ProjectView::from_json(input.value("project", Json::object()));
        return wc::evaluate_readiness(
                   project, input.at("contract_id").get<std::string>(),
                   &reg, probe_for(input, holder))
            .to_dict();
    }
    if (fn == "report_consultation") {
        wc::ProjectView p;
        const wc::ProjectView* pp = nullptr;
        if (input.contains("project")) {
            p = wc::ProjectView::from_json(input.at("project"));
            pp = &p;
        }
        return Json(wc::generate_consultation_report(&reg, pp));
    }
    if (fn == "report_gap")
        return Json(wc::generate_gap_report(&reg));
    throw std::runtime_error("unknown fn: " + fn);
}

// ---------------------------------------------------------------------------

int main() {
    const std::string fixture_path = PWB_CONTRACTS_FIXTURE;
    std::ifstream in(fixture_path);
    if (!in) {
        std::fprintf(stderr, "cannot open fixture %s\n",
                     fixture_path.c_str());
        return 2;
    }
    std::ostringstream buf;
    buf << in.rdbuf();
    const Json doc = Json::parse(buf.str());

    for (const Json& c : doc.at("cases")) {
        const std::string id = c.at("id").get<std::string>();
        const Json& expect = c.at("expect");
        try {
            const Json result = run_case(c);
            if (expect.contains("raises") &&
                !expect.at("raises").is_null()) {
                check(false,
                      id + " expected raise " +
                          expect.at("raises").get<std::string>() +
                          " but got result " +
                          result.dump().substr(0, 200));
            } else if (!sem_eq(result, expect.at("result"))) {
                const auto diff = pwb::domain::json_semantic_diff(
                    norm(result), norm(expect.at("result")));
                check(false, id + " mismatch at " + diff.path + ": got " +
                                 result.dump().substr(0, 240));
            }
        } catch (const std::exception& e) {
            const std::string cls = raise_class(e);
            if (!expect.contains("raises") ||
                expect.at("raises").is_null()) {
                check(false,
                      id + " unexpected raise " + cls + ": " + e.what());
                continue;
            }
            check(cls == expect.at("raises").get<std::string>(),
                  id + " raise class " + cls +
                      " != " + expect.at("raises").get<std::string>());
            check(std::string(e.what()) ==
                      expect.at("message").get<std::string>(),
                  id + " message '" + std::string(e.what()) + "' != '" +
                      expect.at("message").get<std::string>() + "'");
        }
    }

    std::printf("workflow.contracts: %d checks, %d failures\n", g_checks,
                g_failures);
    return g_failures ? 1 : 0;
}
