// pwb::science_service — IAlgorithm adapters over the typed services
// (CONV-28). Adapters are translation only: params_json/input_refs ->
// typed request, typed result -> AlgorithmResultV1 (grid view + envelope
// record + diagnostics + provenance). No science logic lives here.

#include <pwb/science_service/registry.hpp>

#include <pwb/factor_fusion/factor_grid.hpp>

#include <pwb/domain/json.hpp>
#include <pwb/workflow/task_runtime.hpp>

#include <chrono>
#include <cmath>
#include <functional>
#include <limits>
#include <stdexcept>
#include <utility>

#include "support.hpp"

namespace pwb::science_service {

using pwb::domain::Json;
using science::AlgorithmDescriptor;
using science::AlgorithmRequestV1;
using science::AlgorithmResultV1;
using science::Diagnostic;
using science::ParamSpec;
using science::PortKind;
using science::PortSpec;

namespace {

// ---- params_json helpers (values are JSON-encoded texts) ------------------

[[nodiscard]] bool param_present(const AlgorithmRequestV1& request,
                                 const std::string& key) {
    return request.params_json.count(key) != 0;
}

[[nodiscard]] Json param_json(const AlgorithmRequestV1& request,
                              const std::string& key) {
    const auto it = request.params_json.find(key);
    if (it == request.params_json.end()) {
        return Json(nullptr);
    }
    return Json::parse(it->second);
}

[[nodiscard]] std::string param_string(const AlgorithmRequestV1& request,
                                       const std::string& key,
                                       const std::string& fallback = "") {
    if (!param_present(request, key)) {
        return fallback;
    }
    const Json v = param_json(request, key);
    if (v.is_string()) {
        return v.get<std::string>();
    }
    if (v.is_null()) {
        return fallback;
    }
    return v.dump();
}

[[nodiscard]] long long param_int(const AlgorithmRequestV1& request,
                                  const std::string& key, long long fallback) {
    if (!param_present(request, key)) {
        return fallback;
    }
    const Json v = param_json(request, key);
    return v.is_number() ? v.get<long long>() : fallback;
}

[[nodiscard]] double param_number(const AlgorithmRequestV1& request,
                                  const std::string& key, double fallback) {
    if (!param_present(request, key)) {
        return fallback;
    }
    const Json v = param_json(request, key);
    return v.is_number() ? v.get<double>() : fallback;
}

[[nodiscard]] bool param_bool(const AlgorithmRequestV1& request,
                              const std::string& key, bool fallback) {
    if (!param_present(request, key)) {
        return fallback;
    }
    const Json v = param_json(request, key);
    return v.is_boolean() ? v.get<bool>() : fallback;
}

[[nodiscard]] std::optional<long long> param_int_opt(
    const AlgorithmRequestV1& request, const std::string& key) {
    if (!param_present(request, key)) {
        return std::nullopt;
    }
    const Json v = param_json(request, key);
    if (v.is_null()) {
        return std::nullopt;
    }
    return v.is_number() ? std::optional<long long>(v.get<long long>())
                         : std::nullopt;
}

[[nodiscard]] std::optional<double> param_number_opt(
    const AlgorithmRequestV1& request, const std::string& key) {
    if (!param_present(request, key)) {
        return std::nullopt;
    }
    const Json v = param_json(request, key);
    if (v.is_null()) {
        return std::nullopt;
    }
    return v.is_number() ? std::optional<double>(v.get<double>())
                         : std::nullopt;
}

[[nodiscard]] std::vector<double> param_double_array(
    const AlgorithmRequestV1& request, const std::string& key) {
    if (!param_present(request, key)) {
        return {};
    }
    const Json v = param_json(request, key);
    std::vector<double> out;
    if (v.is_array()) {
        for (const auto& item : v) {
            if (item.is_number()) {
                out.push_back(item.get<double>());
            }
        }
    }
    return out;
}

[[nodiscard]] std::vector<std::string> param_string_array(
    const AlgorithmRequestV1& request, const std::string& key) {
    if (!param_present(request, key)) {
        return {};
    }
    const Json v = param_json(request, key);
    std::vector<std::string> out;
    if (v.is_array()) {
        for (const auto& item : v) {
            if (item.is_string()) {
                out.push_back(item.get<std::string>());
            }
        }
    }
    return out;
}

// Boundary/ring params: a malformed entry is an ERROR, not a silently
// dropped vertex — a shrunken polygon would change the geological intent.
[[nodiscard]] std::vector<std::array<double, 2>> param_ring(
    const AlgorithmRequestV1& request, const std::string& key) {
    if (!param_present(request, key)) {
        return {};
    }
    const Json v = param_json(request, key);
    std::vector<std::array<double, 2>> out;
    if (!v.is_array()) {
        throw std::invalid_argument("'" + key + "' must be an array of [x, y]");
    }
    for (const auto& item : v) {
        if (!item.is_array() || item.size() != 2 || !item.at(0).is_number()
            || !item.at(1).is_number()) {
            throw std::invalid_argument("'" + key
                                        + "' entries must be [x, y] pairs");
        }
        out.push_back({item.at(0).get<double>(), item.at(1).get<double>()});
    }
    return out;
}

// ---- shared adapter skeleton ----------------------------------------------

class AdapterBase : public science::IAlgorithm {
public:
    explicit AdapterBase(AlgorithmDescriptor descriptor)
        : descriptor_(std::move(descriptor)) {}

