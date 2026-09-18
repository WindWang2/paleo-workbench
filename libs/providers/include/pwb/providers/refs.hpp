// Typed references exchanged with capability providers — C++ port of
// paleo_workbench/providers/refs.py.
//
// Providers never receive bare paths or anonymous dicts: every input carries
// a type name from the TYPED_REFS vocabulary plus a JSON payload (the typed
// ref itself or an in-process domain object in its JSON form). Data outputs
// enter the catalog through the port, keeping it the single write authority.
#pragma once

#include <pwb/domain/json.hpp>

#include <optional>
#include <string>
#include <vector>

namespace pwb::providers {

using Json = pwb::domain::Json;

struct WellRef {
    std::string well_id;
    std::string name;
    std::optional<std::string> path;  // LAS/XML backing file when known

    Json to_json() const;
};

struct SeismicVolumeRef {
    std::string volume_id;
    std::string path;
    std::string kind = "zarr";  // zarr | segy
    std::optional<std::string> version_id;  // catalog version when registered

    Json to_json() const;
};

struct MapDocumentRef {
    std::string document_id;
    std::string title;
    std::optional<std::string> run_id;  // producing DataRun when known

    Json to_json() const;
};

struct FactorDatasetRef {
    std::string factor_name;
    std::string target_horizon;
    std::string unit;
    std::vector<std::string> well_ids;

    Json to_json() const;
};

struct FactorGridRef {
    std::string grid_key;
    std::optional<std::string> artifact_path;
    std::optional<std::string> version_id;

    Json to_json() const;
};

struct PathRef {
    std::string path;
    std::string label;
    std::optional<std::string> mime;

    Json to_json() const;
};

// One output artifact of a provider run. `version` is the catalog's own DTO
// when the artifact entered the catalog; `value` carries an in-memory result
// payload (grid array, map document JSON, …) for the immediate caller.
// to_json() mirrors the Python ArtifactRef.to_dict() key set (no "value").
struct ArtifactRef {
    std::string name;
    std::string kind;  // e.g. "derived_store" | "grid" | "map_document" | "file"
    Json version = Json(nullptr);
    Json value = Json(nullptr);
    std::optional<std::string> path;
    Json metadata = Json::object();

    Json to_json() const;
};

// Uniform outcome of one provider execution.
struct ProviderResult {
    std::vector<ArtifactRef> artifacts;
    std::vector<std::string> warnings;
    Json diagnostics = Json::object();
    Json provenance = Json::object();
    Json metrics = Json::object();

    Json to_json() const;
};

}  // namespace pwb::providers
