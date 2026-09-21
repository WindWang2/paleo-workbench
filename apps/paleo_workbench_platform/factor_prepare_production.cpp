// V14-CONSTRAINT-FACTOR — production binding of the factor-prepare
// scheduler to the native scientific kernels. See
// docs/development/v14-constraint-factor/02-architecture.md for the
// composition contract and honesty rules.
//
// Numeric authorities (single implementations, never duplicated here):
//   * duplicate normalization  — mapping::normalize_factor_samples
//   * plain interpolation      — mapping::interpolate_factor (idw|kriging)
//   * constrained interpolation— mapping::constrained_idw::generate_constrained_idw
//   * fingerprints             — factor_host::build_factor_fingerprints /
//                                classify_factor_recompute
//   * plan group keys          — factor_host::PlanKey::digest
//   * envelope codec           — mapping::factor_grid_io
// Task-record mutation (the _attach_result_to_task contract) is implemented
// here against the task's source JSON — the commit replaces the live task
// wholesale so unknown fields survive.

#include "factor_prepare_production.hpp"

#include <pwb/factor_host/evaluation.hpp>
#include <pwb/factor_host/fingerprint.hpp>
#include <pwb/factor_host/interop.hpp>
#include <pwb/factor_host/plan.hpp>
#include <pwb/mapping/constrained_idw.hpp>
#include <pwb/mapping/factor_grid_io.hpp>
#include <pwb/mapping/interpolator.hpp>
#include <pwb/mapping/sample_normalization.hpp>
#include <pwb/ui_workers/worker_common.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <ctime>
#include <fstream>
#include <iomanip>
#include <limits>
#include <list>
#include <map>
#include <mutex>
#include <random>
#include <sstream>
#include <stdexcept>
#include <thread>
#include <unordered_map>