    [[nodiscard]] const AlgorithmDescriptor& descriptor() const override {
        return descriptor_;
    }

protected:
    AlgorithmDescriptor descriptor_;
};

[[nodiscard]] std::vector<Diagnostic> diagnostics_from_envelope(
    const ScienceEnvelope& envelope) {
    std::vector<Diagnostic> out;
    for (const auto& item : envelope.diagnostics) {
        if (!item.is_object()) {
            continue;
        }
        Diagnostic d;
        d.code = item.value("code", std::string());
        d.message = item.value("message", std::string());
        d.severity = item.value("severity", std::string("warning"));
        out.push_back(std::move(d));
    }
    return out;
}

void fill_provenance(science::ProvenanceRecord& record,
                     const AlgorithmRequestV1& request,
                     const AlgorithmDescriptor& descriptor,
                     const std::string& started, std::uint64_t wall_ms) {
    record.algorithm_id = descriptor.algorithm_id;
    record.algorithm_version = descriptor.version;
    record.build_identity = descriptor.build_identity;
    record.params_json = request.params_json;
    record.input_refs = request.input_refs;
    record.started_utc = started;
    record.finished_utc = detail::utc_now_iso();
    record.wall_time_ms = wall_ms;
}

// Post-run packing (records/diagnostics/provenance) is JSON-heavy and must
// honour the no-exceptions-escape IAlgorithm contract even on hostile input
// (e.g. invalid UTF-8 in params would make the strict dump throw). Wrap the
// packing step for every adapter.
template <typename Pack>
[[nodiscard]] science::Result<AlgorithmResultV1> pack_result(
    const AlgorithmRequestV1& request, const AlgorithmDescriptor& descriptor,
    const std::string& started, std::uint64_t t0, Pack pack) {
    AlgorithmResultV1 result;
    result.request_id = request.request_id;
    try {
        pack(result);
    } catch (const std::bad_alloc&) {
        throw;
    } catch (const std::exception& e) {
        return detail::make_error("result.pack",
                                  std::string("result packing failed: ")
                                      + e.what());
    }
    fill_provenance(result.provenance, request, descriptor, started,
                    detail::epoch_ms() - t0);
    return result;
}

[[nodiscard]] science::ProducedRecord envelope_record(
    const ScienceEnvelope& envelope) {
    science::ProducedRecord record;
    record.name = "envelope";
    record.media_type = "application/json";
    record.content_json = dump_envelope(envelope);
    return record;
}

// ---- factor interpolation adapter ------------------------------------------

class FactorInterpolationAdapter : public AdapterBase {
public:
    FactorInterpolationAdapter(std::shared_ptr<IPayloadSource> source,
                               std::string build_identity, ResourceLimits limits)
        : AdapterBase(make_descriptor(std::move(build_identity))),
          service_(descriptor_.build_identity, limits),
          source_(std::move(source)) {}

