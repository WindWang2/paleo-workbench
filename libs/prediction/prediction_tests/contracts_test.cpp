// prediction.contracts — C++ prediction contract cores (libs/prediction)
// vs the frozen Python oracle. The oracle was produced by running the REAL
// paleo_workbench.prediction modules (postprocess / spatial_result /
// input_contract / model_package) — see
// tools/oracle/generate_prediction_contract_fixtures.py. "$FX" in case
// inputs and expects is replaced by the fixture-files dir so file paths
// are portable.

#include <pwb/domain/json.hpp>
#include <pwb/prediction/errors.hpp>
#include <pwb/prediction/input_contract.hpp>
#include <pwb/prediction/model_package.hpp>
#include <pwb/prediction/postprocess.hpp>
#include <pwb/prediction/spatial_result.hpp>

#include <cstdio>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>

namespace {

namespace fs = std::filesystem;
using pwb::domain::Json;

int g_failures = 0;
int g_checks = 0;

void check(bool ok, const std::string& what) {
    ++g_checks;
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

// Python has one int type: oracle numbers parse as unsigned while C++
// construction writes signed — dump/parse roundtrip puts both sides on the
// same number kind (int-vs-float stays a real difference), matching the
// interchange preflight/mapping grid-envelope convention.
Json norm(const Json& v) { return Json::parse(v.dump()); }

bool sem_eq(const Json& a, const Json& b) {
    return pwb::domain::json_semantically_equal(norm(a), norm(b));
}

Json subst(Json v, const std::string& prefix) {
    if (v.is_string()) {
        std::string s = v.get_ref<const std::string&>();
        const std::string marker = "$FX";
        size_t pos = 0;
        while ((pos = s.find(marker, pos)) != std::string::npos) {
            s.replace(pos, marker.size(), prefix);
            pos += prefix.size();
        }
        return Json(s);
    }
    if (v.is_array()) {
        for (auto& el : v) el = subst(el, prefix);
        return v;
    }
    if (v.is_object()) {
        for (auto& [k, el] : v.items()) el = subst(el, prefix);
        return v;
    }
    return v;
}

std::string raise_class(const std::exception& e) {
    if (dynamic_cast<const pwb::prediction::ModelPackageError*>(&e)) {
        return "ModelPackageError";
    }
    if (dynamic_cast<const pwb::prediction::UnicodeDecodeError*>(&e)) {
        return "UnicodeDecodeError";
    }
    if (dynamic_cast<const pwb::prediction::AttributeError*>(&e)) {
        return "AttributeError";
    }
    if (dynamic_cast<const pwb::prediction::ValueError*>(&e)) {
        return "ValueError";
    }
    if (dynamic_cast<const pwb::prediction::TypeError*>(&e)) {
        return "TypeError";
    }
    return "std::exception";
}

Json run_case(const Json& c, const std::string& fx) {
    const std::string fn = c.at("fn").get<std::string>();
    const Json input = subst(c.at("input"), fx);
    if (fn == "parse_input_schema") {
        return pwb::prediction::parse_input_schema(input.at("schema"));
    }
    if (fn == "postprocess_prediction_regions") {
        auto r = pwb::prediction::postprocess_prediction_regions(
            input.at("regions"), input.at("formation_boundaries"));
        return Json::array({r.records, r.summary});
    }
    if (fn == "resolve_formation_boundaries") {
        auto r = pwb::prediction::resolve_formation_boundaries(
            input.at("well_name"), input.at("well_log"), input.at("inputs"));
        return Json::array({r.boundaries, r.diagnostics});
    }
    if (fn == "spatial_type_of") {
        return Json(pwb::prediction::spatial_type_of(input.at("payload")));
    }
    if (fn == "extract_polygon_features") {
        return pwb::prediction::extract_polygon_features(input.at("payload"));
    }
    if (fn == "validate_spatial_result") {
        return pwb::prediction::validate_spatial_result(
            input.at("payload"), input.at("expected_type"),
            input.at("require_scientific").get<bool>());
    }
    if (fn == "bounded_result_summary") {
        return pwb::prediction::bounded_result_summary(input.at("payload"));
    }
    if (fn == "is_map_compilable") {
        return Json(pwb::prediction::is_map_compilable(input.at("payload")));
    }
    if (fn == "load_manifest_dict") {
        return pwb::prediction::load_manifest_dict(input.at("source"));
    }
    if (fn == "parse_model_package_manifest") {
        const auto m = pwb::prediction::parse_model_package_manifest(
            input.at("source"), input.at("base_dir"));
        return m.to_dict();
    }
    if (fn == "validate_model_package") {
        auto m = pwb::prediction::ModelPackageManifest::from_dict(
            input.at("manifest"));
        Json errors = pwb::prediction::validate_model_package(
            m, input.at("require_artifact").get<bool>(),
            input.at("allow_non_scientific").get<bool>());
        return Json::object({{"errors", errors},
                             {"manifest_after", m.to_dict()}});
    }
    throw std::runtime_error("unknown fn: " + fn);
}

}  // namespace

int main() {
    const std::string fixture_path = PWB_CONTRACTS_FIXTURE;
    const std::string fx =
        (fs::path(fixture_path).parent_path() / "prediction_contract_files")
            .string();

    std::ifstream in(fixture_path);
    if (!in) {
        std::fprintf(stderr, "cannot open fixture %s\n", fixture_path.c_str());
        return 2;
    }
    std::ostringstream buf;
    buf << in.rdbuf();
    const Json doc = Json::parse(buf.str());

    for (const Json& c : doc.at("cases")) {
        const std::string id = c.at("id").get<std::string>();
        const Json expect = subst(c.at("expect"), fx);
        try {
            const Json result = run_case(c, fx);
            if (c.at("fn").get<std::string>() == "validate_model_package") {
                check(sem_eq(result.at("errors"), expect.at("result")),
                      id + " errors mismatch: got " + result.at("errors").dump());
                check(sem_eq(result.at("manifest_after"),
                             subst(c.at("manifest_after"), fx)),
                      id + " manifest_after mismatch: got " +
                          result.at("manifest_after").dump());
            } else if (expect.contains("raises") && !expect.at("raises").is_null()) {
                check(false, id + " expected raise " +
                             expect.at("raises").get<std::string>() +
                             " but got result " + result.dump().substr(0, 200));
            } else {
                if (!sem_eq(result, expect.at("result"))) {
                    const auto diff = pwb::domain::json_semantic_diff(
                        norm(result), norm(expect.at("result")));
                    check(false, id + " mismatch at " + diff.path + ": got " +
                                 result.dump().substr(0, 240));
                }
            }
        } catch (const std::exception& e) {
            const std::string cls = raise_class(e);
            if (!expect.contains("raises") || expect.at("raises").is_null()) {
                check(false, id + " unexpected raise " + cls + ": " + e.what());
                continue;
            }
            check(cls == expect.at("raises").get<std::string>(),
                  id + " raise class " + cls + " != " +
                      expect.at("raises").get<std::string>());
            const std::string want = expect.at("message").get<std::string>();
            const std::string got = e.what();
            if (want.rfind("Invalid manifest JSON:", 0) == 0) {
                // nlohmann parse diagnostics differ from CPython wording;
                // the contract prefix is what callers see (21-decisions D9).
                check(got.rfind("Invalid manifest JSON:", 0) == 0,
                      id + " message prefix mismatch: " + got);
            } else {
                check(got == want,
                      id + " message '" + got + "' != '" + want + "'");
            }
        }
    }

    std::printf("prediction.contracts: %d checks, %d failures\n", g_checks,
                g_failures);
    return g_failures ? 1 : 0;
}
