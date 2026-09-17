#include <pwb/factor_host/evaluation.hpp>

#include "semantics.hpp"

#include <pwb/factor_host/canonical_json.hpp>

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdio>
#include <limits>
#include <numeric>
#include <set>
#include <utility>

namespace pwb::factor_host {

namespace {

double sum_of_squares_diff(const std::vector<double>& a,
                           const std::vector<double>& b) {
    double total = 0.0;
    for (std::size_t i = 0; i < a.size(); ++i) {
        total += (a[i] - b[i]) * (a[i] - b[i]);
    }
    return total;
}

double mean_of(const std::vector<double>& values) {
    double total = 0.0;
    for (double v : values) total += v;
    return total / static_cast<double>(values.size());
}

// float(pt["key"]) — a missing key is a programming error (Python crashes on
// float(pt.get("x")) with KeyError); mirror that with a loud throw. Numeric
// strings and bools coerce exactly like Python float().
double require_number(const Json& point, const char* key) {
    const auto it = point.find(key);
    if (it == point.end() || it->is_null()) {
        throw std::invalid_argument(std::string("point missing '") + key + "'");
    }
    if (it->is_number()) return it->get<double>();
    if (it->is_boolean()) return it->get<bool>() ? 1.0 : 0.0;
    if (it->is_string()) {
        const auto parsed = python_float_from_string(it->get<std::string>());
        if (!parsed) {
            throw std::invalid_argument(std::string("could not convert ") +
                                        key + " to float");
        }
        return *parsed;
    }
    throw std::invalid_argument(std::string("float() argument must be a "
                                            "number, not '") +
                                std::string(it->type_name()) + "'");
}

double value_or_nan(const Json& point) {
    if (point.contains("value")) return require_number(point, "value");
    if (point.contains("z")) return require_number(point, "z");
    return std::nan("");
}

}  // namespace

EvaluationMetrics EvaluationMetrics::from_arrays(
    const std::vector<double>& observed, const std::vector<double>& predicted) {
    if (observed.size() != predicted.size()) {
        char obs_buf[32];
        char pred_buf[32];
        std::snprintf(obs_buf, sizeof obs_buf, "(%zu,)", observed.size());
        std::snprintf(pred_buf, sizeof pred_buf, "(%zu,)", predicted.size());
        throw std::invalid_argument(
            std::string("observed/predicted shape mismatch: ") + obs_buf +
            " vs " + pred_buf);
    }
    std::vector<double> o;
    std::vector<double> p;
    o.reserve(observed.size());
    p.reserve(predicted.size());
    int n_skipped = 0;
    for (std::size_t i = 0; i < observed.size(); ++i) {
        if (std::isfinite(observed[i]) && std::isfinite(predicted[i])) {
            o.push_back(observed[i]);
            p.push_back(predicted[i]);
        } else {
            ++n_skipped;
        }
    }
    EvaluationMetrics m;
    m.n_samples = static_cast<int>(o.size());
    m.n_skipped = n_skipped;
    if (o.empty()) return m;
    double ss_res = 0.0;
    double ss_abs = 0.0;
    double err_sum = 0.0;
    for (std::size_t i = 0; i < o.size(); ++i) {
        const double err = o[i] - p[i];
        ss_res += err * err;
        ss_abs += std::fabs(err);
        err_sum += err;
    }
    const double n = static_cast<double>(o.size());
    m.rmse = std::sqrt(ss_res / n);
    m.mae = ss_abs / n;
    m.bias = err_sum / n;
    m.r_squared = signed_r_squared(o, p);
    return m;
}

Json EvaluationMetrics::to_dict() const {
    auto num = [](const std::optional<double>& v) -> Json {
        if (!v || !std::isfinite(*v)) return Json();
        return *v;
    };
    Json out = Json::object();
    out["rmse"] = num(rmse);
    out["mae"] = num(mae);
    out["bias"] = num(bias);
    out["r_squared"] = num(r_squared);
    out["n_samples"] = n_samples;
    out["n_skipped"] = n_skipped;
    return out;
}

std::optional<double> bilinear_sample_grid(const std::vector<double>& grid_z,
                                           const std::vector<double>& grid_x,
                                           const std::vector<double>& grid_y,
                                           double px, double py) {
    if (grid_x.empty() || grid_y.empty()) return std::nullopt;
    const double x0 = grid_x.front();
    const double x1 = grid_x.back();
    const double y0 = grid_y.front();
    const double y1 = grid_y.back();
    const std::size_t nx = grid_x.size();
    const std::size_t ny = grid_y.size();
    const double fi = nx > 1 ? (px - x0) / (x1 - x0) * static_cast<double>(nx - 1) : 0.0;
    const double fj = ny > 1 ? (py - y0) / (y1 - y0) * static_cast<double>(ny - 1) : 0.0;
    if (!(std::isfinite(fi) && std::isfinite(fj))) return std::nullopt;
    if (fi < 0.0 || fi > static_cast<double>(nx - 1) || fj < 0.0 ||
        fj > static_cast<double>(ny - 1)) {
        return std::nullopt;
    }
    // Python computes int indices i = min(max(floor(fi), 0), nx - 2) — for
    // nx == 1 that is -1, and numpy negative indexing wraps it back to the
    // last column (column 0 when nx == 1, the same cell as i + 1). The
    // fraction a = fi - i is computed BEFORE the wrap, so keep signed
    // arithmetic all the way down.
    const std::ptrdiff_t i_int = std::min<std::ptrdiff_t>(
        std::max<std::ptrdiff_t>(static_cast<std::ptrdiff_t>(std::floor(fi)), 0),
        static_cast<std::ptrdiff_t>(nx) - 2);
    const std::ptrdiff_t j_int = std::min<std::ptrdiff_t>(
        std::max<std::ptrdiff_t>(static_cast<std::ptrdiff_t>(std::floor(fj)), 0),
        static_cast<std::ptrdiff_t>(ny) - 2);
    const auto wrap = [](std::ptrdiff_t k, std::size_t size) {
        return k < 0 ? k + static_cast<std::ptrdiff_t>(size) : k;
    };
    const std::ptrdiff_t i = wrap(i_int, nx);
    const std::ptrdiff_t j = wrap(j_int, ny);
    const double a = fi - static_cast<double>(i_int);
    const double b = fj - static_cast<double>(j_int);
    const double at = 1.0 - a;
    const double bt = 1.0 - b;
    // Same expression shape as Python so results stay bit-identical. The
    // "+1" indices are i_int+1 / j_int+1 (never wrapped: when nx == 1 they
    // are 0, which is exactly Python's z[j, i+1] with i = -1).
    const auto cell = [&](std::ptrdiff_t row, std::ptrdiff_t col) -> double {
        return grid_z[static_cast<std::size_t>(row) * nx +
                      static_cast<std::size_t>(col)];
    };
    const double v = cell(j, i) * at * bt +
                     cell(j, i_int + 1) * a * bt +
                     cell(j_int + 1, i) * at * b +
                     cell(j_int + 1, i_int + 1) * a * b;
    if (!std::isfinite(v)) return std::nullopt;
    return v;
}

double signed_r_squared(const std::vector<double>& observed,
                        const std::vector<double>& predicted) {
    const double ss_res = sum_of_squares_diff(observed, predicted);
    const double obs_mean = mean_of(observed);
    double ss_tot = 0.0;
    for (double v : observed) ss_tot += (v - obs_mean) * (v - obs_mean);
    if (ss_tot < 1e-12) return 1.0;
    return 1.0 - ss_res / ss_tot;
}

std::vector<std::vector<int>> spatial_fold_assignment(
    const std::vector<double>& x, const std::vector<double>& y, int k) {
    if (k < 2) {
        throw std::invalid_argument("k must be >= 2, got " + std::to_string(k));
    }
    if (x.size() != y.size()) {
        throw std::invalid_argument("x/y size mismatch");
    }
    if (x.empty()) return {};
    const double mx = mean_of(x);
    const double my = mean_of(y);
    std::vector<int> order(x.size());
    std::iota(order.begin(), order.end(), 0);
    std::vector<double> angle(x.size());
    for (std::size_t i = 0; i < x.size(); ++i) {
        angle[i] = std::atan2(y[i] - my, x[i] - mx);
    }
    std::stable_sort(order.begin(), order.end(), [&](int a, int b) {
        // numpy sorts NaN to the end; keep the comparator a strict weak
        // order by treating NaN as greater than everything.
        const double ca = angle[a];
        const double cb = angle[b];
        if (std::isnan(ca)) return false;
        if (std::isnan(cb)) return true;
        return ca < cb;
    });
    std::vector<std::vector<int>> folds(static_cast<std::size_t>(k));
    int rank = 0;
    for (int idx : order) {
        folds[static_cast<std::size_t>(rank % k)].push_back(idx);
        ++rank;
    }
    return folds;
}

std::vector<std::vector<int>> leave_one_well_out_folds(const Json& points) {
    // Python: str(pt.get("well_id") or pt.get("name") or "").strip()
    auto well_key = [&](const Json& pt) {
        for (const char* field : {"well_id", "name"}) {
            const auto it = pt.find(field);
            if (it == pt.end()) continue;
            bool truthy;
            std::string text;
            if (it->is_string()) {
                text = it->get<std::string>();
                truthy = !text.empty();
            } else if (it->is_boolean()) {
                truthy = it->get<bool>();
                text = python_str_scalar(*it);
            } else if (it->is_number()) {
                truthy = it->get<double>() != 0.0;
                text = python_str_scalar(*it);
            } else {
                truthy = false;
            }
            if (truthy) return detail::python_strip(text);
        }
        return std::string();
    };

    std::vector<std::pair<std::string, std::vector<int>>> groups;
    for (std::size_t index = 0; index < points.size(); ++index) {
        std::string key = well_key(points[index]);
        if (key.empty()) {
            key = "__anonymous_" + std::to_string(index);
        }
        auto it = std::find_if(groups.begin(), groups.end(),
                               [&](const auto& g) { return g.first == key; });
        if (it == groups.end()) {
            groups.emplace_back(std::move(key),
                                std::vector<int>{static_cast<int>(index)});
        } else {
            it->second.push_back(static_cast<int>(index));
        }
    }
    std::vector<std::vector<int>> folds;
    folds.reserve(groups.size());
    for (auto& group : groups) folds.push_back(std::move(group.second));
    return folds;
}

std::optional<CrossValidationReport> cross_validate_surface(
    const Json& points,
    const std::function<GridFrame(const Json& train)>& run_fold, int k,
    std::string method_label, std::string engine) {
    Json scorable = Json::array();
    std::set<std::pair<double, double>> seen_coords;
    int n_nonfinite = 0;
    int n_duplicates = 0;
    for (const Json& pt : points) {
        const double x_v = require_number(pt, "x");
        const double y_v = require_number(pt, "y");
        const double z_v = value_or_nan(pt);
        if (!(std::isfinite(x_v) && std::isfinite(y_v) && std::isfinite(z_v))) {
            ++n_nonfinite;
            continue;
        }
        // Twin wells (identical coordinates) enter as ONE sample (R3-P1).
        if (!seen_coords.insert({x_v, y_v}).second) {
            ++n_duplicates;
            continue;
        }
        scorable.push_back(pt);
    }
    if (static_cast<int>(scorable.size()) < k + 2) return std::nullopt;

    std::vector<double> xs;
    std::vector<double> ys;
    xs.reserve(scorable.size());
    ys.reserve(scorable.size());
    for (const Json& p : scorable) {
        xs.push_back(require_number(p, "x"));
        ys.push_back(require_number(p, "y"));
    }
    const std::vector<std::vector<int>> folds =
        spatial_fold_assignment(xs, ys, k);

    std::vector<double> observed_all;
    std::vector<double> predicted_all;
    int attempted = 0;
    Json fold_records = Json::array();
    Json residuals = Json::array();
    for (std::size_t fold_idx = 0; fold_idx < folds.size(); ++fold_idx) {
        const std::vector<int>& test_indices = folds[fold_idx];
        std::vector<int> test_set = test_indices;
        std::sort(test_set.begin(), test_set.end());
        Json train = Json::array();
        Json held = Json::array();
        std::size_t cursor = 0;
        for (int i = 0; i < static_cast<int>(scorable.size()); ++i) {
            if (cursor < test_set.size() && test_set[cursor] == i) {
                held.push_back(scorable[static_cast<std::size_t>(i)]);
                ++cursor;
            } else {
                train.push_back(scorable[static_cast<std::size_t>(i)]);
            }
        }
        if (train.size() < 2 || held.empty()) {
            Json record = Json::object();
            record["fold"] = static_cast<int>(fold_idx);
            record["status"] = "skipped";
            record["n_skipped"] = static_cast<int>(held.size());
            fold_records.push_back(std::move(record));
            continue;
        }
        GridFrame frame;
        try {
            frame = run_fold(train);
        } catch (const FoldEngineError& exc) {
            CrossValidationReport failed;
            failed.method = method_label;
            failed.scheme = "unavailable";
            failed.k = k;
            failed.folds = std::move(fold_records);
            failed.engine = engine;
            failed.detail = "fold " + std::to_string(fold_idx) + " failed: " +
                            exc.exc_type() + ": " + exc.what();
            return failed;
        } catch (const std::exception& exc) {
            // A fold engine failure must stay visible (Python converts ANY
            // exception). FoldEngineError carries the Python exception type
            // name; anything else falls back to the "error" convention
            // documented in 08-decisions.md D-6.
            CrossValidationReport failed;
            failed.method = method_label;
            failed.scheme = "unavailable";
            failed.k = k;
            failed.folds = std::move(fold_records);
            failed.engine = engine;
            failed.detail = "fold " + std::to_string(fold_idx) +
                            " failed: error: " + exc.what();
            return failed;
        }
        std::vector<double> fold_obs;
        std::vector<double> fold_pred;
        int fold_skipped = 0;
        attempted += static_cast<int>(held.size());
        for (const Json& pt : held) {
            const double px = require_number(pt, "x");
            const double py = require_number(pt, "y");
            const double pv = value_or_nan(pt);
            const std::optional<double> sampled = bilinear_sample_grid(
                frame.grid_z, frame.grid_x, frame.grid_y, px, py);
            if (!sampled) {
                ++fold_skipped;
                continue;
            }
            fold_obs.push_back(pv);
            fold_pred.push_back(*sampled);
            Json residual = Json::object();
            residual["x"] = px;
            residual["y"] = py;
            residual["value"] = pv;
            residual["predicted"] = *sampled;
            residual["residual"] = pv - *sampled;
            residuals.push_back(std::move(residual));
        }
        observed_all.insert(observed_all.end(), fold_obs.begin(), fold_obs.end());
        predicted_all.insert(predicted_all.end(), fold_pred.begin(),
                             fold_pred.end());
        EvaluationMetrics fold_metrics =
            EvaluationMetrics::from_arrays(fold_obs, fold_pred);
        Json fold_payload = fold_metrics.to_dict();
        fold_payload["n_held_skipped"] = fold_skipped;
        Json record = Json::object();
        record["fold"] = static_cast<int>(fold_idx);
        record["n_train"] = static_cast<int>(train.size());
        record["n_held"] = static_cast<int>(held.size());
        for (auto it = fold_payload.begin(); it != fold_payload.end(); ++it) {
            record[it.key()] = it.value();
        }
        fold_records.push_back(std::move(record));
    }

    EvaluationMetrics metrics =
        EvaluationMetrics::from_arrays(observed_all, predicted_all);
    if (metrics.n_samples < attempted) {
        metrics.n_skipped = attempted - metrics.n_samples;
    }
    CrossValidationReport report;
    report.method = std::move(method_label);
    report.scheme = "kfold_surface";
    report.k = k;
    report.metrics = std::move(metrics);
    report.folds = std::move(fold_records);
    report.residuals = std::move(residuals);
    report.engine = std::move(engine);
    report.detail = "scorable=" + std::to_string(scorable.size());
    if (n_nonfinite) {
        report.detail += "; non_finite_dropped=" + std::to_string(n_nonfinite);
    }
    if (n_duplicates) {
        report.detail += "; duplicates_merged=" + std::to_string(n_duplicates);
    }
    return report;
}

Json CrossValidationReport::to_dict() const {
    Json out = Json::object();
    out["method"] = method;
    out["scheme"] = scheme;
    out["k"] = k;
    out["metrics"] = metrics.to_dict();
    out["folds"] = folds;
    out["engine"] = engine;
    out["detail"] = detail;
    return out;
}

std::pair<Json, EvaluationMetrics> surface_residuals(
    const Json& points, const std::vector<double>& grid_x,
    const std::vector<double>& grid_y, const std::vector<double>& grid_z) {
    Json records = Json::array();
    std::vector<double> observed;
    std::vector<double> predicted;
    for (const Json& pt : points) {
        const double px = require_number(pt, "x");
        const double py = require_number(pt, "y");
        const double pv = value_or_nan(pt);
        const std::optional<double> sampled =
            bilinear_sample_grid(grid_z, grid_x, grid_y, px, py);
        if (!sampled) continue;
        observed.push_back(pv);
        predicted.push_back(*sampled);
        Json record = Json::object();
        record["x"] = px;
        record["y"] = py;
        record["value"] = pv;
        record["predicted"] = *sampled;
        record["residual"] = pv - *sampled;
        records.push_back(std::move(record));
    }
    return {std::move(records), EvaluationMetrics::from_arrays(observed, predicted)};
}

Json residual_features(const Json& residuals) {
    Json out = Json::array();
    int i = 0;
    for (const Json& r : residuals) {
        Json feature = Json::object();
        feature["type"] = "Feature";
        feature["id"] = "residual_" + std::to_string(i);
        Json geometry = Json::object();
        geometry["type"] = "Point";
        Json coordinates = Json::array();
        coordinates.push_back(r.at("x").get<double>());
        coordinates.push_back(r.at("y").get<double>());
        geometry["coordinates"] = std::move(coordinates);
        Json properties = Json::object();
        properties["value"] = r.at("value").get<double>();
        properties["predicted"] = r.at("predicted").get<double>();
        properties["residual"] = r.at("residual").get<double>();
        feature["geometry"] = std::move(geometry);
        feature["properties"] = std::move(properties);
        out.push_back(std::move(feature));
        ++i;
    }
    return out;
}

RecommendationContext validate_recommendation_context(
    const std::optional<std::string>& unit,
    const std::optional<std::string>& crs, CrsValidator crs_valid) {
    RecommendationContext context;
    if (!unit || detail::python_strip(*unit).empty()) {
        context.gate = "unit_unknown";
        return context;
    }
    std::string unit_norm = detail::python_strip(*unit);
    std::transform(unit_norm.begin(), unit_norm.end(), unit_norm.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    static const std::set<std::string> kKnownUnits = {
        "m", "米", "ft", "feet", "英尺", "%", "percent", "ratio",
        "dimensionless", "v/v", "g/cm3", "api", "us/cm", "md", "1",
    };
    if (!kKnownUnits.count(unit_norm)) {
        context.warnings.push_back(
            "unrecognized unit " + detail::python_repr_string(*unit) +
            " — treated as declared-unknown");
        context.gate = "unit_unknown";
        return context;
    }
    if (crs && !detail::python_strip(*crs).empty()) {
        const bool valid =
            crs_valid != nullptr ? crs_valid(detail::python_strip(*crs)) : false;
        if (!valid) {
            context.gate = "crs_invalid";
            return context;
        }
    }
    return context;
}

std::pair<Json, std::optional<std::string>> adjudicate_recommendation(
    Json entries, const std::optional<std::string>& gate,
    const std::optional<std::vector<std::string>>& unknown_constraints,
    std::string_view scheme_caveat) {
    std::optional<std::string> gate_rationale;
    if (gate) {
        if (*gate == "unit_unknown") {
            gate_rationale =
                "no recommendation: measurement unit is unknown — cross-method "
                "ranking on ununitized data is not a defensible comparison";
        } else if (*gate == "crs_invalid") {
            gate_rationale =
                "no recommendation: declared CRS is invalid/unparseable — "
                "distances and folds cannot be trusted";
        }
    }
    if (!gate_rationale && unknown_constraints && !unknown_constraints->empty()) {
        // Python repr list formatting: ['a', 'b'] (repr switches to double
        // quotes for elements containing ' — python_repr_string mirrors it).
        std::string joined = "[";
        for (std::size_t i = 0; i < unknown_constraints->size(); ++i) {
            if (i) joined += ", ";
            joined += detail::python_repr_string((*unknown_constraints)[i]);
        }
        joined += "]";
        gate_rationale =
            "no recommendation: requested constraint(s) " + joined +
            " are unknown to the capability matrix — no method can be "
            "certified as honoring them";
    }

    auto rmse_of = [](const Json& entry) {
        const auto metrics = entry.find("metrics");
        if (metrics == entry.end() || metrics->is_null()) {
            return std::numeric_limits<double>::infinity();
        }
        const auto rmse = metrics->find("rmse");
        if (rmse == metrics->end() || rmse->is_null()) {
            return std::numeric_limits<double>::infinity();
        }
        return rmse->get<double>();
    };
    auto has_unsupported = [](const Json& entry) {
        const auto warnings = entry.find("capability_warnings");
        if (warnings == entry.end() || !warnings->is_array()) return false;
        for (const Json& w : *warnings) {
            if (w.is_string() && w.get<std::string>().find(":unsupported:") !=
                                     std::string::npos) {
                return true;
            }
        }
        return false;
    };
    auto eligible = [&](const Json& entry) {
        const auto metrics = entry.find("metrics");
        return metrics != entry.end() && !metrics->is_null() &&
               !has_unsupported(entry);
    };

    std::optional<std::string> best;
    double best_score = std::numeric_limits<double>::infinity();
    for (const Json& entry : entries) {
        if (!eligible(entry)) continue;
        const double score = rmse_of(entry);
        if (!best || score < best_score) {  // first minimal element wins (Python min)
            best = entry["method"].get<std::string>();
            best_score = score;
        }
    }

    const std::string caveat =
        scheme_caveat.empty() ? std::string()
                              : "; caveat: " + std::string(scheme_caveat);
    for (Json& entry : entries) {
        const auto metrics = entry.find("metrics");
        if (metrics == entry.end() || metrics->is_null()) continue;
        const std::string method = entry["method"].get<std::string>();
        if (gate_rationale) {
            entry["recommended"] = false;
            entry["rationale"] = *gate_rationale;
        } else if (has_unsupported(entry)) {
            entry["recommended"] = false;
            entry["rationale"] =
                "disqualified: requested constraints ignored by this method "
                "(capability matrix) — metrics alone cannot justify it";
        } else if (best && method == *best) {
            entry["recommended"] = true;
            entry["rationale"] =
                "best cross-validated RMSE among methods that honor every "
                "requested constraint" + caveat;
        } else {
            entry["recommended"] = false;
            entry["rationale"] = "higher cross-validated RMSE than " +
                                 detail::python_repr_string(
                                     best.value_or(std::string())) +
                                 caveat;
        }
    }
    std::optional<std::string> recommended_method;
    if (!gate_rationale) {
        for (const Json& entry : entries) {
            const auto recommended = entry.find("recommended");
            if (recommended != entry.end() && recommended->is_boolean() &&
                recommended->get<bool>()) {
                recommended_method = entry["method"].get<std::string>();
                break;
            }
        }
    }
    return {std::move(entries), recommended_method};
}

}  // namespace pwb::factor_host
