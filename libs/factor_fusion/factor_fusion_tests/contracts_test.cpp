// CONV-24 oracle replay: drives every frozen case in
// fixtures/factor_fusion_oracle.json through the C++ port and compares
// against the real-Python expectation (result or raise{class,message}).

#include <pwb/domain/json.hpp>
#include <pwb/factor_fusion/errors.hpp>
#include <pwb/factor_fusion/factor_units.hpp>
#include <pwb/factor_fusion/fusion.hpp>

#include <cmath>
#include <cstdio>
#include <fstream>
#include <map>
#include <sstream>
#include <string>
#include <vector>

using pwb::domain::Json;
using namespace pwb::factor_fusion;

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

// dump()/parse() round-trip normalises int/unsigned/float representations —
// the repo-standard comparison (interchange/mapping precedent).
bool semantically_equal(const Json& a, const Json& b) {
    return Json::parse(a.dump()) == Json::parse(b.dump());
}

// The fixture encodes non-finite floats as "NaN"/"Infinity"/"-Infinity"
// sentinel strings (strict JSON); decode them back on input reads. No
// frozen case carries a real string with one of those exact literals.
Json unsentinel(const Json& v) {
    if (v.is_string()) {
        const std::string& s = v.get_ref<const std::string&>();
        if (s == "NaN") return Json(std::numeric_limits<double>::quiet_NaN());
        if (s == "Infinity")
            return Json(std::numeric_limits<double>::infinity());
        if (s == "-Infinity")
            return Json(-std::numeric_limits<double>::infinity());
        return v;
    }
    if (v.is_array()) {
        Json out = Json::array();
        for (const Json& item : v) out.push_back(unsentinel(item));
        return out;
    }
    if (v.is_object()) {
        Json out = Json::object();
        for (auto it = v.begin(); it != v.end(); ++it) {
            out[it.key()] = unsentinel(it.value());
        }
        return out;
    }
    return v;
}

std::vector<double> rows_to_doubles(const Json& rows) {
    std::vector<double> out;
    for (const Json& row : rows) {
        for (const Json& v : row) {
            out.push_back(v.is_null()
                              ? std::numeric_limits<double>::quiet_NaN()
                              : v.get<double>());
        }
    }
    return out;
}

Json doubles_to_rows(const std::vector<double>& v, int height, int width) {
    Json rows = Json::array();
    for (int r = 0; r < height; ++r) {
        Json row = Json::array();
        for (int c = 0; c < width; ++c) {
            const double d = v[static_cast<std::size_t>(r) * width + c];
            row.push_back(std::isfinite(d) ? Json(d) : Json(nullptr));
        }
        rows.push_back(std::move(row));
    }
    return rows;
}

Json floats_to_rows(const std::vector<float>& v, int height, int width) {
    Json rows = Json::array();
    for (int r = 0; r < height; ++r) {
        Json row = Json::array();
        for (int c = 0; c < width; ++c) {
            const float f = v[static_cast<std::size_t>(r) * width + c];
            row.push_back(std::isfinite(f)
                              ? Json(static_cast<double>(f))
                              : Json(nullptr));
        }
        rows.push_back(std::move(row));
    }
    return rows;
}

FactorGrid make_grid(const Json& spec) {
    FactorGrid g;
    const Json& z = spec.at("grid_z");
    g.height = static_cast<int>(z.size());
    g.width = g.height ? static_cast<int>(z[0].size()) : 0;
    for (const Json& row : z) {
        for (const Json& v : row) {
            g.grid_z.push_back(v.is_null()
                                   ? std::numeric_limits<float>::quiet_NaN()
                                   : static_cast<float>(v.get<double>()));
        }
    }
    for (const Json& v : spec.at("grid_x")) g.grid_x.push_back(v.get<double>());
    for (const Json& v : spec.at("grid_y")) g.grid_y.push_back(v.get<double>());
    g.factor_name = spec.at("factor_name").get<std::string>();
    g.algorithm_id = spec.value("algorithm_id", "idw");
    if (spec.contains("algorithm_parameters") &&
        spec["algorithm_parameters"].is_object()) {
        g.algorithm_parameters = spec["algorithm_parameters"];
    }
    if (spec.contains("crs") && !spec["crs"].is_null()) {
        g.crs = spec["crs"].get<std::string>();
    }
    if (spec.contains("unit") && !spec["unit"].is_null()) {
        g.unit = spec["unit"].get<std::string>();
    }
    if (spec.contains("source_refs") && spec["source_refs"].is_array()) {
        for (const Json& r : spec["source_refs"]) {
            g.source_refs.push_back(r.get<std::string>());
        }
    }
    if (spec.contains("variance_grid") && !spec["variance_grid"].is_null()) {
        std::vector<float> var;
        for (const Json& row : spec["variance_grid"]) {
            for (const Json& v : row) {
                var.push_back(v.is_null()
                                  ? std::numeric_limits<float>::quiet_NaN()
                                  : static_cast<float>(v.get<double>()));
            }
        }
        g.variance_grid = std::move(var);
    }
    return g;
}

