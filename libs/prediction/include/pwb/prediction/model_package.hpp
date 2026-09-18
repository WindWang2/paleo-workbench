// Port of the pure half of paleo_workbench/prediction/model_package.py
// (CONV-21): spatial type constants, ModelPackageManifest, manifest
// loading/parsing and production validation. register_model_package (the
// catalog side-effect half) stays in Python (21-decisions.md D1).
#pragma once

#include <optional>
#include <set>
#include <string>
#include <string_view>

#include "pwb/domain/json.hpp"
#include "pwb/prediction/errors.hpp"

namespace pwb::prediction {

using pwb::domain::Json;

inline constexpr std::string_view kSpatialVectorPolygons = "VECTOR_POLYGONS";
inline constexpr std::string_view kSpatialWellIntervals = "WELL_INTERVALS";
inline constexpr std::string_view kSpatialClassifiedRaster =
    "CLASSIFIED_RASTER";
inline constexpr std::string_view kSpatialNone = "NONE";

inline const std::set<std::string, std::less<>> kKnownSpatialTypes = {
    std::string(kSpatialVectorPolygons), std::string(kSpatialWellIntervals),
    std::string(kSpatialClassifiedRaster), std::string(kSpatialNone), ""};

// model_gates.NON_PROMOTABLE_PROVIDERS / NON_PROMOTABLE_MODEL_TYPES —
// exact-membership checks (no casefold) like the Python source.
inline const std::set<std::string, std::less<>> kNonPromotableProviders = {
    "demo", "local_asset"};
inline const std::set<std::string, std::less<>> kNonPromotableModelTypes = {
    "demo", "heuristic"};

// ModelPackageManifest dataclass — fields and defaults mirror Python.
struct ModelPackageManifest {
    std::string model_id;
    std::string model_version = "1";
    std::string model_name;
    std::string capability;
    std::string provider;
    std::string artifact;
    std::optional<std::string> checksum;
    Json input_schema = Json::object();
    Json output_schema = Json::object();
    std::string preprocessing_version;
    std::string runtime = "python_callable";
    bool deterministic = true;
    std::string spatial_output_type = std::string(kSpatialVectorPolygons);
    std::string model_type = "ml";
    bool demo_only = false;
    bool scientific = true;
    Json provenance = Json::object();
    Json metadata = Json::object();

    // to_dict() — the 17-key fixed-order mapping of the Python dataclass.
    Json to_dict() const;

    // Construct from a to_dict()-shaped Json (adapter for tests/ports;
    // Python callers construct the dataclass directly instead).
    static ModelPackageManifest from_dict(const Json& d);
};

// load_manifest_dict(source): JSON object -> copy; JSON string -> manifest
// file path. Raises ModelPackageError / UnicodeDecodeError like Python.
Json load_manifest_dict(const Json& source);

// parse_model_package_manifest(source, *, base_dir=None).
// base_dir: JSON string path or null.
ModelPackageManifest parse_model_package_manifest(const Json& source,
                                                  const Json& base_dir);

// validate_model_package(manifest, *, require_artifact=True,
// allow_non_scientific=False) -> JSON array of error strings. May fill
// manifest.checksum from the artifact digest (Python side effect).
Json validate_model_package(ModelPackageManifest& manifest,
                            bool require_artifact, bool allow_non_scientific);

}  // namespace pwb::prediction