    science::Result<AlgorithmResultV1> run(const AlgorithmRequestV1& request,
                                           science::ProgressSink progress,
                                           std::stop_token stop) override {
        const std::string started = detail::utc_now_iso();
        const std::uint64_t t0 = detail::epoch_ms();
        FactorInterpolationRequest typed;
        try {
            typed.factor_name = param_string(request, "factor_name");
            if (typed.factor_name.empty()) {
                return detail::make_error("param.factor_name",
                                          "factor_name is required");
            }
            if (param_present(request, "records_json")) {
                typed.well_records = param_json(request, "records_json");
            } else if (!request.input_refs.empty()) {
                // Resolve the first table input through the payload source.
                if (!source_) {
                    return detail::make_error(
                        "payload.source_unavailable",
                        "input_refs given but no payload source is wired");
                }
                auto payload = source_->resolve(request.input_refs.front());
                if (payload.is_error()) {
                    return payload.error();
                }
                if (payload.value().kind != Payload::Kind::table) {
                    return detail::make_error(
                        "payload.wrong_kind",
                        "input ref resolved to "
                            + std::string(payload.value().kind_name())
                            + ", expected table");
                }
                typed.well_records = std::move(payload.value().table);
            }
            typed.crs = param_string(request, "crs");
            if (param_present(request, "unit")) {
                const Json v = param_json(request, "unit");
                typed.unit = v.is_string()
                                 ? std::optional<std::string>(
                                       v.get<std::string>())
                                 : std::nullopt;
            }
            typed.duplicate_policy =
                param_string(request, "duplicate_policy", "mean");
            typed.interpolate.method =
                param_string(request, "method", "idw");
            typed.interpolate.grid_n =
                static_cast<int>(param_int(request, "grid_n", 50));
            typed.interpolate.power =
                param_number(request, "power", 2.0);
            typed.interpolate.min_neighbors =
                static_cast<int>(param_int(request, "min_neighbors", 1));
            typed.interpolate.max_neighbors = [&]() -> std::optional<int> {
                const auto v = param_int_opt(request, "max_neighbors");
                if (!v) return std::nullopt;
                return static_cast<int>(*v);
            }();
            typed.interpolate.search_radius =
                param_number_opt(request, "search_radius");
            typed.interpolate.variogram_model =
                param_string(request, "variogram_model", "spherical");
            typed.interpolate.distance_policy =
                param_string(request, "distance_policy", "planar");
            typed.include_layer_products =
                param_bool(request, "include_layer_products", false);
            typed.contour_options.leveling_mode =
                param_string(request, "leveling_mode", "nice");
            typed.contour_options.simplify_tolerance =
                param_number(request, "simplify_tolerance", 0.0);
            typed.contour_options.smooth_iterations =
                static_cast<int>(param_int(request, "smooth_iterations", 0));
            const std::vector<double> levels =
                param_double_array(request, "contour_levels");
            if (!levels.empty()) {
                typed.contour_options.levels = levels;
            }
            typed.contour_options.interval =
                param_number_opt(request, "contour_interval");
            const std::vector<double> thresholds =
                param_double_array(request, "facies_thresholds");
            if (!thresholds.empty()) {
                typed.facies_options.thresholds = thresholds;
            }
            const std::vector<std::string> facies_names =
                param_string_array(request, "facies_names");
            if (!facies_names.empty()) {
                typed.facies_options.facies_names = facies_names;
            }
            if (param_present(request, "metadata")) {
                typed.metadata = param_json(request, "metadata");
            }
            // Constrained-IDW engine wiring (mapping::constrained_idw).
            typed.use_constrained_idw =
                param_bool(request, "use_constrained_idw", false)
                || param_string(request, "engine") == "constrained_idw";
            if (typed.use_constrained_idw) {
                // Engine scalars the caller may pin; everything else derives
                // from the samples inside the service (Python production
                // semantics — never the kernel's [0,1]/10000/6500 defaults).
                typed.constrained.power =
                    param_number(request, "constrained_power", 2.0);
                typed.constrained.min_points =
                    static_cast<int>(param_int(request,
                                               "constrained_min_points", 3));
                typed.constrained.max_points =
                    static_cast<int>(param_int(request,
                                               "constrained_max_points", 12));
                if (auto v = param_number_opt(request,
                                              "constrained_grid_resolution")) {
                    typed.constrained_grid_resolution =
                        static_cast<int>(*v);
                }
                if (auto v = param_number_opt(request,
                                              "constrained_value_min")) {
                    typed.constrained_value_min = *v;
                }
                if (auto v = param_number_opt(request,
                                              "constrained_value_max")) {
                    typed.constrained_value_max = *v;
                }
                if (auto v = param_number_opt(request,
                                              "constrained_search_radius")) {
                    typed.constrained_search_radius = *v;
                }
                if (auto v = param_number_opt(request,
                                              "constrained_decluster_radius")) {
                    typed.constrained_decluster_radius = *v;
                }
                // Geometry passthrough: [[ [x,y], ... ], ...] line lists.
                for (const char* key :
                     {"barriers_json", "directions_json"}) {
                    if (!param_present(request, key)) {
                        continue;
                    }
                    const Json lines = param_json(request, key);
                    if (!lines.is_array()) {
                        continue;
                    }
                    for (const auto& line : lines) {
                        if (!line.is_array()) {
                            continue;
                        }
                        std::vector<std::array<double, 2>> pts;
                        for (const auto& p : line) {
                            if (p.is_array() && p.size() == 2
                                && p.at(0).is_number()
                                && p.at(1).is_number()) {
                                pts.push_back({p.at(0).get<double>(),
                                               p.at(1).get<double>()});
                            }
                        }
                        if (pts.size() >= 2) {
                            (key[0] == 'b' ? typed.barrier_lines
                                           : typed.direction_lines)
                                .push_back(std::move(pts));
                        }
                    }
                }
                const auto ring = param_ring(request, "constrained_boundary_json");
                if (!ring.empty()) {
                    typed.constrained_boundary = ring;
                } else {
                    // Fall back to the plain-interpolation boundary mask.
                    const auto mask = param_ring(request, "boundary_json");
                    if (!mask.empty()) {
                        typed.constrained_boundary = mask;
                    }
                }
            }
        } catch (const std::exception& e) {
            return detail::make_error("request.params",
                                      std::string("invalid params_json: ")
                                          + e.what());
        }

        auto outcome =
            service_.run(typed, std::move(progress), std::move(stop));
        if (outcome.is_error()) {
            return outcome.error();
        }
        if (outcome.is_cancelled()) {
            return outcome.cancelled();
        }
        auto& value = outcome.value();

        return pack_result(request, descriptor_, started,
                           detail::epoch_ms() - t0,
                           [&](AlgorithmResultV1& result) {
                               if (value.grid && !value.grid->grid_z.empty()) {
                                   science::ProducedVolume volume;
                                   volume.name = "factor_grid";
                                   volume.unit = value.envelope.units;
                                   volume.volume.data =
                                       value.grid->grid_z.data();
                                   volume.volume.shape = {
                                       1,
                                       static_cast<std::int64_t>(
                                           value.grid->grid_y.size()),
                                       static_cast<std::int64_t>(
                                           value.grid->grid_x.size())};
                                   volume.volume.strides = {0, 0, 0};
                                   volume.volume.lifetime = value.grid;
                                   result.outputs.push_back(
                                       std::move(volume));
                               }
                               result.records.push_back(
                                   envelope_record(value.envelope));
                               result.diagnostics =
                                   diagnostics_from_envelope(value.envelope);
                           });
    }

private:
    [[nodiscard]] static AlgorithmDescriptor make_descriptor(
        std::string build_identity) {
        AlgorithmDescriptor d;
        d.algorithm_id = "mapping.factor_interpolate";
        d.version = "1.0.0";
        d.display_name = "Factor interpolation pipeline";
        d.family = "mapping";
        PortSpec records;
        records.name = "well_records";
        records.kind = PortKind::table;
        records.required = false;
        d.inputs.push_back(records);
        PortSpec grid;
        grid.name = "factor_grid";
        grid.kind = PortKind::grid_f32;
        grid.required = true;
        d.outputs.push_back(grid);
        auto add = [&d](const char* name, ParamSpec::Type type,
                        const char* def) {
            ParamSpec p;
            p.name = name;
            p.type = type;
            p.default_json = def;
            d.parameters.push_back(std::move(p));
        };
        add("factor_name", ParamSpec::Type::string, "");
        add("method", ParamSpec::Type::string, "\"idw\"");
        add("grid_n", ParamSpec::Type::integer, "50");
        add("power", ParamSpec::Type::number, "2.0");
        add("min_neighbors", ParamSpec::Type::integer, "1");
        add("duplicate_policy", ParamSpec::Type::string, "\"mean\"");
        add("variogram_model", ParamSpec::Type::string, "\"spherical\"");
        add("crs", ParamSpec::Type::string, "\"\"");
        add("include_layer_products", ParamSpec::Type::boolean, "false");
        add("leveling_mode", ParamSpec::Type::string, "\"nice\"");
        d.supports_cancel = true;
        d.deterministic = true;
        d.build_identity = std::move(build_identity);
        return d;
    }