FactorEvidence make_evidence(const Json& spec) {
    const Json& n = spec.at("normalization");
    return FactorEvidence(
        spec.at("factor_name").get<std::string>(), make_grid(spec.at("grid")),
        spec.at("weight").get<double>(),
        Normalization(n.at("kind").get<std::string>(),
                      n.at("low").get<double>(), n.at("high").get<double>()));
}

FusionModel make_model(const Json& spec,
                       const std::vector<FactorEvidence>& evidences) {
    FusionModel m;
    m.name = spec.at("name").get<std::string>();
    m.kind = spec.at("kind").get<std::string>();
    m.evidences = evidences;
    if (spec.contains("rules") && spec["rules"].is_array()) {
        for (const Json& r : spec["rules"]) {
            m.rules.push_back(rule_from_rows(
                r.at("conditions"), r.at("class_name").get<std::string>(),
                false));
        }
    }
    if (spec.contains("default_class") &&
        spec["default_class"].is_string()) {
        m.default_class = spec["default_class"].get<std::string>();
    }
    if (spec.contains("class_thresholds") &&
        spec["class_thresholds"].is_array()) {
        for (const Json& t : spec["class_thresholds"]) {
            m.class_thresholds.push_back(t.get<double>());
        }
    }
    if (spec.contains("class_names") && spec["class_names"].is_array()) {
        for (const Json& n2 : spec["class_names"]) {
            m.class_names.push_back(n2.get<std::string>());
        }
    }
    if (spec.contains("weight_provenance") &&
        !spec["weight_provenance"].is_null()) {
        m.weight_provenance = spec["weight_provenance"];
    }
    m.validate();
    return m;
}

std::vector<FactorEvidence> make_evidences(const Json& list) {
    std::vector<FactorEvidence> out;
    for (const Json& e : list) out.push_back(make_evidence(e));
    return out;
}

Json freeze_grid(const FactorGrid& g) {
    Json refs = Json::array();
    for (const std::string& r : g.source_refs) refs.push_back(r);
    return {
        {"grid_z", floats_to_rows(g.grid_z, g.height, g.width)},
        {"variance_grid",
         g.variance_grid.has_value()
             ? floats_to_rows(*g.variance_grid, g.height, g.width)
             : Json(nullptr)},
        {"factor_name", g.factor_name},
        {"algorithm_id", g.algorithm_id},
        {"algorithm_parameters", g.algorithm_parameters},
        {"crs", g.crs.has_value() ? Json(*g.crs) : Json(nullptr)},
        {"unit", g.unit.has_value() ? Json(*g.unit) : Json(nullptr)},
        {"generator_version",
         g.generator_version.has_value() ? Json(*g.generator_version)
                                         : Json(nullptr)},
        {"source_refs", std::move(refs)},
    };
}

Json freeze_result(const FusionResult& r) {
    return {
        {"likelihood", freeze_grid(r.likelihood)},
        {"confidence", freeze_grid(r.confidence)},
        {"variance", r.variance.has_value() ? freeze_grid(*r.variance)
                                            : Json(nullptr)},
        {"class_names", r.class_names},
        {"qc", r.qc},
        {"model_dict", r.model_dict},
        {"provenance", r.provenance()},
    };
}

std::string raise_class(const std::exception& e) {
    if (const auto* pe = dynamic_cast<const PyError*>(&e)) {
        return pe->python_class();
    }
    return "std::exception";
}

}  // namespace

