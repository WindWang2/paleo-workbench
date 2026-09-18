// pwb::science_service — well science service implementation.

#include <pwb/science_service/well_service.hpp>

#include <pwb/well_science/curve_ops.hpp>

#include <algorithm>
#include <cmath>
#include <set>
#include <utility>

#include "support.hpp"

namespace pwb::science_service {

using pwb::domain::Json;

namespace {

bool get_number(const Json& params, const std::string& key,
                              double& out) {
    if (!params.is_object() || !params.contains(key)) {
        return false;
    }
    const Json& v = params.at(key);
    if (!v.is_number()) {
        return false;
    }
    out = v.get<double>();
    return true;
}

bool get_int(const Json& params, const std::string& key,
                           long long& out) {
    double v = 0.0;
    if (!get_number(params, key, v)) {
        return false;
    }
    out = static_cast<long long>(v);
    return true;
}

Json finite_safe_array(const std::vector<double>& values,
                       std::size_t limit) {
    Json arr = Json::array();
    const std::size_t n = std::min(values.size(), limit);
    for (std::size_t i = 0; i < n; ++i) {
        arr.push_back(std::isfinite(values[i]) ? Json(values[i]) : Json(nullptr));
    }
    return arr;
}

}  // namespace

// ---------------------------------------------------------------------------
// CurveOperationService
// ---------------------------------------------------------------------------

CurveOperationService::CurveOperationService(std::string build_identity,
                                             ResourceLimits limits)
    : build_identity_(std::move(build_identity)), limits_(limits) {}

science::Result<CurveOperationResult> CurveOperationService::run(
    const CurveOperationRequest& request, science::ProgressSink progress,
    std::stop_token stop) {
    if (request.values.size() > limits_.max_curve_samples) {
        return detail::make_error(
            limit_code("curve_samples"),
            "curve length " + std::to_string(request.values.size())
                + " exceeds limit " + std::to_string(limits_.max_curve_samples));
    }
    // Scope discipline (mirrors curve_interpretation's CURVE_OPERATIONS
    // table): depth-scoped operations need the axis; curve ops need values.
    const bool needs_depth = request.operation == "resample"
                             || request.operation == "depth_shift";
    if (needs_depth) {
        if (request.depth.size() != request.values.size()) {
            return detail::make_error(
                "well.curve_mismatch",
                "operation '" + request.operation + "' requires depth and "
                 "values of equal length ("
                 + std::to_string(request.depth.size()) + " vs "
                 + std::to_string(request.values.size()) + ")");
        }
    } else if (!request.depth.empty()
               && request.depth.size() != request.values.size()) {
        return detail::make_error(
            "well.curve_mismatch",
            "depth and values lengths differ ("
                + std::to_string(request.depth.size()) + " vs "
                + std::to_string(request.values.size()) + ")");
    }
    if (detail::stage_guard(stop, progress, 0.1, "validate")) {
        return science::TaskCancelled{"validate"};
    }

    const auto& ops = pwb::well_science::curve_operations();
    const auto info_it = std::find_if(
        ops.begin(), ops.end(),
        [&request](const pwb::well_science::CurveOperationInfo& info) {
            return info.name == request.operation;
        });    if (info_it == ops.end()) {
        std::string known;
        for (const auto& info : ops) {
            if (!known.empty()) known += ", ";
            known += std::string(info.name);
        }
        return detail::make_error(
            "well.unknown_operation",
            "unknown curve operation '" + request.operation
                + "'; registered: " + known);
    }
    // Required-parameter check (the table's required_params list). A param
    // counts as supplied when it is in the params object OR carried by the
    // typed request fields (unit_conversion reads from_unit/to_unit fields).
    for (const auto& required : info_it->required_params) {
        const std::string name(required);
        const bool in_params =
            request.params.is_object() && request.params.contains(name);
        bool in_typed = false;
        if (name == "from_unit") in_typed = request.from_unit.has_value();
        else if (name == "to_unit") in_typed = request.to_unit.has_value();
        else if (name == "axis_unit") in_typed = request.axis_unit.has_value();
        else in_typed = false;
        if (!in_params && !in_typed) {
            return detail::make_error(
                "well.missing_param",
                "operation '" + request.operation + "' requires parameter '"
                    + name + "'");
        }
    }

    std::vector<double> out_depth = request.depth;
    std::vector<double> out_values;
    Json report = Json::object();
    const std::string& op = request.operation;

    // Dispatch returns an int so catch_kernel's Result<T> has an object type
    // (std::variant<void> is not instantiable).
    auto dispatch = [&]() -> int {
        if (op == "smooth") {
            int window = 5;
            long long w = 0;
            if (get_int(request.params, "window", w)) window = static_cast<int>(w);
            out_values = pwb::well_science::moving_average(request.values, window);
        } else if (op == "median_filter") {
            int window = 5;
            long long w = 0;
            if (get_int(request.params, "window", w)) window = static_cast<int>(w);
            out_values = pwb::well_science::median_filter_curve(request.values, window);
        } else if (op == "normalize") {
            std::string method = request.params.value("method", "zscore");
            out_values = pwb::well_science::normalize_curve(request.values, method);
        } else if (op == "clip_outliers") {
            std::optional<double> lower, upper, percentile;
            double v = 0.0;
            if (get_number(request.params, "lower", v)) lower = v;
            if (get_number(request.params, "upper", v)) upper = v;
            if (get_number(request.params, "percentile", v)) percentile = v;
            out_values =
                pwb::well_science::clip_outliers(request.values, lower, upper, percentile);
        } else if (op == "unit_conversion") {
            out_values = pwb::well_science::convert_values(
                request.values, request.from_unit, request.to_unit);
            report["factor"] =
                pwb::well_science::conversion_factor(request.from_unit, request.to_unit);
        } else if (op == "resample") {
            double step = 0.0;
            get_number(request.params, "step", step);
            out_depth = pwb::well_science::resample_axis(request.depth, step);
            out_values = pwb::well_science::interp_gap_preserving(
                out_depth, request.depth, request.values);
            report["step"] = step;
            report["n_output"] = static_cast<std::uint64_t>(out_depth.size());
        } else if (op == "depth_shift") {
            double delta_m = 0.0;
            get_number(request.params, "delta_m", delta_m);
            out_depth = pwb::well_science::depth_shift(request.depth, delta_m,
                                                       request.axis_unit);
            out_values = request.values;
            report["delta_m"] = delta_m;
        } else if (op == "despike") {
            double threshold_sigma = 3.0;
            int window = 3;
            double v = 0.0;
            long long w = 0;
            if (get_number(request.params, "threshold_sigma", v)) {
                threshold_sigma = v;
            }
            if (get_int(request.params, "window", w)) window = static_cast<int>(w);
            out_values = pwb::well_science::despike(request.values,
                                                    threshold_sigma, window);
        } else if (op == "baseline_shift") {
            double delta = 0.0;
            get_number(request.params, "delta", delta);
            out_values = pwb::well_science::baseline_shift(request.values, delta);
        } else {
            // Registered in the table but not yet dispatched by this
            // service (depth_unit_normalize / derive_curve): refuse
            // honestly instead of half-running.
            throw std::runtime_error(
                "operation '" + op
                + "' is registered but not dispatched by the science "
                  "service yet");
        }
        return 0;
    };
    auto outcome = detail::catch_kernel<int>("well.curve_operation", dispatch);
    if (outcome.is_error()) {
        return outcome.error();
    }
    if (detail::stage_guard(stop, progress, 0.8, "compute")) {
        return science::TaskCancelled{"compute"};
    }

    ScienceEnvelope envelope;
    envelope.result_type = "curve_operation";
    envelope.units = request.to_unit.value_or(request.from_unit.value_or(""));

    Json payload = Json::object();
    payload["operation"] = op;
    payload["scope"] = std::string(info_it->scope);
    payload["params"] = request.params;
    payload["n_input"] = static_cast<std::uint64_t>(request.values.size());
    payload["n_output"] = static_cast<std::uint64_t>(out_values.size());
    if (!out_depth.empty() || needs_depth) {
        payload["depth"] =
            finite_safe_array(out_depth, limits_.max_envelope_samples);
    }
    payload["values"] = finite_safe_array(out_values, limits_.max_envelope_samples);
    if (out_values.size() > limits_.max_envelope_samples) {
        envelope.diagnostics.push_back(Json{
            {"code", "envelope.truncated"},
            {"severity", "warning"},
            {"message", "curve truncated to "
                            + std::to_string(limits_.max_envelope_samples)
                            + " samples in envelope"},
        });
    }
    payload["report"] = std::move(report);
    envelope.payload = std::move(payload);

    Json provenance = Json::object();
    provenance["algorithm_id"] = "well.curve_operation";
    provenance["algorithm_version"] = "1.0.0";
    provenance["build_identity"] = build_identity_;
    provenance["operation"] = op;
    envelope.provenance = std::move(provenance);
    envelope.compute_fingerprint();

    CurveOperationResult result;
    result.envelope = std::move(envelope);
    result.depth = std::move(out_depth);
    result.values = std::move(out_values);
    detail::stage_guard(stop, progress, 1.0, "envelope");
    return result;
}

// ---------------------------------------------------------------------------
// LogMatchService
// ---------------------------------------------------------------------------

LogMatchService::LogMatchService(std::string build_identity,
                                 ResourceLimits limits)
    : build_identity_(std::move(build_identity)), limits_(limits) {}

science::Result<LogMatchResult> LogMatchService::run(
    const LogMatchRequest& request, science::ProgressSink progress,
    std::stop_token stop) {
    if (request.reference.size() > limits_.max_curve_samples
        || request.target.size() > limits_.max_curve_samples) {
        return detail::make_error(
            limit_code("curve_samples"),
            "curve length exceeds limit "
                + std::to_string(limits_.max_curve_samples));
    }
    if (detail::stage_guard(stop, progress, 0.1, "validate")) {
        return science::TaskCancelled{"validate"};
    }

    // Production decimation policy (DTWLogMatcher): when n*m would exceed the
    // cost-cell budget, min-max downsample BOTH curves by the same bin size.
    std::vector<double> ref = request.reference;
    std::vector<double> target = request.target;
    bool decimated = false;
    std::int64_t bin_size = 1;
    const std::int64_t cells = static_cast<std::int64_t>(ref.size())
                               * static_cast<std::int64_t>(target.size());
    if (cells > limits_.max_dtw_cost_cells && !ref.empty() && !target.empty()) {
        const double ratio = static_cast<double>(cells)
                             / static_cast<double>(limits_.max_dtw_cost_cells);
        bin_size = static_cast<std::int64_t>(std::ceil(std::sqrt(ratio)));
        if (bin_size < 1) bin_size = 1;
        ref = pwb::well_science::min_max_downsample(ref, bin_size).values;
        target = pwb::well_science::min_max_downsample(target, bin_size).values;
        decimated = true;
    }
    if (detail::stage_guard(stop, progress, 0.4, "decimate")) {
        return science::TaskCancelled{"decimate"};
    }

    auto outcome = detail::catch_kernel<pwb::well_science::AlignmentResult>(
        "well.log_match", [&] {
            return pwb::well_science::match_curves(ref, target, request.window);
        });
    if (outcome.is_error()) {
        return outcome.error();
    }

    ScienceEnvelope envelope;
    envelope.result_type = "log_match";
    Json payload = Json::object();
    payload["cost"] = std::isfinite(outcome.value().cost)
                          ? Json(outcome.value().cost)
                          : Json(nullptr);
    payload["n_reference"] = static_cast<std::uint64_t>(request.reference.size());
    payload["n_target"] = static_cast<std::uint64_t>(request.target.size());
    payload["decimated"] = decimated;
    payload["bin_size"] = bin_size;
    payload["aligned"] = !outcome.value().path_ref.empty();
    if (outcome.value().path_ref.size() <= limits_.max_envelope_samples) {
        Json path_ref = Json::array();
        for (std::int64_t v : outcome.value().path_ref) path_ref.push_back(v);
        Json path_target = Json::array();
        for (std::int64_t v : outcome.value().path_target) path_target.push_back(v);
        payload["path_reference"] = std::move(path_ref);
        payload["path_target"] = std::move(path_target);
    } else {
        payload["path_lengths"] = Json{
            static_cast<std::uint64_t>(outcome.value().path_ref.size()),
            static_cast<std::uint64_t>(outcome.value().path_target.size())};
    }
    envelope.payload = std::move(payload);
    Json provenance = Json::object();
    provenance["algorithm_id"] = "well.log_match";
    provenance["algorithm_version"] = "1.0.0";
    provenance["build_identity"] = build_identity_;
    provenance["window"] = request.window ? Json(*request.window) : Json(nullptr);
    envelope.provenance = std::move(provenance);
    envelope.compute_fingerprint();

    LogMatchResult result;
    result.envelope = std::move(envelope);
    result.cost = outcome.value().cost;
    result.path_reference = std::move(outcome.value().path_ref);
    result.path_target = std::move(outcome.value().path_target);
    result.decimated = decimated;
    result.bin_size = bin_size;
    detail::stage_guard(stop, progress, 1.0, "envelope");
    return result;
}

std::int64_t LogMatchService::transfer_top(const LogMatchResult& result,
                                           std::int64_t ref_top_idx) {
    return pwb::well_science::transfer_top_index(ref_top_idx,
                                                 result.path_reference,
                                                 result.path_target);
}

}  // namespace pwb::science_service
