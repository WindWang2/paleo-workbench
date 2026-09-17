// Faithful port of paleo_workbench/interchange/package/manifest.py.
// Key order in to_dict() is the on-disk manifest layout — do not reorder.

#include <pwb/interchange/manifest.hpp>

#include <pwb/interchange/path_safety.hpp>

#include <cstdio>
#include <stdexcept>

namespace pwb::interchange {

namespace {

// Python repr() of a raw JSON scalar, for the schema_version error message.
std::string repr_scalar(const Json& value) {
    if (value.is_boolean()) {
        return value.get<bool>() ? "True" : "False";
    }
    if (value.is_null()) {
        return "None";
    }
    if (value.is_string()) {
        return python_repr(value.get<std::string>());
    }
    if (value.is_number_float()) {
        // %g matches Python repr for the frozen 2.5-class values only
        // (6 significant digits); exotic floats are out of oracle scope.
        const double number = value.get<double>();
        char buffer[32];
        std::snprintf(buffer, sizeof(buffer), "%g", number);
        return buffer;
    }
    return value.dump();
}

// Python str() coercion of a raw JSON scalar (from_dict stores strings).
std::string py_str(const Json& value) {
    if (value.is_null()) {
        return "None";
    }
    if (value.is_boolean()) {
        return value.get<bool>() ? "True" : "False";
    }
    if (value.is_string()) {
        return value.get<std::string>();
    }
    return repr_scalar(value);
}

// Python int() coercion of a raw JSON scalar; raises ValueError/TypeError
// with the Python message on un-coercible input.
long long py_llong(const Json& value) {
    if (value.is_boolean()) {
        return value.get<bool>() ? 1 : 0;
    }
    if (value.is_number_integer()) {
        return value.get<long long>();
    }
    if (value.is_number_float()) {
        return static_cast<long long>(value.get<double>());
    }
    if (value.is_string()) {
        const std::string raw = value.get<std::string>();
        std::size_t begin = raw.find_first_not_of(" \t\n\r\v\f");
        const bool negative = begin != std::string::npos
            && (raw[begin] == '+' || raw[begin] == '-');
        const std::size_t digits_begin = begin + (negative ? 1 : 0);
        if (begin == std::string::npos
            || raw.find_first_not_of("0123456789", digits_begin)
                != std::string::npos
            || digits_begin >= raw.size()) {
            throw std::invalid_argument(
                "invalid literal for int() with base 10: " + python_repr(raw));
        }
        long long parsed = std::stoll(raw.substr(digits_begin));
        return negative ? -parsed : parsed;
    }
    // Frozen scope: only JSON null reaches this line in the oracle; Python
    // would name the actual type here.
    throw std::invalid_argument(
        "int() argument must be a string, a bytes-like object or a real "
        "number, not 'NoneType'");
}

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
    if (data.contains("entries") && data.at("entries").is_array()) {
        for (const auto& item : data.at("entries")) {
            manifest.entries.push_back(PackageEntry::from_dict(item));
        }
    }
    if (data.contains("external_dependencies")
        && data.at("external_dependencies").is_array()) {
        manifest.external_dependencies = data.at("external_dependencies");
    }
    if (data.contains("missing_dependencies")
        && data.at("missing_dependencies").is_array()) {
        manifest.missing_dependencies = data.at("missing_dependencies");
    }
    if (data.contains("generated_outputs")
        && data.at("generated_outputs").is_array()) {
        for (const auto& item : data.at("generated_outputs")) {
            manifest.generated_outputs.push_back(py_str(item));
        }
    }
    if (data.contains("provenance") && data.at("provenance").is_object()) {
        manifest.provenance = data.at("provenance");
    }
    if (data.contains("options") && data.at("options").is_object()) {
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
    } catch (const Json::parse_error& exc) {
        throw std::runtime_error(std::string("manifest 解析失败: ") + exc.what());
    }
    PackageManifest manifest = PackageManifest::from_dict(data);
    manifest.validate_paths();
    return manifest;
}

}  // namespace pwb::interchange
