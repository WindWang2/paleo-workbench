#include "pwb/catalog/models.hpp"
#include "pwb/domain/sha256.hpp"

#include <algorithm>
#include <utility>

namespace pwb::catalog {

namespace {

// Strict-typed manifest field readers (pydantic-parity subset): absent →
// keep the model default; present-but-wrong-typed → error (the caller maps
// that to the corrupt-manifest branch). from_dict never coerces.
using pwb::domain::DataError;
using pwb::domain::ErrorCode;

bool read_string(const domain::Json& data, const char* key, std::string& out,
                 bool required, std::string* error) {
    if (!data.contains(key)) {
        if (required) {
            *error = std::string("missing required field '") + key + "'";
            return false;
        }
        return true;  // keep default
    }
    const domain::Json& value = data.at(key);
    if (!value.is_string()) {
        *error = std::string("field '") + key + "' is not a string";
        return false;
    }
    out = value.get<std::string>();
    return true;
}

bool read_bool(const domain::Json& data, const char* key, bool& out,
               std::string* error) {
    if (!data.contains(key)) return true;  // keep default
    const domain::Json& value = data.at(key);
    if (!value.is_boolean()) {
        *error = std::string("field '") + key + "' is not a boolean";
        return false;
    }
    out = value.get<bool>();
    return true;
}

bool read_json_object(const domain::Json& data, const char* key,
                      domain::Json& out, std::string* error) {
    if (!data.contains(key)) return true;  // keep default
    const domain::Json& value = data.at(key);
    if (!value.is_object()) {
        *error = std::string("field '") + key + "' is not an object";
        return false;
    }
    out = value;
    return true;
}

DataError parse_error(const char* entity, const std::string& reason) {
    return DataError(ErrorCode::InvalidArgument,
                     std::string("invalid ") + entity + " entry: " + reason);
}

}  // namespace

const DataAsset* CatalogDocument::find_asset(
    const domain::AssetId& id) const {
    for (const auto& asset : assets) {
        if (asset.id == id) return &asset;
    }
    return nullptr;
}

const DataVersion* CatalogDocument::find_version(
    const domain::VersionId& id) const {
    for (const auto& version : versions) {
        if (version.id == id) return &version;
    }
    return nullptr;
}

const DataRun* CatalogDocument::find_run(const domain::RunId& id) const {
    for (const auto& run : runs) {
        if (run.id == id) return &run;
    }
    return nullptr;
}

DataAsset* CatalogDocument::find_asset_mut(const domain::AssetId& id) {
    for (auto& asset : assets) {
        if (asset.id == id) return &asset;
    }
    return nullptr;
}

DataVersion* CatalogDocument::find_version_mut(
    const domain::VersionId& id) {
    for (auto& version : versions) {
        if (version.id == id) return &version;
    }
    return nullptr;
}

int CatalogDocument::next_version_number(
    const domain::AssetId& asset_id) const {
    int next = 1;
    for (const auto& version : versions) {
        if (version.asset_id == asset_id) {
            next = std::max(next, version.version_number + 1);
        }
    }
    return next;
}

std::optional<std::string> aggregate_member_sha256(
    const std::vector<VersionMember>& members) {
    std::vector<const VersionMember*> ordered;
    ordered.reserve(members.size());
    for (const auto& member : members) ordered.push_back(&member);
    std::sort(ordered.begin(), ordered.end(),
              [](const VersionMember* a, const VersionMember* b) {
                  if (a->ordinal != b->ordinal) return a->ordinal < b->ordinal;
                  return a->name < b->name;
              });
    std::string text;
    for (const VersionMember* member : ordered) {
        if (!member->sha256.has_value()) return std::nullopt;
        text += member->rel_path + ":" + *member->sha256 + "\n";
    }
    if (text.empty()) return std::nullopt;
    // models.py joins with "\n" WITHOUT a trailing newline.
    if (!text.empty() && text.back() == '\n') text.pop_back();
    return domain::Sha256::of_bytes(text);
}

const Model* CatalogDocument::find_model(const std::string& model_id) const {
    for (const auto& model : models) {
        if (model.model_id == model_id) return &model;
    }
    return nullptr;
}

const ModelVersion* CatalogDocument::find_model_version(
    const std::string& model_id, const std::string& model_version) const {
    for (const auto& version : model_versions) {
        if (version.model_id == model_id &&
            version.model_version == model_version) {
            return &version;
        }
    }
    return nullptr;
}

const ModelVersion* CatalogDocument::find_model_version_by_id(
    const std::string& id) const {
    for (const auto& version : model_versions) {
        if (version.id == id) return &version;
    }
    return nullptr;
}

Model* CatalogDocument::find_model_mut(const std::string& model_id) {
    for (auto& model : models) {
        if (model.model_id == model_id) return &model;
    }
    return nullptr;
}

ModelVersion* CatalogDocument::find_model_version_mut(
    const std::string& model_id, const std::string& model_version) {
    for (auto& version : model_versions) {
        if (version.model_id == model_id &&
            version.model_version == model_version) {
            return &version;
        }
    }
    return nullptr;
}

ModelVersion* CatalogDocument::find_model_version_by_id_mut(
    const std::string& id) {
    for (auto& version : model_versions) {
        if (version.id == id) return &version;
    }
    return nullptr;
}

domain::Json Model::to_dict() const {
    // Key order = pydantic model_dump declaration order (models.py Model).
    domain::Json out = domain::Json::object();
    out["id"] = id;
    out["model_id"] = model_id;
    out["model_name"] = model_name;
    out["model_type"] = model_type;
    out["capability"] = capability;
    out["provider"] = provider;
    out["status"] = status;
    out["metadata"] = metadata;
    out["created_at"] = created_at;
    out["provenance"] = provenance;
    return out;
}

domain::Result<Model> Model::from_dict(const domain::Json& data) {
    if (!data.is_object()) {
        return parse_error("model", "entry is not a JSON object");
    }
    Model model;
    std::string error;
    if (!read_string(data, "model_id", model.model_id, true, &error) ||
        !read_string(data, "model_name", model.model_name, true, &error) ||
        !read_string(data, "id", model.id, false, &error) ||
        !read_string(data, "model_type", model.model_type, false, &error) ||
        !read_string(data, "capability", model.capability, false, &error) ||
        !read_string(data, "provider", model.provider, false, &error) ||
        !read_string(data, "status", model.status, false, &error) ||
        !read_string(data, "created_at", model.created_at, false, &error) ||
        !read_json_object(data, "metadata", model.metadata, &error) ||
        !read_json_object(data, "provenance", model.provenance, &error)) {
        return parse_error("model", error);
    }
    return model;
}

domain::Json ModelVersion::to_dict() const {
    // Key order = pydantic model_dump declaration order (models.py
    // ModelVersion); checksum is the only nullable field.
    domain::Json out = domain::Json::object();
    out["id"] = id;
    out["model_id"] = model_id;
    out["model_version"] = model_version;
    out["artifact_uri"] = artifact_uri;
    out["checksum"] = checksum.has_value()
                          ? domain::Json(*checksum)
                          : domain::Json(nullptr);
    out["input_schema"] = input_schema;
    out["output_schema"] = output_schema;
    out["preprocessing_version"] = preprocessing_version;
    out["runtime"] = runtime;
    out["deterministic"] = deterministic;
    out["demo_only"] = demo_only;
    out["status"] = status;
    out["metadata"] = metadata;
    out["created_at"] = created_at;
    out["provenance"] = provenance;
    return out;
}

domain::Result<ModelVersion> ModelVersion::from_dict(const domain::Json& data) {
    if (!data.is_object()) {
        return parse_error("model version", "entry is not a JSON object");
    }
    ModelVersion version;
    std::string error;
    if (!read_string(data, "model_id", version.model_id, true, &error) ||
        !read_string(data, "id", version.id, false, &error) ||
        !read_string(data, "model_version", version.model_version, false,
                     &error) ||
        !read_string(data, "artifact_uri", version.artifact_uri, false,
                     &error) ||
        !read_string(data, "preprocessing_version",
                     version.preprocessing_version, false, &error) ||
        !read_string(data, "runtime", version.runtime, false, &error) ||
        !read_string(data, "status", version.status, false, &error) ||
        !read_string(data, "created_at", version.created_at, false, &error) ||
        !read_bool(data, "deterministic", version.deterministic, &error) ||
        !read_bool(data, "demo_only", version.demo_only, &error) ||
        !read_json_object(data, "input_schema", version.input_schema,
                          &error) ||
        !read_json_object(data, "output_schema", version.output_schema,
                          &error) ||
        !read_json_object(data, "metadata", version.metadata, &error) ||
        !read_json_object(data, "provenance", version.provenance, &error)) {
        return parse_error("model version", error);
    }
    if (data.contains("checksum")) {
        const domain::Json& checksum = data.at("checksum");
        if (!checksum.is_null()) {
            if (!checksum.is_string()) {
                return parse_error("model version",
                                   "field 'checksum' is not a string");
            }
            version.checksum = checksum.get<std::string>();
        }
    }
    return version;
}

}  // namespace pwb::catalog