    FactorInterpolationService service_;
    std::shared_ptr<IPayloadSource> source_;
};

// ---- factor layer products adapter (grid envelope -> GeoJSON products) ----

class FactorLayerProductsAdapter : public AdapterBase {
public:
    FactorLayerProductsAdapter(std::string build_identity, ResourceLimits limits)
        : AdapterBase(make_descriptor(std::move(build_identity))),
          limits_(limits) {}

    science::Result<AlgorithmResultV1> run(const AlgorithmRequestV1& request,
                                           science::ProgressSink progress,
                                           std::stop_token stop) override {
        const std::string started = detail::utc_now_iso();
        const std::uint64_t t0 = detail::epoch_ms();
        pwb::mapping::FactorGrid grid;
        pwb::mapping::LayerGridContext ctx;
        pwb::mapping::ContourLayerOptions contour_opts;
        pwb::mapping::FaciesLayerOptions facies_opts;
        try {
            if (!param_present(request, "grid_json")) {
                return detail::make_error(
                    "param.grid_json",
                    "grid_json (legacy grid dict) is required");
            }
            const Json legacy = param_json(request, "grid_json");
            // Shared decoder (the same one fusion uses): shape-validated
            // legacy dict -> mapping grid carrier.
            grid = legacy_dict_to_mapping_grid(
                legacy, param_string(request, "factor_name", "factor"));
            ctx.factor_name = param_string(request, "factor_name", "factor");
            ctx.unit = param_string(request, "unit");
            ctx.crs = param_string(request, "crs");
            contour_opts.leveling_mode =
                param_string(request, "leveling_mode", "nice");
            contour_opts.simplify_tolerance =
                param_number(request, "simplify_tolerance", 0.0);
            contour_opts.smooth_iterations =
                static_cast<int>(param_int(request, "smooth_iterations", 0));
            const std::vector<double> levels =
                param_double_array(request, "contour_levels");
            if (!levels.empty()) {
                contour_opts.levels = levels;
            }
            contour_opts.interval = param_number_opt(request, "contour_interval");
            const std::vector<double> thresholds =
                param_double_array(request, "facies_thresholds");
            if (!thresholds.empty()) {
                facies_opts.thresholds = thresholds;
            }
        } catch (const std::exception& e) {
            return detail::make_error("request.params",
                                      std::string("invalid params_json: ")
                                          + e.what());
        }
        if (grid.grid_z.size() > limits_.max_grid_cells) {
            return detail::make_error(
                limit_code("grid_cells"),
                "grid exceeds cell limit " + std::to_string(limits_.max_grid_cells));
        }
        if (detail::stage_guard(stop, progress, 0.2, "validate")) {
            return science::TaskCancelled{"validate"};
        }

        auto make_product = [&]() -> std::pair<
            pwb::mapping::ContourLayerProduct, pwb::mapping::FaciesLayerProduct> {
            auto contours = pwb::mapping::generate_contour_layer_product(
                grid, ctx, contour_opts);
            auto facies = pwb::mapping::generate_facies_polygon_layer_product(
                grid, ctx, facies_opts);
            return {std::move(contours), std::move(facies)};
        };
        auto products = detail::catch_kernel<
            std::pair<pwb::mapping::ContourLayerProduct,
                      pwb::mapping::FaciesLayerProduct>>(
            "factor.products", make_product);
        if (products.is_error()) {
            return products.error();
        }

        ScienceEnvelope envelope;
        envelope.result_type = "factor_layer_products";
        envelope.units = ctx.unit;
        envelope.crs = ctx.crs;
        Json payload = Json::object();
        Json contour_json = Json::object();
        contour_json["levels"] = products.value().first.levels;
        contour_json["features"] = products.value().first.features;
        contour_json["qc"] = products.value().first.contour_qc;
        payload["contour_layer"] = std::move(contour_json);
        Json facies_json = Json::object();
        facies_json["features"] = products.value().second.features;
        facies_json["qc"] = products.value().second.polygon_qc;
        payload["facies_layer"] = std::move(facies_json);
        envelope.payload = std::move(payload);
        Json provenance = Json::object();
        provenance["algorithm_id"] = "mapping.factor_layer_products";
        provenance["algorithm_version"] = "1.0.0";
        provenance["build_identity"] = descriptor_.build_identity;
        provenance["factor_name"] = ctx.factor_name;
        envelope.provenance = std::move(provenance);
        envelope.compute_fingerprint();

        detail::stage_guard(stop, progress, 1.0, "envelope");
        return pack_result(request, descriptor_, started,
                           detail::epoch_ms() - t0,
                           [&](AlgorithmResultV1& result) {
                               result.records.push_back(
                                   envelope_record(envelope));
                               result.diagnostics =
                                   diagnostics_from_envelope(envelope);
                           });
    }

private:
    [[nodiscard]] static AlgorithmDescriptor make_descriptor(
        std::string build_identity) {
        AlgorithmDescriptor d;
        d.algorithm_id = "mapping.factor_layer_products";
        d.version = "1.0.0";
        d.display_name = "Factor contour/facies layer products";
        d.family = "mapping";
        PortSpec products;
        products.name = "layer_products";
        products.kind = PortKind::artifact;
        products.required = true;
        d.outputs.push_back(products);
        ParamSpec grid;
        grid.name = "grid_json";
        grid.type = ParamSpec::Type::string;
        d.parameters.push_back(grid);
        d.supports_cancel = false;
        d.deterministic = true;
        d.build_identity = std::move(build_identity);
        return d;
    }