int main(int argc, char** argv) {
    const char* fixture_path = argc > 1 ? argv[1] : "factor_fusion_oracle.json";
    const Json fixture = read_fixture(fixture_path);
    int total = 0;
    for (const Json& c : fixture.at("cases")) {
        ++total;
        const std::string id = c.at("id").get<std::string>();
        const std::string fn = c.at("fn").get<std::string>();
        const Json input = unsentinel(c.at("input"));
        const Json& expect = c.at("expect");

        Json actual;
        std::string raised_class, raised_message;
        try {
            if (fn == "normalization_ctor") {
                actual = Normalization(input.at("kind").get<std::string>(),
                                       input.at("low").get<double>(),
                                       input.at("high").get<double>())
                             .to_dict();
            } else if (fn == "normalization_apply") {
                const Json& ns = input.at("normalization");
                const Normalization n(ns.at("kind").get<std::string>(),
                                      ns.at("low").get<double>(),
                                      ns.at("high").get<double>());
                const Json& vals = input.at("values");
                const int h = static_cast<int>(vals.size());
                const int w = h ? static_cast<int>(vals[0].size()) : 0;
                actual = doubles_to_rows(
                    n.apply(rows_to_doubles(vals)), h, w);
            } else if (fn == "evidence_ctor") {
                actual = make_evidence(input).to_dict();
            } else if (fn == "rule_ctor") {
                actual = rule_from_rows(
                             input.at("conditions"),
                             input.at("class_name").get<std::string>(), false)
                             .to_dict();
            } else if (fn == "rule_from_dict") {
                actual = FusionRule::from_dict(input.at("data")).to_dict();
            } else if (fn == "model_ctor") {
                actual = make_model(input.at("model"),
                                    make_evidences(input.at("evidences")))
                             .to_dict();
            } else if (fn == "model_fingerprint") {
                actual = make_model(input.at("model"),
                                    make_evidences(input.at("evidences")))
                             .fingerprint();
            } else if (fn == "model_from_dict") {
                std::map<std::string, FactorGrid> grids;
                for (auto it = input.at("grids").begin();
                     it != input.at("grids").end(); ++it) {
                    grids.emplace(it.key(), make_grid(it.value()));
                }
                actual = FusionModel::from_dict(input.at("data"), grids)
                             .to_dict();
            } else if (fn == "fuse") {
                actual = freeze_result(fuse(make_model(
                    input.at("model"), make_evidences(input.at("evidences")))));
            } else if (fn == "aligned_or_raise") {
                std::vector<FactorGrid> grids;
                for (const Json& s : input.at("grids")) {
                    grids.push_back(make_grid(s));
                }
                const auto crs = aligned_or_raise(grids);
                actual = crs.has_value() ? Json(*crs) : Json(nullptr);
            } else if (fn == "sensitivity") {
                const FusionModel m = make_model(
                    input.at("model"), make_evidences(input.at("evidences")));
                actual = sensitivity_report(m, fuse(m));
            } else if (fn == "normalize_key") {
                actual = normalize_factor_key(input.at("name").get<std::string>());
            } else if (fn == "unit_for_factor") {
                const auto u = unit_for_factor(input.at("name").get<std::string>());
                actual = u.has_value() ? Json(*u) : Json(nullptr);
            } else if (fn == "color_ramp_for_factor") {
                const auto r =
                    color_ramp_for_factor(input.at("name").get<std::string>());
                actual = r.has_value() ? Json(*r) : Json(nullptr);
            } else if (fn == "validate_unit") {
                std::vector<float> values;
                for (const Json& row : input.at("values")) {
                    for (const Json& v : row) {
                        values.push_back(
                            v.is_null()
                                ? std::numeric_limits<float>::quiet_NaN()
                                : static_cast<float>(v.get<double>()));
                    }
                }
                std::optional<std::string> unit;
                if (!input.at("unit").is_null()) {
                    unit = input.at("unit").get<std::string>();
                }
                actual = validate_factor_unit_against_values(
                    input.at("factor_name").get<std::string>(), unit, values);
            } else {
                check(false, id, "unknown fn " + fn);
                continue;
            }
        } catch (const std::exception& e) {
            raised_class = raise_class(e);
            raised_message = e.what();
        }

        if (expect.contains("raise")) {
            const Json& er = expect.at("raise");
            check(raised_class == er.at("python_class").get<std::string>(), id,
                  "raise class " + raised_class + " != " +
                      er.at("python_class").get<std::string>());
            check(raised_message == er.at("message").get<std::string>(), id,
                  "raise message " + raised_message + " != " +
                      er.at("message").get<std::string>());
        } else {
            if (!raised_class.empty()) {
                check(false, id, "unexpected raise " + raised_class + ": " +
                                 raised_message);
                continue;
            }
            if (!semantically_equal(actual, expect.at("result"))) {
                check(false, id,
                      "result mismatch\n  actual:   " + actual.dump() +
                          "\n  expected: " + expect.at("result").dump());
            }
        }
    }
    std::printf("factor_fusion.contracts: %d checks, %d failures (%d cases)\n",
                g_checks, g_failures, total);
    return g_failures ? 1 : 0;
}
