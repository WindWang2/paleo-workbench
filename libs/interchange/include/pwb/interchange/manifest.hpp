#pragma once

// pwb::interchange — package manifest V2, a faithful C++ port of
// paleo_workbench/interchange/package/manifest.py (conv-14).
//
// Every stored path is a package-relative POSIX path validated by
// safe_relative_path on write AND read; machine-local absolute paths may
// appear only in external_dependencies/missing_dependencies payloads.
// dumps() must be byte-identical to Python's
// json.dumps(to_dict(), ensure_ascii=False, indent=1) — the oracle freezes
// full manifest texts including CJK paths.

#include <pwb/domain/json.hpp>

#include <filesystem>
#include <set>
#include <string>
#include <vector>

namespace pwb::interchange {

using pwb::domain::Json;

inline constexpr const char* kManifestFilename = "manifest.json";
inline constexpr const char* kManifestKind = "paleo-package";
inline constexpr int kManifestSchemaVersion = 2;

struct PackageEntry {
    std::string path;  // package-relative POSIX
    std::string sha256;
    long long size_bytes = 0;
    std::string kind = "artifact";  // "project" | "artifact" | "metadata"

    Json to_dict() const;
    static PackageEntry from_dict(const Json& data);
    bool operator==(const PackageEntry&) const = default;
};

struct PackageManifest {
    std::string kind = kManifestKind;
    int schema_version = kManifestSchemaVersion;
    std::string project_name;
    std::string project_file;  // package-relative path of the .paleo.json
    std::string created_at;
    std::string application_name = "paleo-workbench";
    std::string application_version;
    std::vector<PackageEntry> entries;
    Json external_dependencies = Json::array();  // opaque records, order kept
    Json missing_dependencies = Json::array();
    std::vector<std::string> generated_outputs;  // version ids
    Json provenance = Json::object();
    Json options = Json::object();
    long long total_size_bytes = 0;

    Json to_dict() const;
    static PackageManifest from_dict(const Json& data);
    std::string dumps() const;
    std::set<std::string> entry_paths() const;
    // Fail-closed: every stored path must be a safe, collision-free relative
    // path (duplicates after NFC/casefold are rejected). Throws
    // UnsafePathError with the Python message.
    void validate_paths() const;
    bool operator==(const PackageManifest&) const = default;
};

// validate_paths() then atomically write "<package_root>/manifest.json".
std::filesystem::path write_manifest(const PackageManifest& manifest,
                                     const std::filesystem::path& package_root);

// Parse manifest.json; throws on corrupt JSON or unsafe paths (the JSON
// syntax error text is parser-specific and NOT oracle-frozen).
PackageManifest read_manifest(const std::filesystem::path& package_root);

}  // namespace pwb::interchange