    ResourceLimits limits_;
};

// ---- curve operation adapter ----------------------------------------------

class CurveOperationAdapter : public AdapterBase {
public:
    CurveOperationAdapter(std::string build_identity, ResourceLimits limits)
        : AdapterBase(make_descriptor(std::move(build_identity))),
          service_(descriptor_.build_identity, limits) {}

    science::Result<AlgorithmResultV1> run(const AlgorithmRequestV1& request,
                                           science::ProgressSink progress,
                                           std::stop_token stop) override {
        const std::string started = detail::utc_now_iso();
        const std::uint64_t t0 = detail::epoch_ms();
        CurveOperationRequest typed;
        try {
            typed.operation = param_string(request, "operation");
            if (param_present(request, "params")) {
                typed.params = param_json(request, "params");
            }
            const Json depth = param_json(request, "depth_json");
            if (depth.is_array()) {
                for (const auto& v : depth) {
                    typed.depth.push_back(v.is_number() ? v.get<double>()
                                                        : std::numeric_limits<double>::quiet_NaN());
                }
            }
            const Json values = param_json(request, "values_json");
            if (values.is_array()) {
                for (const auto& v : values) {
                    typed.values.push_back(v.is_number() ? v.get<double>()
                                                         : std::numeric_limits<double>::quiet_NaN());
                }
            }
            if (param_present(request, "axis_unit")) {
                const Json v = param_json(request, "axis_unit");
                typed.axis_unit =
                    v.is_string() ? std::optional<std::string>(v.get<std::string>())
                                  : std::nullopt;
            }
            if (param_present(request, "from_unit")) {
                const Json v = param_json(request, "from_unit");
                typed.from_unit =
                    v.is_string() ? std::optional<std::string>(v.get<std::string>())
                                  : std::nullopt;
            }
            if (param_present(request, "to_unit")) {
                const Json v = param_json(request, "to_unit");
                typed.to_unit =
                    v.is_string() ? std::optional<std::string>(v.get<std::string>())
                                  : std::nullopt;
            }
        } catch (const std::exception& e) {
            return detail::make_error("request.params",
                                      std::string("invalid params_json: ")
                                          + e.what());
        }
        auto outcome =
            service_.run(typed, std::move(progress), std::move(stop));
        if (outcome.is_error()) {
            return outcome.error();
        }
        if (outcome.is_cancelled()) {
            return outcome.cancelled();
        }
        return pack_result(request, descriptor_, started,
                           detail::epoch_ms() - t0,
                           [&](AlgorithmResultV1& result) {
                               result.records.push_back(
                                   envelope_record(outcome.value().envelope));
                               result.diagnostics =
                                   diagnostics_from_envelope(
                                       outcome.value().envelope);
                           });
    }

private:
    [[nodiscard]] static AlgorithmDescriptor make_descriptor(
        std::string build_identity) {
        AlgorithmDescriptor d;
        d.algorithm_id = "well.curve_operation";
        d.version = "1.0.0";
        d.display_name = "Well curve operation";
        d.family = "well_science";
        PortSpec curve;
        curve.name = "curve";
        curve.kind = PortKind::well_log;
        curve.required = true;
        d.outputs.push_back(curve);
        ParamSpec op;
        op.name = "operation";
        op.type = ParamSpec::Type::string;
        d.parameters.push_back(op);
        d.supports_cancel = false;
        d.deterministic = true;
        d.build_identity = std::move(build_identity);
        return d;
    }

    CurveOperationService service_;
};

// ---- log match adapter -----------------------------------------------------

class LogMatchAdapter : public AdapterBase {
public:
    LogMatchAdapter(std::string build_identity, ResourceLimits limits)
        : AdapterBase(make_descriptor(std::move(build_identity))),
          service_(descriptor_.build_identity, limits) {}

    science::Result<AlgorithmResultV1> run(const AlgorithmRequestV1& request,
                                           science::ProgressSink progress,
                                           std::stop_token stop) override {
        const std::string started = detail::utc_now_iso();
        const std::uint64_t t0 = detail::epoch_ms();
        LogMatchRequest typed;
        try {
            for (const char* key : {"reference_json", "target_json"}) {
                const Json curve = param_json(request, key);
                if (!curve.is_array()) {
                    continue;
                }
                std::vector<double> samples;
                for (const auto& v : curve) {
                    samples.push_back(v.is_number()
                                          ? v.get<double>()
                                          : std::numeric_limits<double>::quiet_NaN());
                }
                if (key[0] == 'r') {
                    typed.reference = std::move(samples);
                } else {
                    typed.target = std::move(samples);
                }
            }
            if (auto w = param_int_opt(request, "window")) {
                typed.window = *w;
            }
        } catch (const std::exception& e) {
            return detail::make_error("request.params",
                                      std::string("invalid params_json: ")
                                          + e.what());
        }
        auto outcome =
            service_.run(typed, std::move(progress), std::move(stop));
        if (outcome.is_error()) {
            return outcome.error();
        }
        if (outcome.is_cancelled()) {
            return outcome.cancelled();
        }
        return pack_result(request, descriptor_, started,
                           detail::epoch_ms() - t0,
                           [&](AlgorithmResultV1& result) {
                               result.records.push_back(
                                   envelope_record(outcome.value().envelope));
                               result.diagnostics =
                                   diagnostics_from_envelope(
                                       outcome.value().envelope);
                           });
    }

private:
    [[nodiscard]] static AlgorithmDescriptor make_descriptor(
        std::string build_identity) {
        AlgorithmDescriptor d;
        d.algorithm_id = "well.log_match";
        d.version = "1.0.0";
        d.display_name = "DTW well-log match";
        d.family = "well_science";
        PortSpec out;
        out.name = "alignment";
        out.kind = PortKind::table;
        out.required = true;
        d.outputs.push_back(out);
        d.supports_cancel = false;
        d.deterministic = true;
        d.build_identity = std::move(build_identity);
        return d;
    }

