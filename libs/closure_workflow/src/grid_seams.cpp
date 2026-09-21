#include <pwb/closure_workflow/grid_seams.hpp>

#include <pwb/closure_workflow/integrated_compilation.hpp>

#include <cmath>
#include <cstdint>
#include <string>
#include <vector>

namespace pwb::closure_workflow {
namespace {

// A grid cell on the wire: a JSON number, or the literal "NaN" string for
// a non-finite cell (encode_grid_artifact's convention).
bool decode_cell(const pwb::domain::Json& value, float& out) {
    if (value.is_number()) {
        const double v = value.get<double>();
        out = pwb::factor_fusion::to_grid_cell(v);
        return true;
    }
    if (value.is_string() && value.get<std::string>() == "NaN") {
        out = std::numeric_limits<float>::quiet_NaN();
        return true;
    }
    return false;
}

bool decode_cells(const pwb::domain::Json& array, std::size_t expected,
                  std::vector<float>& out) {
    if (!array.is_array() || array.size() != expected) return false;
    out.clear();
    out.reserve(expected);
    for (const auto& cell : array) {
        float decoded = 0.0f;
        if (!decode_cell(cell, decoded)) return false;
        out.push_back(decoded);
    }
    return true;
}

bool decode_axes(const pwb::domain::Json& array, std::size_t expected,
                 std::vector<double>& out) {
    if (!array.is_array() || array.size() != expected) return false;
    out.clear();
    out.reserve(expected);
    for (const auto& value : array) {
        if (!value.is_number()) return false;
        out.push_back(value.get<double>());
    }
    return true;
}

std::optional<std::string> optional_string(const pwb::domain::Json& value) {
    if (value.is_string()) return value.get<std::string>();
    return std::nullopt;
}

}  // namespace

std::optional<FactorGrid> decode_grid_artifact(const std::string& payload) {
    pwb::domain::Json artifact;
    try {
        artifact = pwb::domain::Json::parse(payload);
    } catch (const std::exception&) {
        return std::nullopt;
    }
    if (!artifact.is_object()) return std::nullopt;
    if (!artifact.contains("artifact_kind") || !artifact["artifact_kind"].is_string() ||
        artifact["artifact_kind"].get<std::string>() != "factor_grid") {
        return std::nullopt;
    }

    FactorGrid grid;
    auto number_or = [](const pwb::domain::Json& object, const char* key,
                        long long fallback) -> long long {
        auto it = object.find(key);
        if (it == object.end() || !it->is_number()) return fallback;
        return it->get<long long>();
    };
    const long long width = number_or(artifact, "width", -1);
    const long long height = number_or(artifact, "height", -1);
    if (width <= 0 || height <= 0) return std::nullopt;
    grid.width = static_cast<int>(width);
    grid.height = static_cast<int>(height);
    const std::size_t cells =
        static_cast<std::size_t>(width) * static_cast<std::size_t>(height);

    if (!decode_cells(artifact.value("grid_z", pwb::domain::Json::array()), cells,
                      grid.grid_z)) {
        return std::nullopt;
    }
    if (!decode_axes(artifact.value("grid_x", pwb::domain::Json::array()),
                     static_cast<std::size_t>(width), grid.grid_x)) {
        return std::nullopt;
    }
    if (!decode_axes(artifact.value("grid_y", pwb::domain::Json::array()),
                     static_cast<std::size_t>(height), grid.grid_y)) {
        return std::nullopt;
    }
    if (artifact.contains("variance_grid") && !artifact["variance_grid"].is_null()) {
        std::vector<float> variance;
        if (!decode_cells(artifact["variance_grid"], cells, variance)) {
            return std::nullopt;
        }
        grid.variance_grid = std::move(variance);
    }

    grid.factor_name = artifact.value("factor_name", std::string());
    grid.algorithm_id = artifact.value("algorithm_id", std::string());
    grid.algorithm_parameters =
        artifact.value("algorithm_parameters", pwb::domain::Json::object());
    if (!grid.algorithm_parameters.is_object()) {
        grid.algorithm_parameters = pwb::domain::Json::object();
    }
    grid.crs = optional_string(artifact.value("crs", pwb::domain::Json(nullptr)));
    grid.unit = optional_string(artifact.value("unit", pwb::domain::Json(nullptr)));
    grid.generator_version =
        optional_string(artifact.value("generator_version", pwb::domain::Json(nullptr)));
    grid.run_ref =
        optional_string(artifact.value("run_ref", pwb::domain::Json(nullptr)));
    const pwb::domain::Json source_refs =
        artifact.value("source_refs", pwb::domain::Json::array());
    if (source_refs.is_array()) {
        for (const auto& ref : source_refs) {
            if (ref.is_string()) grid.source_refs.push_back(ref.get<std::string>());
        }
    }
    return grid;
}

std::optional<FactorGrid> load_grid_from_version(CatalogRepository* catalog,
                                                 const std::string& version_id) {
    if (catalog == nullptr) return std::nullopt;
    const auto version = catalog->resolve_version(version_id);
    if (!version.has_value() || version->payload_json.empty()) return std::nullopt;
    return decode_grid_artifact(version->payload_json);
}

IntegratedGridSeams make_production_grid_seams(CatalogRepository* catalog,
                                               LiveGridResolver live_resolver) {
    IntegratedGridSeams seams;
    seams.grid_from_version = [catalog](const std::string& version_id)
        -> std::optional<FactorGrid> {
        return load_grid_from_version(catalog, version_id);
    };
    // The task's CURRENT grid (Python factor_grid_artifacts' three-level
    // resolution, C++ form): the persisted catalog artifact is the
    // on-disk source of truth (the npz artifact's C++ transport), then the
    // host's live cache / legacy inline parameters. A resolver that is
    // absent leaves only the catalog level — every other case refuses.
    seams.grid_for_task = [catalog, live_resolver](const Json& task)
        -> std::optional<FactorGrid> {
        if (task.is_object()) {
            auto it = task.find("grid_artifact_version_id");
            if (it != task.end() && it->is_string()) {
                const std::string version_id = it->get<std::string>();
                if (!version_id.empty()) {
                    // The task PINS a catalog version: when that artifact
                    // cannot be loaded the seam refuses. Falling back to the
                    // live grid would silently substitute current data for a
                    // stale pin — exactly what the acceptance loop's
                    // staleness detection must see.
                    return load_grid_from_version(catalog, version_id);
                }
            }
        }
        if (live_resolver) return live_resolver(task);
        return std::nullopt;
    };
    return seams;
}

}  // namespace pwb::closure_workflow
