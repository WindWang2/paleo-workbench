// factor_host.fingerprint — the C++ factor_host kernel (CONV-08) against the
// Python oracle frozen by tools/oracle/generate_factor_host_fixtures.py.
//
// Tolerances: hashes / digests / canonical encodings / error text are exact;
// floating-point metric comparisons allow 1e-9 relative slack because
// numpy's pairwise summation may differ from naive accumulation in the last
// ulps (bilinear sampling and grid axes are expression-identical and compared
// exactly).

#include <cmath>
#include <cstdio>
#include <exception>
#include <filesystem>
#include <fstream>
#include <functional>
#include <optional>
#include <sstream>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/factor_host/canonical_json.hpp>
#include <pwb/factor_host/evaluation.hpp>
#include <pwb/factor_host/fingerprint.hpp>
#include <pwb/factor_host/interop.hpp>
#include <pwb/factor_host/plan.hpp>

using pwb::domain::Json;
using namespace pwb::factor_host;

namespace {

int g_failures = 0;
int g_checks = 0;

void check(bool ok, const std::string& what) {
    ++g_checks;
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

void check_eq_str(const std::string& got, const std::string& want,
                  const std::string& what) {
    check(got == want, what + ": got '" + got + "' want '" + want + "'");
}

void check_num(const Json& got, const Json& want, const std::string& what,
               double rel_tol = 1e-9) {
    if (want.is_null()) {
        check(got.is_null(), what + ": expected null");
        return;
    }
    check(got.is_number(), what + ": expected a number");
    if (!got.is_number()) return;
    const double g = got.get<double>();
    const double w = want.get<double>();
    const double diff = std::fabs(g - w);
    const double scale = std::max(1.0, std::max(std::fabs(g), std::fabs(w)));
    check(diff <= rel_tol * scale,
          what + ": got " + std::to_string(g) + " want " + std::to_string(w));
}

void check_int(const Json& got, const Json& want, const std::string& what) {
    check(got.is_number() && want.is_number() &&
              got.get<long long>() == want.get<long long>(),
          what + ": got " + got.dump() + " want " + want.dump());
}

// Restore non-finite sentinels ("NaN" / "Infinity" / "-Infinity") that the
// strict-JSON fixture carries; nothing else in the fixture uses these exact
// strings.
void restore_sentinels(Json& node) {
    if (node.is_string()) {
        const std::string& s = node.get<std::string>();
        if (s == "NaN") node = std::nan("");
        else if (s == "Infinity") node = HUGE_VAL;
        else if (s == "-Infinity") node = -HUGE_VAL;
        return;
    }
    if (node.is_array()) {
        for (auto& item : node) restore_sentinels(item);
        return;
    }
    if (node.is_object()) {
        for (auto it = node.begin(); it != node.end(); ++it) {
            restore_sentinels(it.value());
        }
    }
}

std::vector<double> to_doubles(const Json& arr) {
    std::vector<double> out;
    out.reserve(arr.size());
    for (const Json& v : arr) out.push_back(v.get<double>());
    return out;
}

// Row-major flatten of a (possibly nested) numeric JSON array.
void flatten_into(const Json& node, std::vector<double>& out) {
    if (node.is_array()) {
        for (const Json& item : node) flatten_into(item, out);
        return;
    }
    out.push_back(node.get<double>());
}

std::vector<double> flatten(const Json& node) {
    std::vector<double> out;
    flatten_into(node, out);
    return out;
}

std::vector<Polyline> polylines_from_fixture(const Json& polys) {
    std::vector<Polyline> out;
    for (const Json& poly : polys) {
        Polyline line;
        for (const Json& p : poly) {
            line.emplace_back(p.at(0).get<double>(), p.at(1).get<double>());
        }
        out.push_back(std::move(line));
    }
    return out;
}

GridFrame to_frame(const Json& gx, const Json& gy, const Json& gz) {
    GridFrame frame;
    frame.grid_x = to_doubles(gx);
    frame.grid_y = to_doubles(gy);
    frame.grid_z = to_doubles(gz);
    return frame;
}

double finite_or_nan(const Json& v) {
    return v.is_number() ? v.get<double>() : std::nan("");
}

BuildFingerprintsArgs args_from_inputs(const Json& inputs) {
    BuildFingerprintsArgs args;
    args.sample_points = &inputs.at("sample_points");
    args.method = inputs.at("method").get<std::string>();
    // grid_n may arrive as float (32.0) — Python int() semantics.
    const Json& gn = inputs.at("grid_n");
    args.grid_n = gn.is_number_float()
        ? static_cast<int>(gn.get<double>())
        : gn.get<int>();
    args.power = inputs.at("power").get<double>();
    args.azimuth_deg = inputs.at("azimuth_deg").get<double>();
    args.semi_major = inputs.at("semi_major").get<double>();
    args.semi_minor = inputs.at("semi_minor").get<double>();
    if (!inputs.at("fault_polylines").is_null()) {
        args.fault_polylines = &inputs.at("fault_polylines");
    }
    if (!inputs.at("direction_params").is_null()) {
        args.direction_params = &inputs.at("direction_params");
    }
    if (!inputs.at("crs").is_null()) {
        args.crs = inputs.at("crs").get<std::string>();
    }
    if (!inputs.at("generator_version").is_null()) {
        args.generator_version = inputs.at("generator_version").get<std::string>();
    }
    if (!inputs.at("target_horizon").is_null()) {
        args.target_horizon = inputs.at("target_horizon").get<std::string>();
    }
    if (!inputs.at("duplicate_policy").is_null()) {
        args.duplicate_policy = inputs.at("duplicate_policy").get<std::string>();
    }
    return args;
}

void check_fingerprints(const Json& case_data) {
    const std::string id = case_data.at("id").get<std::string>();
    const Json inputs = case_data.at("inputs");
    BuildFingerprintsArgs args = args_from_inputs(inputs);
    const FactorFingerprints fps = build_factor_fingerprints(args);

    const Json want = case_data.at("fingerprints");
    check_eq_str(fps.geometry, want.at("geometry").get<std::string>(), id + ".geometry");
    check_eq_str(fps.values, want.at("values").get<std::string>(), id + ".values");
    check_eq_str(fps.algorithm, want.at("algorithm").get<std::string>(), id + ".algorithm");
    check_eq_str(fps.constraints, want.at("constraints").get<std::string>(), id + ".constraints");
    check_eq_str(fps.result, want.at("result").get<std::string>(), id + ".result");
    check_eq_str(fps.backend, want.at("backend").get<std::string>(), id + ".backend");
    // Exact hash equality proves the canonical payload encodings are
    // byte-identical to Python's json.dumps form (the frozen `payloads`
    // strings document those encodings for humans/debugging).

    // to_dict round-trips the Python dict exactly (keys and values).
    const Json dict = fps.to_dict();
    const Json want_dict = want.at("to_dict");
    for (auto it = want_dict.begin(); it != want_dict.end(); ++it) {
        const Json got = dict.contains(it.key()) ? dict.at(it.key()) : Json();
        if (it.value().is_number()) {
            if (it.key() == "schema_version") {
                check_int(got, it.value(), id + ".to_dict." + it.key());
            } else {
                check_num(got, it.value(), id + ".to_dict." + it.key());
            }
        } else {
            check(got == it.value(), id + ".to_dict." + it.key());
        }
    }
}

void check_records(const Json& case_data) {
    const std::string id = case_data.at("id").get<std::string>();
    const BuildFingerprintsArgs args = args_from_inputs(case_data.at("inputs"));
    const Json records = extract_sample_records(*args.sample_points);
    const Json want = case_data.at("records");
    check(records.size() == want.size(), id + ".records.size");
    for (std::size_t i = 0; i < want.size() && i < records.size(); ++i) {
        const Json& w = want[i];
        const Json& g = records[i];
        check(g.size() == w.size(), id + ".record[" + std::to_string(i) + "].keys");
        for (auto it = w.begin(); it != w.end(); ++it) {
            const Json got = g.contains(it.key()) ? g.at(it.key()) : Json();
            if (it.value().is_number_float() || it.value().is_null()) {
                if (it.value().is_null()) {
                    check(got.is_null(), id + ".record." + it.key() + " null");
                } else if (std::isnan(it.value().get<double>())) {
                    check(got.is_number() && std::isnan(got.get<double>()),
                          id + ".record." + it.key() + " NaN");
                } else if (std::isinf(it.value().get<double>())) {
                    check(got.is_number() && std::isinf(got.get<double>()) &&
                              std::signbit(it.value().get<double>()) ==
                                  std::signbit(got.get<double>()),
                          id + ".record." + it.key() + " inf");
                } else {
                    check_num(got, it.value(), id + ".record." + it.key(), 0.0);
                }
            } else {
                check(got == it.value(), id + ".record." + it.key());
            }
        }
    }
}

FactorTaskView task_view_from(const Json& task) {
    FactorTaskView view;
    view.parameters = &task.at("parameters");
    view.grid_metadata = &task.at("grid_metadata");
    view.status = task.at("status").get<std::string>();
    if (!task.at("input_snapshot_hash").is_null()) {
        view.input_snapshot_hash = task.at("input_snapshot_hash").get<std::string>();
    }
    if (!task.at("grid_artifact_path").is_null()) {
        view.grid_artifact_path = task.at("grid_artifact_path").get<std::string>();
    }
    return view;
}

void check_classify(const Json& case_data) {
    const std::string id = case_data.at("id").get<std::string>();
    FactorTaskView view = task_view_from(case_data.at("task"));
    const Json want_fps = case_data.at("current");
    FactorFingerprints current;
    current.geometry = want_fps.at("geometry").get<std::string>();
    current.values = want_fps.at("values").get<std::string>();
    current.algorithm = want_fps.at("algorithm").get<std::string>();
    current.constraints = want_fps.at("constraints").get<std::string>();
    current.result = want_fps.at("result").get<std::string>();
    current.backend = want_fps.at("backend").get<std::string>();
    const FactorDirtyState state = classify_factor_recompute(
        view, current, case_data.at("force").get<bool>());
    check_eq_str(to_string(state), case_data.at("expected").get<std::string>(),
                 id + ".state");
}

void check_plan_section(const Json& plan_cases) {
    for (const auto& c : plan_cases.at("xy_signature")) {
        const std::string id = "xy_signature." + c.at("id").get<std::string>();
        check_eq_str(xy_signature(to_doubles(c.at("x")), to_doubles(c.at("y"))),
                     c.at("sig").get<std::string>(), id);
    }
    for (const auto& c : plan_cases.at("fault_signature")) {
        const std::string id = "fault_signature." + c.at("id").get<std::string>();
        const std::vector<Polyline> polys =
            c.at("polylines").is_null()
                ? std::vector<Polyline>{}
                : polylines_from_fixture(c.at("polylines"));
        check_eq_str(fault_signature(polys), c.at("sig").get<std::string>(), id);
    }
    for (const auto& c : plan_cases.at("plan_key")) {
        const std::string id = "plan_key." + c.at("id").get<std::string>();
        const Json& kw = c.at("kwargs");
        PlanKey key;
        key.method = kw.at("method").get<std::string>();
        const std::vector<double> x = to_doubles(kw.at("x"));
        const std::vector<double> y = to_doubles(kw.at("y"));
        key.xy_sig = xy_signature(x, y);
        key.grid_n = kw.at("grid_n").get<int>();
        key.power = kw.at("power").get<double>();
        const std::vector<Polyline> polys =
            kw.at("fault_polylines").is_null()
                ? std::vector<Polyline>{}
                : polylines_from_fixture(kw.at("fault_polylines"));
        key.fault_sig = fault_signature(polys);
        key.azimuth_deg = kw.at("azimuth_deg").get<double>();
        key.semi_major = kw.at("semi_major").get<double>();
        key.semi_minor = kw.at("semi_minor").get<double>();
        const Json& want = c.at("fields");
        check_eq_str(key.method, want.at("method").get<std::string>(), id + ".method");
        check_eq_str(key.xy_sig, want.at("xy_sig").get<std::string>(), id + ".xy_sig");
        check_int(Json(key.grid_n), want.at("grid_n"), id + ".grid_n");
        check_num(Json(key.power), want.at("power"), id + ".power", 0.0);
        check_eq_str(key.fault_sig, want.at("fault_sig").get<std::string>(), id + ".fault_sig");
        check_num(Json(key.azimuth_deg), want.at("azimuth_deg"), id + ".az", 0.0);
        check_num(Json(key.semi_major), want.at("semi_major"), id + ".major", 0.0);
        check_num(Json(key.semi_minor), want.at("semi_minor"), id + ".minor", 0.0);
        check_eq_str(key.digest(), c.at("digest").get<std::string>(), id + ".digest");
    }
    for (const auto& c : plan_cases.at("build_idw_plan")) {
        const std::string id = "build_idw_plan." + c.at("id").get<std::string>();
        const Json& inputs = c.at("inputs");
        std::vector<Polyline> polys;
        const bool has_faults = !inputs.at("fault_polylines").is_null();
        if (has_faults) polys = polylines_from_fixture(inputs.at("fault_polylines"));
        const InterpolationPlan plan = build_idw_plan(
            inputs.at("sample_points"), inputs.at("grid_n").get<int>(),
            inputs.at("power").get<double>(),
            has_faults ? &polys : nullptr);
        const std::vector<double> sx = to_doubles(c.at("source_x"));
        const std::vector<double> sy = to_doubles(c.at("source_y"));
        const std::vector<double> gx = to_doubles(c.at("grid_x"));
        const std::vector<double> gy = to_doubles(c.at("grid_y"));
        check(plan.source_x == sx, id + ".source_x");
        check(plan.source_y == sy, id + ".source_y");
        check(plan.grid_x.size() == gx.size(), id + ".grid_x.size");
        check(plan.grid_y.size() == gy.size(), id + ".grid_y.size");
        for (std::size_t i = 0; i < gx.size() && i < plan.grid_x.size(); ++i) {
            check(plan.grid_x[i] == gx[i], id + ".grid_x[" + std::to_string(i) + "]");
            check(plan.grid_y[i] == gy[i], id + ".grid_y[" + std::to_string(i) + "]");
        }
        check_eq_str(plan.geometry_id, c.at("geometry_id").get<std::string>(), id + ".geometry_id");
        check_eq_str(plan.key.digest(), c.at("key").at("digest").get<std::string>(), id + ".key.digest");
        check_eq_str(plan.key.xy_sig, c.at("key").at("xy_sig").get<std::string>(), id + ".key.xy_sig");
        check_eq_str(plan.key.fault_sig, c.at("key").at("fault_sig").get<std::string>(), id + ".key.fault_sig");

        // JSON round-trip (host-side plan codec contract).
        const Json encoded = plan.to_json();
        const InterpolationPlan decoded = InterpolationPlan::from_json(encoded);
        check(decoded.key.digest() == plan.key.digest(), id + ".roundtrip.digest");
        check(decoded.source_x == plan.source_x, id + ".roundtrip.source_x");
        check(decoded.source_y == plan.source_y, id + ".roundtrip.source_y");
        check(decoded.grid_x == plan.grid_x, id + ".roundtrip.grid_x");
        check(decoded.grid_y == plan.grid_y, id + ".roundtrip.grid_y");
        check(decoded.geometry_id == plan.geometry_id, id + ".roundtrip.geometry_id");
        check(decoded.fault_polylines.size() == plan.fault_polylines.size(),
              id + ".roundtrip.faults");
    }
    for (const auto& c : plan_cases.at("build_idw_plan_errors")) {
        const std::string id = "build_idw_plan_errors." + c.at("id").get<std::string>();
        bool threw = false;
        std::string message;
        try {
            build_idw_plan(c.at("sample_points"), 10);
        } catch (const std::invalid_argument& exc) {
            threw = true;
            message = exc.what();
        }
        check(threw, id + ".must throw");
        check_eq_str(message, c.at("error").get<std::string>(), id + ".error");
    }
    for (const auto& c : plan_cases.at("extract_values_aligned")) {
        const std::string id = "extract_values_aligned." + c.at("id").get<std::string>();
        const Json& plan_points =
            c.contains("plan_points") ? c.at("plan_points") : c.at("sample_points");
        InterpolationPlan plan = build_idw_plan(plan_points, 16);
        if (c.at("id").get<std::string>() == "ok") {
            const std::vector<double> values =
                extract_values_aligned(c.at("sample_points"), plan);
            check(values == to_doubles(c.at("values")), id + ".values");
        } else {
            bool threw = false;
            std::string message;
            try {
                extract_values_aligned(c.at("sample_points"), plan);
            } catch (const std::invalid_argument& exc) {
                threw = true;
                message = exc.what();
            }
            check(threw, id + ".must throw");
            check_eq_str(message, c.at("error").get<std::string>(), id + ".error");
        }
    }
}

void check_metrics_cases(const Json& cases) {
    for (const auto& c : cases) {
        const std::string id = "metrics." + c.at("id").get<std::string>();
        if (c.contains("error")) {
            bool threw = false;
            std::string message;
            try {
                EvaluationMetrics::from_arrays(to_doubles(c.at("observed")),
                                               to_doubles(c.at("predicted")));
            } catch (const std::invalid_argument& exc) {
                threw = true;
                message = exc.what();
            }
            check(threw, id + ".must throw");
            check_eq_str(message, c.at("error").get<std::string>(), id + ".error");
            continue;
        }
        const EvaluationMetrics m = EvaluationMetrics::from_arrays(
            to_doubles(c.at("observed")), to_doubles(c.at("predicted")));
        const Json want = c.at("metrics");
        auto opt_json = [](const std::optional<double>& v) {
            return v ? Json(*v) : Json();
        };
        check_num(opt_json(m.rmse), want.at("rmse"), id + ".rmse");
        check_num(opt_json(m.mae), want.at("mae"), id + ".mae");
        check_num(opt_json(m.bias), want.at("bias"), id + ".bias");
        check_num(opt_json(m.r_squared), want.at("r_squared"), id + ".r2");
        check_int(Json(m.n_samples), want.at("n_samples"), id + ".n_samples");
        check_int(Json(m.n_skipped), Json(c.at("n_skipped")), id + ".n_skipped");
        const Json dict = m.to_dict();
        check(dict.size() == want.size(), id + ".to_dict.keys");
        check_num(dict.at("rmse"), want.at("rmse"), id + ".dict.rmse");
        check_num(dict.at("mae"), want.at("mae"), id + ".dict.mae");
        check_num(dict.at("bias"), want.at("bias"), id + ".dict.bias");
        check_num(dict.at("r_squared"), want.at("r_squared"), id + ".dict.r2");
        check_int(dict.at("n_samples"), want.at("n_samples"), id + ".dict.n");
        check_int(dict.at("n_skipped"), want.at("n_skipped"), id + ".dict.skipped");
    }
}

void check_bilinear_cases(const Json& cases) {
    for (const auto& c : cases) {
        const std::string id = "bilinear." + c.at("id").get<std::string>();
        const std::optional<double> got = bilinear_sample_grid(
            flatten(c.at("grid_z")), to_doubles(c.at("grid_x")),
            to_doubles(c.at("grid_y")), c.at("px").get<double>(),
            c.at("py").get<double>());
        const Json& want = c.at("sampled");
        if (want.is_null()) {
            check(!got.has_value(), id + ".expected None");
        } else {
            check(got.has_value(), id + ".expected a value");
            if (got) check(*got == want.get<double>(), id + ".exact value");
        }
    }
}

void check_signed_r2_cases(const Json& cases) {
    for (const auto& c : cases) {
        const std::string id = "signed_r2." + c.at("id").get<std::string>();
        const double got = signed_r_squared(to_doubles(c.at("observed")),
                                            to_doubles(c.at("predicted")));
        check_num(Json(got), Json(c.at("r2").get<double>()), id);
    }
}

void check_fold_cases(const Json& cases) {
    for (const auto& c : cases) {
        const std::string id = "folds." + c.at("id").get<std::string>();
        if (c.contains("error")) {
            bool threw = false;
            std::string message;
            try {
                spatial_fold_assignment(to_doubles(c.at("x")),
                                        to_doubles(c.at("y")), c.at("k").get<int>());
            } catch (const std::invalid_argument& exc) {
                threw = true;
                message = exc.what();
            }
            check(threw, id + ".must throw");
            check_eq_str(message, c.at("error").get<std::string>(), id + ".error");
            continue;
        }
        const std::vector<std::vector<int>> folds = spatial_fold_assignment(
            to_doubles(c.at("x")), to_doubles(c.at("y")), c.at("k").get<int>());
        const Json& want = c.at("folds");
        check(folds.size() == want.size(), id + ".fold count");
        for (std::size_t f = 0; f < folds.size() && f < want.size(); ++f) {
            const Json& want_fold = want[f];
            check(folds[f].size() == want_fold.size(), id + ".fold size");
            for (std::size_t i = 0; i < want_fold.size() && i < folds[f].size();
                 ++i) {
                check(folds[f][i] == want_fold[i].get<int>(),
                      id + ".fold[" + std::to_string(f) + "][" + std::to_string(i) + "]");
            }
        }
    }
}

void check_lowo_cases(const Json& cases) {
    for (const auto& c : cases) {
        const std::string id = "lowo." + c.at("id").get<std::string>();
        const std::vector<std::vector<int>> folds =
            leave_one_well_out_folds(c.at("points"));
        const Json& want = c.at("folds");
        check(folds.size() == want.size(), id + ".group count");
        for (std::size_t f = 0; f < folds.size() && f < want.size(); ++f) {
            check(folds[f].size() == want[f].size(), id + ".group size");
            for (std::size_t i = 0; i < want[f].size() && i < folds[f].size(); ++i) {
                check(folds[f][i] == want[f][i].get<int>(),
                      id + ".group[" + std::to_string(f) + "][" + std::to_string(i) + "]");
            }
        }
    }
}

// C++ mirrors of the generator's deterministic fold engines (same maths;
// metrics inherit numpy-vs-naive summation differences within tolerance).
GridFrame crude_idw_fold(const Json& train) {
    const std::size_t n = train.size();
    std::vector<double> xs(n), ys(n), zs(n);
    for (std::size_t i = 0; i < n; ++i) {
        xs[i] = train[i].at("x").get<double>();
        ys[i] = train[i].at("y").get<double>();
        zs[i] = train[i].at("value").get<double>();
    }
    const auto [xmin, xmax] = std::minmax_element(xs.begin(), xs.end());
    const auto [ymin, ymax] = std::minmax_element(ys.begin(), ys.end());
    GridFrame frame;
    frame.grid_x = linspace(*xmin - 50, *xmax + 50, 40);
    frame.grid_y = linspace(*ymin - 50, *ymax + 50, 40);
    const std::size_t W = frame.grid_x.size();
    const std::size_t H = frame.grid_y.size();
    frame.grid_z.assign(H * W, 0.0);
    for (std::size_t j = 0; j < H; ++j) {
        for (std::size_t i = 0; i < W; ++i) {
            const double gx = frame.grid_x[i];
            const double gy = frame.grid_y[j];
            double num = 0.0;
            double den = 0.0;
            for (std::size_t s = 0; s < n; ++s) {
                const double dx = gx - xs[s];
                const double dy = gy - ys[s];
                const double d = std::sqrt(dx * dx + dy * dy) + 1e-9;
                const double w = 1.0 / (d * d);
                num += zs[s] * w;
                den += w;
            }
            frame.grid_z[j * W + i] = num / den;
        }
    }
    return frame;
}

GridFrame flat_fold(const Json& train) {
    const std::size_t n = train.size();
    std::vector<double> xs(n), ys(n);
    for (std::size_t i = 0; i < n; ++i) {
        xs[i] = train[i].at("x").get<double>();
        ys[i] = train[i].at("y").get<double>();
    }
    const auto [xmin, xmax] = std::minmax_element(xs.begin(), xs.end());
    const auto [ymin, ymax] = std::minmax_element(ys.begin(), ys.end());
    GridFrame frame;
    frame.grid_x = linspace(*xmin - 50, *xmax + 50, 8);
    frame.grid_y = linspace(*ymin - 50, *ymax + 50, 6);
    frame.grid_z.assign(frame.grid_x.size() * frame.grid_y.size(), 0.0);
    return frame;
}

GridFrame hole_fold(const Json& train) {
    GridFrame frame = crude_idw_fold(train);
    frame.grid_z.assign(frame.grid_z.size(), std::nan(""));
    return frame;
}

void check_cross_validate_cases(const Json& cases) {
    for (const auto& c : cases) {
        const std::string id = "cross_validate." + c.at("id").get<std::string>();
        const std::string engine_name = c.at("id").get<std::string>();
        std::function<GridFrame(const Json&)> run_fold;
        if (engine_name == "boom") {
            run_fold = [](const Json&) -> GridFrame {
                throw FoldEngineError("ValueError", "engine exploded");
            };
        } else if (engine_name == "hole") {
            run_fold = hole_fold;
        } else if (engine_name == "flat") {
            run_fold = flat_fold;
        } else {
            run_fold = crude_idw_fold;
        }
        const std::optional<CrossValidationReport> report = cross_validate_surface(
            c.at("points"), run_fold, c.at("k").get<int>(), "IDW", "test");
        const Json& want = c.at("report");
        if (want.is_null()) {
            check(!report.has_value(), id + ".expected None");
            continue;
        }
        check(report.has_value(), id + ".expected a report");
        if (!report) continue;
        check_eq_str(report->scheme, want.at("scheme").get<std::string>(), id + ".scheme");
        check_eq_str(report->detail, want.at("detail").get<std::string>(), id + ".detail");
        check_int(Json(report->k), want.at("k"), id + ".k");
        const Json& want_metrics = want.at("metrics");
        check_int(Json(report->metrics.n_samples), want_metrics.at("n_samples"), id + ".n_samples");
        check_int(Json(report->metrics.n_skipped), want_metrics.at("n_skipped"), id + ".n_skipped");
        if (!want_metrics.at("rmse").is_null()) {
            check_num(report->metrics.rmse ? Json(*report->metrics.rmse) : Json(),
                      want_metrics.at("rmse"), id + ".rmse");
            check_num(report->metrics.mae ? Json(*report->metrics.mae) : Json(),
                      want_metrics.at("mae"), id + ".mae");
            check_num(report->metrics.bias ? Json(*report->metrics.bias) : Json(),
                      want_metrics.at("bias"), id + ".bias");
            check_num(report->metrics.r_squared ? Json(*report->metrics.r_squared) : Json(),
                      want_metrics.at("r_squared"), id + ".r2");
        }
        const Json& want_folds = want.at("folds");
        check(report->folds.size() == want_folds.size(), id + ".folds count");
        for (std::size_t f = 0; f < want_folds.size() && f < report->folds.size();
             ++f) {
            const Json& wf = want_folds[f];
            const Json gf = report->folds[f];
            if (wf.contains("status")) {
                check_eq_str(gf.at("status").get<std::string>(),
                             wf.at("status").get<std::string>(), id + ".fold status");
                continue;
            }
            check_int(gf.at("n_train"), wf.at("n_train"), id + ".fold n_train");
            check_int(gf.at("n_held"), wf.at("n_held"), id + ".fold n_held");
            check_int(gf.at("n_samples"), wf.at("n_samples"), id + ".fold n_samples");
            check_int(gf.at("n_skipped"), wf.at("n_skipped"), id + ".fold n_skipped");
            check_int(gf.at("n_held_skipped"), wf.at("n_held_skipped"),
                      id + ".fold n_held_skipped");
        }
        const Json& want_residuals = c.at("residuals");
        check(report->residuals.size() == want_residuals.size(), id + ".residuals count");
        for (std::size_t r = 0; r < want_residuals.size() && r < report->residuals.size();
             ++r) {
            const Json& wr = want_residuals[r];
            const Json& gr = report->residuals[r];
            check_num(gr.at("x"), wr.at("x"), id + ".residual x");
            check_num(gr.at("y"), wr.at("y"), id + ".residual y");
            check_num(gr.at("value"), wr.at("value"), id + ".residual value");
            check_num(gr.at("predicted"), wr.at("predicted"), id + ".residual predicted");
            check_num(gr.at("residual"), wr.at("residual"), id + ".residual");
        }
    }
}

void check_surface_residual_cases(const Json& cases) {
    for (const auto& c : cases) {
        const std::string id = "surface_residuals." + c.at("id").get<std::string>();
        auto [records, metrics] = surface_residuals(
            c.at("points"), to_doubles(c.at("grid_x")), to_doubles(c.at("grid_y")),
            flatten(c.at("grid_z")));
        const Json& want_records = c.at("records");
        check(records.size() == want_records.size(), id + ".records count");
        for (std::size_t r = 0; r < want_records.size() && r < records.size(); ++r) {
            const Json& wr = want_records[r];
            const Json& gr = records[r];
            check_num(gr.at("x"), wr.at("x"), id + ".x", 0.0);
            check_num(gr.at("y"), wr.at("y"), id + ".y", 0.0);
            check_num(gr.at("value"), wr.at("value"), id + ".value", 0.0);
            check_num(gr.at("predicted"), wr.at("predicted"), id + ".predicted", 0.0);
            check_num(gr.at("residual"), wr.at("residual"), id + ".residual", 0.0);
        }
        const Json& want_metrics = c.at("metrics");
        check_int(Json(metrics.n_samples), want_metrics.at("n_samples"), id + ".n_samples");
        check_num(metrics.rmse ? Json(*metrics.rmse) : Json(),
                  want_metrics.at("rmse"), id + ".rmse");
    }
}

void check_residual_feature_cases(const Json& cases) {
    for (const auto& c : cases) {
        const std::string id = "residual_features." + c.at("id").get<std::string>();
        const Json features = residual_features(c.at("residuals"));
        const Json& want = c.at("features");
        check(features.size() == want.size(), id + ".count");
        for (std::size_t i = 0; i < want.size() && i < features.size(); ++i) {
            check_eq_str(features[i].at("id").get<std::string>(),
                         want[i].at("id").get<std::string>(), id + ".id");
            check(features[i].at("geometry") == want[i].at("geometry"), id + ".geometry");
            check(features[i].at("properties") == want[i].at("properties"),
                  id + ".properties");
        }
    }
}

void check_context_cases(const Json& cases) {
    // Mirrors the generator environment: pyproj is present there, and the
    // frozen CRS cases only use verdicts the mapping-kernel-style rule
    // (EPSG:<digits> valid) reproduces exactly.
    auto crs_valid = [](const std::string& crs) {
        if (crs.rfind("EPSG:", 0) != 0) return false;
        const std::string digits = crs.substr(5);
        if (digits.empty()) return false;
        for (char c : digits) {
            if (!std::isdigit(static_cast<unsigned char>(c))) return false;
        }
        return true;
    };
    for (const auto& c : cases) {
        const std::string id = "context." + c.at("id").get<std::string>();
        const std::optional<std::string> unit =
            c.at("unit").is_null()
                ? std::nullopt
                : std::optional<std::string>(c.at("unit").get<std::string>());
        const std::optional<std::string> crs =
            c.at("crs").is_null()
                ? std::nullopt
                : std::optional<std::string>(c.at("crs").get<std::string>());
        const RecommendationContext context =
            validate_recommendation_context(unit, crs, crs_valid);
        const Json& want_gate = c.at("gate");
        if (want_gate.is_null()) {
            check(!context.gate.has_value(), id + ".expected open gate");
        } else {
            check(context.gate.has_value(), id + ".expected a gate");
            if (context.gate) {
                check_eq_str(*context.gate, want_gate.get<std::string>(), id + ".gate");
            }
        }
        check(context.warnings.size() == c.at("warnings").size(),
              id + ".warnings count");
        if (!context.warnings.empty() && !c.at("warnings").empty()) {
            check_eq_str(context.warnings[0],
                         c.at("warnings")[0].get<std::string>(), id + ".warning");
        }
    }
}

void check_adjudicate_cases(const Json& cases) {
    for (const auto& c : cases) {
        const std::string id = "adjudicate." + c.at("id").get<std::string>();
        const std::optional<std::string> gate =
            c.at("gate").is_null()
                ? std::nullopt
                : std::optional<std::string>(c.at("gate").get<std::string>());
        std::optional<std::vector<std::string>> unknown;
        if (!c.at("unknown_constraints").is_null()) {
            unknown = std::vector<std::string>{};
            for (const Json& v : c.at("unknown_constraints")) {
                unknown->push_back(v.get<std::string>());
            }
        }
        auto [mutated, recommended] = adjudicate_recommendation(
            c.at("entries"), gate, unknown,
            c.at("scheme_caveat").get<std::string>());
        const Json& want = c.at("mutated");
        check(mutated.size() == want.size(), id + ".entry count");
        for (std::size_t i = 0; i < want.size() && i < mutated.size(); ++i) {
            check_eq_str(mutated[i].at("method").get<std::string>(),
                         want[i].at("method").get<std::string>(), id + ".method");
            if (!want[i].contains("recommended")) {
                check(!mutated[i].contains("recommended"),
                      id + ".null-metrics entry stays untouched");
                continue;
            }
            check(mutated[i].at("recommended") == want[i].at("recommended"),
                  id + ".recommended");
            check_eq_str(mutated[i].at("rationale").get<std::string>(),
                         want[i].at("rationale").get<std::string>(), id + ".rationale");
        }
        const Json& want_recommended = c.at("recommended_method");
        if (want_recommended.is_null()) {
            check(!recommended.has_value(), id + ".expected no recommendation");
        } else {
            check(recommended.has_value(), id + ".expected a recommendation");
            if (recommended) {
                check_eq_str(*recommended, want_recommended.get<std::string>(),
                             id + ".recommended_method");
            }
        }
    }
}

void check_interop_cases(const Json& interop) {
    for (const auto& c : interop.at("resolve_engine_method")) {
        const std::string id = "resolve_engine_method." + c.at("id").get<std::string>();
        try {
            const std::string engine =
                resolve_engine_method(c.at("input").get<std::string>());
            check(c.at("error").is_null(), id + ".expected a throw");
            if (c.at("error").is_null()) {
                check_eq_str(engine, c.at("engine").get<std::string>(), id);
            }
        } catch (const std::invalid_argument& exc) {
            check(!c.at("error").is_null(), id + ".unexpected throw");
            check_eq_str(exc.what(), c.at("error").get<std::string>(), id + ".error");
        }
    }
    for (const auto& c : interop.at("variogram")) {
        const std::string id = "variogram." + c.at("id").get<std::string>();
        const Json settings = variogram_settings_from_params(c.at("params"));
        const Json& want = c.at("settings");
        check(settings.size() == want.size(), id + ".size");
        for (auto it = want.begin(); it != want.end(); ++it) {
            check(settings.contains(it.key()) && settings.at(it.key()) == it.value(),
                  id + "." + it.key());
        }
    }
    for (const auto& c : interop.at("interp_params")) {
        const std::string id = "interp_params." + c.at("id").get<std::string>();
        // task_method may be a non-string scalar in the fixture (Python
        // str()s it on the library side when the params method is falsy).
        const Json& task_method_json = c.at("task_method");
        const std::string task_method = task_method_json.is_string()
            ? task_method_json.get<std::string>()
            : task_method_json.dump();
        auto [method, grid_n, power] =
            interp_params_from_task(c.at("params"), task_method);
        check_eq_str(method, c.at("method").get<std::string>(), id + ".method");
        check_int(Json(grid_n), c.at("grid_n"), id + ".grid_n");
        check_num(Json(power), Json(c.at("power").get<double>()), id + ".power");
    }
}

void check_parity(const Json& parity) {
    // V8 M3: fingerprints over the normalized set (with the policy recorded)
    // must differ from fingerprints over the raw duplicate-bearing set.
    const Json& raw_fps = parity.at("fps_on_raw");
    const Json& norm_fps = parity.at("fps_on_normalized");
    BuildFingerprintsArgs args;
    args.sample_points = &parity.at("normalized");
    args.method = "IDW";
    args.grid_n = 20;
    args.target_horizon = "H1";
    const bool duplicates_present =
        parity.at("report").at("n_duplicate_groups").get<int>() > 0;
    if (duplicates_present) {
        args.duplicate_policy = parity.at("report").at("policy").get<std::string>();
    }
    const FactorFingerprints fps = build_factor_fingerprints(args);
    check_eq_str(fps.values, norm_fps.at("values").get<std::string>(),
                 "parity.normalized.values");
    check_eq_str(fps.result, norm_fps.at("result").get<std::string>(),
                 "parity.normalized.result");
    check(raw_fps.at("values") != norm_fps.at("values"),
          "parity.raw vs normalized differ");
}

}  // namespace

int main() {
    std::ifstream stream(PWB_FACTOR_HOST_FIXTURE, std::ios::binary);
    if (!stream.good()) {
        std::fprintf(stderr, "FAIL cannot open fixture\n");
        return 1;
    }
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    Json oracle;
    try {
        oracle = Json::parse(buffer.str());
    } catch (const std::exception& exc) {
        std::fprintf(stderr, "FAIL fixture parse: %s\n", exc.what());
        return 1;
    }
    restore_sentinels(oracle);

    const Json& meta = oracle.at("meta");
    check(meta.at("constrained_idw_label").get<std::string>() ==
              std::string(kConstrainedIdwLabel),
          "meta.constrained_idw_label");
    check_int(Json(kFingerprintSchemaVersion), meta.at("schema_version"),
              "meta.schema_version");

    // Fingerprint component + record cases (hash equality pins the encodings).
    for (const auto& c : oracle.at("fingerprint")) {
        check_fingerprints(c);
        check_records(c);
    }
    for (const auto& c : oracle.at("classify")) {
        check_classify(c);
    }
    check_plan_section(oracle.at("plan"));
    const Json& eval_cases = oracle.at("evaluation");
    check_metrics_cases(eval_cases.at("metrics"));
    check_signed_r2_cases(eval_cases.at("signed_r2"));
    check_bilinear_cases(eval_cases.at("bilinear"));
    check_fold_cases(eval_cases.at("folds"));
    check_lowo_cases(eval_cases.at("lowo"));
    check_cross_validate_cases(eval_cases.at("cross_validate"));
    check_surface_residual_cases(eval_cases.at("surface_residuals"));
    check_residual_feature_cases(eval_cases.at("residual_features"));
    check_context_cases(eval_cases.at("context"));
    check_adjudicate_cases(eval_cases.at("adjudicate"));
    check_interop_cases(oracle.at("interop"));
    check_parity(oracle.at("normalization_parity"));

    // C++-side branch coverage the oracle cannot freeze: a LIVE artifact file
    // makes task_has_numerical_output true (Python Path.is_file semantics).
    {
        const std::filesystem::path dir =
            std::filesystem::temp_directory_path() / "factor_host_selftest";
        std::filesystem::create_directories(dir);
        const std::filesystem::path artifact = dir / "factor.factor_grid.npz";
        {
            std::ofstream out(artifact, std::ios::binary);
            out << "oracle";
        }
        Json params = Json::object();
        FactorTaskView view;
        view.parameters = &params;
        view.grid_artifact_path = artifact.string();
        check(task_has_numerical_output(view), "artifact.existing file counts");
        std::filesystem::remove(artifact);
        check(!task_has_numerical_output(view), "artifact.missing file is false");
        std::filesystem::remove_all(dir);
    }

    // Plan cache LRU behavior (session semantics; Python has no numeric
    // oracle for this — pytest pins eviction shape only).
    {
        PlanCache cache;
        check(cache.stats().at("entries") == 0, "plan_cache.empty");
        auto make = [&](int n) {
            return std::make_shared<const InterpolationPlan>(
                build_idw_plan(
                    Json::array({Json::object({{"x", 0.0}, {"y", 0.0}, {"value", 1.0}}),
                                 Json::object({{"x", 1.0}, {"y", 1.0}, {"value", 2.0}})}),
                    n));
        };
        for (int i = 0; i < 40; ++i) {
            cache.put("k" + std::to_string(i), make(10 + i));
        }
        check_int(cache.stats().at("entries"), Json(32), "plan_cache.bounded");
        check(cache.get("k39") != nullptr, "plan_cache.newest retained");
        check(cache.get("k0") == nullptr, "plan_cache.oldest evicted");
        cache.clear();
        check_int(cache.stats().at("entries"), Json(0), "plan_cache.cleared");
    }

    std::printf("%s (%d checks, %d failures)\n",
                g_failures == 0 ? "PASS factor_host.fingerprint" : "FAIL factor_host.fingerprint",
                g_checks, g_failures);
    return g_failures == 0 ? 0 : 1;
}