    LogMatchService service_;
};

// ---- factor fusion adapter -------------------------------------------------

class FactorFusionAdapter : public AdapterBase {
public:
    FactorFusionAdapter(std::string build_identity, ResourceLimits limits)
        : AdapterBase(make_descriptor(std::move(build_identity))),
          service_(descriptor_.build_identity, limits) {}

    science::Result<AlgorithmResultV1> run(const AlgorithmRequestV1& request,
                                           science::ProgressSink progress,
                                           std::stop_token stop) override {
        const std::string started = detail::utc_now_iso();
        const std::uint64_t t0 = detail::epoch_ms();
        FactorFusionRequest typed;
        try {
            if (param_present(request, "model_json")) {
                typed.model_dict = param_json(request, "model_json");
            }
            if (param_present(request, "grids_json")) {
                typed.grids = param_json(request, "grids_json");
            }
        } catch (const std::exception& e) {
            return detail::make_error("request.params",
                                      std::string("invalid params_json: ")
                                          + e.what());
        }
        auto outcome =
            service_.run(typed, std::move(progress), std::move(stop));
        if (outcome.is_error()) {
            return outcome.error();
        }
        if (outcome.is_cancelled()) {
            return outcome.cancelled();
        }
        return pack_result(request, descriptor_, started,
                           detail::epoch_ms() - t0,
                           [&](AlgorithmResultV1& result) {
                               result.records.push_back(
                                   envelope_record(outcome.value().envelope));
                               result.diagnostics =
                                   diagnostics_from_envelope(
                                       outcome.value().envelope);
                           });
    }

private:
    [[nodiscard]] static AlgorithmDescriptor make_descriptor(
        std::string build_identity) {
        AlgorithmDescriptor d;
        d.algorithm_id = "factor.fuse";
        d.version = "1.0.0";
        d.display_name = "Factor evidence fusion";
        d.family = "factor_fusion";
        PortSpec out;
        out.name = "fused_grid";
        out.kind = PortKind::grid_f32;
        out.required = true;
        d.outputs.push_back(out);
        d.supports_cancel = false;
        d.deterministic = true;
        d.build_identity = std::move(build_identity);
        return d;
    }

    FactorFusionService service_;
};

// ---- facies surface adapter ------------------------------------------------

class FaciesSurfaceAdapter : public AdapterBase {
public:
    FaciesSurfaceAdapter(std::string build_identity, ResourceLimits limits)
        : AdapterBase(make_descriptor(std::move(build_identity))),
          service_(descriptor_.build_identity, limits) {}

    science::Result<AlgorithmResultV1> run(const AlgorithmRequestV1& request,
                                           science::ProgressSink progress,
                                           std::stop_token stop) override {
        const std::string started = detail::utc_now_iso();
        const std::uint64_t t0 = detail::epoch_ms();
        FaciesSurfaceRequest typed;
        try {
            if (param_present(request, "well_points_json")) {
                typed.well_points = param_json(request, "well_points_json");
            }
            if (param_present(request, "result_summary_json")) {
                typed.result_summary =
                    param_json(request, "result_summary_json");
            }
            typed.horizon = param_string(request, "horizon");
            typed.grid_n = static_cast<int>(param_int(request, "grid_n", 80));
            typed.crs = param_string(request, "crs");
            typed.task_id = param_string(request, "task_id");
            if (param_present(request, "extent_json")) {
                const Json v = param_json(request, "extent_json");
                if (v.is_array() && v.size() == 4 && v.at(0).is_number()
                    && v.at(1).is_number() && v.at(2).is_number()
                    && v.at(3).is_number()) {
                    typed.extent = std::array<double, 4>{
                        v.at(0).get<double>(), v.at(1).get<double>(),
                        v.at(2).get<double>(), v.at(3).get<double>()};
                }
            }
            const auto ring = param_ring(request, "clip_ring_json");
            if (!ring.empty()) {
                typed.clip_ring = ring;
            }
        } catch (const std::exception& e) {
            return detail::make_error("request.params",
                                      std::string("invalid params_json: ")
                                          + e.what());
        }
        auto outcome =
            service_.run(typed, std::move(progress), std::move(stop));
        if (outcome.is_error()) {
            return outcome.error();
        }
        if (outcome.is_cancelled()) {
            return outcome.cancelled();
        }
        return pack_result(request, descriptor_, started,
                           detail::epoch_ms() - t0,
                           [&](AlgorithmResultV1& result) {
                               result.records.push_back(
                                   envelope_record(outcome.value().envelope));
                               result.diagnostics =
                                   diagnostics_from_envelope(
                                       outcome.value().envelope);
                           });
    }

private:
    [[nodiscard]] static AlgorithmDescriptor make_descriptor(
        std::string build_identity) {
        AlgorithmDescriptor d;
        d.algorithm_id = "mapping.facies_surface";
        d.version = "1.0.0";
        d.display_name = "Well facies surface (representative + NN class grid)";
        d.family = "mapping";
        PortSpec out;
        out.name = "facies_surface";
        out.kind = PortKind::artifact;
        out.required = true;
        d.outputs.push_back(out);
        d.supports_cancel = true;
        d.deterministic = true;
        d.build_identity = std::move(build_identity);
        return d;
    }

    FaciesSurfaceService service_;
};

// ---- geomodel adapters ------------------------------------------------------

[[nodiscard]] AlgorithmDescriptor geomodel_descriptor(
    const std::string& id, const std::string& display, bool cancelable,
    const std::string& build_identity) {
    AlgorithmDescriptor d;
    d.algorithm_id = id;
    d.version = "1.0.0";
    d.display_name = display;
    d.family = "geomodel";
    d.build_identity = build_identity;
    PortSpec out;
    out.name = "model";
    out.kind = PortKind::artifact;
    out.required = true;
    d.outputs.push_back(out);
    d.supports_cancel = cancelable;
    d.deterministic = true;
    return d;
}

class GeomodelBuildAdapter : public AdapterBase {
public:
    GeomodelBuildAdapter(std::string build_identity, ResourceLimits limits)
        : AdapterBase(geomodel_descriptor("geomodel.build",
                                          "Geomodel volume shell build", true,
                                          build_identity)),
          service_(descriptor_.build_identity, limits) {}

