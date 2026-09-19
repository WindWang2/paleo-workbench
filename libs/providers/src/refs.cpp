#include <pwb/providers/refs.hpp>

namespace pwb::providers {

Json WellRef::to_json() const {
    Json out = Json::object();
    out["kind"] = "well";
    out["well_id"] = well_id;
    out["name"] = name;
    out["path"] = path.has_value() ? Json(*path) : Json(nullptr);
    return out;
}

Json SeismicVolumeRef::to_json() const {
    Json out = Json::object();
    out["kind"] = "seismic_volume";
    out["volume_id"] = volume_id;
    out["path"] = path;
    out["store_kind"] = kind;
    out["version_id"] = version_id.has_value() ? Json(*version_id) : Json(nullptr);
    return out;
}

Json MapDocumentRef::to_json() const {
    Json out = Json::object();
    out["kind"] = "map_document";
    out["document_id"] = document_id;
    out["title"] = title;
    out["run_id"] = run_id.has_value() ? Json(*run_id) : Json(nullptr);
    return out;
}

Json FactorDatasetRef::to_json() const {
    Json out = Json::object();
    out["kind"] = "factor_dataset";
    out["factor_name"] = factor_name;
    out["target_horizon"] = target_horizon;
    out["unit"] = unit;
    out["well_ids"] = well_ids;
    return out;
}

Json FactorGridRef::to_json() const {
    Json out = Json::object();
    out["kind"] = "factor_grid";
    out["grid_key"] = grid_key;
    out["artifact_path"] = artifact_path.has_value() ? Json(*artifact_path) : Json(nullptr);
    out["version_id"] = version_id.has_value() ? Json(*version_id) : Json(nullptr);
    return out;
}

Json PathRef::to_json() const {
    Json out = Json::object();
    out["kind"] = "path";
    out["path"] = path;
    out["label"] = label;
    out["mime"] = mime.has_value() ? Json(*mime) : Json(nullptr);
    return out;
}

Json ArtifactRef::to_json() const {
    Json out = Json::object();
    out["name"] = name;
    out["kind"] = kind;
    out["version"] = version;
    out["path"] = path.has_value() ? Json(*path) : Json(nullptr);
    out["metadata"] = metadata;
    return out;
}

Json ProviderResult::to_json() const {
    Json out = Json::object();
    out["artifacts"] = Json::array();
    for (const auto& artifact : artifacts) {
        out["artifacts"].push_back(artifact.to_json());
    }
    out["warnings"] = warnings;
    out["diagnostics"] = diagnostics;
    out["provenance"] = provenance;
    out["metrics"] = metrics;
    return out;
}

}  // namespace pwb::providers
