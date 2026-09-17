#include <pwb/factor_host/fingerprint.hpp>

#include "semantics.hpp"

#include <pwb/domain/sha256.hpp>
#include <pwb/factor_host/canonical_json.hpp>

#include <cmath>
#include <filesystem>

namespace pwb::factor_host {

namespace {

// Raw Python float() coercion WITHOUT the finite filter and WITHOUT -0.0
// normalization: polylines / direction coordinates keep inf, nan and -0.0
// exactly like the Python reference (only _finite_float normalizes).
// nullopt = Python float() raised.
std::optional<double> raw_float(const Json& value) {
    if (value.is_number()) return value.get<double>();
    if (value.is_boolean()) return value.get<bool>() ? 1.0 : 0.0;
    if (value.is_string()) {
        return python_float_from_string(value.get<std::string>());
    }
    return std::nullopt;
}

std::string strip(const std::string& text) {
    return detail::python_strip(text);
}

// str() of the qc_flag JSON scalar, or nullopt when the key is absent/null.
std::optional<std::string> str_field(const Json& point, const char* key) {
    const auto it = point.find(key);
    if (it == point.end() || it->is_null()) return std::nullopt;
    return python_str_scalar(*it);
}

}  // namespace

std::string stable_sha256(const Json& payload) {
    return pwb::domain::Sha256::of_bytes(canonical_encode(payload));
}

std::optional<double> finite_double(const Json& value) {
    std::optional<double> number;
    if (value.is_number()) {
        number = value.get<double>();
    } else if (value.is_boolean()) {
        number = value.get<bool>() ? 1.0 : 0.0;
    } else if (value.is_string()) {
        number = python_float_from_string(value.get<std::string>());
        if (!number) return std::nullopt;
    } else {
        return std::nullopt;
    }
    if (!std::isfinite(*number)) return std::nullopt;
    return *number + 0.0;  // normalize -0.0 → 0.0
}

Json extract_sample_records(const Json& sample_points) {
    Json out = Json::array();
    if (!sample_points.is_array()) return out;
    for (const Json& pt : sample_points) {
        if (!pt.is_object()) continue;
        std::optional<double> x;
        std::optional<double> y;
        const bool has_xy = pt.contains("x") && pt.contains("y");
        const bool has_lnglat = pt.contains("lng") && pt.contains("lat");
        if (has_xy) {
            x = finite_double(pt.at("x"));
            y = finite_double(pt.at("y"));
        } else if (has_lnglat) {
            x = finite_double(pt.at("lng"));
            y = finite_double(pt.at("lat"));
        } else {
            continue;
        }
        const Json* z_raw = nullptr;
        if (pt.contains("value")) z_raw = &pt.at("value");
        else if (pt.contains("z")) z_raw = &pt.at("z");
        else if (pt.contains("v")) z_raw = &pt.at("v");
        const std::optional<double> z =
            z_raw != nullptr ? finite_double(*z_raw) : std::nullopt;
        if (!x || !y || !z) continue;
        Json record = Json::object();
        record["x"] = *x;
        record["y"] = *y;
        record["z"] = *z;
        for (const char* key : {"q", "b_i"}) {
            const auto it = pt.find(key);
            if (it != pt.end() && !it->is_null()) {
                std::optional<double> extra;
                if (it->is_number()) {
                    extra = it->get<double>();
                } else if (it->is_boolean()) {
                    extra = it->get<bool>() ? 1.0 : 0.0;
                } else if (it->is_string()) {
                    extra = python_float_from_string(it->get<std::string>());
                }
                // Python float() may yield inf/nan here — no finite filter
                // on the directional-engine extras (H11 covers them as-is).
                if (extra) record[key] = *extra;
            }
        }
        if (auto qc = str_field(pt, "qc_flag")) {
            record["qc_flag"] = *qc;
        }
        out.push_back(std::move(record));
    }
    return out;
}

const Json& method_backend_table() {
    static const Json table = [] {
        Json t = Json::object();
        t["克里金"] = "kriging";
        t["克里金(MVP·线性)"] = "kriging";
        t["IDW"] = "idw";
        t["idw"] = "idw";
        t["样条"] = "cubic";
        t["方向趋势"] = "directional";
        t["约束IDW"] = kConstrainedIdwLabel;
        t["mock"] = "idw";
        t["kriging"] = "kriging";
        t["directional"] = "directional";
        t[kConstrainedIdwLabel] = kConstrainedIdwLabel;
        return t;
    }();
    return table;
}

std::string resolve_backend(const std::string& method) {
    const Json& table = method_backend_table();
    const auto it = table.find(method);
    return it != table.end() ? it->get<std::string>() : std::string("idw");
}

bool backend_uses_breaks(std::string_view backend) {
    return backend == "idw" || backend == kConstrainedIdwLabel;
}

bool backend_uses_directions(std::string_view backend) {
    return backend == "directional" || backend == kConstrainedIdwLabel;
}

bool backend_uses_power(std::string_view backend) {
    return backend == "idw" || backend == kConstrainedIdwLabel;
}

bool backend_uses_anisotropy(std::string_view backend) {
    return backend == "directional";
}

Json normalize_polylines(const Json& polylines) {
    Json out = Json::array();
    if (!polylines.is_array()) return out;
    for (const Json& poly : polylines) {
        if (!poly.is_array()) continue;
        Json pts = Json::array();
        for (const Json& p : poly) {
            // Python float(p[0]) — non-finite and -0.0 ride along; only
            // conversion failures (and structurally wrong points) skip.
            if (!p.is_array() || p.size() < 2) continue;
            std::optional<double> px = raw_float(p.at(0));
            std::optional<double> py = raw_float(p.at(1));
            if (!px || !py) continue;
            Json pair = Json::array();
            pair.push_back(*px);
            pair.push_back(*py);
            pts.push_back(std::move(pair));
        }
        if (pts.size() >= 2) out.push_back(std::move(pts));
    }
    return out;
}

Json normalize_direction_params(const Json& params) {
    Json out = Json::array();
    if (!params.is_array()) return out;
    for (const Json& raw : params) {
        if (!raw.is_object()) continue;
        const auto coords = raw.find("coordinates");
        Json pts = Json::array();
        if (coords != raw.end() && coords->is_array()) {
            for (const Json& p : *coords) {
                if (!p.is_array() || p.size() < 2) continue;
                std::optional<double> px = raw_float(p.at(0));
                std::optional<double> py = raw_float(p.at(1));
                if (!px || !py) continue;
                Json pair = Json::array();
                pair.push_back(*px);
                pair.push_back(*py);
                pts.push_back(std::move(pair));
            }
        }
        if (pts.size() < 2) continue;
        Json entry = Json::object();
        // Python str(raw.get("id") or ""): falsy ids (0 / false / "" / [])
        // fall back to "".
        const auto id_it = raw.find("id");
        entry["id"] =
            (id_it != raw.end() && detail::json_truthy(&*id_it))
                ? python_str_scalar(*id_it)
                : std::string();
        entry["coordinates"] = std::move(pts);
        for (const char* key : {"semi_major", "semi_minor", "azimuth_deg"}) {
            const auto it = raw.find(key);
            if (it != raw.end() && !it->is_null()) {
                if (auto parsed = raw_float(*it)) {
                    entry[key] = *parsed;
                }
            }
        }
        out.push_back(std::move(entry));
    }
    return out;
}

Json FactorFingerprints::to_dict() const {
    Json out = Json::object();
    out["schema_version"] = schema_version;
    out["geometry_fingerprint"] = geometry;
    out["values_fingerprint"] = values;
    out["algorithm_fingerprint"] = algorithm;
    out["constraints_fingerprint"] = constraints;
    out["result_fingerprint"] = result;
    out["backend"] = backend;
    return out;
}

FactorFingerprints build_factor_fingerprints(const BuildFingerprintsArgs& args) {
    const std::string backend = resolve_backend(args.method);
    const Json empty_array = Json::array();
    const Json samples = extract_sample_records(
        args.sample_points != nullptr ? *args.sample_points : empty_array);

    const bool uses_breaks = backend_uses_breaks(backend);
    const bool uses_directions = backend_uses_directions(backend);
    Json breaks = uses_breaks
        ? normalize_polylines(args.fault_polylines != nullptr
                                  ? *args.fault_polylines : empty_array)
        : Json::array();
    Json dirs = uses_directions
        ? normalize_direction_params(args.direction_params != nullptr
                                         ? *args.direction_params : empty_array)
        : Json::array();

    Json xy = Json::array();
    Json zz = Json::array();
    for (const Json& s : samples) {
        Json pair = Json::array();
        pair.push_back(s.at("x").get<double>());
        pair.push_back(s.at("y").get<double>());
        xy.push_back(std::move(pair));
        zz.push_back(s.at("z").get<double>());
    }

    Json geometry_payload = Json::object();
    geometry_payload["schema"] = kFingerprintSchemaVersion;
    geometry_payload["xy"] = std::move(xy);
    geometry_payload["grid_n"] = args.grid_n;
    geometry_payload["breaks"] = std::move(breaks);
    geometry_payload["target_horizon"] = strip(args.target_horizon);

    Json values_payload = Json::object();
    values_payload["schema"] = kFingerprintSchemaVersion;
    values_payload["z"] = std::move(zz);
    if (backend == "directional") {
        for (const char* key : {"q", "b_i", "qc_flag"}) {
            Json column = Json::array();
            for (const Json& s : samples) {
                const auto it = s.find(key);
                if (it != s.end()) column.push_back(*it);
                else column.push_back(Json());
            }
            values_payload[key] = std::move(column);
        }
    }

    Json algorithm_payload = Json::object();
    algorithm_payload["schema"] = kFingerprintSchemaVersion;
    algorithm_payload["method"] = args.method;
    algorithm_payload["backend"] = backend;
    algorithm_payload["generator_version"] = args.generator_version;
    if (args.duplicate_policy.has_value()) {
        algorithm_payload["duplicate_policy"] = *args.duplicate_policy;
    }
    if (backend_uses_power(backend)) {
        algorithm_payload["power"] = args.power;
    }
    if (backend_uses_anisotropy(backend)) {
        algorithm_payload["azimuth_deg"] = args.azimuth_deg;
        algorithm_payload["semi_major"] = args.semi_major;
        algorithm_payload["semi_minor"] = args.semi_minor;
    }

    Json constraints_payload = Json::object();
    constraints_payload["schema"] = kFingerprintSchemaVersion;
    constraints_payload["directions"] = std::move(dirs);
    constraints_payload["constrained"] = backend == kConstrainedIdwLabel;

    FactorFingerprints fps;
    fps.geometry = stable_sha256(geometry_payload);
    fps.values = stable_sha256(values_payload);
    fps.algorithm = stable_sha256(algorithm_payload);
    fps.constraints = stable_sha256(constraints_payload);
    Json result_payload = Json::object();
    result_payload["schema"] = kFingerprintSchemaVersion;
    result_payload["geometry"] = fps.geometry;
    result_payload["values"] = fps.values;
    result_payload["algorithm"] = fps.algorithm;
    result_payload["constraints"] = fps.constraints;
    result_payload["crs"] = args.crs;
    fps.result = stable_sha256(result_payload);
    fps.backend = backend;
    return fps;
}

std::string to_string(FactorDirtyState state) {
    switch (state) {
        case FactorDirtyState::CLEAN: return "CLEAN";
        case FactorDirtyState::DIRTY_VALUES: return "DIRTY_VALUES";
        case FactorDirtyState::DIRTY_GEOMETRY: return "DIRTY_GEOMETRY";
        case FactorDirtyState::DIRTY_ALGORITHM: return "DIRTY_ALGORITHM";
        case FactorDirtyState::DIRTY_CONSTRAINTS: return "DIRTY_CONSTRAINTS";
        case FactorDirtyState::MISSING_OUTPUT: return "MISSING_OUTPUT";
        case FactorDirtyState::UNKNOWN: return "UNKNOWN";
    }
    return "UNKNOWN";
}

std::optional<FactorFingerprints> stored_fingerprints_from_task(
    const FactorTaskView& task) {
    const Json empty = Json::object();
    const Json& params = task.parameters != nullptr ? *task.parameters : empty;
    const Json& meta = task.grid_metadata != nullptr ? *task.grid_metadata : empty;
    const auto algo_it = meta.find("algorithm_parameters");
    const Json& algo = algo_it != meta.end() && algo_it->is_object() ? *algo_it : empty;

    auto get = [&](const char* key) -> std::optional<std::string> {
        for (const Json* bag : {&params, &meta, &algo}) {
            const auto it = bag->find(key);
            if (it != bag->end() && it->is_string() && !it->get<std::string>().empty()) {
                return it->get<std::string>();
            }
        }
        return std::nullopt;
    };

    auto result = get("result_fingerprint");
    if (!result && !task.input_snapshot_hash.empty()) {
        result = task.input_snapshot_hash;
    }
    auto geometry = get("geometry_fingerprint");
    auto values = get("values_fingerprint");
    auto algorithm = get("algorithm_fingerprint");
    auto constraints = get("constraints_fingerprint");
    if (!result || !geometry || !values || !algorithm || !constraints) {
        return std::nullopt;
    }
    FactorFingerprints fps;
    fps.geometry = *geometry;
    fps.values = *values;
    fps.algorithm = *algorithm;
    fps.constraints = *constraints;
    fps.result = *result;
    auto backend = get("backend");
    if (backend) {
        fps.backend = *backend;
    } else {
        // Python: str(_get("backend") or params.get("interp_backend") or "idw")
        // — a truthy non-string interp_backend is str()-ed, not dropped.
        const auto interp = params.find("interp_backend");
        if (interp != params.end() && detail::json_truthy(&*interp)) {
            fps.backend = python_str_scalar(*interp);
        }
    }
    return fps;
}

bool task_has_numerical_output(const FactorTaskView& task) {
    if (task.has_live_factor_grid) return true;
    if (!task.grid_artifact_path.empty()) {
        std::error_code ec;
        return std::filesystem::is_regular_file(task.grid_artifact_path, ec);
    }
    const Json empty = Json::object();
    const Json& params = task.parameters != nullptr ? *task.parameters : empty;
    const auto it = params.find("grid_z");
    // Python: params.get("grid_z") is not None — ANY non-null value (even
    // [] or 0) counts as a live inline grid here (truthiness is only used
    // by the classify inline-grid branch below).
    return it != params.end() && !it->is_null();
}

FactorDirtyState classify_factor_recompute(const FactorTaskView& task,
                                           const FactorFingerprints& current,
                                           bool force) {
    if (force) return FactorDirtyState::UNKNOWN;
    const Json empty = Json::object();
    const Json& params = task.parameters != nullptr ? *task.parameters : empty;
    const bool has_output = task_has_numerical_output(task);
    if (!has_output) {
        const auto grid_z = params.find("grid_z");
        const bool inline_grid =
            grid_z != params.end() && detail::json_truthy(&*grid_z);
        if (task.status != "complete" && !inline_grid) {
            return FactorDirtyState::MISSING_OUTPUT;
        }
        if (!task.grid_artifact_path.empty()) {
            return FactorDirtyState::MISSING_OUTPUT;
        }
        if (task.status != "complete") {
            return FactorDirtyState::MISSING_OUTPUT;
        }
    }

    const std::optional<FactorFingerprints> stored =
        stored_fingerprints_from_task(task);
    if (!stored) {
        if (!task.input_snapshot_hash.empty() &&
            task.input_snapshot_hash == current.result && has_output) {
            return FactorDirtyState::CLEAN;
        }
        if (has_output && task.status == "complete") {
            return FactorDirtyState::UNKNOWN;
        }
        return FactorDirtyState::MISSING_OUTPUT;
    }

    if (stored->result == current.result && has_output) {
        return FactorDirtyState::CLEAN;
    }
    if (stored->geometry != current.geometry) {
        return FactorDirtyState::DIRTY_GEOMETRY;
    }
    if (stored->values != current.values) {
        return FactorDirtyState::DIRTY_VALUES;
    }
    if (stored->algorithm != current.algorithm) {
        return FactorDirtyState::DIRTY_ALGORITHM;
    }
    if (stored->constraints != current.constraints) {
        return FactorDirtyState::DIRTY_CONSTRAINTS;
    }
    return FactorDirtyState::DIRTY_ALGORITHM;  // CRS or schema drift only
}

}  // namespace pwb::factor_host