    science::Result<AlgorithmResultV1> run(const AlgorithmRequestV1& request,
                                           science::ProgressSink progress,
                                           std::stop_token stop) override {
        const std::string started = detail::utc_now_iso();
        const std::uint64_t t0 = detail::epoch_ms();
        GeomodelBuildRequest typed;
        try {
            typed.top = param_json(request, "top_json");
            typed.base = param_json(request, "base_json");
            typed.object_id = param_string(request, "object_id", "vol:service");
            typed.build_hex = param_bool(request, "build_hex", false);
            typed.hex_layers =
                static_cast<int>(param_int(request, "hex_layers", 4));
            const auto ring = param_ring(request, "boundary_json");
            if (!ring.empty()) {
                typed.boundary = ring;
            }
        } catch (const std::exception& e) {
            return detail::make_error("request.params",
                                      std::string("invalid params_json: ")
                                          + e.what());
        }
        auto outcome =
            service_.run(typed, std::move(progress), std::move(stop));
        if (outcome.is_error()) {
            return outcome.error();
        }
        if (outcome.is_cancelled()) {
            return outcome.cancelled();
        }
        return pack_result(request, descriptor_, started,
                           detail::epoch_ms() - t0,
                           [&](AlgorithmResultV1& result) {
                               result.records.push_back(
                                   envelope_record(outcome.value().envelope));
                               result.diagnostics =
                                   diagnostics_from_envelope(
                                       outcome.value().envelope);
                           });
    }

private:
    GeomodelBuildService service_;
};

class GeomodelSectionAdapter : public AdapterBase {
public:
    GeomodelSectionAdapter(std::string build_identity, ResourceLimits limits)
        : AdapterBase(geomodel_descriptor("geomodel.section",
                                          "Geomodel section extraction", true,
                                          build_identity)),
          service_(descriptor_.build_identity, limits) {}

    science::Result<AlgorithmResultV1> run(const AlgorithmRequestV1& request,
                                           science::ProgressSink progress,
                                           std::stop_token stop) override {
        const std::string started = detail::utc_now_iso();
        const std::uint64_t t0 = detail::epoch_ms();
        GeomodelSectionRequest typed;
        try {
            typed.source = param_json(request, "source_json");
            typed.plane = param_json(request, "plane_json");
        } catch (const std::exception& e) {
            return detail::make_error("request.params",
                                      std::string("invalid params_json: ")
                                          + e.what());
        }
        auto outcome =
            service_.run(typed, std::move(progress), std::move(stop));
        if (outcome.is_error()) {
            return outcome.error();
        }
        if (outcome.is_cancelled()) {
            return outcome.cancelled();
        }
        return pack_result(request, descriptor_, started,
                           detail::epoch_ms() - t0,
                           [&](AlgorithmResultV1& result) {
                               result.records.push_back(
                                   envelope_record(outcome.value().envelope));
                               result.diagnostics =
                                   diagnostics_from_envelope(
                                       outcome.value().envelope);
                           });
    }

private:
    GeomodelSectionService service_;
};

class GeomodelFaultDisplacementAdapter : public AdapterBase {
public:
    GeomodelFaultDisplacementAdapter(std::string build_identity,
                                     ResourceLimits limits)
        : AdapterBase(geomodel_descriptor("geomodel.fault_displacement",
                                          "Geomodel fault displacement",
                                          false, build_identity)),
          service_(descriptor_.build_identity, limits) {}

    science::Result<AlgorithmResultV1> run(const AlgorithmRequestV1& request,
                                           science::ProgressSink progress,
                                           std::stop_token stop) override {
        const std::string started = detail::utc_now_iso();
        const std::uint64_t t0 = detail::epoch_ms();
        FaultDisplacementRequest typed;
        try {
            typed.mesh = param_json(request, "mesh_json");
            typed.spec = param_json(request, "spec_json");
        } catch (const std::exception& e) {
            return detail::make_error("request.params",
                                      std::string("invalid params_json: ")
                                          + e.what());
        }
        auto outcome =
            service_.run(typed, std::move(progress), std::move(stop));
        if (outcome.is_error()) {
            return outcome.error();
        }
        if (outcome.is_cancelled()) {
            return outcome.cancelled();
        }
        return pack_result(request, descriptor_, started,
                           detail::epoch_ms() - t0,
                           [&](AlgorithmResultV1& result) {
                               result.records.push_back(
                                   envelope_record(outcome.value()));
                               result.diagnostics =
                                   diagnostics_from_envelope(
                                       outcome.value());
                           });
    }

private:
    FaultDisplacementService service_;
};

class GeomodelExportAdapter : public AdapterBase {
public:
    GeomodelExportAdapter(std::string build_identity, ResourceLimits limits)
        : AdapterBase(geomodel_descriptor("geomodel.export",
                                          "Geomodel export (QC-gated)", false,
                                          build_identity)),
          service_(descriptor_.build_identity, limits) {}

