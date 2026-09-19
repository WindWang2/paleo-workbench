// pwb::science_service — factor fusion service implementation.

#include <pwb/science_service/fusion_service.hpp>
#include <pwb/science_service/legacy_grid_codec.hpp>

#include <pwb/mapping/factor_grid_io.hpp>

#include <cmath>
#include <limits>
#include <utility>

#include "support.hpp"

namespace pwb::science_service {

using pwb::domain::Json;
using pwb::factor_fusion::FactorGrid;

namespace {

float cell_value(const Json& v) {
    if (v.is_null() || !v.is_number()) {
        return std::numeric_limits<float>::quiet_NaN();
    }
    return pwb::factor_fusion::to_grid_cell(v.get<double>());
}

}  // namespace

FactorGrid legacy_dict_to_fusion_grid(const Json& legacy,
                                      const std::string& factor_name) {
    if (!legacy.is_object() || !legacy.contains("grid_z")
        || !legacy.contains("grid_x") || !legacy.contains("grid_y")) {
        throw std::invalid_argument(
            "legacy grid dict for factor '" + factor_name
                + "' must carry grid_z / grid_x / grid_y");
    }
    const Json& rows = legacy.at("grid_z");
    if (!rows.is_array()) {
        throw std::invalid_argument("grid_z must be a nested array of rows");
    }
    FactorGrid grid;
    grid.factor_name = factor_name;
    const Json& grid_x = legacy.at("grid_x");
    const Json& grid_y = legacy.at("grid_y");
    if (!grid_x.is_array() || !grid_y.is_array()) {
        throw std::invalid_argument("grid_x / grid_y must be arrays");
    }
    grid.width = static_cast<int>(grid_x.size());
    grid.height = static_cast<int>(grid_y.size());
    for (const auto& x : grid_x) {
        grid.grid_x.push_back(x.get<double>());
    }
    for (const auto& y : grid_y) {
        grid.grid_y.push_back(y.get<double>());
    }
    grid.grid_z.reserve(static_cast<std::size_t>(grid.width) * grid.height);
    for (const auto& row : rows) {
        if (!row.is_array()
            || static_cast<int>(row.size()) != grid.width) {
            throw std::invalid_argument(
                "grid_z row width mismatch for factor '" + factor_name + "'");
        }
        for (const auto& v : row) {
            grid.grid_z.push_back(cell_value(v));
        }
    }
    if (static_cast<int>(rows.size()) != grid.height) {
        throw std::invalid_argument(
            "grid_z height mismatch for factor '" + factor_name + "'");
    }
    if (legacy.contains("variance_grid") && legacy.at("variance_grid").is_array()) {
        std::vector<float> variance;
        variance.reserve(grid.grid_z.size());
        for (const auto& row : legacy.at("variance_grid")) {
            if (!row.is_array()) {
                throw std::invalid_argument(
                    "variance_grid rows must be arrays for factor '"
                    + factor_name + "'");
            }
            for (const auto& v : row) {
                variance.push_back(cell_value(v));
            }
        }
        if (variance.size() != grid.grid_z.size()) {
            throw std::invalid_argument(
                "variance_grid size mismatch for factor '" + factor_name
                + "'");
        }
        grid.variance_grid = std::move(variance);
    }
    return grid;
}

pwb::mapping::FactorGrid legacy_dict_to_mapping_grid(
    const Json& legacy, const std::string& factor_name) {
    // One decoder, two carriers: reuse the fusion decode (it owns the shape
    // validation) and widen into the mapping grid vocabulary.
    pwb::factor_fusion::FactorGrid decoded =
        legacy_dict_to_fusion_grid(legacy, factor_name);
    pwb::mapping::FactorGrid grid;
    grid.grid_x = std::move(decoded.grid_x);
    grid.grid_y = std::move(decoded.grid_y);
    grid.grid_z = std::move(decoded.grid_z);
    if (decoded.variance_grid) {
        grid.variance_grid = std::move(*decoded.variance_grid);
    }
    grid.grid_n = static_cast<int>(std::max(decoded.grid_x.size(),
                                            decoded.grid_y.size()));
    grid.n_samples = 0;
    grid.method = "legacy";
    return grid;
}

FactorFusionService::FactorFusionService(std::string build_identity,
                                         ResourceLimits limits)
    : build_identity_(std::move(build_identity)), limits_(limits) {}

science::Result<FactorFusionResult> FactorFusionService::run(
    const FactorFusionRequest& request, science::ProgressSink progress,
    std::stop_token stop) {
    // Grid size guard on every input grid before fuse() allocates.
    for (const auto& [name, grid] : request.parsed_grids) {
        if (grid.grid_z.size() > limits_.max_grid_cells) {
            return detail::make_error(
                limit_code("grid_cells"),
                "fusion input grid '" + name + "' has "
                    + std::to_string(grid.grid_z.size()) + " cells (limit "
                    + std::to_string(limits_.max_grid_cells) + ")");
        }
    }
    if (detail::stage_guard(stop, progress, 0.1, "validate")) {
        return science::TaskCancelled{"validate"};
    }

    // Convert legacy dicts; parsed grids win by name. The parsed payload
    // grids are mapping-kernel carriers — convert to fusion carriers.
    std::map<std::string, FactorGrid> grids;
    for (const auto& [name, parsed] : request.parsed_grids) {
        FactorGrid converted;
        converted.grid_z = parsed.grid_z;
        converted.height = static_cast<int>(parsed.grid_y.size());
        converted.width = static_cast<int>(parsed.grid_x.size());
        converted.grid_x = parsed.grid_x;
        converted.grid_y = parsed.grid_y;
        converted.factor_name = name;
        grids.emplace(name, std::move(converted));
    }
    if (request.grids.is_object()) {
        for (auto it = request.grids.begin(); it != request.grids.end(); ++it) {
            if (grids.contains(it.key())) {
                continue;
            }
            auto converted = detail::catch_kernel<FactorGrid>(
                "factor.fusion_grid", [&] {
                    return legacy_dict_to_fusion_grid(it.value(), it.key());
                });
            if (converted.is_error()) {
                return converted.error();
            }
            if (converted.value().grid_z.size() > limits_.max_grid_cells) {
                return detail::make_error(
                    limit_code("grid_cells"),
                    "fusion input grid '" + it.key() + "' exceeds cell limit "
                        + std::to_string(limits_.max_grid_cells));
            }
            grids[it.key()] = std::move(converted.value());
        }
    }
    if (detail::stage_guard(stop, progress, 0.3, "convert")) {
        return science::TaskCancelled{"convert"};
    }

    auto fused = detail::catch_kernel<pwb::factor_fusion::FusionResult>(
        "factor.fuse", [&]() -> pwb::factor_fusion::FusionResult {
            auto model = pwb::factor_fusion::FusionModel::from_dict(
                request.model_dict, grids);
            return pwb::factor_fusion::fuse(model);
        });
    if (fused.is_error()) {
        return fused.error();
    }
    if (detail::stage_guard(stop, progress, 0.8, "fuse")) {
        return science::TaskCancelled{"fuse"};
    }
    auto& fusion = fused.value();

    ScienceEnvelope envelope;
    envelope.result_type = "factor_fusion";
    // Units: fused products are class likelihoods (unitless); CRS is the
    // common grid CRS when every input agreed (aligned_or_raise guarantees
    // they did — nullptr only when every grid is undeclared).
    envelope.units = "";

    Json payload = Json::object();
    payload["class_names"] = fusion.class_names;
    const std::size_t cells = fusion.likelihood.grid_z.size();
    // Reuse the frozen CONV-18 nested-list encoder (same finite->double /
    // non-finite->null semantics) instead of a third hand-rolled copy.
    auto grid_payload = [](const FactorGrid& g) {
        Json out = Json::object();
        out["width"] = g.width;
        out["height"] = g.height;
        out["grid_z"] = pwb::mapping::encode_legacy_grid_lists(
            g.grid_z, g.height, g.width);
        return out;
    };
    if (cells <= limits_.max_envelope_grid_cells) {
        payload["likelihood"] = grid_payload(fusion.likelihood);
        payload["confidence"] = grid_payload(fusion.confidence);
        if (fusion.variance) {
            payload["variance"] = grid_payload(*fusion.variance);
        }
    } else {
        envelope.diagnostics.push_back(Json{
            {"code", "envelope.grid_omitted"},
            {"severity", "warning"},
            {"message", "fused grids of " + std::to_string(cells)
                            + " cells exceed envelope limit "
                            + std::to_string(limits_.max_envelope_grid_cells)
                            + "; grids omitted (class_names/qc only)"},
        });
    }
    payload["qc"] = fusion.qc;
    envelope.payload = std::move(payload);

    // Common CRS from the fused likelihood's provenance context: from_dict
    // validated alignment, so mirror the first evidence grid's CRS.
    if (!fusion.model.evidences.empty()) {
        const auto& crs = fusion.model.evidences.front().grid.crs;
        if (crs) {
            envelope.crs = *crs;
        }
    }

    Json provenance = Json::object();
    provenance["algorithm_id"] = "factor.fuse";
    provenance["algorithm_version"] = "1.0.0";
    provenance["build_identity"] = build_identity_;
    provenance["generator_version"] =
        pwb::factor_fusion::kFusionGeneratorVersion;
    provenance["model_fingerprint"] = fusion.model.fingerprint();
    provenance["model"] = fusion.model_dict;
    envelope.provenance = std::move(provenance);
    envelope.compute_fingerprint();

    FactorFusionResult result;
    result.envelope = std::move(envelope);
    result.fusion = std::move(fusion);
    detail::stage_guard(stop, progress, 1.0, "envelope");
    return result;
}

}  // namespace pwb::science_service