namespace pwb::factor_production {

using pwb::domain::Json;
using ui_workers::FactorDirtyState;
using ui_workers::FactorPrepareSeams;
using ui_workers::FactorTaskSlice;

namespace {

// ------------------------------------------------------------------ misc --

[[nodiscard]] std::string range_label(double lo, double hi) {
    // Python f"{min:.2f} – {max:.2f}" — two fixed decimals, en dash.
    std::ostringstream out;
    out << std::fixed << std::setprecision(2) << lo << " – " << hi;
    return out.str();
}
[[nodiscard]] std::string format_range(double lo, double hi) {
    return range_label(lo, hi);
}

[[nodiscard]] const Json* find_field(const Json& object,
                                      const std::string& key) {
    if (!object.is_object()) return nullptr;
    const auto it = object.find(key);
    return it == object.end() ? nullptr : &*it;
}

[[nodiscard]] Json* find_field(Json& object, const std::string& key) {
    if (!object.is_object()) return nullptr;
    const auto it = object.find(key);
    return it == object.end() ? nullptr : &*it;
}

[[nodiscard]] std::string field_str(const Json& object,
                                    const std::string& key,
                                    const std::string& fallback = "") {
    const Json* field = find_field(object, key);
    if (field == nullptr || !field->is_string()) return fallback;
    return field->get<std::string>();
}

[[nodiscard]] std::string new_id(const char* prefix) {
    // Python _id(): prefix + uuid4 hex[:12]. Deterministic-enough process
    // uniqueness via random_device seeded mt19937.
    static std::mutex mutex;
    static std::mt19937_64 rng(std::random_device{}());
    std::lock_guard<std::mutex> guard(mutex);
    std::ostringstream out;
    out << std::hex << std::setfill('0') << std::setw(16) << rng()
        << std::setw(16) << rng();
    const std::string hex = out.str();
    return std::string(prefix) + "_" + hex.substr(0, 12);
}

[[nodiscard]] std::string now_iso() {
    // Python _now_iso: datetime.now(timezone.utc).isoformat(timespec="seconds")
    const std::time_t now = std::time(nullptr);
    std::tm tm{};
    gmtime_r(&now, &tm);
    std::ostringstream out;
    out << std::put_time(&tm, "%Y-%m-%dT%H:%M:%S+00:00");
    return out.str();
}

// Python truthiness for a JSON value (parameters lookups).
[[nodiscard]] bool json_truthy(const Json& value) {
    if (value.is_null()) return false;
    if (value.is_boolean()) return value.get<bool>();
    if (value.is_number_integer()) return value.get<long long>() != 0;
    if (value.is_number()) return value.get<double>() != 0.0;
    if (value.is_string()) return !value.get<std::string>().empty();
    if (value.is_array() || value.is_object()) return !value.empty();
    return true;
}

[[nodiscard]] Json sample_points_to_json(const std::any& value) {
    // The slice loader stores sample_points as vector<map<string,any>>;
    // the synthetic seam uses the same convention.
    if (const auto* points =
            std::any_cast<std::vector<std::map<std::string, std::any>>>(
                &value)) {
        Json out = Json::array();
        for (const auto& point : *points) {
            Json entry = Json::object();
            for (const auto& [key, field] : point) {
                if (const auto* s = std::any_cast<std::string>(&field)) {
                    entry[key] = *s;
                } else if (const auto* d = std::any_cast<double>(&field)) {
                    entry[key] = *d;
                } else if (const auto* i = std::any_cast<int>(&field)) {
                    entry[key] = *i;
                } else if (const auto* b = std::any_cast<bool>(&field)) {
                    entry[key] = *b;
                } else if (const auto* j = std::any_cast<Json>(&field)) {
                    entry[key] = *j;
                }
                // Unrepresentable payloads are dropped (honest subset; the
                // loader below only produces string/double/int/bool).
            }
            out.push_back(std::move(entry));
        }
        return out;
    }
    if (const auto* points = std::any_cast<Json>(&value)) {
        return *points;
    }
    return Json::array();
}

[[nodiscard]] std::any sample_points_to_any(const Json& points) {
    // Project JSON → the any convention (vector<map<string,any>> with
    // scalar leaves), so param_truthy("sample_points") matches the
    // synthetic seam exactly.
    std::vector<std::map<std::string, std::any>> out;
    if (points.is_array()) {
        for (const auto& point : points) {
            if (!point.is_object()) continue;
            std::map<std::string, std::any> entry;
            for (auto it = point.begin(); it != point.end(); ++it) {
                const Json& field = it.value();
                if (field.is_string()) {
                    entry[it.key()] = field.get<std::string>();
                } else if (field.is_number_float()) {
                    entry[it.key()] = field.get<double>();
                } else if (field.is_number_integer()) {
                    entry[it.key()] = static_cast<int>(
                        field.get<long long>());
                } else if (field.is_boolean()) {
                    entry[it.key()] = field.get<bool>();
                }
                // null / nested containers are not consumed by the kernels.
            }
            out.push_back(std::move(entry));
        }
    }
    return out;
}

// -------------------------------------------------------- constraint glue --

struct ConstraintSet {
    Json break_polylines = Json::array();   // normalized [[ [x,y], ... ], ...]
    Json direction_params = Json::array();  // [{id, azimuth_deg, semi_*}]
    std::vector<std::vector<std::array<double, 2>>> break_lines;
    std::vector<std::vector<std::array<double, 2>>> direction_lines;
    std::vector<std::vector<std::array<double, 2>>> boundary_rings;
    // Per consumed group: {group_id, group_name, content_hash, line_count,
    // version_id?} — Python constraint_pins_for_task.
    Json pins = Json::array();
    // Non-empty → the consumed groups declare mutually incompatible CRSes
    // (or one disagrees with the project CRS): interpolation must refuse.
    std::string crs_conflict;
};

// constraint_versions.py constraint_group_content_hash parity: the pin
// digest is ID-free, ORDER-free and ACTIVE-lines-only — renames, id
// regeneration, inactive lines and version rebinding must not flip it.
// Per canonical line: role + 9-decimal-rounded coordinates (auto-closed
// rings keep their closure point like boundary_rings_for_engine).
[[nodiscard]] std::string canonical_line_key(const Json& line) {
    Json payload = Json::object();
    payload["role"] = field_str(line, "role", "other");
    Json coords = Json::array();
    if (const Json* raw = find_field(line, "coordinates");
        raw != nullptr && raw->is_array()) {
        for (const auto& xy : *raw) {
            if (!xy.is_array() || xy.size() < 2) continue;
            if (!xy[0].is_number() || !xy[1].is_number()) continue;
            std::ostringstream x_out, y_out;
            x_out << std::fixed << std::setprecision(9)
                  << xy[0].get<double>();
            y_out << std::fixed << std::setprecision(9)
                  << xy[1].get<double>();
            coords.push_back(x_out.str() + "," + y_out.str());
        }
    }
    payload["coordinates"] = std::move(coords);
    return payload.dump();
}

[[nodiscard]] std::string polyline_content_hash(
    const Json& layer, const std::string& horizon) {
    std::vector<std::string> keys;
    if (const Json* lines = find_field(layer, "lines");
        lines != nullptr && lines->is_array()) {
        for (const auto& line : *lines) {
            if (!line.is_object()) continue;
            const bool active = [&] {
                const Json* flag = find_field(line, "active");
                return flag == nullptr || !flag->is_boolean() ? true
                                                              : flag->get<bool>();
            }();
            if (!active) continue;
            keys.push_back(canonical_line_key(line));
        }
    }
    std::sort(keys.begin(), keys.end());
    Json payload = Json::object();
    payload["canonical_lines"] = keys;
    payload["target_horizon"] = horizon;
    return pwb::factor_host::stable_sha256(payload);
}

// constraint_layers_for_project: empty layer horizon or exact match.
[[nodiscard]] std::string horizon_of(const Json& layer) {
    return field_str(layer, "target_horizon");
}

[[nodiscard]] std::vector<const Json*> layers_for_horizon(
    const std::vector<std::any>& constraint_layers,
    const std::string& target_horizon) {
    std::vector<const Json*> out;
    for (const auto& layer_any : constraint_layers) {
        const auto* layer = std::any_cast<Json>(&layer_any);
        if (layer == nullptr || !layer->is_object()) continue;
        const std::string horizon =
            field_str(*layer, "target_horizon");
        if (!horizon.empty() && !target_horizon.empty()
            && horizon != target_horizon) {
            continue;
        }
        out.push_back(layer);
    }
    return out;
}

[[nodiscard]] ConstraintSet resolve_constraints(
    const std::vector<std::any>& constraint_layers,
    const std::string& target_horizon, const std::string& project_crs) {
    ConstraintSet out;
    std::vector<std::string> declared_crs;
    for (const Json* layer : layers_for_horizon(constraint_layers,
                                                target_horizon)) {
        const Json* lines = find_field(*layer, "lines");
        if (lines == nullptr || !lines->is_array()) continue;

        const std::string layer_crs = field_str(*layer, "crs");
        if (!layer_crs.empty()) {
            declared_crs.push_back(layer_crs);
        }

        const std::string group_id =
            field_str(*layer, "id", "clayers_unknown");
        const std::string group_name = field_str(*layer, "name", "约束层");
        int consumed = 0;
        for (const auto& line : *lines) {
            if (!line.is_object()) continue;
            // active_lines parity: a line's own horizon (falling back to
            // the layer's) must be empty or match the target.
            const std::string line_horizon =
                field_str(line, "target_horizon", horizon_of(*layer));
            if (!line_horizon.empty() && !target_horizon.empty()
                && line_horizon != target_horizon) {
                continue;
            }
            const bool active = [&] {
                const Json* flag = find_field(line, "active");
                return flag == nullptr || !flag->is_boolean()
                           ? true
                           : flag->get<bool>();
            }();
            if (!active) continue;
            const std::string role = field_str(line, "role", "other");
            const Json* coords = find_field(line, "coordinates");
            if (coords == nullptr || !coords->is_array()) continue;
            std::vector<std::array<double, 2>> points;
            for (const auto& xy : *coords) {
                if (!xy.is_array() || xy.size() < 2) continue;
                if (!xy[0].is_number() || !xy[1].is_number()) continue;
                points.push_back({xy[0].get<double>(), xy[1].get<double>()});
            }
            if (role == "break" && points.size() >= 2) {
                Json polyline = Json::array();
                for (const auto& [x, y] : points) {
                    polyline.push_back(Json::array({x, y}));
                }
                out.break_polylines.push_back(std::move(polyline));
                out.break_lines.push_back(std::move(points));
                ++consumed;
            } else if (role == "direction" && points.size() >= 2) {
                // direction_line_params parity: an explicit azimuth wins;
                // else the whole-line endpoint bearing from north, kept in
                // [0, 360) (Python % 360.0 on a positive quantity).
                const double dx = points.back()[0] - points.front()[0];
                const double dy = points.back()[1] - points.front()[1];
                const Json* explicit_azimuth_probe =
                    find_field(line, "azimuth_deg");
                const bool has_explicit =
                    explicit_azimuth_probe != nullptr
                    && explicit_azimuth_probe->is_number();
                // A zero-length line without an explicit azimuth is a
                // degenerate direction (atan2(0,0)=0 would silently
                // fabricate a north-pointing constraint) — skip it.
                if (dx == 0.0 && dy == 0.0 && !has_explicit) continue;
                double azimuth =
                    std::atan2(dx, dy) * 180.0 / M_PI;
                azimuth = std::fmod(azimuth + 360.0, 360.0);
                const Json* explicit_azimuth =
                    find_field(line, "azimuth_deg");
                if (explicit_azimuth != nullptr
                    && explicit_azimuth->is_number()) {
                    azimuth = explicit_azimuth->get<double>();
                }
                Json params = Json::object();
                params["id"] = field_str(line, "id", "cline_direction");
                params["azimuth_deg"] = azimuth;
                Json coordinates = Json::array();
                for (const auto& [px, py] : points) {
                    coordinates.push_back(Json::array({px, py}));
                }
                params["coordinates"] = std::move(coordinates);
                const Json* semi_major = find_field(line, "semi_major");
                if (semi_major != nullptr && semi_major->is_number()) {
                    params["semi_major"] =
                        semi_major->get<double>();
                }
                const Json* semi_minor = find_field(line, "semi_minor");
                if (semi_minor != nullptr && semi_minor->is_number()) {
                    params["semi_minor"] =
                        semi_minor->get<double>();
                }
                out.direction_params.push_back(std::move(params));
                out.direction_lines.push_back(std::move(points));
                ++consumed;
            } else if (role == "boundary" && points.size() >= 3) {
                // boundary_rings_for_engine parity: drop duplicate closing
                // points, auto-close open rings (the drawer may have left
                // the ring open); >=3 unique vertices required.
                std::vector<std::array<double, 2>> unique;
                for (const auto& point : points) {
                    const bool dup =
                        !unique.empty()
                        && std::abs(unique.back()[0] - point[0]) < 1e-12
                        && std::abs(unique.back()[1] - point[1]) < 1e-12;
                    if (!dup) unique.push_back(point);
                }
                if (unique.size() >= 3) {
                    const auto& first = unique.front();
                    const auto& last = unique.back();
                    const bool closed =
                        std::abs(first[0] - last[0]) < 1e-9
                        && std::abs(first[1] - last[1]) < 1e-9;
                    if (!closed) unique.push_back(first);
                    out.boundary_rings.push_back(std::move(unique));
                    ++consumed;
                }
            }
        }
        if (consumed > 0) {
            Json pin = Json::object();
            pin["group_id"] = group_id;
            pin["group_name"] = group_name;
            pin["line_count"] = consumed;
            const Json* version_id = find_field(*layer, "version_id");
            if (version_id != nullptr && version_id->is_string()) {
                pin["version_id"] = version_id->get<std::string>();
            }
            out.pins.push_back(std::move(pin));
            // canonical content hash per consumed group (constraint_
            // versions.py parity — see polyline_content_hash).
            out.pins.back()["content_hash"] =
                polyline_content_hash(*layer, target_horizon);
        }
    }
    // CRS discipline (fail-closed): mutually incompatible constraint
    // groups, or a group disagreeing with the declared project CRS.
    std::sort(declared_crs.begin(), declared_crs.end());
    declared_crs.erase(
        std::unique(declared_crs.begin(), declared_crs.end()),
        declared_crs.end());
    if (declared_crs.size() > 1) {
        std::string joined;
        for (const auto& crs : declared_crs) {
            if (!joined.empty()) joined += " vs ";
            joined += crs;
        }
        out.crs_conflict = "约束层 CRS 不兼容: " + joined;
    } else if (declared_crs.size() == 1 && !project_crs.empty()
               && declared_crs.front() != project_crs) {
        out.crs_conflict = "约束层 CRS 与工程 CRS 不兼容: "
                           + declared_crs.front() + " vs " + project_crs;
    }
    return out;
}

// resolve_anisotropy_params: circular-mean azimuth over direction lines,
// arithmetic-mean axes; task overrides win. Defaults (0.0, 1.0, 0.4).
struct AnisotropyParams {
    double azimuth_deg = 0.0;
    double semi_major = 1.0;
    double semi_minor = 0.4;
};

[[nodiscard]] AnisotropyParams resolve_anisotropy(
    const Json& direction_params, const Json& task_parameters) {
    AnisotropyParams out;
    if (direction_params.is_array() && !direction_params.empty()) {
        // resolve_anisotropy_params parity: the FIRST direction dict wins
        // (geoviz takes params[0]), not a mean.
        const Json& params = direction_params.front();
        const Json* azimuth = find_field(params, "azimuth_deg");
        if (azimuth != nullptr && azimuth->is_number()) {
            out.azimuth_deg = azimuth->get<double>();
        }
        const Json* major = find_field(params, "semi_major");
        if (major != nullptr && major->is_number()) {
            out.semi_major = major->get<double>();
        }
        const Json* minor = find_field(params, "semi_minor");
        if (minor != nullptr && minor->is_number()) {
            out.semi_minor = minor->get<double>();
        }
    }
    if (task_parameters.is_object()) {
        const Json* azimuth =
            find_field(task_parameters, "azimuth_deg");
        if (azimuth != nullptr && azimuth->is_number()) {
            out.azimuth_deg = azimuth->get<double>();
        }
        const Json* major = find_field(task_parameters, "semi_major");
        if (major != nullptr && major->is_number()) {
            out.semi_major = major->get<double>();
        }
        const Json* minor = find_field(task_parameters, "semi_minor");
        if (minor != nullptr && minor->is_number()) {
            out.semi_minor = minor->get<double>();
        }
    }
    return out;
}

// ------------------------------------------------------- fingerprint glue --

[[nodiscard]] const Json& nlohmann_json_empty_params() {
    static const Json empty = Json::object();
    return empty;
}

struct ResolvedFingerprints {
    pwb::factor_host::FactorFingerprints fingerprints;
    std::string backend;
    Json break_polylines;  // normalized (backend-consumed only)
    Json direction_params;
    AnisotropyParams anisotropy;
    std::string error;     // non-empty → classification failed (task-level)
};

// fingerprints_for_task with scheduled overrides (prepare-time semantics:
// ctx method/grid_n/power win over stored task parameters) and optional
// request-scoped memo.
[[nodiscard]] ResolvedFingerprints fingerprints_for_task(
    const FactorTaskSlice& task,
    const ui_workers::PrepareExecContext& ctx,
    const std::string& generator_version,
    ui_workers::FingerprintMemo* memo) {
    ResolvedFingerprints out;

    const Json empty_params = Json::object();
    const Json& params = [&]() -> const Json& {
        if (task.source_json.has_value() && task.source_json->is_object()) {
            const Json* field =
                find_field(*task.source_json, "parameters");
            if (field != nullptr && field->is_object()) return *field;
        }
        return empty_params;
    }();

    // Python: the schedule override wins, then the TASK's own method —
    // parameters.method is never consulted at prepare time.
    std::string method = task.method;
    if (!ctx.method.empty()) method = ctx.method;
    out.backend = pwb::factor_host::resolve_backend(method);

    int grid_n = 0;
    if (ctx.grid_n > 0) {
        grid_n = ctx.grid_n;
    } else {
        const Json* field = find_field(params, "grid_n");
        if (field != nullptr && field->is_number_integer()) {
            grid_n = static_cast<int>(field->get<long long>());
        }
    }
    if (grid_n <= 0) grid_n = ui_workers::kDefaultGridN;
    // Plain path clamp mirrors the constrained engine's [20, 200]
    // resolution bounds (a hand-edited 2000 would be 4M cells).
    grid_n = std::max(20, std::min(200, grid_n));
    // Python parity: the SCHEDULED power wins unconditionally
    // (parameters.power is never read at prepare time — an override must
    // invalidate results computed with a different power).
    const double power = ctx.power;

    const Json sample_points = sample_points_to_json(
        [&] {
            const auto it = task.parameters.find("sample_points");
            return it != task.parameters.end() ? it->second : std::any{};
        }());

    const bool uses_breaks =
        pwb::factor_host::backend_uses_breaks(out.backend);
    const bool uses_directions =
        pwb::factor_host::backend_uses_directions(out.backend);

    ConstraintSet constraints;
    if (uses_breaks || uses_directions
        || out.backend == pwb::factor_host::kConstrainedIdwLabel) {
        constraints = resolve_constraints(ctx.constraint_layers,
                                          ctx.target_horizon,
                                          ctx.project_crs.value_or(""));
    }
    if (uses_breaks) {
        out.break_polylines =
            pwb::factor_host::normalize_polylines(constraints.break_polylines);
    }
    if (uses_directions) {
        out.direction_params = pwb::factor_host::normalize_direction_params(
            constraints.direction_params);
    }
    out.anisotropy = resolve_anisotropy(out.direction_params, params);

    // Memo key: the Python request-scope tuple.
    std::string memo_key;
    if (memo != nullptr) {
        const Json xy_digest = pwb::factor_host::extract_sample_records(
            sample_points);
        std::ostringstream key;
        key << task.id << '|' << method << '|' << grid_n << '|' << power
            << '|' << generator_version << '|' << ctx.target_horizon << '|'
            << xy_digest.size() << '|'
            << pwb::factor_host::stable_sha256(xy_digest) << '|'
            << (out.break_polylines.is_array()
                    ? pwb::factor_host::stable_sha256(out.break_polylines)
                    : std::string("[]"));
        memo_key = key.str();
        std::lock_guard<std::mutex> guard(memo->mutex);
        const auto it = memo->entries.find(memo_key);
        if (it != memo->entries.end()) {
            if (const auto* cached =
                    std::any_cast<pwb::factor_host::FactorFingerprints>(
                        &it->second)) {
                out.fingerprints = *cached;
                return out;
            }
        }
    }

    const Json normalized = [&] {
        const std::string policy =
            pwb::mapping::duplicate_policy_from_params(params);
        try {
            return pwb::mapping::normalize_factor_samples(sample_points,
                                                          policy)
                .first;
        } catch (const std::exception&) {
            // policy=error with duplicates → classification failure for
            // this task only (Python: ValueError fails the task).
            out.error = "duplicate_policy=error 拒绝了重复采样点";
            return sample_points;
        }
    }();
    if (!out.error.empty()) return out;

    std::optional<std::string> duplicate_policy;
    {
        const Json* field = find_field(params, "duplicate_policy");
        if (field != nullptr && field->is_string()
            && json_truthy(*field)) {
            duplicate_policy = field->get<std::string>();
        }
    }

    pwb::factor_host::BuildFingerprintsArgs args;
    args.sample_points = &normalized;
    args.method = method;
    args.grid_n = grid_n;
    args.power = power;
    args.azimuth_deg = out.anisotropy.azimuth_deg;
    args.semi_major = out.anisotropy.semi_major;
    args.semi_minor = out.anisotropy.semi_minor;
    if (!out.break_polylines.is_null()) {
        args.fault_polylines = &out.break_polylines;
    }
    if (!out.direction_params.is_null()) {
        args.direction_params = &out.direction_params;
    }
    args.crs = ctx.project_crs.value_or("");
    args.generator_version = generator_version;
    args.target_horizon = ctx.target_horizon;
    args.duplicate_policy = duplicate_policy;
    out.fingerprints = pwb::factor_host::build_factor_fingerprints(args);

    if (memo != nullptr && !memo_key.empty()) {
        std::lock_guard<std::mutex> guard(memo->mutex);
        memo->entries[memo_key] = out.fingerprints;
    }
    return out;
}

[[nodiscard]] std::string grid_result_fingerprint(const std::any& grid) {
    if (const auto* entry = std::any_cast<LiveGridEntry>(&grid)) {
        return entry->result_fingerprint;
    }
    return "";
}

// ------------------------------------------------------------------ batch --

struct InterpSamples {
    std::vector<pwb::mapping::SamplePoint> points;  // normalized
    Json normalized_json;
    pwb::mapping::SampleNormalizationReport report;
};

[[nodiscard]] InterpSamples load_samples(const Json& raw_points,
                                         const Json& params) {
    InterpSamples out;
    const std::string policy =
        pwb::mapping::duplicate_policy_from_params(params);
    auto [normalized, report] =
        pwb::mapping::normalize_factor_samples(raw_points, policy);
    out.normalized_json = std::move(normalized);
    out.report = report;
    for (const auto& record :
         out.normalized_json.is_array() ? out.normalized_json : Json::array()) {
        pwb::mapping::SamplePoint point;
        const Json* x = find_field(record, "x");
        const Json* y = find_field(record, "y");
        const Json* z = find_field(record, "z");
        if (x == nullptr || y == nullptr || z == nullptr) continue;
        if (!x->is_number() || !y->is_number() || !z->is_number()) continue;
        point.x = x->get<double>();
        point.y = y->get<double>();
        point.value = z->get<double>();
        const Json* qc = find_field(record, "qc_flag");
        if (qc != nullptr && qc->is_string()) {
            point.qc_flag = qc->get<std::string>();
        }
        out.points.push_back(std::move(point));
    }
    return out;
}

// LOO R² (Python parity: cap MAX_LOO_SAMPLES=64 via linspace subsample,
// re-interpolate per fold; <2 valid pairs → null). Constrained backend →
// null (spatial-4-fold metric not ported — honest).
//
// Production efficiency: each fold consumes exactly ONE bilinear sample
// of the fold grid, so the fold runs on a coarse grid (kLooGridN) instead
// of the production grid — same estimator, orders of magnitude cheaper
// (200x200 -> 20x20 is 100x fewer cell solves). Cancellation is checked
// per fold.
[[nodiscard]] Json loo_r_squared(
    const std::vector<pwb::mapping::SamplePoint>& points,
    const pwb::mapping::InterpolateOptions& options,
    const job::CancellationToken& token) {
    constexpr int kLooGridN = 20;
    constexpr int kMaxLooSamples = 64;
    Json out = Json(nullptr);
    if (points.size() < 3) return out;
    std::vector<std::size_t> indices;
    if (points.size() > static_cast<std::size_t>(kMaxLooSamples)) {
        for (int i = 0; i < kMaxLooSamples; ++i) {
            indices.push_back(static_cast<std::size_t>(
                std::min<double>(
                    std::floor(static_cast<double>(i)
                               * static_cast<double>(points.size() - 1)
                               / (kMaxLooSamples - 1)),
                    static_cast<double>(points.size() - 1))));
        }
    } else {
        for (std::size_t i = 0; i < points.size(); ++i) indices.push_back(i);
    }
    std::vector<double> observed;
    std::vector<double> predicted;
    for (const std::size_t held : indices) {
        std::vector<pwb::mapping::SamplePoint> train;
        train.reserve(points.size() - 1);
        for (std::size_t i = 0; i < points.size(); ++i) {
            if (i != held) train.push_back(points[i]);
        }
        try {
            token.check_cancelled();
            pwb::mapping::InterpolateOptions fold_options = options;
            fold_options.grid_n = kLooGridN;
            const auto grid =
                pwb::mapping::interpolate_factor(train, fold_options);
            std::vector<double> z(grid.grid_z.begin(), grid.grid_z.end());
            const auto sampled = pwb::factor_host::bilinear_sample_grid(
                z, grid.grid_x, grid.grid_y, points[held].x, points[held].y);
            if (sampled.has_value() && std::isfinite(*sampled)) {
                observed.push_back(points[held].value);
                predicted.push_back(*sampled);
            }
        } catch (const std::exception&) {
            // Degenerate fold (e.g. <2 train points) — skip the pair.
        }
    }
    if (observed.size() < 2) return out;
    out = pwb::factor_host::signed_r_squared(observed, predicted);
    return out;
}

[[nodiscard]] pwb::mapping::constrained_idw::Config
derived_constrained_config(
    const std::vector<pwb::mapping::SamplePoint>& points, int grid_n,
    bool has_directions, double power) {
    // Python constrained_idw_adapter derivation (mirrored from
    // science_service factor_service — single semantic, two hosts):
    //   value range <- finite min/max + tiny pad
    //   search      <- 1.05 * bbox diagonal (>= 0.75 * span)
    //   decluster   <- 0.15 * search (0 with directions)
    //   resolution  <- clamp(grid_n, 20, 200)
    pwb::mapping::constrained_idw::Config config;
    double lo = std::numeric_limits<double>::infinity();
    double hi = -std::numeric_limits<double>::infinity();
    double xmin = lo, ymin = lo, xmax = hi, ymax = hi;
    for (const auto& point : points) {
        if (!std::isfinite(point.value)) continue;
        lo = std::min(lo, point.value);
        hi = std::max(hi, point.value);
        xmin = std::min(xmin, point.x);
        ymin = std::min(ymin, point.y);
        xmax = std::max(xmax, point.x);
        ymax = std::max(ymax, point.y);
    }
    const double span = std::max(xmax - xmin, ymax - ymin);
    const double diag =
        std::hypot(xmax - xmin, ymax - ymin);
    // Adapter parity: pad = (hi-lo)*1e-9, floored at max(|lo|*1e-6, 1e-9)
    // for the degenerate constant field.
    double pad = (hi - lo) * 1e-9;
    if (hi == lo) pad = std::max(std::abs(lo) * 1e-6, 1e-9);
    config.value_min = lo - pad;
    config.value_max = hi + pad;
    config.search_radius =
        std::max(1.05 * diag, 0.75 * std::max(span, 1e-9));
    config.decluster_radius =
        has_directions
            ? 0.0
            : std::max({0.15 * config.search_radius, 0.05 * span, 1e-6});
    config.grid_resolution = std::max(20, std::min(200, grid_n));
    config.power = power;
    // Direction-active recipe (adapter): along-track blend 1.0 (cell_g
    // 0.025, exp_k 8.0), corridor 2.65, perpendicular 1.85, taper 0.95,
    // direction SMOOTHING STRENGTH 3.0 (iterations stay at the default),
    // declustering off.
    if (has_directions) {
        config.along_track_blend_strength = 1.0;
        config.along_track_min_cell_g = 0.025;
        config.along_track_exp_k = 8.0;
        config.direction_corridor_strength = 2.65;
        config.direction_perpendicular_strength = 1.85;
        config.direction_taper_plateau = 0.95;
        config.direction_smoothing_strength = 3.0;
        config.decluster_strength = 0.0;
    }
    return config;
}

struct AttachedResult {
    pwb::mapping::FactorGrid grid;        // plain path
    bool constrained = false;
    pwb::mapping::constrained_idw::Result constrained_grid;
    std::string backend;
    Json r_squared = Json(nullptr);
    int n_break_lines = 0;
    int n_direction_lines = 0;
    // Effective boundary rings (user rings, or the synthesized hull).
    std::vector<std::vector<std::array<double, 2>>> effective_boundary;
};

// The per-task numeric core. Throws on task failure (caller isolates).
[[nodiscard]] AttachedResult apply_interpolation(
    const Json& raw_points, const Json& params, const std::string& method,
    int grid_n, double power, const ConstraintSet& constraints,
    const std::string& crs,
    const pwb::factor_host::FactorFingerprints& fingerprints,
    const job::CancellationToken& token) {
    AttachedResult out;
    const std::string engine_method =
        pwb::factor_host::resolve_engine_method(method);
    const std::string backend =
        pwb::factor_host::resolve_backend(engine_method);

    const InterpSamples samples = load_samples(raw_points, params);

    if (backend == "cubic" || backend == "directional") {
        throw std::runtime_error(
            "插值后端 " + backend + " 未原生接入（" + engine_method
            + "）：请选择 IDW / 克里金 / 约束IDW");
    }

    // Honesty gates: the native plain kernels do not consume break lines
    // (geoviz fault-LOS not ported) and kriging has no anisotropy input —
    // refuse instead of fingerprinting constraints as consumed.
    const bool breaks_active = !constraints.break_lines.empty();
    const bool directions_active = !constraints.direction_lines.empty();
    if ((backend == "idw" || backend == "kriging") && breaks_active) {
        throw std::runtime_error(
            "激活的断层线(break)需要 constrained_idw 后端消费：原生 "
            + backend + " 不支持断层遮挡，拒绝静默忽略约束");
    }
    if (backend == "kriging" && directions_active) {
        throw std::runtime_error(
            "激活的方向线(direction)需要 constrained_idw 后端消费：原生"
            "克里金不支持各向异性，拒绝静默忽略约束");
    }

    token.check_cancelled();

    if (backend == pwb::factor_host::kConstrainedIdwLabel) {
        // The hull fallback below extends the ring set locally (the input
        // constraint set stays const — callers fingerprint it as consumed).
        std::vector<std::vector<std::array<double, 2>>> boundary_rings =
            constraints.boundary_rings;
        if (samples.points.size() < 3) {
            throw std::invalid_argument(
                "约束IDW至少需要 3 口有效井（当前 "
                + std::to_string(samples.points.size()) + "）");
        }
        // Duplicate wells: first-wins (Python adapter).
        std::vector<pwb::mapping::constrained_idw::Well> wells;
        std::map<std::pair<double, double>, std::size_t> seen;
        int duplicates_dropped = 0;
        for (const auto& point : samples.points) {
            const auto key = std::make_pair(point.x, point.y);
            const auto it = seen.find(key);
            if (it != seen.end()) {
                ++duplicates_dropped;
                continue;
            }
            seen.emplace(key, wells.size());
            pwb::mapping::constrained_idw::Well well;
            well.well_id = "w" + std::to_string(wells.size());
            well.x = point.x;
            well.y = point.y;
            well.value = point.value;
            wells.push_back(std::move(well));
        }
        if (wells.size() < 3) {
            throw std::invalid_argument(
                "约束IDW去重后有效井不足 3 口（丢弃 "
                + std::to_string(duplicates_dropped) + "）");
        }
        if (constraints.boundary_rings.empty()) {
            // constrained_idw_adapter._boundary_from_samples parity: no
            // user ring -> synthesize the sample convex hull (Andrew
            // monotone chain over the valid wells). Fewer than 3 unique
            // positions genuinely cannot bound a surface — engine text.
            std::vector<std::array<double, 2>> hull;
            {
                std::vector<std::array<double, 2>> pts;
                for (const auto& point : samples.points) {
                    pts.push_back({point.x, point.y});
                }
                std::sort(pts.begin(), pts.end());
                pts.erase(std::unique(pts.begin(), pts.end()), pts.end());
                if (pts.size() >= 3) {
                    auto cross = [](const std::array<double, 2>& o,
                                    const std::array<double, 2>& a,
                                    const std::array<double, 2>& b) {
                        return (a[0] - o[0]) * (b[1] - o[1])
                               - (a[1] - o[1]) * (b[0] - o[0]);
                    };
                    std::vector<std::array<double, 2>> lower, upper;
                    for (const auto& pt : pts) {
                        while (lower.size() >= 2
                               && cross(lower[lower.size() - 2],
                                        lower[lower.size() - 1], pt)
                                      <= 0) {
                            lower.pop_back();
                        }
                        lower.push_back(pt);
                    }
                    for (std::size_t i = pts.size(); i-- > 0;) {
                        const auto& pt = pts[i];
                        while (upper.size() >= 2
                               && cross(upper[upper.size() - 2],
                                        upper[upper.size() - 1], pt)
                                      <= 0) {
                            upper.pop_back();
                        }
                        upper.push_back(pt);
                    }
                    lower.pop_back();
                    upper.pop_back();
                    hull = std::move(lower);
                    hull.insert(hull.end(), upper.begin(), upper.end());
                    hull.push_back(hull.front());  // close the ring
                    // A degenerate (collinear) well set collapses the
                    // chain to a zero-area ring — scipy raises QhullError
                    // here; refuse with the same engine text instead of
                    // completing an all-NaN surface.
                    double area2 = 0.0;
                    for (std::size_t i = 0; i + 1 < hull.size(); ++i) {
                        area2 += hull[i][0] * hull[i + 1][1]
                                 - hull[i + 1][0] * hull[i][1];
                    }
                    if (hull.size() < 4
                        || std::abs(area2) <= 1e-12) {
                        hull.clear();
                    }
                }
            }
            if (hull.empty()) {
                throw std::invalid_argument(
                    "constrained_idw requires a boundary polygon "
                    "(constrained_boundary or interpolate.boundary)");
            }
            boundary_rings.push_back(std::move(hull));
        }
        std::vector<pwb::mapping::constrained_idw::BoundaryPolygon>
            boundaries;
        for (const auto& ring : boundary_rings) {
            pwb::mapping::constrained_idw::BoundaryPolygon polygon;
            for (const auto& [x, y] : ring) {
                polygon.exterior.push_back({x, y});
            }
            boundaries.push_back(std::move(polygon));
        }
        std::vector<pwb::mapping::constrained_idw::BarrierLine> barriers;
        for (const auto& line : constraints.break_lines) {
            pwb::mapping::constrained_idw::BarrierLine barrier;
            barrier.line_id = "barrier_" + std::to_string(barriers.size());
            for (const auto& [x, y] : line) {
                barrier.points.push_back({x, y});
            }
            barriers.push_back(std::move(barrier));
        }
        std::vector<pwb::mapping::constrained_idw::DirectionLine>
            directions;
        for (const auto& line : constraints.direction_lines) {
            pwb::mapping::constrained_idw::DirectionLine direction;
            direction.line_id =
                "direction_" + std::to_string(directions.size());
            for (const auto& [x, y] : line) {
                direction.points.push_back({x, y});
            }
            directions.push_back(std::move(direction));
        }
        const auto config = derived_constrained_config(
            samples.points, grid_n, !directions.empty(), power);
        out.constrained = true;
        out.backend = backend;
        out.constrained_grid = pwb::mapping::constrained_idw::
            generate_constrained_idw(wells, boundaries, barriers,
                                     directions, config);
        out.n_break_lines = static_cast<int>(barriers.size());
        out.n_direction_lines = static_cast<int>(directions.size());
        out.effective_boundary = std::move(boundary_rings);
        return out;
    }

    // Plain path (idw | kriging).
    pwb::mapping::InterpolateOptions options;
    options.method = backend == "kriging" ? "kriging" : "idw";
    options.grid_n = grid_n;
    options.power = power;
    options.crs = crs;
    // Production neighborhoods: without max_neighbors the kriging path
    // solves an (n+1)x(n+1) system PER CELL (O(n^3) per cell); the
    // kernel's kNN path caps the system at k+1 (<=256). 12 neighbours is
    // the standard production default and keeps a 1000-well kriging
    // sub-second instead of hours.
    if (backend == "kriging" && samples.points.size() > 32) {
        options.max_neighbors = 12;
        options.min_neighbors = 1;
    }
    const Json variogram =
        pwb::factor_host::variogram_settings_from_params(params);
    if (variogram.is_object()) {
        const Json* model = find_field(variogram, "variogram_model");
        if (model != nullptr && model->is_string()) {
            options.variogram_model = model->get<std::string>();
        }
    }
    out.grid = pwb::mapping::interpolate_factor(samples.points, options);
    out.backend = backend;
    out.r_squared = loo_r_squared(samples.points, options, token);
    out.n_break_lines = 0;
    out.n_direction_lines = 0;
    // The result fingerprint must reflect the scheduled inputs (the caller
    // stamps it); the grid itself carries the algorithm record.
    (void)fingerprints;
    return out;
}

// _attach_result_to_task: mutate the task's source JSON in place.
void attach_result_to_task(Json& task_json, const Json& raw_points,
                           const InterpSamples& samples,
                           const AttachedResult& attached,
                           const std::string& method, int grid_n,
                           double power, const ConstraintSet& constraints,
                           const pwb::factor_host::FactorFingerprints& fps,
                           const std::string& backend,
                           const AnisotropyParams& anisotropy,
                           const std::string& generator_version,
                           const std::string& crs) {
    if (!task_json.is_object()) task_json = Json::object();
    if (!task_json.contains("parameters")
        || !task_json["parameters"].is_object()) {
        task_json["parameters"] = Json::object();
    }
    Json& params = task_json["parameters"];

    // Grid arrays never ride parameters (GRID_ARRAY_PARAMETER_KEYS).
    params.erase("grid_x");
    params.erase("grid_y");
    params.erase("grid_z");
    params.erase("grid_var");
    params.erase("grid_boundary");

    params["sample_points"] = raw_points;  // RAW, not the normalized set
    Json normalization = Json::object();
    normalization["policy"] = samples.report.policy;
    normalization["n_input"] = samples.report.n_input;
    normalization["n_valid"] = samples.report.n_valid;
    normalization["n_nonfinite_dropped"] =
        samples.report.n_nonfinite_dropped;
    normalization["n_duplicate_groups"] =
        samples.report.n_duplicate_groups;
    normalization["n_duplicates_merged"] =
        samples.report.n_duplicates_merged;
    normalization["n_qc_flagged"] = samples.report.n_qc_flagged;
    params["sample_normalization"] = std::move(normalization);

    if (!constraints.pins.empty()) {
        params["constraint_pins"] = constraints.pins;
    } else {
        params.erase("constraint_pins");
    }

    const int height = attached.constrained
                           ? static_cast<int>(
                                 attached.constrained_grid.grid_y.size())
                           : static_cast<int>(attached.grid.grid_y.size());
    const int width = attached.constrained
                          ? static_cast<int>(
                                attached.constrained_grid.grid_x.size())
                          : static_cast<int>(attached.grid.grid_x.size());
    params["grid"] = std::to_string(height) + "×"
                     + std::to_string(width);
    params["interp_backend"] = backend;
    params["grid_n"] = grid_n;
    if (backend == "idw" || backend == "constrained_idw") {
        params["power"] = power;
    } else {
        params.erase("power");
    }

    Json diagnostics = Json::object();
    diagnostics["n_break_lines"] = attached.n_break_lines;
    diagnostics["n_direction_lines"] = attached.n_direction_lines;
    if (backend == "kriging") {
        Json ignored = Json::array();
        if (!constraints.break_lines.empty()) {
            ignored.push_back("barrier:" + std::to_string(
                                    constraints.break_lines.size())
                              + " break line(s) not consumed by kriging");
        }
        diagnostics["engine_ignored"] = std::move(ignored);
    }
    params["constraint_diagnostics"] = std::move(diagnostics);
    params["n_break_lines"] = attached.n_break_lines;
    params["n_direction_lines"] = attached.n_direction_lines;

    if (backend == "kriging") {
        Json kriging = Json::object();
        kriging["variogram_model"] = attached.grid.model;
        kriging["nugget"] = attached.grid.nugget;
        kriging["sill"] = attached.grid.sill;
        kriging["range"] = attached.grid.range;
        params["kriging_diagnostics"] = std::move(kriging);
    } else {
        params.erase("kriging_diagnostics");
    }

    if (backend == "directional") {
        params["azimuth_deg"] = anisotropy.azimuth_deg;
        params["semi_major"] = anisotropy.semi_major;
        params["semi_minor"] = anisotropy.semi_minor;
    } else {
        params.erase("azimuth_deg");
        params.erase("semi_major");
        params.erase("semi_minor");
    }

    if ((backend == "idw" || backend == "constrained_idw")
        && !constraints.break_lines.empty()) {
        params["break_polylines"] = pwb::factor_host::normalize_polylines(
            constraints.break_polylines);
    } else {
        params.erase("break_polylines");
    }

    if (attached.constrained && !attached.effective_boundary.empty()) {
        Json ring = Json::array();
        for (const auto& [x, y] : attached.effective_boundary.front()) {
            ring.push_back(Json::array({x, y}));
        }
        params["grid_boundary"] = std::move(ring);
    }

    // Stage-4 fingerprints (stamp_fingerprints_on_task).
    params["schema_version"] =
        pwb::factor_host::kFingerprintSchemaVersion;
    // stamp_fingerprints_on_task key contract (interpolation_fingerprint.py
    // L625+ / factor_host stored_fingerprints_from_task): *_fingerprint.
    params["geometry_fingerprint"] = fps.geometry;
    params["values_fingerprint"] = fps.values;
    params["algorithm_fingerprint"] = fps.algorithm;
    params["constraints_fingerprint"] = fps.constraints;
    params["result_fingerprint"] = fps.result;
    params["backend"] = fps.backend;

    task_json["status"] = "complete";
    // Python: task.method = method ("mock" launders to "IDW").
    task_json["method"] = method == "mock" ? std::string("IDW") : method;
    task_json["generator_version"] = generator_version;
    task_json["input_snapshot_hash"] = fps.result;
    task_json["grid_artifact_path"] = Json(nullptr);
    task_json["grid_artifact_version_id"] = Json(nullptr);

    // quality_metrics.
    Json quality = Json::object();
    const auto& stats = attached.constrained
                            ? pwb::mapping::grid_statistics(
                                  std::vector<float>(
                                      attached.constrained_grid.grid_z
                                          .begin(),
                                      attached.constrained_grid.grid_z
                                          .end()))
                            : attached.grid.statistics;
    quality["range"] = format_range(stats.min, stats.max);
    quality["r_squared"] = attached.r_squared;
    quality["grid"] = std::to_string(height) + "×"
                      + std::to_string(width);
    quality["n_points"] = samples.report.n_valid;
    quality["backend"] = backend;
    quality["mean"] = Json(nullptr);
    if (std::isfinite(stats.mean)) {
        quality["mean"] = stats.mean;
    }
    // Python quality_metrics companions: distance policy annotation,
    // duplicate accounting, kriging variance envelope.
    if (!attached.constrained
        && !attached.grid.distance_policy_annotation.empty()) {
        quality["distance_policy"] =
            attached.grid.distance_policy_annotation;
    }
    quality["duplicate_locations_merged"] =
        samples.report.n_duplicate_groups;
    quality["duplicate_samples_merged"] =
        samples.report.n_duplicates_merged;
    quality["duplicate_policy"] = samples.report.policy;
    if (backend == "kriging") {
        double vmin = std::numeric_limits<double>::infinity();
        double vmax = -std::numeric_limits<double>::infinity();
        for (const float v : attached.grid.variance_grid) {
            if (!std::isfinite(v)) continue;
            vmin = std::min(vmin, static_cast<double>(v));
            vmax = std::max(vmax, static_cast<double>(v));
        }
        if (vmin <= vmax) {
            quality["variance_min"] = vmin;
            quality["variance_max"] = vmax;
        }
    }
    task_json["quality_metrics"] = std::move(quality);

    // grid_metadata descriptor (CONV-18 codec, metadata only).
    pwb::mapping::FactorGridEnvelope envelope;
    envelope.height = height;
    envelope.width = width;
    envelope.grid_x = attached.constrained
                          ? attached.constrained_grid.grid_x
                          : attached.grid.grid_x;
    envelope.grid_y = attached.constrained
                          ? attached.constrained_grid.grid_y
                          : attached.grid.grid_y;
    envelope.grid_z = attached.constrained
                          ? std::vector<float>(
                                attached.constrained_grid.grid_z.begin(),
                                attached.constrained_grid.grid_z.end())
                          : attached.grid.grid_z;
    envelope.factor_name = field_str(task_json, "factor_type",
                                     field_str(task_json, "name", ""));
    envelope.algorithm_id =
        attached.constrained ? "constrained_idw" : attached.grid.method;
    Json algorithm_parameters = Json::object();
    algorithm_parameters["result_fingerprint"] = fps.result;
    algorithm_parameters["r_squared"] = attached.r_squared;
    algorithm_parameters["n_points"] = samples.report.n_valid;
    algorithm_parameters["grid_label"] = std::to_string(height) + "×"
                                         + std::to_string(width);
    algorithm_parameters["n_break_lines"] = attached.n_break_lines;
    algorithm_parameters["method"] = method;
    if (backend == "idw" || backend == "constrained_idw") {
        algorithm_parameters["power"] = power;
    }
    envelope.algorithm_parameters = std::move(algorithm_parameters);
    envelope.crs = crs.empty() ? Json(nullptr) : Json(crs);
    envelope.generator_version = generator_version;
    envelope.statistics = stats;
    task_json["grid_metadata"] = pwb::mapping::to_descriptor(envelope);
}

[[nodiscard]] LiveGridEntry grid_entry_from_attached(
    const AttachedResult& attached,
    const pwb::factor_host::FactorFingerprints& fps, const Json& task_json,
    const std::string& crs, const std::string& generator_version,
    const Json& raw_points, const InterpSamples& samples,
    const std::string& method, int grid_n, double power,
    const ConstraintSet& constraints, const AnisotropyParams& anisotropy,
    const std::string& backend) {
    // Build the entry via the same attach path (single writer of the
    // descriptor), then harvest the pieces.
    Json scratch = task_json;
    attach_result_to_task(scratch, raw_points, samples, attached, method,
                          grid_n, power, constraints, fps, backend,
                          anisotropy, generator_version, crs);
    LiveGridEntry entry;
    entry.grid_x = attached.constrained ? attached.constrained_grid.grid_x
                                        : attached.grid.grid_x;
    entry.grid_y = attached.constrained ? attached.constrained_grid.grid_y
                                        : attached.grid.grid_y;
    entry.grid_z = attached.constrained
                       ? std::vector<float>(
                             attached.constrained_grid.grid_z.begin(),
                             attached.constrained_grid.grid_z.end())
                       : attached.grid.grid_z;
    entry.variance_grid = attached.grid.variance_grid;
    entry.result_fingerprint = fps.result;
    entry.metadata = scratch["grid_metadata"];
    return entry;
}

// Ensure a task JSON exists for synthesized default tasks (no source).
// The synthesized sample points ride the any-map (the scheduler's
// convention) — materialize them into the parameters JSON so the batch
// path and the commit see the same document a project task would have.
[[nodiscard]] Json task_json_from_slice(const FactorTaskSlice& task) {
    if (task.source_json.has_value() && task.source_json->is_object()) {
        return *task.source_json;
    }
    Json out = Json::object();
    out["id"] = task.id;
    out["name"] = task.name;
    out["target_horizon"] = task.target_horizon;
    out["factor_type"] = task.factor_type;
    out["method"] = task.method;
    out["status"] = task.status;
    out["source_kind"] = task.source_kind;
    if (task.seed.has_value()) out["seed"] = *task.seed;
    Json parameters = Json::object();
    const auto points = task.parameters.find("sample_points");
    if (points != task.parameters.end()) {
        parameters["sample_points"] = sample_points_to_json(points->second);
    }
    const auto last_error = task.parameters.find("last_error");
    if (last_error != task.parameters.end()) {
        if (const auto* error = std::any_cast<std::string>(&last_error->second)) {
            parameters["last_error"] = *error;
        }
    }
    out["parameters"] = std::move(parameters);
    return out;
}

void fail_task(Json& task_json, FactorTaskSlice& slice,
               const std::string& error) {
    task_json["status"] = "failed";
    if (!task_json.contains("parameters")
        || !task_json["parameters"].is_object()) {
        task_json["parameters"] = Json::object();
    }
    task_json["parameters"]["last_error"] = error;
    slice.status = "failed";
    slice.parameters["last_error"] = error;
    slice.source_json = task_json;
}

}  // namespace

// ------------------------------------------------------------- live store --

struct LiveFactorGridStore::Impl {
    mutable std::mutex mutex;
    std::list<std::pair<std::string, LiveGridEntry>> lru;
    std::size_t max_entries = 64;
    std::size_t max_bytes = 256u * 1024u * 1024u;
    std::shared_ptr<const ui_workers::FactorPrepareBatchResult> last_result;