    science::Result<AlgorithmResultV1> run(const AlgorithmRequestV1& request,
                                           science::ProgressSink progress,
                                           std::stop_token stop) override {
        const std::string started = detail::utc_now_iso();
        const std::uint64_t t0 = detail::epoch_ms();
        GeomodelExportRequest typed;
        try {
            typed.object = param_json(request, "object_json");
            typed.format = param_string(request, "format");
            typed.out_name = param_string(request, "out_name", "model.obj");
            typed.hex_layers =
                static_cast<int>(param_int(request, "hex_layers", 4));
        } catch (const std::exception& e) {
            return detail::make_error("request.params",
                                      std::string("invalid params_json: ")
                                          + e.what());
        }
        auto outcome =
            service_.run(typed, std::move(progress), std::move(stop));
        if (outcome.is_error()) {
            return outcome.error();
        }
        if (outcome.is_cancelled()) {
            return outcome.cancelled();
        }
        return pack_result(request, descriptor_, started,
                           detail::epoch_ms() - t0,
                           [&](AlgorithmResultV1& result) {
                               result.records.push_back(
                                   envelope_record(outcome.value().envelope));
                               // Export bytes ride as an extra record (the
                               // envelope carries sidecar + size + sha256).
                               science::ProducedRecord file_record;
                               file_record.name = outcome.value().envelope
                                                      .payload.value(
                                                          "out_name",
                                                          std::string(
                                                              "export"));
                               file_record.media_type =
                                   "application/octet-stream";
                               file_record.content_json =
                                   std::move(outcome.value().file_bytes);
                               result.records.push_back(
                                   std::move(file_record));
                               result.diagnostics =
                                   diagnostics_from_envelope(
                                       outcome.value().envelope);
                           });
    }

private:
    GeomodelExportService service_;
};

}  // namespace

std::unique_ptr<science::IAlgorithm> make_factor_interpolation_adapter(
    std::shared_ptr<IPayloadSource> source, std::string build_identity,
    ResourceLimits limits) {
    return std::make_unique<FactorInterpolationAdapter>(
        std::move(source), std::move(build_identity), limits);
}

std::unique_ptr<science::IAlgorithm> make_factor_layer_products_adapter(
    std::string build_identity, ResourceLimits limits) {
    return std::make_unique<FactorLayerProductsAdapter>(
        std::move(build_identity), limits);
}

std::unique_ptr<science::IAlgorithm> make_facies_surface_adapter(
    std::string build_identity, ResourceLimits limits) {
    return std::make_unique<FaciesSurfaceAdapter>(std::move(build_identity),
                                                  limits);
}

std::unique_ptr<science::IAlgorithm> make_curve_operation_adapter(
    std::string build_identity, ResourceLimits limits) {
    return std::make_unique<CurveOperationAdapter>(std::move(build_identity),
                                                   limits);
}

std::unique_ptr<science::IAlgorithm> make_log_match_adapter(
    std::string build_identity, ResourceLimits limits) {
    return std::make_unique<LogMatchAdapter>(std::move(build_identity),
                                             limits);
}

std::unique_ptr<science::IAlgorithm> make_factor_fusion_adapter(
    std::string build_identity, ResourceLimits limits) {
    return std::make_unique<FactorFusionAdapter>(std::move(build_identity),
                                                 limits);
}

std::unique_ptr<science::IAlgorithm> make_geomodel_build_adapter(
    std::string build_identity, ResourceLimits limits) {
    return std::make_unique<GeomodelBuildAdapter>(std::move(build_identity),
                                                  limits);
}

std::unique_ptr<science::IAlgorithm> make_geomodel_section_adapter(
    std::string build_identity, ResourceLimits limits) {
    return std::make_unique<GeomodelSectionAdapter>(std::move(build_identity),
                                                    limits);
}

std::unique_ptr<science::IAlgorithm> make_geomodel_fault_displacement_adapter(
    std::string build_identity, ResourceLimits limits) {
    return std::make_unique<GeomodelFaultDisplacementAdapter>(
        std::move(build_identity), limits);
}

std::unique_ptr<science::IAlgorithm> make_geomodel_export_adapter(
    std::string build_identity, ResourceLimits limits) {
    return std::make_unique<GeomodelExportAdapter>(std::move(build_identity),
                                                   limits);
}

std::vector<std::string> register_science_services(
    science::AlgorithmRegistry& registry,
    std::shared_ptr<IPayloadSource> source, const std::string& build_identity,
    const ResourceLimits& limits) {
    std::vector<std::unique_ptr<science::IAlgorithm>> adapters;
    adapters.push_back(make_factor_interpolation_adapter(
        std::move(source), build_identity, limits));
    adapters.push_back(
        make_factor_layer_products_adapter(build_identity, limits));
    adapters.push_back(make_facies_surface_adapter(build_identity, limits));
    adapters.push_back(make_curve_operation_adapter(build_identity, limits));
    adapters.push_back(make_log_match_adapter(build_identity, limits));
    adapters.push_back(make_factor_fusion_adapter(build_identity, limits));
    adapters.push_back(make_geomodel_build_adapter(build_identity, limits));
    adapters.push_back(make_geomodel_section_adapter(build_identity, limits));
    adapters.push_back(
        make_geomodel_fault_displacement_adapter(build_identity, limits));
    adapters.push_back(make_geomodel_export_adapter(build_identity, limits));
    std::vector<std::string> registered;
    for (auto& adapter : adapters) {
        const std::string id = adapter->descriptor().algorithm_id;
        if (registry.register_algorithm(std::move(adapter)).empty()) {
            registered.push_back(id);
        }
    }
    return registered;
}

science::AlgorithmRequestV1 node_request(const std::string& algorithm_id,
                                         const Json& node_params,
                                         std::vector<science::VersionRef> input_refs,
                                         std::string request_id) {
    science::AlgorithmRequestV1 request;
    request.request_id = std::move(request_id);
    request.algorithm_id = algorithm_id;
    if (node_params.is_object()) {
        for (auto it = node_params.begin(); it != node_params.end(); ++it) {
            request.params_json[it.key()] = it.value().dump();
        }
    }
    request.input_refs = std::move(input_refs);
    return request;
}

}  // namespace pwb::science_service
