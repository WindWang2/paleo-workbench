// well_science.curve_ops — C++ port vs the frozen Python oracle
// (curve_ops_oracle.json, generated from the REAL implementations by
// tools/oracle/generate_curve_ops_fixtures.py).
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <exception>
#include <fstream>
#include <functional>
#include <limits>
#include <optional>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/well_science/curve_expr.hpp>
#include <pwb/well_science/curve_ops.hpp>
#include <pwb/well_science/depth_unit.hpp>
#include <pwb/well_science/errors.hpp>
#include <pwb/well_science/null_policy.hpp>

using pwb::domain::Json;

namespace {

#ifndef PWB_CURVE_OPS_FIXTURE
#error "PWB_CURVE_OPS_FIXTURE must point at curve_ops_oracle.json"
#endif

int g_cases = 0;
int g_failures = 0;
std::string g_group;
std::string g_case;

void fail(const std::string& what) {
    std::fprintf(stderr, "FAIL [%s/%s] %s\n", g_group.c_str(),
                 g_case.c_str(), what.c_str());
    ++g_failures;
}

double nan_value() { return std::numeric_limits<double>::quiet_NaN(); }

bool special_equal(double a, double b) {
    if (std::isnan(a) && std::isnan(b)) return true;
    return a == b;
}

bool value_close(double got, double want, double abs_tol) {
    if (special_equal(got, want)) return true;
    if (!std::isfinite(got) || !std::isfinite(want)) return false;
    const double diff = std::fabs(got - want);
    return diff <= abs_tol || diff <= 1e-9 * std::fabs(want);
}

// JSON number | null(NaN) | "Infinity"/"-Infinity" → double
double jnum(const Json& v) {
    if (v.is_null()) return nan_value();
    if (v.is_string()) {
        const std::string s = v.get<std::string>();
        if (s == "Infinity") return std::numeric_limits<double>::infinity();
        if (s == "-Infinity") return -std::numeric_limits<double>::infinity();
        fail("fixture number is neither a number nor an infinity: " + s);
        return nan_value();
    }
    return v.get<double>();
}

std::vector<double> jarr_to_vec(const Json& arr) {
    std::vector<double> out;
    for (const auto& v : arr) out.push_back(jnum(v));
    return out;
}

std::optional<double> jopt(const Json& v) {
    if (v.is_null()) return std::nullopt;
    return jnum(v);
}

std::optional<std::string> jopt_str(const Json& v) {
    if (v.is_null()) return std::nullopt;
    return v.get<std::string>();
}

void compare_array(const std::vector<double>& got, const Json& want, double abs_tol) {
    if (got.size() != want.size()) {
        fail("length " + std::to_string(got.size()) + " != " +
             std::to_string(want.size()));
        return;
    }
    for (std::size_t i = 0; i < got.size(); ++i)
        if (!value_close(got[i], jnum(want[i]), abs_tol)) {
            fail("index " + std::to_string(i) + ": got " + std::to_string(got[i]) +
                 " want " + want[i].dump());
            return;
        }
}

// ---------------------------------------------------------------- runners --

void check_error(const std::function<void()>& call, const Json& expect) {
    try {
        call();
        fail("expected an exception, none raised");
    } catch (const pwb::well_science::CurveOpError& exc) {
        const std::string msg = exc.what();
        const std::string want = expect["message"].get<std::string>();
        const std::string mode =
            expect.value("match_mode", std::string("exact"));
        if (mode == "exact" ? msg != want : msg.rfind(want, 0) != 0)
            fail("message mismatch:\n  got:  " + msg + "\n  want: " + want);
    } catch (const std::exception& exc) {
        fail(std::string("unexpected exception type: ") + exc.what());
    }
}

void run_group(const Json& fx, const char* name,
               const std::function<std::vector<double>(
                   const std::vector<double>&, const Json&)>& call,
               double abs_tol = 1e-12) {
    g_group = name;
    for (const auto& c : fx[name]) {
        ++g_cases;
        g_case = c.value("name", std::string("case") + std::to_string(g_cases));
        const std::vector<double> values = jarr_to_vec(c["values"]);
        if (c.contains("raises")) {
            check_error([&] { (void)call(values, c); }, c);
            continue;
        }
        compare_array(call(values, c), c["expected"], abs_tol);
    }
}

void run_moving_average(const Json& fx) {
    run_group(fx, "moving_average",
              [](const std::vector<double>& v, const Json& c) {
                  return pwb::well_science::moving_average(v,
                                                           c.value("window", 5));
              });
}

void run_median_filter(const Json& fx) {
    run_group(fx, "median_filter",
              [](const std::vector<double>& v, const Json& c) {
                  return pwb::well_science::median_filter_curve(
                      v, c.value("window", 5));
              });
}

void run_normalize(const Json& fx) {
    run_group(fx, "normalize_curve",
              [](const std::vector<double>& v, const Json& c) {
                  return pwb::well_science::normalize_curve(
                      v, c.value("method", std::string("zscore")));
              });
}

void run_clip(const Json& fx) {
    run_group(fx, "clip_outliers",
              [](const std::vector<double>& v, const Json& c) {
                  return pwb::well_science::clip_outliers(
                      v, c.contains("lower") ? jopt(c["lower"]) : std::nullopt,
                      c.contains("upper") ? jopt(c["upper"]) : std::nullopt,
                      c.contains("percentile") ? jopt(c["percentile"])
                                               : std::nullopt);
              });
}

void run_units(const Json& fx) {
    g_group = "normalize_unit_name";
    for (const auto& c : fx["normalize_unit_name"]) {
        ++g_cases;
        g_case = c["name"].get<std::string>();
        const auto got = pwb::well_science::normalize_unit_name(
            jopt_str(c["token"]));
        if (c["expected"].is_null()) {
            if (got.has_value()) fail("expected nullopt, got " + *got);
        } else if (!got || *got != c["expected"].get<std::string>()) {
            fail("token '" + c["token"].dump() + "' -> " +
                 (got ? *got : "nullopt"));
        }
    }
    g_group = "conversion_factor";
    for (const auto& c : fx["conversion_factor"]) {
        ++g_cases;
        g_case = c["name"].get<std::string>();
        if (c.contains("raises")) {
            check_error([&] {
                (void)pwb::well_science::conversion_factor(jopt_str(c["from"]),
                                                           jopt_str(c["to"]));
            }, c);
            continue;
        }
        const double got = pwb::well_science::conversion_factor(
            jopt_str(c["from"]), jopt_str(c["to"]));
        if (!value_close(got, c["expected"].get<double>(), 1e-15))
            fail(c["name"].get<std::string>() + ": got " + std::to_string(got));
    }
    g_group = "convert_values";
    for (const auto& c : fx["convert_values"]) {
        ++g_cases;
        g_case = c["name"].get<std::string>();
        if (c.contains("raises")) {
            check_error([&] {
                (void)pwb::well_science::convert_values(
                    jarr_to_vec(c["values"]), jopt_str(c["from"]),
                    jopt_str(c["to"]));
            }, c);
            continue;
        }
        compare_array(pwb::well_science::convert_values(
                          jarr_to_vec(c["values"]), jopt_str(c["from"]),
                          jopt_str(c["to"])),
                      c["expected"], 1e-12);
    }
}

void run_resample(const Json& fx) {
    g_group = "resample_axis";
    for (const auto& c : fx["resample_axis"]) {
        ++g_cases;
        g_case = c["name"].get<std::string>();
        if (c.contains("raises")) {
            check_error([&] {
                (void)pwb::well_science::resample_axis(
                    jarr_to_vec(c["depth"]), jnum(c["step"]));
            }, c);
            continue;
        }
        compare_array(pwb::well_science::resample_axis(jarr_to_vec(c["depth"]),
                                                       jnum(c["step"])),
                      c["expected"], 1e-12);
    }
}

void run_interp(const Json& fx) {
    for (const char* group : {"interp_nan_aware", "interp_gap_preserving"}) {
        g_group = group;
        for (const auto& c : fx[group]) {
            ++g_cases;
            g_case = c.value("name", std::string("case") + std::to_string(g_cases));
            const auto new_x = jarr_to_vec(c["new_x"]);
            const auto x = jarr_to_vec(c["x"]);
            const auto y = jarr_to_vec(c["y"]);
            const bool is_nan_aware = group == std::string("interp_nan_aware");
            if (c.contains("raises")) {
                check_error([&] {
                    (void)(is_nan_aware
                               ? pwb::well_science::interp_nan_aware(new_x, x, y)
                               : pwb::well_science::interp_gap_preserving(new_x, x, y));
                }, c);
                continue;
            }
            compare_array(is_nan_aware
                              ? pwb::well_science::interp_nan_aware(new_x, x, y)
                              : pwb::well_science::interp_gap_preserving(new_x, x, y),
                          c["expected"], 1e-12);
        }
    }
}

void run_missing_report(const Json& fx) {
    g_group = "missing_interval_report";
    for (const auto& c : fx["missing_interval_report"]) {
        ++g_cases;
        g_case = c["name"].get<std::string>();
        const auto rep = pwb::well_science::missing_interval_report(
            jarr_to_vec(c["depth"]), jarr_to_vec(c["values"]));
        if (rep.total_samples != c["total_samples"].get<long>())
            fail(c["name"].get<std::string>() + ": total_samples");
        if (rep.missing_samples != c["missing_samples"].get<long>())
            fail(c["name"].get<std::string>() + ": missing_samples");
        if (rep.intervals.size() != c["intervals"].size()) {
            fail(c["name"].get<std::string>() + ": interval count " +
                 std::to_string(rep.intervals.size()));
            continue;
        }
        for (std::size_t i = 0; i < rep.intervals.size(); ++i) {
            if (!value_close(rep.intervals[i].first, jnum(c["intervals"][i][0]), 1e-12) ||
                !value_close(rep.intervals[i].second, jnum(c["intervals"][i][1]), 1e-12))
                fail(c["name"].get<std::string>() + ": interval " +
                     std::to_string(i));
        }
        if (!value_close(rep.missing_fraction(), jnum(c["expect_fraction"]), 1e-15))
            fail(c["name"].get<std::string>() + ": missing_fraction");
        if (!value_close(rep.largest_gap(), jnum(c["expect_largest"]), 1e-15))
            fail(c["name"].get<std::string>() + ": largest_gap");
    }
}

void run_expression(const Json& fx) {
    g_group = "evaluate_curve_expression";
    for (const auto& c : fx["evaluate_curve_expression"]) {
        ++g_cases;
        g_case = c["name"].get<std::string>();
        std::vector<pwb::well_science::CurveVariable> vars;
        for (auto it = c["variables"].begin(); it != c["variables"].end(); ++it)
            vars.push_back({it.key(), jarr_to_vec(it.value())});
        if (c.contains("raises")) {
            check_error([&] {
                (void)pwb::well_science::evaluate_curve_expression(
                    c["expr"].get<std::string>(), vars);
            }, c);
            continue;
        }
        compare_array(pwb::well_science::evaluate_curve_expression(
                          c["expr"].get<std::string>(), vars),
                      c["expected"], 1e-12);
    }
}

void run_depth_units(const Json& fx) {
    using namespace pwb::well_science;
    g_group = "classify_depth_unit";
    for (const auto& c : fx["classify_depth_unit"]) {
        ++g_cases;
        g_case = c["name"].get<std::string>();
        const auto info = classify_depth_unit(jopt_str(c["token"]));
        const bool unit_ok = c["unit"].is_null()
                                 ? !info.unit.has_value()
                                 : info.unit && *info.unit == c["unit"].get<std::string>();
        if (!unit_ok || info.declared != c["declared"].get<bool>() ||
            info.raw != c["raw"].get<std::string>() ||
            info.known() != c["known"].get<bool>())
            fail(c["name"].get<std::string>());
    }
    g_group = "require_depth_unit";
    for (const auto& c : fx["require_depth_unit"]) {
        ++g_cases;
        g_case = c["name"].get<std::string>();
        const std::string op = c["operation"].get<std::string>();
        const std::string kind = c["token_kind"].get<std::string>();
        if (kind == "info") {
            // input was a pre-classified DepthUnitInfo
            const auto info = classify_depth_unit(c["token"].get<std::string>());
            if (c.contains("raises")) {
                check_error([&] { (void)require_depth_unit(info, op); }, c);
            } else if (require_depth_unit(info, op) != c["expected"].get<std::string>()) {
                fail(c["name"].get<std::string>());
            }
            continue;
        }
        const std::optional<std::string> token =
            kind == "none" ? std::nullopt : std::optional<std::string>(c["token"].get<std::string>());
        if (c.contains("raises")) {
            check_error([&] { (void)require_depth_unit(token, op); }, c);
        } else if (require_depth_unit(token, op) != c["expected"].get<std::string>()) {
            fail(c["name"].get<std::string>());
        }
    }
}

void run_depth_unit_of(const Json& fx) {
    using namespace pwb::well_science;
    g_group = "depth_unit_of";
    for (const auto& c : fx["depth_unit_of"]) {
        ++g_cases;
        g_case = c["name"].get<std::string>();
        // "__ABSENT__" marks a document without a depth_unit attribute —
        // the C++ core receives nullopt for it (same as a null envelope).
        std::optional<std::string> envelope;
        if (!c["envelope"].is_null() && c["envelope"] != "__ABSENT__")
            envelope = c["envelope"].get<std::string>();
        const auto info = depth_unit_of(std::move(envelope));
        const bool unit_ok =
            c["unit"].is_null() ? !info.unit.has_value()
                                : info.unit && *info.unit == c["unit"].get<std::string>();
        if (!unit_ok || info.declared != c["declared"].get<bool>() ||
            info.raw != c["raw"].get<std::string>() ||
            info.known() != c["known"].get<bool>())
            fail(c["name"].get<std::string>());
    }
}

void run_null_policy(const Json& fx) {
    using namespace pwb::well_science;
    g_group = "null_policy";
    for (const auto& c : fx["null_policy"]) {
        ++g_cases;
        g_case = c["name"].get<std::string>();
        const Json& p = c["policy"];
        NullPolicy policy;
        policy.source = p["source"].get<std::string>();
        policy.sentinel = p.contains("sentinel") && !p["sentinel"].is_null()
                              ? std::optional<double>(jnum(p["sentinel"]))
                              : std::nullopt;
        if (p.contains("inferred_sentinels"))
            for (const auto& s : p["inferred_sentinels"])
                policy.inferred_sentinels.push_back(jnum(s));
        if (c.contains("expected_mask")) {
            const auto mask = policy.matches(jarr_to_vec(c["values"]));
            const Json& want = c["expected_mask"];
            if (mask.size() != want.size()) {
                fail(c["name"].get<std::string>() + ": mask length");
                continue;
            }
            for (std::size_t i = 0; i < mask.size(); ++i)
                if (static_cast<int>(mask[i]) != want[i].get<int>())
                    fail(c["name"].get<std::string>() + ": mask[" +
                         std::to_string(i) + "]");
            continue;
        }
        // as_dict contract: presence of keys mirrors the optionals
        const Json& want = c["expected"];
        bool ok = policy.source == want["source"].get<std::string>() &&
                  policy.declared() == c["declared_flag"].get<bool>();
        if (want.contains("sentinel") != policy.sentinel.has_value()) ok = false;
        if (policy.sentinel && !value_close(*policy.sentinel, jnum(want["sentinel"]), 0.0))
            ok = false;
        const bool want_inferred = want.contains("inferred_sentinels");
        if (want_inferred != !policy.inferred_sentinels.empty()) ok = false;
        if (want_inferred) {
            const Json& iw = want["inferred_sentinels"];
            if (iw.size() != policy.inferred_sentinels.size()) ok = false;
            else for (std::size_t i = 0; i < iw.size(); ++i)
                if (!value_close(policy.inferred_sentinels[i], jnum(iw[i]), 0.0))
                    ok = false;
        }
        if (!ok) fail(c["name"].get<std::string>());
    }
    g_group = "null_policy_from_declared";
    for (const auto& c : fx["null_policy_from_declared"]) {
        ++g_cases;
        g_case = c["name"].get<std::string>();
        const auto policy = null_policy_from_declared(jopt_str(c["raw"]));
        if (policy.source != c["source"].get<std::string>()) {
            fail(c["name"].get<std::string>() + ": source " + policy.source);
            continue;
        }
        const bool want_sentinel = !c["sentinel"].is_null();
        if (want_sentinel != policy.sentinel.has_value() ||
            (want_sentinel && !value_close(*policy.sentinel, jnum(c["sentinel"]), 0.0)))
            fail(c["name"].get<std::string>() + ": sentinel");
    }
}

void run_interpretation_kernels(const Json& fx) {
    using namespace pwb::well_science;
    g_group = "depth_shift";
    for (const auto& c : fx["depth_shift"]) {
        ++g_cases;
        g_case = c["name"].get<std::string>();
        const auto depths = jarr_to_vec(c["depths"]);
        if (c.contains("raises")) {
            check_error([&] {
                (void)depth_shift(depths, jnum(c["delta_m"]), jopt_str(c["axis_unit"]));
            }, c);
            continue;
        }
        compare_array(depth_shift(depths, jnum(c["delta_m"]), jopt_str(c["axis_unit"])),
                      c["expected"], 1e-12);
    }
    run_group(fx, "despike",
              [](const std::vector<double>& v, const Json& c) {
                  return pwb::well_science::despike(v, jnum(c["threshold_sigma"]),
                                                    c.value("window", 3));
              },
              1e-9);
    run_group(fx, "baseline_shift",
              [](const std::vector<double>& v, const Json& c) {
                  return pwb::well_science::baseline_shift(v, jnum(c["delta"]));
              });
}

void run_registry(const Json& fx) {
    using namespace pwb::well_science;
    g_group = "operation_registry";
    const Json& ops = fx["operation_registry"]["operations"];
    const auto& registry = curve_operations();
    if (registry.size() != ops.size()) {
        fail("registry size " + std::to_string(registry.size()) + " != " +
             std::to_string(ops.size()));
        return;
    }
    std::size_t i = 0;
    for (auto it = ops.begin(); it != ops.end(); ++it, ++i) {
        if (registry[i].name != it.key()) {
            fail("order mismatch at " + std::to_string(i) + ": " +
                 std::string(registry[i].name) + " vs " + it.key());
            return;
        }
        const Json& want = it.value();
        if (registry[i].scope != want["scope"].get<std::string>()) {
            fail(std::string(registry[i].name) + ": scope");
            continue;
        }
        if (registry[i].required_params.size() != want["required_params"].size()) {
            fail(std::string(registry[i].name) + ": params");
            continue;
        }
        for (std::size_t k = 0; k < registry[i].required_params.size(); ++k)
            if (registry[i].required_params[k] !=
                want["required_params"][k].get<std::string>())
                fail(std::string(registry[i].name) + ": param " +
                     std::to_string(k));
    }
}

// Regression pins for the adversarial-audit fixes (round 1): branches whose
// Python text comes from numpy internals are pinned to the C++ contract
// (raise + our message) — see ledgers/11-decisions.md D17/D18.
void run_audit_regression() {
    using namespace pwb::well_science;
    auto expect_throw = [](const char* what, const std::string& needle,
                           const std::function<void()>& call) {
        ++g_cases;
        g_case = what;
        try {
            call();
            fail(std::string(what) + ": expected an exception");
        } catch (const CurveOpError& exc) {
            if (std::string(exc.what()).find(needle) == std::string::npos)
                fail(std::string(what) + std::string(": got '") + exc.what() + "'");
        } catch (const std::exception& exc) {
            fail(std::string(what) + std::string(": wrong exception type: ") +
                 exc.what());
        }
    };
    const double nan = std::numeric_limits<double>::quiet_NaN();

    // clip_outliers: a NaN bound propagates through np.maximum/np.minimum.
    ++g_cases;
    g_case = "clip-nan-bound";
    const auto clipped = clip_outliers({1.0, 5.0}, nan, std::nullopt, std::nullopt);
    if (!(std::isnan(clipped[0]) && std::isnan(clipped[1])))
        fail("clip nan-bound must propagate");

    // expression clip with a single bound is a TypeError in the frozen env.
    expect_throw("clip-one-bound", "takes exactly 3", [&] {
        (void)evaluate_curve_expression("clip(GR, 1)", {{"GR", {1.0, 2.0}}});
    });
    // keyword detection precedes name resolution.
    expect_throw("keywords-before-names", "keyword arguments", [&] {
        (void)evaluate_curve_expression("clip(NOPE, a_min=0)", {{"GR", {1.0}}});
    });
    // resample with a non-finite span/step ratio must not be UB.
    expect_throw("resample-nonfinite-span", "not finite", [&] {
        (void)resample_axis({1000.0, std::numeric_limits<double>::infinity()}, 1.0);
    });
    // interp / report length mismatches raise instead of silently truncating.
    expect_throw("interp-nan-aware-length", "equal length", [&] {
        (void)interp_nan_aware({0.5}, {1.0, 2.0}, {1.0});
    });
    expect_throw("interp-gap-length", "equal length", [&] {
        (void)interp_gap_preserving({0.5}, {1.0, 2.0}, {1.0});
    });
    expect_throw("report-length", "equal length", [&] {
        (void)missing_interval_report({1.0}, {1.0, 2.0});
    });
}

}  // namespace

