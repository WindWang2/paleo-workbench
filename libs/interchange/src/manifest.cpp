// Faithful port of paleo_workbench/interchange/package/manifest.py.
// Key order in to_dict() is the on-disk manifest layout — do not reorder.

#include <pwb/interchange/manifest.hpp>

#include <pwb/interchange/path_safety.hpp>

#include "py_compat.hpp"

#include <cstdio>
#include <stdexcept>

namespace pwb::interchange {

namespace {
using detail::py_llong;
using detail::py_str;
using detail::repr_scalar;
}  // namespace

Json PackageEntry::to_dict() const {
    Json out = Json::object();
    out["path"] = path;
    out["sha256"] = sha256;
    out["size_bytes"] = size_bytes;
    out["kind"] = kind;
    return out;
}

PackageEntry PackageEntry::from_dict(const Json& data) {
    PackageEntry entry;
    entry.path = py_str(data.at("path"));
    entry.sha256 = py_str(data.at("sha256"));
    entry.size_bytes = py_llong(data.at("size_bytes"));
    entry.kind = data.contains("kind") ? py_str(data.at("kind")) : "artifact";
    return entry;
}

Json PackageManifest::to_dict() const {
    Json out = Json::object();
    out["kind"] = kind;
    out["schema_version"] = schema_version;
    Json project = Json::object();
    project["name"] = project_name;
    project["file"] = project_file;
    out["project"] = project;
    out["created_at"] = created_at;
    Json application = Json::object();
    application["name"] = application_name;
    application["version"] = application_version;
    out["application"] = application;
    Json entry_list = Json::array();
    for (const auto& entry : entries) {
        entry_list.push_back(entry.to_dict());
    }
    out["entries"] = entry_list;
    out["external_dependencies"] = external_dependencies;
    out["missing_dependencies"] = missing_dependencies;
    Json outputs = Json::array();
    for (const auto& output : generated_outputs) {
        outputs.push_back(output);
    }
    out["generated_outputs"] = outputs;
    out["provenance"] = provenance;
    out["options"] = options;
    out["total_size_bytes"] = total_size_bytes;
    out["entry_count"] = static_cast<long long>(entries.size());
    return out;
}

PackageManifest PackageManifest::from_dict(const Json& data) {
    const Json project = data.contains("project") && data.at("project").is_object()
        ? data.at("project")
        : Json::object();
    const Json application =
        data.contains("application") && data.at("application").is_object()
        ? data.at("application")
        : Json::object();

    const Json raw_version = data.contains("schema_version")
        ? data.at("schema_version")
        : Json(0);
    if (raw_version.is_boolean() || !raw_version.is_number_integer()) {
        throw std::invalid_argument("schema_version 必须是整数，得到 "
                                    + repr_scalar(raw_version));
    }

    PackageManifest manifest;
    manifest.kind = data.contains("kind") ? py_str(data.at("kind")) : kManifestKind;
    manifest.schema_version = raw_version.get<int>();
    manifest.project_name = project.contains("name") ? py_str(project.at("name")) : "";
    manifest.project_file = project.contains("file") ? py_str(project.at("file")) : "";
    manifest.created_at = data.contains("created_at") ? py_str(data.at("created_at")) : "";
    manifest.application_name =
        application.contains("name") ? py_str(application.at("name")) : "paleo-workbench";
    manifest.application_version =
        application.contains("version") ? py_str(application.at("version")) : "";
    // Python is fail-closed here: list(5) / dict(5) / int(None) raise
    // TypeError/ValueError, which the verifiers surface as corrupt-manifest.
    // Silently skipping malformed fields could flip a verify verdict.
    if (data.contains("entries")) {
        const Json& entries = data.at("entries");
        if (!entries.is_array()) {
            throw std::invalid_argument("'int' object is not iterable");
        }
        for (const auto& item : entries) {
            manifest.entries.push_back(PackageEntry::from_dict(item));
        }
    }
    if (data.contains("external_dependencies")) {
        if (!data.at("external_dependencies").is_array()) {
            throw std::invalid_argument("'int' object is not iterable");
        }
        manifest.external_dependencies = data.at("external_dependencies");
    }
    if (data.contains("missing_dependencies")) {
        if (!data.at("missing_dependencies").is_array()) {
            throw std::invalid_argument("'int' object is not iterable");
        }
        manifest.missing_dependencies = data.at("missing_dependencies");
    }
    if (data.contains("generated_outputs")) {
        if (!data.at("generated_outputs").is_array()) {
            throw std::invalid_argument("'int' object is not iterable");
        }
        for (const auto& item : data.at("generated_outputs")) {
            manifest.generated_outputs.push_back(py_str(item));
        }
    }
    if (data.contains("provenance")) {
        if (!data.at("provenance").is_object()) {
            throw std::invalid_argument("'" +
                std::string(data.at("provenance").is_null() ? "NoneType" : "int") +
                "' object is not iterable");
        }
        manifest.provenance = data.at("provenance");
    }
    if (data.contains("options")) {
        if (!data.at("options").is_object()) {
            throw std::invalid_argument("argument must be a dict, not " +
                std::string(data.at("options").is_null() ? "NoneType" : "int"));
        }
        manifest.options = data.at("options");
    }
    if (data.contains("total_size_bytes")
        && !data.at("total_size_bytes").is_null()) {
        manifest.total_size_bytes =
            py_llong(data.at("total_size_bytes"));
    }
    return manifest;
}

std::string PackageManifest::dumps() const { return to_dict().dump(1); }

std::set<std::string> PackageManifest::entry_paths() const {
    std::set<std::string> paths;
    for (const auto& entry : entries) {
        paths.insert(entry.path);
    }
    return paths;
}

void PackageManifest::validate_paths() const {
    std::set<std::string> seen_casefold;
    std::set<std::string> seen_nfc;
    for (const auto& entry : entries) {
        const std::string pure =
            safe_relative_path(entry.path, "manifest entry");
        check_collision(pure, seen_casefold, seen_nfc);
    }
    if (!project_file.empty()) {
        safe_relative_path(project_file, "manifest project file");
    }
}

std::filesystem::path write_manifest(const PackageManifest& manifest,
                                     const std::filesystem::path& package_root) {
    manifest.validate_paths();
    const std::filesystem::path target = package_root / kManifestFilename;
    const std::string payload = manifest.dumps();
    const std::filesystem::path temp = package_root
        / (std::string(".") + kManifestFilename + ".tmp");
    {
        std::FILE* handle = std::fopen(temp.string().c_str(), "wb");
        if (handle == nullptr) {
            throw std::runtime_error("cannot write manifest temp: "
                                     + temp.string());
        }
        const std::size_t written = std::fwrite(payload.data(), 1, payload.size(),
                                                handle);
        std::fclose(handle);
        if (written != payload.size()) {
            throw std::runtime_error("short write on manifest temp");
        }
    }
    std::filesystem::rename(temp, target);
    return target;
}

PackageManifest read_manifest(const std::filesystem::path& package_root) {
    const std::filesystem::path path = package_root / kManifestFilename;
    std::FILE* handle = std::fopen(path.string().c_str(), "rb");
    if (handle == nullptr) {
        throw std::runtime_error("cannot open manifest: " + path.string());
    }
    std::string payload;
    char buffer[8192];
    std::size_t chunk = 0;
    while ((chunk = std::fread(buffer, 1, sizeof(buffer), handle)) > 0) {
        payload.append(buffer, chunk);
    }
    std::fclose(handle);
    Json data;
    try {
        data = Json::parse(payload);
    } catch (const Json::parse_error&) {
        throw;  // raw parser error; verifier.py adds the single prefix
    }
    PackageManifest manifest = PackageManifest::from_dict(data);
    manifest.validate_paths();
    return manifest;
}

}  // namespace pwb::interchange