    [[nodiscard]] static std::size_t entry_bytes(const LiveGridEntry& e) {
        return e.grid_x.size() * sizeof(double)
               + e.grid_y.size() * sizeof(double)
               + e.grid_z.size() * sizeof(float)
               + e.variance_grid.size() * sizeof(float);
    }

    void evict_locked() {
        while (!lru.empty()
               && (lru.size() > max_entries
                   || total_bytes_locked() > max_bytes)) {
            lru.pop_front();
        }
    }

    [[nodiscard]] std::size_t total_bytes_locked() const {
        std::size_t total = 0;
        for (const auto& [id, entry] : lru) total += entry_bytes(entry);
        return total;
    }
};

LiveFactorGridStore::LiveFactorGridStore() : impl_(new Impl()) {
    impl_->max_entries = static_cast<std::size_t>(
        ui_workers::env_int("PALEO_LIVE_FACTOR_GRIDS_MAX", 64));
    const int mb = ui_workers::env_int(
        "PALEO_LIVE_FACTOR_GRIDS_MAX_BYTES_MB", 256);
    impl_->max_bytes =
        static_cast<std::size_t>(std::max(1, mb)) * 1024u * 1024u;
}

void LiveFactorGridStore::store(const std::string& task_id,
                                LiveGridEntry grid) {
    std::lock_guard<std::mutex> guard(impl_->mutex);
    impl_->lru.remove_if(
        [&](const std::pair<std::string, LiveGridEntry>& item) {
            return item.first == task_id;
        });
    impl_->lru.emplace_back(task_id, std::move(grid));
    impl_->evict_locked();
}

std::optional<LiveGridEntry> LiveFactorGridStore::peek(
    const std::string& task_id) const {
    std::lock_guard<std::mutex> guard(impl_->mutex);
    for (auto it = impl_->lru.begin(); it != impl_->lru.end(); ++it) {
        if (it->first == task_id) {
            // LRU semantics: a hit refreshes recency (move to back).
            impl_->lru.splice(impl_->lru.end(), impl_->lru, it);
            return it->second;
        }
    }
    return std::nullopt;
}

void LiveFactorGridStore::clear(const std::string& task_id) {
    std::lock_guard<std::mutex> guard(impl_->mutex);
    impl_->lru.remove_if(
        [&](const std::pair<std::string, LiveGridEntry>& item) {
            return item.first == task_id;
        });
}

bool LiveFactorGridStore::clear_if_fingerprint(const std::string& task_id,
                                               const std::string&
                                                   fingerprint) {
    if (fingerprint.empty()) return false;
    std::lock_guard<std::mutex> guard(impl_->mutex);
    for (auto it = impl_->lru.begin(); it != impl_->lru.end(); ++it) {
        if (it->first == task_id
            && it->second.result_fingerprint == fingerprint) {
            impl_->lru.erase(it);
            return true;
        }
    }
    return false;
}

bool LiveFactorGridStore::has(const std::string& task_id) const {
    std::lock_guard<std::mutex> guard(impl_->mutex);
    for (const auto& [id, entry] : impl_->lru) {
        if (id == task_id) return true;
    }
    return false;
}

std::size_t LiveFactorGridStore::size() const {
    std::lock_guard<std::mutex> guard(impl_->mutex);
    return impl_->lru.size();
}

void LiveFactorGridStore::stash_last_result(
    std::shared_ptr<const ui_workers::FactorPrepareBatchResult> result) {
    std::lock_guard<std::mutex> guard(impl_->mutex);
    impl_->last_result = std::move(result);
}

void LiveFactorGridStore::clear_all() {
    std::lock_guard<std::mutex> guard(impl_->mutex);
    impl_->lru.clear();
    impl_->last_result = nullptr;
}

std::optional<ui_workers::FactorPrepareBatchResult>
LiveFactorGridStore::take_last_result() {
    std::lock_guard<std::mutex> guard(impl_->mutex);
    if (impl_->last_result == nullptr) return std::nullopt;
    auto copy = *impl_->last_result;
    impl_->last_result = nullptr;  // one-shot: a stale stash never lands twice
    return copy;
}

// ---------------------------------------------------------- slice builder --

ui_workers::PrepareProjectSlice build_prepare_slice(const Json& project_root) {
    ui_workers::PrepareProjectSlice slice;
    if (!project_root.is_object()) return slice;

    const Json* tasks = find_field(project_root, "factor_map_tasks");
    if (tasks != nullptr && tasks->is_array()) {
        for (const auto& entry : *tasks) {
            if (!entry.is_object()) continue;
            FactorTaskSlice task;
            task.id = field_str(entry, "id");
            task.name = field_str(entry, "name");
            task.status = field_str(entry, "status", "pending");
            task.target_horizon = field_str(entry, "target_horizon");
            task.factor_type = field_str(entry, "factor_type");
            task.method = field_str(entry, "method");
            task.source_kind = field_str(entry, "source_kind", "mock");
            task.input_snapshot_hash =
                field_str(entry, "input_snapshot_hash");
            task.grid_artifact_path = field_str(entry, "grid_artifact_path");
            const Json* seed = find_field(entry, "seed");
            if (seed != nullptr && seed->is_number_integer()) {
                task.seed = static_cast<int>(seed->get<long long>());
            }
            const Json* params = find_field(entry, "parameters");
            if (params != nullptr && params->is_object()) {
                const Json* points = find_field(*params, "sample_points");
                if (points != nullptr && points->is_array()) {
                    task.parameters["sample_points"] =
                        sample_points_to_any(*points);
                }
            }
            task.source_json = entry;
            slice.factor_map_tasks.push_back(std::move(task));
        }
    }

    const Json* layers = find_field(project_root, "constraint_layers");
    if (layers != nullptr && layers->is_array()) {
        for (const auto& layer : *layers) {
            slice.constraint_layers.emplace_back(layer);
        }
    }

    Json coordinate = Json::object();
    if (const Json* field = find_field(project_root, "coordinate")) {
        if (field->is_object()) coordinate = *field;
    }
    Json stratigraphy = Json::object();
    if (const Json* field = find_field(project_root, "stratigraphy")) {
        if (field->is_object()) stratigraphy = *field;
    }
    slice.coordinate = coordinate;
    slice.stratigraphy = stratigraphy;
    slice.stratigraphy_target_horizon =
        field_str(stratigraphy, "target_horizon");
    const std::string crs = field_str(coordinate, "project_crs");
    slice.project_crs = crs.empty() ? std::optional<std::string>()
                                    : std::optional<std::string>(crs);
    return slice;
}

// ---------------------------------------------------------------- kernels --

ui_workers::FactorPrepareSeams make_factor_prepare_seams(
    std::shared_ptr<LiveFactorGridStore> grids,
    const FactorPrepareKernelConfig& config) {
    ui_workers::FactorPrepareSeams seams;
    auto grids_ptr = grids.get();

    seams.classify_fn =
        [grids_ptr, generator = config.generator_version](
            const FactorTaskSlice& task,
            const ui_workers::PrepareExecContext& ctx, bool force,
            ui_workers::FingerprintMemo* memo)
        -> std::pair<FactorDirtyState, std::string> {
        auto resolved = fingerprints_for_task(task, ctx, generator, memo);
        if (!resolved.error.empty()) {
            // Python: classification ValueError fails the task — expressed
            // as UNKNOWN (non-CLEAN, lands on the dirty side) and the batch
            // path re-raises the concrete error when it runs.
            return {FactorDirtyState::unknown, ""};
        }
        const Json empty_object = Json::object();
        const Json empty_metadata = Json::object();
        const Json& params = [&]() -> const Json& {
            if (task.source_json.has_value()
                && task.source_json->is_object()) {
                const Json* field =
                    find_field(*task.source_json, "parameters");
                if (field != nullptr && field->is_object()) return *field;
            }
            return empty_object;
        }();
        const Json& grid_metadata = [&]() -> const Json& {
            if (task.source_json.has_value()
                && task.source_json->is_object()) {
                const Json* field =
                    find_field(*task.source_json, "grid_metadata");
                if (field != nullptr && field->is_object()) {
                    return *field;
                }
            }
            return empty_metadata;
        }();
        pwb::factor_host::FactorTaskView view;
        view.parameters = &params;
        view.grid_metadata = &grid_metadata;
        view.status = task.status;
        view.input_snapshot_hash = task.input_snapshot_hash;
        view.grid_artifact_path = task.grid_artifact_path;
        view.grid_artifact_version_id =
            field_str(*task.source_json, "grid_artifact_version_id");
        view.has_live_factor_grid =
            grids_ptr != nullptr && grids_ptr->has(task.id);
        const auto state = pwb::factor_host::classify_factor_recompute(
            view, resolved.fingerprints, force);
        FactorDirtyState mapped;
        switch (state) {
        case pwb::factor_host::FactorDirtyState::CLEAN:
            mapped = FactorDirtyState::clean;
            break;
        case pwb::factor_host::FactorDirtyState::DIRTY_VALUES:
            mapped = FactorDirtyState::dirty_values;
            break;
        case pwb::factor_host::FactorDirtyState::DIRTY_GEOMETRY:
            mapped = FactorDirtyState::dirty_geometry;
            break;
        case pwb::factor_host::FactorDirtyState::DIRTY_ALGORITHM:
            mapped = FactorDirtyState::dirty_algorithm;
            break;
        case pwb::factor_host::FactorDirtyState::DIRTY_CONSTRAINTS:
            mapped = FactorDirtyState::dirty_constraints;
            break;
        case pwb::factor_host::FactorDirtyState::MISSING_OUTPUT:
            mapped = FactorDirtyState::missing_output;
            break;
        case pwb::factor_host::FactorDirtyState::UNKNOWN:
        default:
            mapped = FactorDirtyState::unknown;
            break;
        }
        return {mapped, resolved.fingerprints.result};
    };

    seams.batch_fn =
        [grids_ptr, generator = config.generator_version](
            ui_workers::FactorPrepareSeams::BatchArgs& args,
            const job::CancellationToken& token) {
        for (auto& task : args.tasks) {
            try {
                token.check_cancelled();
                Json task_json = task_json_from_slice(task);
                if (!task_json.contains("parameters")
                    || !task_json["parameters"].is_object()) {
                    task_json["parameters"] = Json::object();
                }
                Json& params = task_json["parameters"];
                const Json raw_points = params.value(
                    "sample_points", Json::array());

                auto resolved = fingerprints_for_task(task, args.ctx,
                                                      generator, args.memo);
                if (!resolved.error.empty()) {
                    fail_task(task_json, task, resolved.error);
                    continue;
                }

                const std::string crs =
                    args.ctx.project_crs.value_or("");
                if (!crs.empty()
                    || !args.ctx.constraint_layers.empty()) {
                    // CRS discipline over the consumed constraint groups.
                    const auto probe = resolve_constraints(
                        args.ctx.constraint_layers,
                        args.ctx.target_horizon, crs);
                    if (!probe.crs_conflict.empty()) {
                        fail_task(task_json, task, probe.crs_conflict);
                        continue;
                    }
                }

                const std::string method = [&] {
                    std::string label = task.method;
                    if (!args.ctx.method.empty()) label = args.ctx.method;
                    return label;
                }();
                int grid_n = args.ctx.grid_n;
                if (grid_n <= 0) grid_n = ui_workers::kDefaultGridN;
                grid_n = std::max(20, std::min(200, grid_n));
                const double power = args.ctx.power;

                const ConstraintSet constraints = resolve_constraints(
                    args.ctx.constraint_layers, args.ctx.target_horizon,
                    crs);
                const AnisotropyParams anisotropy =
                    resolve_anisotropy(resolved.direction_params, params);

                const InterpSamples samples =
                    load_samples(raw_points, params);
                AttachedResult attached;
                try {
                    attached = apply_interpolation(
                        raw_points, params, method, grid_n, power,
                        constraints, crs, resolved.fingerprints, token);
                } catch (const job::JobCancelled&) {
                    throw;
                } catch (const std::exception& exc) {
                    fail_task(task_json, task, exc.what());
                    continue;
                }

                attach_result_to_task(task_json, raw_points, samples,
                                      attached, method, grid_n, power,
                                      constraints, resolved.fingerprints,
                                      attached.backend, anisotropy,
                                      generator, crs);
                if (grids_ptr != nullptr) {
                    grids_ptr->store(
                        task.id,
                        grid_entry_from_attached(
                            attached, resolved.fingerprints, task_json, crs,
                            generator, raw_points, samples, method, grid_n,
                            power, constraints, anisotropy,
                            attached.backend));
                }
                task.status = "complete";
                task.parameters.erase("last_error");
                task.source_json = std::move(task_json);
            } catch (const job::JobCancelled&) {
                throw;
            } catch (const std::exception& exc) {
                // _apply_interpolation_isolated: only this task fails.
                Json task_json = task_json_from_slice(task);
                fail_task(task_json, task, exc.what());
            }
        }
    };

    seams.group_key_fn =
        [](const FactorTaskSlice& task,
           const ui_workers::PrepareExecContext& ctx)
        -> std::optional<std::string> {
        const std::string method = [&] {
            std::string label = task.method;
            if (!ctx.method.empty()) label = ctx.method;
            return label;
        }();
        if (method != "IDW" && method != "idw" && method != "mock") {
            return std::nullopt;
        }
        // _task_plan_group_key parity: the NORMALIZED sample set feeds
        // the geometry digest (duplicates/partial-invalid inputs group
        // like the oracle).
        Json raw_points = sample_points_to_json(
            [&] {
                const auto it = task.parameters.find("sample_points");
                return it != task.parameters.end() ? it->second
                                                   : std::any{};
            }());
        try {
            raw_points = pwb::mapping::normalize_factor_samples(
                                 raw_points,
                                 pwb::mapping::duplicate_policy_from_params(
                                     nlohmann_json_empty_params()))
                             .first;
        } catch (const std::exception&) {
            return std::nullopt;
        }
        const auto constraints = resolve_constraints(
            ctx.constraint_layers, ctx.target_horizon,
            ctx.project_crs.value_or(""));
        std::vector<pwb::factor_host::Polyline> breaks;
        for (const auto& line : constraints.break_lines) {
            pwb::factor_host::Polyline polyline;
            for (const auto& [x, y] : line) polyline.emplace_back(x, y);
            breaks.push_back(std::move(polyline));
        }
        try {
            const auto plan = pwb::factor_host::build_idw_plan(
                raw_points, ctx.grid_n, ctx.power, &breaks);
            return plan.key.digest();
        } catch (const std::exception&) {
            return std::nullopt;
        }
    };

    seams.grid_peek_fn = [grids_ptr](const std::string& task_id) {
        if (grids_ptr == nullptr) return std::any{};
        auto entry = grids_ptr->peek(task_id);
        if (!entry.has_value()) return std::any{};
        return std::any(std::move(*entry));
    };

    seams.governor_clamp_fn = [max_workers = config.max_workers](
                                  int requested) {
        int hardware = static_cast<int>(std::thread::hardware_concurrency());
        if (hardware <= 0) hardware = 1;
        int bounded = std::max(1, std::min({requested, hardware, 4}));
        if (max_workers > 0) bounded = std::min(bounded, max_workers);
        return std::max(1, bounded);
    };

    seams.synthetic_points_fn =
        [](int seed, const std::string& factor_type) {
            return std::any(ui_workers::synthetic_sample_points(
                seed, factor_type));
        };

    seams.stratigraphy_with_horizon_fn =
        [](const std::any& stratigraphy, const std::string& horizon) {
            Json updated = Json::object();
            if (const auto* json = std::any_cast<Json>(&stratigraphy)) {
                if (json->is_object()) updated = *json;
            }
            updated["target_horizon"] = horizon;
            return std::any(std::move(updated));
        };

    return seams;
}

// ---------------------------------------------------------- well-table ops --

std::string value_key_for_factor_type(const std::string& factor_type) {
    // well_table.py parity: normalized EXACT/alias equality (casefold,
    // stripped) — never substring matching (#1151: a mis-selection mixes
    // physical dimensions).
    std::string key = factor_type;
    const auto normalize = [](std::string value) {
        value.erase(0, value.find_first_not_of(" \t"));
        value.erase(value.find_last_not_of(" \t") + 1);
        std::transform(value.begin(), value.end(), value.begin(),
                       [](unsigned char c) {
                           return static_cast<char>(
                               std::tolower(c));
                       });
        return value;
    };
    key = normalize(std::move(key));
    const auto matches = [&](std::initializer_list<const char*> aliases) {
        for (const char* alias : aliases) {
            if (key == normalize(alias)) return true;
        }
        return false;
    };
    if (matches({"砂地比", "sand_ratio", "r_s", "rs"})) return "R_s";
    if (matches({"地层厚度", "thickness", "h_t", "ht", "total_thickness",
                 "formation_thickness"})) {
        return "H_t";
    }
    if (matches({"砂岩厚度", "sand_thickness", "h_s", "hs", "sand"})) {
        return "H_s";
    }
    return "z";
}

Json sample_points_from_well_table(const Json& well_table,
                                   bool include_flagged,
                                   const std::string& value_key_override) {
    Json out = Json::array();
    const std::string value_key = value_key_override.empty()
                                      ? value_key_for_factor_type(
                                            field_str(well_table,
                                                      "factor_type"))
                                      : value_key_override;
    const Json* rows = find_field(well_table, "rows");
    if (rows == nullptr || !rows->is_array()) return out;
    for (const auto& row : *rows) {
        if (!row.is_object()) continue;
        const std::string qc = field_str(row, "qc_flag", "ok");
        if (!include_flagged && qc != "ok") continue;
        const Json* value = find_field(row, value_key);
        if (value == nullptr || !value->is_number()) continue;
        if (!std::isfinite(value->get<double>())) continue;
        Json point = Json::object();
        point["well_id"] = field_str(row, "well_id");
        point["well"] = field_str(row, "name", field_str(row, "well_id"));
        point["x"] = row.value("x", 0.0);
        point["y"] = row.value("y", 0.0);
        point["value"] = value->get<double>();
        point["q"] = row.value("q", 1.0);
        point["b_i"] = row.value("b_i", 1.0);
        point["qc_flag"] = qc;
        out.push_back(std::move(point));
    }
    return out;
}

Json run_well_table_qc(Json& well_table, const std::string& value_key) {
    Json summary = Json::object();
    summary["ok"] = 0;
    summary["outlier"] = 0;
    summary["invalid_ratio"] = 0;
    summary["missing"] = 0;
    Json* rows = find_field(well_table, "rows");
    if (rows == nullptr || !rows->is_array()) return summary;

    // Sand-ratio validation first (invalid_ratio), then MAD outliers on the
    // factor's value column (threshold 3.5), Python run_well_table_qc.
    std::vector<double> values;
    for (auto& row : *rows) {
        if (!row.is_object()) continue;
        if (value_key == "R_s") {
            const double h_s = row.value("H_s", 0.0);
            const double h_t = row.value("H_t", 0.0);
            if (!(h_t > 0.0) || !(h_s >= 0.0) || !(h_s <= h_t)) {
                row["qc_flag"] = "invalid_ratio";
                row["R_s"] = Json(nullptr);
                row["b_i"] = 0.0;
                summary["invalid_ratio"] =
                    summary["invalid_ratio"].get<int>() + 1;
                continue;
            }
            row["R_s"] = h_s / h_t;
        }
        const std::string qc = field_str(row, "qc_flag", "ok");
        if (qc == "invalid_ratio" || qc == "missing") continue;
        const Json* value = find_field(row, value_key);
        if (value == nullptr || !value->is_number()
            || !std::isfinite(value->get<double>())) {
            row["qc_flag"] = "missing";
            row["b_i"] = 0.0;
            summary["missing"] = summary["missing"].get<int>() + 1;
            continue;
        }
        values.push_back(value->get<double>());
    }

    double median = 0.0;
    double mad = 0.0;
    const auto middle_of = [](std::vector<double> sorted) {
        std::sort(sorted.begin(), sorted.end());
        const std::size_t n = sorted.size();
        if (n == 0) return 0.0;
        return n % 2 == 1
                   ? sorted[n / 2]
                   : 0.5 * (sorted[n / 2 - 1] + sorted[n / 2]);
    };
    if (!values.empty()) {
        median = middle_of(values);
        std::vector<double> deviations;
        deviations.reserve(values.size());
        for (const double value : values) {
            deviations.push_back(std::abs(value - median));
        }
        mad = middle_of(std::move(deviations));
    }
    const double sem = 0.6745 * mad;  // consistent-estimator scaling

    for (auto& row : *rows) {
        if (!row.is_object()) continue;
        const std::string qc = field_str(row, "qc_flag", "ok");
        if (qc == "invalid_ratio") continue;
        const Json* value = find_field(row, value_key);
        if (value == nullptr || !value->is_number()) {
            if (qc != "missing") {
                row["qc_flag"] = "missing";
                summary["missing"] =
                    summary["missing"].get<int>() + 1;
            }
            continue;
        }
        if (sem > 0.0) {
            const double z_star =
                0.6745 * (value->get<double>() - median) / mad;
            row["qc_z_star"] = z_star;
            if (std::abs(z_star) > 3.5) {
                row["qc_flag"] = "outlier";
                row["b_i"] = std::min(row.value("b_i", 1.0), 0.1);
                summary["outlier"] =
                    summary["outlier"].get<int>() + 1;
                continue;
            }
        }
        if (qc == "missing") continue;
        row["qc_flag"] = "ok";
        summary["ok"] = summary["ok"].get<int>() + 1;
    }
    return summary;
}

std::vector<std::string> sync_well_table_to_linked_tasks(
    Json& project_root, const Json& well_table,
    const std::string& value_key) {
    std::vector<std::string> updated;
    const std::string table_id = field_str(well_table, "id");
    if (table_id.empty()) return updated;
    const Json points =
        sample_points_from_well_table(well_table, /*include_flagged=*/false,
                                      value_key);
    Json* tasks = find_field(project_root, "factor_map_tasks");
    if (tasks == nullptr || !tasks->is_array()) return updated;
    std::size_t unbound_index = tasks->size();
    std::size_t unbound_count = 0;
    for (std::size_t i = 0; i < tasks->size(); ++i) {
        Json& task = (*tasks)[i];
        if (!task.is_object()) continue;
        Json* params = find_field(task, "parameters");
        const std::string bound = params != nullptr
                                      ? field_str(*params, "well_table_id")
                                      : "";
        if (bound.empty()) {
            ++unbound_count;
            if (unbound_index == tasks->size()) unbound_index = i;
        }
        if (bound != table_id) continue;
        if (params == nullptr) {
            task["parameters"] = Json::object();
            params = find_field(task, "parameters");
        }
        (*params)["sample_points"] = points;
        (*params)["well_table_id"] = table_id;
        updated.push_back(field_str(task, "id"));
    }
    // Legacy convenience: exactly one unbound task adopts the table.
    if (updated.empty() && unbound_count == 1
        && unbound_index < tasks->size()) {
        Json& task = (*tasks)[unbound_index];
        if (!task.contains("parameters")
            || !task["parameters"].is_object()) {
            task["parameters"] = Json::object();
        }
        task["parameters"]["sample_points"] = points;
        task["parameters"]["well_table_id"] = table_id;
        updated.push_back(field_str(task, "id"));
    }
    return updated;
}

// ------------------------------------------------------------- host commit --

CommitPrepareReport commit_prepare_batch_result(
    Json& project_root,
    const ui_workers::FactorPrepareBatchResult& result,
    int expected_generation, LiveFactorGridStore& grids,
    workflow_runtime::CatalogRepository* catalog,
    const std::string& project_crs) {
    CommitPrepareReport report;
    if (!project_root.is_object()) project_root = Json::object();
    if (!project_root.contains("factor_map_tasks")
        || !project_root["factor_map_tasks"].is_array()) {
        project_root["factor_map_tasks"] = Json::array();
    }
    Json& tasks = project_root["factor_map_tasks"];

    // Live project constraint slice for the stale-input re-derivation
    // (Python re-derives fingerprints_for_task against the LIVE project —
    // constraints included — with the scheduled overrides, no memo).
    std::vector<std::any> live_constraints;
    if (const Json* layers = find_field(project_root, "constraint_layers");
        layers != nullptr && layers->is_array()) {
        for (const auto& layer : *layers) {
            live_constraints.emplace_back(layer);
        }
    }
    std::string crs = project_crs;
    if (crs.empty()) {
        if (const Json* coordinate =
                find_field(project_root, "coordinate");
            coordinate != nullptr && coordinate->is_object()) {
            crs = field_str(*coordinate, "project_crs");
        }
    }
    const std::optional<std::string> crs_opt =
        crs.empty() ? std::optional<std::string>()
                    : std::optional<std::string>(crs);

    const auto evict_if_fingerprint =
        [&](const ui_workers::FactorPrepareTaskResult& item) {
            grids.clear_if_fingerprint(
                item.task_id, grid_result_fingerprint(item.grid));
        };

    // Catalog registration for one committed item (register_factor_map_run
    // port). Stamps grid_artifact_version_id into `patched` on success;
    // a registration failure records the error and degrades honestly.
    const auto register_factor_run =
        [&](Json& patched, const FactorTaskSlice& slice,
            const ui_workers::FactorPrepareTaskResult& item) {
            if (catalog == nullptr) return;
            std::string booked_run_id;
            try {
                const std::string generator_version =
                    ui_workers::kFactorInterpGeneratorVersion;
                Json parameters = Json::object();
                parameters["factor_type"] = slice.factor_type;
                parameters["target_horizon"] = slice.target_horizon;
                parameters["method"] = result.method;
                if (result.grid_n.has_value()) {
                    parameters["grid_n"] = *result.grid_n;
                }
                parameters["power"] = result.power;
                const Json* params = find_field(patched, "parameters");
                if (params != nullptr && params->is_object()) {
                    if (const Json* pins =
                            find_field(*params, "constraint_pins");
                        pins != nullptr && pins->is_array()) {
                        parameters["constraint_pins"] = *pins;
                    }
                    if (const Json* grid_label =
                            find_field(*params, "grid");
                        grid_label != nullptr && grid_label->is_string()) {
                        parameters["grid"] = *grid_label;
                    }
                    if (const Json* backend =
                            find_field(*params, "interp_backend");
                        backend != nullptr && backend->is_string()) {
                        parameters["backend"] = *backend;
                    }
                    if (const Json* n_points =
                            find_field(*params, "sample_normalization");
                        n_points != nullptr && n_points->is_object()) {
                        parameters["n_points"] =
                            n_points->value("n_valid", 0);
                    }
                }
                const std::string run_id = catalog->register_run(
                    "factor_map", /*input_version_ids=*/{}, parameters,
                    generator_version, "running", slice.id,
                    field_str(patched, "input_snapshot_hash"));
                booked_run_id = run_id;  // a booked run must not linger
                const auto* entry =
                    std::any_cast<LiveGridEntry>(&item.grid);
                if (entry == nullptr) {
                    // No grid payload (e.g. LRU eviction between execution
                    // and commit): register no version — an empty-payload
                    // INTERMEDIATE record would mispoint the lineage.
                    catalog->update_run_status(booked_run_id, "failed",
                                               Json{{"error",
                                                     "grid payload absent "
                                                     "at registration"}});
                    report.registration_errors.push_back(
                        slice.id + ": grid payload absent at registration");
                    return;
                }
                std::string payload;
                {
                    pwb::mapping::FactorGridEnvelope envelope;
                    envelope.height =
                        static_cast<int>(entry->grid_y.size());
                    envelope.width =
                        static_cast<int>(entry->grid_x.size());
                    envelope.grid_x = entry->grid_x;
                    envelope.grid_y = entry->grid_y;
                    envelope.grid_z = entry->grid_z;
                    envelope.variance_grid = entry->variance_grid;
                    envelope.factor_name = slice.factor_type;
                    envelope.algorithm_parameters = Json::object();
                    envelope.algorithm_parameters["result_fingerprint"] =
                        entry->result_fingerprint;
                    envelope.crs = crs.empty() ? Json(nullptr)
                                               : Json(crs);
                    envelope.generator_version = generator_version;
                    envelope.statistics = pwb::mapping::grid_statistics(
                        entry->grid_z);
                    payload =
                        pwb::mapping::to_legacy_dict(envelope).dump();
                }
                Json asset_metadata = Json::object();
                asset_metadata["task_id"] = slice.id;
                asset_metadata["factor_type"] = slice.factor_type;
                asset_metadata["target_horizon"] = slice.target_horizon;
                Json version_metadata = Json::object();
                version_metadata["generator"] = generator_version;
                const auto registered = catalog->register_result_asset(
                    (slice.target_horizon.empty() ? std::string("图件")
                                                  : slice.target_horizon)
                        + " " + slice.factor_type + " 网格",
                    "factor_map_grid", "json", asset_metadata, payload,
                    "INTERMEDIATE", run_id, version_metadata);
                catalog->attach_run_output(run_id, registered.version_id);
                catalog->update_run_status(run_id, "complete");
                patched["grid_artifact_version_id"] =
                    registered.version_id;
                report.registered_version_ids.push_back(
                    registered.version_id);
            } catch (const std::exception& exc) {
                report.registration_errors.push_back(slice.id + ": "
                                                     + exc.what());
                if (!booked_run_id.empty()) {
                    try {
                        catalog->update_run_status(
                            booked_run_id, "failed",
                            Json{{"error", exc.what()}});
                    } catch (const std::exception&) {
                        // best-effort failure bookkeeping only
                    }
                }
                // Provenance-safety failures (on-disk drift) must not be
                // swallowed: the caller detaches the rail instead.
                const std::string what = exc.what();
                if (what.find("changed on disk") != std::string::npos) {
                    throw;
                }
            }
        };

    if (result.generation != expected_generation) {
        for (const auto& item : result.task_results) {
            if (!item.reused) evict_if_fingerprint(item);
            report.discarded.push_back(item.task_id);
        }
        return report;
    }

    if (result.cancelled) {
        // Python routes cancel through the fingerprint-conditional
        // invalidation (#881): cancelled items carry no grid, so a run
        // that produced nothing clears nothing — the previous run's
        // still-valid payload survives.
        for (const auto& item : result.task_results) {
            if (item.reused) continue;
            evict_if_fingerprint(item);
            report.discarded.push_back(item.task_id);
        }
        return report;
    }

    // Live task index (id → position), Python id-first lookup.
    const auto build_index = [&tasks]() {
        std::unordered_map<std::string, std::size_t> index;
        for (std::size_t i = 0; i < tasks.size(); ++i) {
            if (tasks[i].is_object()) {
                index[field_str(tasks[i], "id")] = i;
            }
        }
        return index;
    };

    // First-prepare defaults bootstrap (#1159: late defaults never graft).
    if (result.created_default_tasks) {
        if (!tasks.empty()) {
            for (const auto& item : result.task_results) {
                report.discarded.push_back(item.task_id);
                evict_if_fingerprint(item);
            }
            return report;
        }
        Json replaced = Json::array();
        std::vector<const ui_workers::FactorPrepareTaskResult*> items;
        for (const auto& item : result.task_results) {
            if (item.reused || !item.task.has_value() || item.error) {
                report.discarded.push_back(item.task_id);
                evict_if_fingerprint(item);
                continue;
            }
            Json patched = task_json_from_slice(*item.task);
            patched["id"] = item.task->id;
            register_factor_run(patched, *item.task, item);
            replaced.push_back(std::move(patched));
            items.push_back(&item);
        }
        tasks = std::move(replaced);
        for (std::size_t i = 0; i < items.size(); ++i) {
            const auto* entry =
                std::any_cast<LiveGridEntry>(&items[i]->grid);
            if (entry != nullptr) {
                grids.store(items[i]->task_id, *entry);
            }
            ++report.applied;
        }
        return report;
    }

    auto index = build_index();
    for (const auto& item : result.task_results) {
        if (item.reused) continue;
        if (!item.task.has_value() || item.error) {
            report.discarded.push_back(item.task_id);
            evict_if_fingerprint(item);
            continue;
        }
        const FactorTaskSlice& slice = *item.task;
        const auto it = index.find(slice.id);
        if (it == index.end()) {
            report.discarded.push_back(slice.id);
            evict_if_fingerprint(item);
            continue;
        }
        Json& live = tasks[it->second];

        // Stale-input guard: re-derive from the LIVE task under the
        // SCHEDULED overrides, no memo, live constraints.
        if (item.scheduled_result_fingerprint.has_value()
            && !item.scheduled_result_fingerprint->empty()) {
            FactorTaskSlice live_view;
            live_view.id = slice.id;
            live_view.name = field_str(live, "name");
            live_view.status = field_str(live, "status", "pending");
            live_view.target_horizon = field_str(live, "target_horizon");
            live_view.factor_type = field_str(live, "factor_type");
            live_view.method = field_str(live, "method");
            live_view.source_kind = field_str(live, "source_kind", "mock");
            live_view.input_snapshot_hash =
                field_str(live, "input_snapshot_hash");
            live_view.grid_artifact_path =
                field_str(live, "grid_artifact_path");
            live_view.source_json = live;
            if (const Json* live_params = find_field(live, "parameters");
                live_params != nullptr && live_params->is_object()) {
                if (const Json* points =
                        find_field(*live_params, "sample_points");
                    points != nullptr && points->is_array()) {
                    live_view.parameters["sample_points"] =
                        sample_points_to_any(*points);
                }
            }
            std::any recheck_coordinate;
            std::any recheck_stratigraphy;
            ui_workers::PrepareExecContext recheck_ctx{
                recheck_coordinate, recheck_stratigraphy, live_constraints,
                crs_opt, result.method,
                result.grid_n.value_or(0), result.power, /*seed=*/0,
                slice.target_horizon};
            bool stale = false;
            try {
                const auto current = fingerprints_for_task(
                    live_view, recheck_ctx,
                    ui_workers::kFactorInterpGeneratorVersion, nullptr);
                stale = current.error.empty()
                            ? current.fingerprints.result
                                  != *item.scheduled_result_fingerprint
                            : true;
            } catch (const std::exception&) {
                stale = true;
            }
            if (stale) {
                report.discarded.push_back(slice.id);
                evict_if_fingerprint(item);
                continue;
            }
        }

        Json patched = task_json_from_slice(slice);
        patched["id"] = slice.id;  // identity, never regenerated
        register_factor_run(patched, slice, item);

        tasks[it->second] = std::move(patched);
        ++report.applied;
        if (const auto* entry = std::any_cast<LiveGridEntry>(&item.grid)) {
            grids.store(slice.id, *entry);
        } else {
            grids.clear(slice.id);
        }
    }
    return report;
}

// -------------------------------------------------------- contour commit --

int commit_contour_drafts_full(Json& project_root, const Json& drafts_array) {
    if (!project_root.is_object()) project_root = Json::object();
    if (!drafts_array.is_array() || drafts_array.empty()) return 0;
    if (!project_root.contains("contour_drafts")
        || !project_root["contour_drafts"].is_array()) {
        project_root["contour_drafts"] = Json::array();
    }
    if (!project_root.contains("paleomap_documents")
        || !project_root["paleomap_documents"].is_array()) {
        project_root["paleomap_documents"] = Json::array();
    }
    Json& drafts = project_root["contour_drafts"];
    Json& documents = project_root["paleomap_documents"];

    int count = 0;
    for (const auto& draft : drafts_array) {
        if (!draft.is_object()) continue;
        const std::string task_link =
            field_str(draft, "linked_factor_task_id");
        const std::string generator =
            field_str(draft, "generator_version", "contour-draft-v2");

        // Upsert: same linked task, else same horizon+factor+generator when
        // unlinked — the existing id is kept (Python upsert_contour_draft).
        Json* target = nullptr;
        for (auto& existing : drafts) {
            if (!existing.is_object()) continue;
            const std::string existing_task =
                field_str(existing, "linked_factor_task_id");
            if (!task_link.empty() && existing_task == task_link) {
                target = &existing;
                break;
            }
            if (task_link.empty() && existing_task.empty()
                && field_str(existing, "target_horizon")
                       == field_str(draft, "target_horizon")
                && field_str(existing, "factor_type")
                       == field_str(draft, "factor_type")
                && field_str(existing, "generator_version",
                             "contour-draft-v2")
                       == generator) {
                target = &existing;
                break;
            }
        }
        Json committed = draft;
        std::string prior_map_document_id;
        if (target != nullptr) {
            committed["id"] = field_str(*target, "id");
            committed["created_at"] =
                field_str(*target, "created_at", now_iso());
            // The wholesale replacement must not drop the map-document
            // backlink the previous commit established (it selects the
            // document below; losing it would mint a duplicate document).
            prior_map_document_id =
                field_str(*target, "linked_map_document_id");
            if (!prior_map_document_id.empty()) {
                committed["linked_map_document_id"] = prior_map_document_id;
            }
            *target = std::move(committed);
        } else {
            if (field_str(committed, "id").empty()) {
                committed["id"] = new_id("cdraft");
            }
            if (!committed.contains("created_at")
                || !committed["created_at"].is_string()) {
                committed["created_at"] = now_iso();
            }
            drafts.push_back(std::move(committed));
            target = &drafts.back();
        }
        (*target)["updated_at"] = now_iso();
        (*target)["status"] = "editing";

        // apply_contour_draft_to_map: reuse the linked document or create
        // one; strip existing contour line features, append the new set.
        std::string document_id = field_str(*target, "linked_map_document_id");
        Json* document = nullptr;
        if (!document_id.empty()) {
            for (auto& existing : documents) {
                if (existing.is_object()
                    && field_str(existing, "id") == document_id) {
                    document = &existing;
                    break;
                }
            }
        }
        if (document == nullptr) {
            Json created = Json::object();
            document_id = new_id("map");
            created["id"] = document_id;
            created["name"] = [&] {
                const std::string horizon =
                    field_str(*target, "target_horizon");
                return (horizon.empty() ? std::string("图件") : horizon)
                       + " 等值线";
            }();
            created["linked_target_horizon"] =
                field_str(*target, "target_horizon");
            created["linked_prediction_task_id"] = Json(nullptr);
            created["linked_contour_draft_id"] = field_str(*target, "id");
            created["linked_factor_task_id"] =
                field_str(*target, "linked_factor_task_id").empty()
                    ? Json(nullptr)
                    : Json(field_str(*target,
                                     "linked_factor_task_id"));
            created["facies_polygons"] = Json::array();
            created["facies_style"] = Json::object();
            created["well_overlays"] = Json::array();
            created["line_features"] = Json::array();
            created["label_features"] = Json::array();
            created["reference_layers"] = Json::array();
            created["map_chrome"] = Json::object();
            created["map_crs"] = Json(nullptr);
            created["layer_state"] = Json::object();
            created["view_state"] = Json::object();
            created["edit_history"] = Json::array();
            documents.push_back(std::move(created));
            document = &documents.back();
        }
        (*target)["linked_map_document_id"] = document_id;

        if (!document->contains("line_features")
            || !(*document)["line_features"].is_array()) {
            (*document)["line_features"] = Json::array();
        }
        // apply_contour_draft_to_map parity: strip BOTH the top-level
        // role=="contour" features and property-tagged ones (properties
        // .role / .contour_draft_id) so repeated commits never stack.
        Json& line_features = (*document)["line_features"];
        const std::string draft_id = field_str(*target, "id");
        line_features.erase(
            std::remove_if(line_features.begin(), line_features.end(),
                           [&](const Json& feature) {
                               if (!feature.is_object()) return false;
                               if (field_str(feature, "role") == "contour") {
                                   return true;
                               }
                               const Json* props =
                                   find_field(feature, "properties");
                               if (props == nullptr || !props->is_object()) {
                                   return false;
                               }
                               if (field_str(*props, "role") == "contour") {
                                   return true;
                               }
                               return field_str(*props, "contour_draft_id")
                                      == draft_id;
                           }),
            line_features.end());
        (*document)["linked_contour_draft_id"] = draft_id;
        (*document)["linked_target_horizon"] =
            field_str(*target, "target_horizon");
        const Json* segments = find_field(*target, "segments");
        if (segments != nullptr && segments->is_array()) {
            for (const auto& segment : *segments) {
                if (!segment.is_object()) continue;
                Json feature = Json::object();
                feature["id"] = new_id("feat");
                feature["kind"] = "line";
                const double level = segment.value("level", 0.0);
                std::ostringstream label;
                label.precision(6);
                label << "L=" << level;
                feature["name"] = label.str();
                feature["role"] = "contour";
                feature["coordinates"] =
                    segment.value("coordinates", Json::array());
                Json properties = Json::object();
                properties["role"] = "contour";
                properties["constraint_role"] = "contour";
                properties["level"] = level;
                properties["closed"] =
                    segment.value("closed", false);
                properties["contour_draft_id"] = field_str(*target, "id");
                properties["factor_type"] = field_str(*target, "factor_type");
                properties["target_horizon"] =
                    field_str(*target, "target_horizon");
                feature["properties"] = std::move(properties);
                line_features.push_back(std::move(feature));
            }
        }
        ++count;
    }
    return count;
}

// ---------------------------------------------------- persistent catalog --

namespace {

// Record codecs — the FileCatalogRepository (<root>.json) field contract.
[[nodiscard]] Json encode_asset(
    const pwb::workflow_runtime::AssetRecord& asset) {
    Json out = Json::object();
    out["id"] = asset.id;
    out["name"] = asset.name;
    out["type"] = asset.type;
    out["format"] = asset.format;
    out["current_version_id"] = asset.current_version_id.has_value()
                                    ? Json(*asset.current_version_id)
                                    : Json(nullptr);
    out["metadata"] =
        asset.metadata.is_object() ? asset.metadata : Json::object();
    return out;
}

[[nodiscard]] pwb::workflow_runtime::AssetRecord decode_asset(
    const Json& node) {
    pwb::workflow_runtime::AssetRecord asset;
    asset.id = node.value("id", "");
    asset.name = node.value("name", "");
    asset.type = node.value("type", "");
    asset.format = node.value("format", "");
    if (const Json* field = find_field(node, "current_version_id");
        field != nullptr && field->is_string()) {
        asset.current_version_id = field->get<std::string>();
    }
    if (const Json* field = find_field(node, "metadata");
        field != nullptr && field->is_object()) {
        asset.metadata = *field;
    }
    return asset;
}

[[nodiscard]] Json encode_version(
    const pwb::workflow_runtime::VersionRecord& version) {
    Json out = Json::object();
    out["asset_id"] = version.asset_id;
    out["version_id"] = version.version_id;
    out["name"] = version.name;
    out["producing_run_id"] = version.producing_run_id.has_value()
                                  ? Json(*version.producing_run_id)
                                  : Json(nullptr);
    out["checksum"] = version.checksum;
    out["trashed"] = version.trashed;
    out["path"] = version.path;
    out["created_at"] = version.created_at;
    out["metadata"] = version.metadata.is_object() ? version.metadata
                                                   : Json::object();
    out["payload_json"] = version.payload_json;
    return out;
}

[[nodiscard]] pwb::workflow_runtime::VersionRecord decode_version(
    const Json& node) {
    pwb::workflow_runtime::VersionRecord version;
    version.asset_id = node.value("asset_id", "");
    version.version_id = node.value("version_id", "");
    version.name = node.value("name", "");
    if (const Json* field = find_field(node, "producing_run_id");
        field != nullptr && field->is_string()) {
        version.producing_run_id = field->get<std::string>();
    }
    version.checksum = node.value("checksum", "");
    version.trashed = node.value("trashed", false);
    version.path = node.value("path", "");
    version.created_at = node.value("created_at", "");
    if (const Json* field = find_field(node, "metadata");
        field != nullptr && field->is_object()) {
        version.metadata = *field;
    }
    if (const Json* field = find_field(node, "payload_json");
        field != nullptr && field->is_string()
        && !field->get<std::string>().empty()) {
        version.payload_json = field->get<std::string>();
    }
    // Sidecar payloads (metadata-only stores): lazily re-read.
    if (version.payload_json.empty() && !version.path.empty()) {
        std::ifstream payload_in(version.path, std::ios::binary);
        if (payload_in) {
            version.payload_json.assign(
                std::istreambuf_iterator<char>(payload_in),
                std::istreambuf_iterator<char>());
        }
    }
    return version;
}

[[nodiscard]] Json encode_run(const pwb::workflow_runtime::RunRecord& run) {
    Json out = Json::object();
    out["run_id"] = run.run_id;
    out["operation"] = run.operation;
    out["input_version_ids"] = run.input_version_ids;
    out["output_version_ids"] = run.output_version_ids;
    out["parameters"] =
        run.parameters.is_object() ? run.parameters : Json::object();
    out["generator_version"] = run.generator_version.has_value()
                                   ? Json(*run.generator_version)
                                   : Json(nullptr);
    out["domain_task_id"] = run.domain_task_id.has_value()
                                ? Json(*run.domain_task_id)
                                : Json(nullptr);
    out["input_snapshot_hash"] = run.input_snapshot_hash.has_value()
                                     ? Json(*run.input_snapshot_hash)
                                     : Json(nullptr);
    out["status"] = run.status;
    out["started_at"] =
        run.started_at.has_value() ? Json(*run.started_at) : Json(nullptr);
    out["finished_at"] =
        run.finished_at.has_value() ? Json(*run.finished_at) : Json(nullptr);
    out["actor"] = run.actor.has_value() ? Json(*run.actor) : Json(nullptr);
    out["run_metadata"] = run.run_metadata.is_object() ? run.run_metadata
                                                       : Json::object();
    return out;
}

[[nodiscard]] pwb::workflow_runtime::RunRecord decode_run(const Json& node) {
    pwb::workflow_runtime::RunRecord run;
    run.run_id = node.value("run_id", "");
    run.operation = node.value("operation", "");
    if (const Json* field = find_field(node, "input_version_ids");
        field != nullptr && field->is_array()) {
        run.input_version_ids =
            field->get<std::vector<std::string>>();
    }
    if (const Json* field = find_field(node, "output_version_ids");
        field != nullptr && field->is_array()) {
        run.output_version_ids =
            field->get<std::vector<std::string>>();
    }
    if (const Json* field = find_field(node, "parameters");
        field != nullptr && field->is_object()) {
        run.parameters = *field;
    }
    if (const Json* field = find_field(node, "generator_version");
        field != nullptr && field->is_string()) {
        run.generator_version = field->get<std::string>();
    }
    if (const Json* field = find_field(node, "domain_task_id");
        field != nullptr && field->is_string()) {
        run.domain_task_id = field->get<std::string>();
    }
    if (const Json* field = find_field(node, "input_snapshot_hash");
        field != nullptr && field->is_string()) {
        run.input_snapshot_hash = field->get<std::string>();
    }
    run.status = node.value("status", "running");
    if (const Json* field = find_field(node, "started_at");
        field != nullptr && field->is_string()) {
        run.started_at = field->get<std::string>();
    }
    if (const Json* field = find_field(node, "finished_at");
        field != nullptr && field->is_string()) {
        run.finished_at = field->get<std::string>();
    }
    if (const Json* field = find_field(node, "actor");
        field != nullptr && field->is_string()) {
        run.actor = field->get<std::string>();
    }
    if (const Json* field = find_field(node, "run_metadata");
        field != nullptr && field->is_object()) {
        run.run_metadata = *field;
    }
    return run;
}

// Byte-exact sha256 (store files are compared byte-for-byte; the
// factor_host canonical encoder would normalize whitespace and defeat
// the drift check).
[[nodiscard]] std::string raw_sha256(const std::string& text) {
    return pwb::factor_host::stable_sha256(Json(text));
}

void atomic_write(const std::filesystem::path& target,
                  const std::string& text) {
    std::filesystem::path tmp = target;
    tmp += ".tmp";
    {
        std::ofstream out(tmp, std::ios::binary | std::ios::trunc);
        if (!out) {
            throw std::runtime_error("cannot write catalog store: "
                                     + tmp.string());
        }
        out << text;
        out.flush();
        if (!out) {
            throw std::runtime_error("short write: " + tmp.string());
        }
    }
    std::filesystem::rename(tmp, target);
}

}  // namespace

void PersistentRuntimeCatalog::open(const std::filesystem::path& root) {
    file_ = root;
    file_ += ".json";
    on_disk_digest_.clear();
    if (!std::filesystem::exists(file_)) {
        restore_state({}, {}, {});
        return;  // fresh store
    }
    std::ifstream in(file_, std::ios::binary);
    if (!in) {
        throw std::runtime_error("cannot open catalog store: "
                                 + file_.string());
    }
    const std::string text((std::istreambuf_iterator<char>(in)),
                           std::istreambuf_iterator<char>());
    Json parsed;
    try {
        parsed = Json::parse(text);
    } catch (const std::exception& exc) {
        throw std::runtime_error("corrupt catalog store "
                                 + file_.string() + ": " + exc.what());
    }
    if (!parsed.is_object() || !parsed.contains("store_version")
        || !parsed["store_version"].is_number_integer()
        || parsed["store_version"].get<int>() != 1) {
        throw std::runtime_error("unsupported catalog store: "
                                 + file_.string());
    }
    std::vector<pwb::workflow_runtime::AssetRecord> assets;
    std::vector<pwb::workflow_runtime::VersionRecord> versions;
    std::vector<pwb::workflow_runtime::RunRecord> runs;
    if (const Json* field = find_field(parsed, "assets");
        field != nullptr && field->is_array()) {
        for (const auto& node : *field) assets.push_back(decode_asset(node));
    }
    if (const Json* field = find_field(parsed, "versions");
        field != nullptr && field->is_array()) {
        for (const auto& node : *field) {
            versions.push_back(decode_version(node));
        }
    }
    if (const Json* field = find_field(parsed, "runs");
        field != nullptr && field->is_array()) {
        for (const auto& node : *field) runs.push_back(decode_run(node));
    }
    restore_state(std::move(assets), std::move(versions), std::move(runs));
    on_disk_digest_ = raw_sha256(text);
}

void PersistentRuntimeCatalog::flush() {
    if (file_.empty()) {
        throw std::runtime_error("catalog store not opened");
    }
    // Payload sidecar files keep the store JSON metadata-only: a 20-task
    // batch at 200x200 otherwise rewrites ~16 MB (with the payloads
    // inlined) FOUR times per committed task — O(T^2) write amplification
    // on the GUI thread. Payload files live in <root>.payloads/ next to
    // the store; VersionRecord.path carries the file path and the
    // checksum stays the payload's sha256 (integrity verify still reads
    // the sidecar).
    Json out = Json::object();
    out["store_version"] = 1;
    Json assets = Json::array();
    for (const auto& asset : this->assets()) {
        assets.push_back(encode_asset(asset));
    }
    out["assets"] = std::move(assets);
    Json versions = Json::array();
    for (const auto& version : this->versions()) {
        Json node = encode_version(version);
        // Payload stays out of the store document; the path field points
        // at the sidecar (decode re-reads it lazily).
        node["payload_json"] = "";
        versions.push_back(std::move(node));
    }
    out["versions"] = std::move(versions);
    Json runs = Json::array();
    for (const auto& run : this->runs()) {
        runs.push_back(encode_run(run));
    }
    out["runs"] = std::move(runs);
    std::filesystem::create_directories(file_.parent_path());
    const std::string text =
        pwb::domain::dump_json_python_compatible(out);
    // Multi-window guard: another window may have rewritten the rail since
    // this store opened (each open() is a snapshot; a blind full-file
    // rewrite would silently delete the other window's runs). Fail closed
    // on drift — the honest degradation (no new versions) beats losing
    // provenance.
    const std::string digest = raw_sha256(text);
    if (!on_disk_digest_.empty() && std::filesystem::exists(file_)) {
        std::ifstream current(file_, std::ios::binary);
        const std::string current_text(
            (std::istreambuf_iterator<char>(current)),
            std::istreambuf_iterator<char>());
        if (raw_sha256(current_text) != on_disk_digest_) {
            throw std::runtime_error(
                "catalog store changed on disk since open (another "
                "window wrote it): refusing to clobber provenance");
        }
    }
    atomic_write(file_, text);
    on_disk_digest_ = digest;
}

void PersistentRuntimeCatalog::write_payload(const std::string& version_id,
                                             const std::string& payload) {
    const std::filesystem::path dir = file_.string() + ".payloads";
    std::filesystem::create_directories(dir);
    // Unique tmp sibling (concurrent windows never share a .tmp).
    std::ostringstream tmp_name;
    tmp_name << version_id << '.' << std::this_thread::get_id() << ".tmp";
    const std::filesystem::path tmp = dir / tmp_name.str();
    const std::filesystem::path final = dir / (version_id + ".json");
    {
        std::ofstream out(tmp, std::ios::binary | std::ios::trunc);
        if (!out) {
            throw std::runtime_error("cannot write payload file: "
                                     + tmp.string());
        }
        out << payload;
        out.flush();
        if (!out) throw std::runtime_error("short write: "
                                           + tmp.string());
    }
    std::error_code ec;
    std::filesystem::rename(tmp, final, ec);
    if (ec) {
        std::filesystem::remove(tmp, ec);
        throw std::runtime_error("cannot rename payload file: "
                                 + final.string());
    }
    // Backfill the in-memory path so decode/verify can find the sidecar.
    for (auto& version : const_cast<std::vector<
             pwb::workflow_runtime::VersionRecord>&>(this->versions())) {
        if (version.version_id == version_id) {
            version.path = final.string();
            return;
        }
    }
}

std::string PersistentRuntimeCatalog::register_run(
    const std::string& operation,
    const std::vector<std::string>& input_version_ids, const Json& parameters,
    const std::optional<std::string>& generator_version,
    const std::string& status, const std::optional<std::string>& domain_task_id,
    const std::optional<std::string>& input_snapshot_hash,
    const std::optional<std::string>& actor) {
    const std::string id = RuntimeStore::register_run(
        operation, input_version_ids, parameters, generator_version, status,
        domain_task_id, input_snapshot_hash, actor);
    flush();
    return id;
}

pwb::workflow_runtime::RegisteredAssetVersion
PersistentRuntimeCatalog::register_result_asset(
    const std::string& name, const std::string& type,
    const std::string& format, const Json& asset_metadata,
    const std::string& payload_json, const std::string& stage,
    const std::string& run_id, const Json& version_metadata) {
    auto registered = RuntimeStore::register_result_asset(
        name, type, format, asset_metadata, payload_json, stage, run_id,
        version_metadata);
    // The payload bytes go to the sidecar BEFORE the metadata flush that
    // references it (a metadata record must never point at a missing
    // sidecar).
    write_payload(registered.version_id, payload_json);
    flush();
    return registered;
}

std::string PersistentRuntimeCatalog::register_version(
    const std::string& asset_id, const std::string& payload_json,
    const std::string& stage,
    const std::vector<std::string>& parent_version_ids,
    const std::string& run_id, const Json& metadata) {
    const std::string id = RuntimeStore::register_version(
        asset_id, payload_json, stage, parent_version_ids, run_id, metadata);
    write_payload(id, payload_json);
    flush();
    return id;
}

void PersistentRuntimeCatalog::update_run_status(const std::string& run_id,
                                                 const std::string& status) {
    RuntimeStore::update_run_status(run_id, status);
    flush();
}

void PersistentRuntimeCatalog::update_run_status(
    const std::string& run_id, const std::string& status,
    const Json& extra_parameters) {
    RuntimeStore::update_run_status(run_id, status, extra_parameters);
    flush();
}

void PersistentRuntimeCatalog::set_current_version(
    const std::string& asset_id, const std::string& version_id) {
    RuntimeStore::set_current_version(asset_id, version_id);
    flush();
}

void PersistentRuntimeCatalog::attach_run_output(
    const std::string& run_id, const std::string& version_id) {
    RuntimeStore::attach_run_output(run_id, version_id);
    flush();
}

std::vector<WellFactorSample> sample_factor_context(
    const Json& project_root,
    const std::vector<std::pair<std::string, std::array<double, 2>>>& wells,
    const LiveFactorGridStore* grids,
    workflow_runtime::CatalogRepository* catalog) {
    std::vector<WellFactorSample> out;
    const Json* tasks = find_field(project_root, "factor_map_tasks");
    if (tasks == nullptr || !tasks->is_array() || wells.empty()) return out;
    for (const auto& entry : *tasks) {
        if (!entry.is_object()) continue;
        if (field_str(entry, "status") != "complete") continue;
        const std::string task_id = field_str(entry, "id");
        if (task_id.empty()) continue;

        // Grid resolution: live cache -> catalog payload -> legacy inline.
        std::vector<double> gx, gy;
        std::vector<double> gz;
        if (grids != nullptr) {
            if (auto live = grids->peek(task_id)) {
                gx = live->grid_x;
                gy = live->grid_y;
                gz.assign(live->grid_z.begin(), live->grid_z.end());
            }
        }
        if (gx.empty() && catalog != nullptr) {
            const std::string vid =
                field_str(entry, "grid_artifact_version_id");
            if (!vid.empty()) {
                try {
                    const auto version = catalog->resolve_version(vid);
                    if (version.has_value()) {
                        const Json payload =
                            Json::parse(version->payload_json);
                        for (const auto& v : payload["grid_x"]) {
                            gx.push_back(v.get<double>());
                        }
                        for (const auto& v : payload["grid_y"]) {
                            gy.push_back(v.get<double>());
                        }
                        for (const auto& row : payload["grid_z"]) {
                            for (const auto& cell : row) {
                                gz.push_back(
                                    cell.is_null()
                                        ? std::numeric_limits<double>::
                                              quiet_NaN()
                                        : cell.get<double>());
                            }
                        }
                    }
                } catch (const std::exception&) {
                    // fall through to the legacy leg
                }
            }
        }
        if (gx.empty()) {
            const Json* params = find_field(entry, "parameters");
            if (params == nullptr || !params->is_object()) continue;
            const Json* px = find_field(*params, "grid_x");
            const Json* py = find_field(*params, "grid_y");
            const Json* pz = find_field(*params, "grid_z");
            if (px == nullptr || py == nullptr || pz == nullptr
                || !px->is_array() || !py->is_array() || !pz->is_array()) {
                continue;
            }
            for (const auto& v : *px) gx.push_back(v.get<double>());
            for (const auto& v : *py) gy.push_back(v.get<double>());
            bool ragged = false;
            for (const auto& row : *pz) {
                if (!row.is_array()
                    || row.size() != gx.size()) {
                    ragged = true;
                    break;
                }
                for (const auto& cell : row) {
                    gz.push_back(cell.is_null()
                                     ? std::numeric_limits<double>::
                                           quiet_NaN()
                                     : cell.get<double>());
                }
            }
            if (ragged) gz.clear();  // reject misaligned payloads
        }
        if (gx.empty() || gy.empty()
            || gz.size() != gx.size() * gy.size()) {
            continue;
        }

        for (const auto& [well, xy] : wells) {
            WellFactorSample sample;
            sample.well = well;
            sample.x = xy[0];
            sample.y = xy[1];
            sample.task_id = task_id;
            sample.factor_type = field_str(entry, "factor_type");
            sample.target_horizon = field_str(entry, "target_horizon");
            sample.version_id =
                field_str(entry, "grid_artifact_version_id");
            const auto value = pwb::factor_host::bilinear_sample_grid(
                gz, gx, gy, xy[0], xy[1]);
            if (value.has_value()) sample.value = *value;
            out.push_back(std::move(sample));
        }
    }
    return out;
}

}  // namespace pwb::factor_production