int main() {
    std::ifstream in(PWB_CURVE_OPS_FIXTURE);
    if (!in) {
        std::fprintf(stderr, "FAIL cannot open fixture " PWB_CURVE_OPS_FIXTURE "\n");
        return 2;
    }
    Json fx;
    try {
        in >> fx;
    } catch (const std::exception& exc) {
        std::fprintf(stderr, "FAIL fixture parse: %s\n", exc.what());
        return 2;
    }

    const auto safe = [&](const char* name, const auto& fn) {
        g_group = name;
        try {
            fn();
        } catch (const std::exception& exc) {
            std::fprintf(stderr, "FAIL [%s] crashed: %s\n", name, exc.what());
            ++g_failures;
        }
    };
    safe("moving_average", [&] { run_moving_average(fx); });
    safe("median_filter", [&] { run_median_filter(fx); });
    safe("normalize_curve", [&] { run_normalize(fx); });
    safe("clip_outliers", [&] { run_clip(fx); });
    safe("units", [&] { run_units(fx); });
    safe("resample_axis", [&] { run_resample(fx); });
    safe("interp", [&] { run_interp(fx); });
    safe("missing_interval_report", [&] { run_missing_report(fx); });
    safe("evaluate_curve_expression", [&] { run_expression(fx); });
    safe("depth_units", [&] { run_depth_units(fx); });
    safe("depth_unit_of", [&] { run_depth_unit_of(fx); });
    safe("null_policy", [&] { run_null_policy(fx); });
    safe("interpretation_kernels", [&] { run_interpretation_kernels(fx); });
    safe("operation_registry", [&] { run_registry(fx); });
    safe("audit_regression", [&] { run_audit_regression(); });

    std::printf("well_science.curve_ops: %d oracle cases, %d failures\n", g_cases,
                g_failures);
    return g_failures == 0 ? 0 : 1;
}
