// Faithful port of paleo_workbench/interchange/package/{verifier,
// verifier_zip,builder}.py (conv-14b). Issue order, message texts and JSON
// key order are the contract — do not reorder.

#include "pwb/interchange/package_runtime.hpp"

#include <pwb/domain/diagnostics.hpp>
#include <pwb/domain/sha256.hpp>
#include <pwb/interchange/atomic_file.hpp>
#include <pwb/interchange/unicode.hpp>
#include <pwb/interchange/zip_archive.hpp>

#include "py_compat.hpp"

#include <algorithm>
#include <cstdio>
#include <fstream>
#include <stdexcept>
#include <system_error>
#include <utility>

namespace pwb::interchange {

namespace {
namespace detail = ::pwb::interchange::detail;
}  // namespace

namespace {

Json issues_to_json(const std::vector<VerifyIssue>& issues) {
    Json out = Json::array();
    for (const auto& issue : issues) out.push_back(issue.to_dict());
    return out;
}

// Python sorted() on pathlib.Path: lexicographic over the *tuple of parts*,
// not the joined string ("a/b" sorts before "a.txt").
struct PathPartsLess {
    static std::vector<std::string> split(const std::filesystem::path& path) {
        std::vector<std::string> parts;
        for (const auto& part : path) parts.push_back(part.string());
        return parts;
    }
    bool operator()(const std::filesystem::path& a, const std::filesystem::path& b) const {
        return split(a) < split(b);
    }
};

void remove_tree_best_effort(const std::filesystem::path& target) {
    std::error_code ec;
    std::filesystem::remove_all(target, ec);
}

// Python fnmatch("*.staging", name) — only case for our policy.
bool matches_staging_ignore(const std::string& name) {
    return name.size() >= 8 && name.compare(name.size() - 8, 8, ".staging") == 0;
}

Json parse_json_text(const std::string& text) {
    return Json::parse(text);  // throws on invalid (parser-specific message)
}

// Python bool() of a raw JSON scalar.
bool python_truth(const Json& value) {
    if (value.is_null()) return false;
    if (value.is_boolean()) return value.get<bool>();
    if (value.is_number()) {
        if (value.is_number_integer()) return value.get<long long>() != 0;
        return value.get<double>() != 0.0;  // bool(float('nan')) is True
    }
    if (value.is_string()) return !value.get<std::string>().empty();
    if (value.is_array()) return !value.empty();
    if (value.is_object()) return !value.empty();
    return true;
}

}  // namespace

Json VerifyIssue::to_dict() const {
    Json out = Json::object();
    out["severity"] = severity;
    out["code"] = code;
    out["message"] = message;
    return out;
}

bool PackageVerifyReport::ok() const {
    for (const auto& issue : issues) {
        if (issue.severity == "error") return false;
    }
    return true;
}

std::vector<VerifyIssue> PackageVerifyReport::errors() const {
    std::vector<VerifyIssue> out;
    for (const auto& issue : issues) {
        if (issue.severity == "error") out.push_back(issue);
    }
    return out;
}

std::vector<VerifyIssue> PackageVerifyReport::warnings() const {
    std::vector<VerifyIssue> out;
    for (const auto& issue : issues) {
        if (issue.severity == "warning") out.push_back(issue);
    }
    return out;
}

Json PackageVerifyReport::to_dict() const {
    Json out = Json::object();
    out["package_path"] = package_path;
    out["ok"] = ok();
    out["checked_entries"] = checked_entries;
    out["total_size_bytes"] = total_size_bytes;
    out["issues"] = issues_to_json(issues);
    out["project_name"] = manifest ? manifest->project_name : "";
    return out;
}

const std::vector<std::string> kKnownPackageExtraFiles = {
    "delivery-report.json", "delivery-report.md",
};

std::string_view to_string(ExternalPolicy policy) {
    switch (policy) {
        case ExternalPolicy::KEEP: return "keep";
        case ExternalPolicy::VENDOR: return "vendor";
        case ExternalPolicy::EXCLUDE: return "exclude";
    }
    return "keep";
}

Json PackagePlan::summary() const {
    Json counts = Json::object();
    for (const auto& item : items) {
        if (counts.contains(item.status)) {
            counts[item.status] = counts[item.status].get<long long>() + 1;
        } else {
            counts[item.status] = 1;
        }
    }
    Json out = Json::object();
    out["project_file"] = project_file;
    out["counts"] = std::move(counts);
    out["estimated_bytes"] = estimated_bytes;
    out["excluded_dirs"] = excluded_dirs;
    return out;
}

std::optional<std::string> sha256_file(const std::filesystem::path& file) {
    return pwb::domain::Sha256::of_file(file);
}

// --- directory verification --------------------------------------------------

namespace {

PackageVerifyReport verify_directory(const std::filesystem::path& package_root, bool deep) {
    PackageVerifyReport report;
    report.package_path = package_root.string();
    if (!std::filesystem::is_directory(package_root)) {
        report.issues.push_back(
            {"error", "missing-package", "包目录不存在: " + package_root.string()});
        return report;
    }

    const std::filesystem::path manifest_path = package_root / kManifestFilename;
    if (!std::filesystem::is_regular_file(manifest_path)) {
        report.issues.push_back({"error", "missing-manifest", "缺少 manifest.json"});
        return report;
    }
    PackageManifest manifest;
    try {
        manifest = read_manifest(package_root);
    } catch (const UnsafePathError& exc) {
        report.issues.push_back({"error", "unsafe-manifest-path", exc.what()});
        return report;
    } catch (const std::exception& exc) {
        report.issues.push_back(
            {"error", "corrupt-manifest", std::string("manifest 解析失败: ") + exc.what()});
        return report;
    }
    report.manifest = manifest;

    if (manifest.kind != kManifestKind) {
        report.issues.push_back(
            {"error", "wrong-kind", "manifest kind=" + python_repr(manifest.kind)});
    }
    if (manifest.schema_version != kManifestSchemaVersion) {
        report.issues.push_back(
            {"error", "unsupported-schema",
             "manifest schema_version=" + std::to_string(manifest.schema_version) +
                 "，支持 (" + std::to_string(kManifestSchemaVersion) + ",)"});
    }

    if (!manifest.project_file.empty()) {
        const std::filesystem::path project_file = package_root / manifest.project_file;
        if (!std::filesystem::is_regular_file(project_file)) {
            report.issues.push_back({"error", "missing-project", "工程文件缺失"});
        } else {
            try {
                std::ifstream in(project_file, std::ios::binary);
                const std::string text((std::istreambuf_iterator<char>(in)),
                                       std::istreambuf_iterator<char>());
                (void)parse_json_text(text);
            } catch (const std::exception& exc) {
                report.issues.push_back(
                    {"error", "corrupt-project", std::string("工程文件损坏: ") + exc.what()});
            }
        }
    } else {
        report.issues.push_back({"error", "missing-project", "工程文件缺失"});
    }

    const std::filesystem::path catalog_manifest = package_root /
        (manifest.project_name + ".artifacts") / "metadata" / "catalog.json";
    if (std::filesystem::is_regular_file(catalog_manifest)) {
        try {
            std::ifstream in(catalog_manifest, std::ios::binary);
            const std::string text((std::istreambuf_iterator<char>(in)),
                                   std::istreambuf_iterator<char>());
            (void)parse_json_text(text);
        } catch (const std::exception& exc) {
            report.issues.push_back(
                {"error", "corrupt-catalog", std::string("catalog manifest 损坏: ") + exc.what()});
        }
    } else {
        report.issues.push_back(
            {"warning", "no-catalog", "包内无 portable catalog manifest（仅工程文件包）"});
    }

    std::set<std::string> seen_casefold;
    std::set<std::string> seen_nfc;
    for (const auto& entry : manifest.entries) {
        std::string canonical;
        try {
            canonical = safe_relative_path(entry.path, "manifest entry");
            check_collision(canonical, seen_casefold, seen_nfc);
        } catch (const UnsafePathError& exc) {
            report.issues.push_back({"error", "unsafe-entry", exc.what()});
            continue;
        }
        const std::filesystem::path target = package_root / entry.path;
        if (std::filesystem::is_symlink(target)) {
            report.issues.push_back(
                {"error", "symlink-entry", "条目是符号链接: " + entry.path});
            continue;
        }
        if (!std::filesystem::is_regular_file(target)) {
            report.issues.push_back(
                {"error", "missing-entry", "条目缺失: " + entry.path});
            continue;
        }
        const long long size = static_cast<long long>(
            std::filesystem::file_size(target));
        report.checked_entries += 1;
        report.total_size_bytes += size;
        if (size != entry.size_bytes) {
            report.issues.push_back(
                {"error", "size-mismatch",
                 entry.path + ": 记录 " + std::to_string(entry.size_bytes) + "B 实际 " +
                     std::to_string(size) + "B"});
            continue;
        }
        if (deep) {
            const std::optional<std::string> digest = sha256_file(target);
            if (!digest || *digest != entry.sha256) {
                report.issues.push_back(
                    {"error", "checksum-mismatch", entry.path + ": sha256 不匹配"});
            }
        }
    }

    // unknown files present in the package but absent from the manifest
    std::set<std::string> known = manifest.entry_paths();
    known.insert(kManifestFilename);
    known.insert(kKnownPackageExtraFiles.begin(), kKnownPackageExtraFiles.end());
    std::vector<std::filesystem::path> all_paths;
    std::error_code ec;
    for (auto it = std::filesystem::recursive_directory_iterator(
             package_root, std::filesystem::directory_options::none, ec);
         it != std::filesystem::recursive_directory_iterator(); it.increment(ec)) {
        all_paths.push_back(it->path());
    }
    std::sort(all_paths.begin(), all_paths.end(), PathPartsLess());
    for (const auto& path : all_paths) {
        std::string rel;
        {
            rel = path.lexically_relative(package_root).generic_string();
        }
        if (known.count(rel) > 0) continue;
        if (std::filesystem::is_symlink(path)) {
            report.issues.push_back(
                {"error", "symlink-extra", "未知符号链接: " + rel});
        } else if (std::filesystem::is_regular_file(path)) {
            report.issues.push_back(
                {"warning", "unknown-file", "manifest 之外的文件: " + rel});
        }
    }

    // the manifest's own totals must not lie
    if (report.total_size_bytes != manifest.total_size_bytes) {
        report.issues.push_back(
            {"error", "total-size-mismatch",
             "manifest total_size_bytes=" + std::to_string(manifest.total_size_bytes) +
                 "，实际校验合计 " + std::to_string(report.total_size_bytes)});
    }
    return report;
}

// --- zip-container verification ---------------------------------------------

PackageVerifyReport verify_zip_container_impl(const std::filesystem::path& zip_path, bool deep) {
    PackageVerifyReport report;
    report.package_path = zip_path.string();

    std::unique_ptr<ZipReader> bundle;
    try {
        bundle = std::make_unique<ZipReader>(zip_path);
    } catch (const ZipError& exc) {
        report.issues.push_back(
            {"error", "bad-zip", std::string("zip 容器损坏: ") + exc.what()});
        return report;
    }

    std::vector<std::string> names;
    try {
        names = safe_members(*bundle, "package zip");
    } catch (const UnsafePathError& exc) {
        report.issues.push_back({"error", "unsafe-zip-entry", exc.what()});
        return report;
    }

    const std::set<std::string> names_set(names.begin(), names.end());
    if (names_set.count(kManifestFilename) == 0) {
        report.issues.push_back({"error", "missing-manifest", "缺少 manifest.json"});
        return report;
    }

    // positional pairing: safe_members name i belongs to infolist entry i
    std::map<std::string, const ZipEntryInfo*> infos;
    {
        const auto& entries = bundle->infolist();
        for (std::size_t i = 0; i < names.size() && i < entries.size(); ++i) {
            infos[names[i]] = &entries[i];
        }
    }

    PackageManifest manifest;
    try {
        const ZipEntryInfo* raw_manifest = bundle->find(kManifestFilename);
        if (raw_manifest == nullptr) {
            throw std::runtime_error(std::string("'") + kManifestFilename + "'");
        }
        const std::string payload = bundle->read_entry_bytes(*raw_manifest);
        manifest = PackageManifest::from_dict(parse_json_text(payload));
        manifest.validate_paths();
    } catch (const ZipError&) {
        throw;  // Python: BadZipFile is not in the corrupt-manifest tuple
    } catch (const std::exception& exc) {
        report.issues.push_back(
            {"error", "corrupt-manifest", std::string("manifest 解析失败: ") + exc.what()});
        return report;
    }
    report.manifest = manifest;

    if (manifest.kind != kManifestKind) {
        report.issues.push_back(
            {"error", "wrong-kind", "manifest kind=" + python_repr(manifest.kind)});
    }
    if (manifest.schema_version != kManifestSchemaVersion) {
        report.issues.push_back(
            {"error", "unsupported-schema",
             "manifest schema_version=" + std::to_string(manifest.schema_version) +
                 "，支持 (" + std::to_string(kManifestSchemaVersion) + ",)"});
    }

    if (!manifest.project_file.empty()) {
        const auto it = infos.find(manifest.project_file);
        if (it != infos.end()) {
            try {
                (void)parse_json_text(bundle->read_entry_bytes(*it->second));
            } catch (const ZipError&) {
                throw;  // Python: BadZipFile is not in the corrupt-project tuple
            } catch (const std::exception& exc) {
                report.issues.push_back(
                    {"error", "corrupt-project", std::string("工程文件损坏: ") + exc.what()});
            }
        } else {
            report.issues.push_back({"error", "missing-project", "工程文件缺失"});
        }
    }

    const std::string catalog_rel = manifest.project_name.empty()
        ? std::string()
        : manifest.project_name + ".artifacts/metadata/catalog.json";
    if (!catalog_rel.empty()) {
        const auto it = infos.find(catalog_rel);
        if (it != infos.end()) {
            try {
                (void)parse_json_text(bundle->read_entry_bytes(*it->second));
            } catch (const ZipError&) {
                throw;  // Python: BadZipFile is not in the corrupt-catalog tuple
            } catch (const std::exception& exc) {
                report.issues.push_back(
                    {"error", "corrupt-catalog", std::string("catalog manifest 损坏: ") + exc.what()});
            }
        } else {
            report.issues.push_back(
                {"warning", "no-catalog", "包内无 portable catalog manifest（仅工程文件包）"});
        }
    }

    for (const auto& entry : manifest.entries) {
        const auto it = infos.find(entry.path);
        if (it == infos.end()) {
            report.issues.push_back({"error", "missing-entry", "条目缺失: " + entry.path});
            continue;
        }
        const ZipEntryInfo* info = it->second;
        if (info->is_dir()) {
            report.issues.push_back(
                {"error", "entry-is-directory", "条目是目录而非文件: " + entry.path});
            continue;
        }
        report.checked_entries += 1;
        report.total_size_bytes += static_cast<long long>(info->size);
        if (static_cast<long long>(info->size) != entry.size_bytes) {
            report.issues.push_back(
                {"error", "size-mismatch",
                 entry.path + ": 记录 " + std::to_string(entry.size_bytes) + "B 实际 " +
                     std::to_string(info->size) + "B"});
            continue;
        }
        if (deep) {
            const std::string payload = bundle->read_entry_bytes(*info);
            if (pwb::domain::Sha256::of_bytes(payload) != entry.sha256) {
                report.issues.push_back(
                    {"error", "checksum-mismatch", entry.path + ": sha256 不匹配"});
            }
        }
    }

    std::set<std::string> known = manifest.entry_paths();
    known.insert(kManifestFilename);
    known.insert(kKnownPackageExtraFiles.begin(), kKnownPackageExtraFiles.end());
    for (const auto& name : names) {
        if (known.count(name) == 0) {
            report.issues.push_back(
                {"warning", "unknown-file", "manifest 之外的文件: " + name});
        }
    }
    return report;
}

}  // namespace

PackageVerifyReport verify_zip_container(const std::filesystem::path& zip_path, bool deep) {
    return verify_zip_container_impl(zip_path, deep);
}

PackageVerifyReport verify_package(const std::filesystem::path& package_path, bool deep) {
    if (zip_is_zipfile(package_path)) {
        return verify_zip_container(package_path, deep);
    }
    return verify_directory(package_path, deep);
}

std::filesystem::path materialize_package(const std::filesystem::path& package_path,
                                          const std::filesystem::path& dest_dir) {
    std::filesystem::create_directories(dest_dir);
    if (zip_is_zipfile(package_path)) {
        std::string stem = package_path.filename().string();
        const std::size_t dot = stem.rfind('.');
        if (dot != std::string::npos) stem = stem.substr(0, dot);  // Path.stem
        if (stem.size() >= 9 && stem.compare(stem.size() - 9, 9, ".paleopkg") == 0) {
            stem.resize(stem.size() - 9);
        }
        const std::filesystem::path target = dest_dir / stem;
        if (std::filesystem::exists(target)) {
            throw std::runtime_error("目标已存在: " + target.string());
        }
        const std::filesystem::path staging = dest_dir / ("." + stem + ".staging");
        remove_tree_best_effort(staging);
        std::filesystem::create_directories(staging);
        try {
            ZipReader bundle(package_path);
            (void)extract_archive(bundle, staging, "package");
            os_replace_atomic(staging, target);
        } catch (...) {
            remove_tree_best_effort(staging);
            throw;
        }
        return target;
    }
    if (std::filesystem::is_directory(package_path)) {
        const std::filesystem::path target = dest_dir / package_path.filename();
        if (std::filesystem::exists(target)) {
            throw std::runtime_error("目标已存在: " + target.string());
        }
        // Validate FIRST (reject any symlink — copying with dereference would
        // inline outside content into the package), then copy.
        std::error_code ec;
        for (auto it = std::filesystem::recursive_directory_iterator(package_path);
             it != std::filesystem::recursive_directory_iterator(); it.increment(ec)) {
            if (ec) throw std::runtime_error("cannot scan package tree: " + ec.message());
            if (it->is_symlink()) {
                throw UnsafePathError("包内符号链接被拒绝: " + it->path().string());
            }
        }
        const std::filesystem::path staging = dest_dir / ("." + target.filename().string() + ".staging");
        remove_tree_best_effort(staging);
        try {
            std::filesystem::create_directories(staging);
            for (auto it = std::filesystem::recursive_directory_iterator(package_path);
                 it != std::filesystem::recursive_directory_iterator(); it.increment(ec)) {
                if (ec) throw std::runtime_error("cannot scan package tree: " + ec.message());
                if (matches_staging_ignore(it->path().filename().string())) {
                    if (it->is_directory()) it.disable_recursion_pending();
                    continue;
                }
                const std::filesystem::path rel =
                    it->path().lexically_relative(package_path);
                const std::filesystem::path dest = staging / rel;
                if (it->is_directory()) {
                    std::filesystem::create_directories(dest);
                } else {
                    std::filesystem::create_directories(dest.parent_path());
                    std::filesystem::copy_file(it->path(), dest,
                                               std::filesystem::copy_options::overwrite_existing);
                }
            }
            std::filesystem::rename(staging, target);
        } catch (...) {
            remove_tree_best_effort(staging);
            throw;
        }
        return target;
    }
    throw std::runtime_error("无法识别的包: " + package_path.string());
}

std::pair<std::filesystem::path, PackageVerifyReport> open_package(
    const std::filesystem::path& package_path, const std::filesystem::path& dest_dir,
    bool deep) {
    const std::filesystem::path package_dir = materialize_package(package_path, dest_dir);
    return {package_dir, verify_package(package_dir, deep)};
}

// --- builder ------------------------------------------------------------------

const std::vector<std::string> kIncludeArtifactDirs = {
    "raw", "derived", "intermediate", "outputs", "metadata", "blobs",
};
const std::vector<std::string> kExcludeArtifactDirs = {
    "working", "trash", "cache", "thumbnails",
};
const std::vector<std::string> kExcludedMetadataFiles = {
    "catalog.sqlite", "catalog.sqlite-wal", "catalog.sqlite-shm",
};

struct PackageBuilder::Impl {
    // Python stamps datetime.now(timezone.utc).isoformat() at build time and
    // the oracle freezes it by monkeypatching builder.datetime; the seam
    // gives the C++ test the same control.
    std::function<std::string()> created_at_provider = pwb::domain::now_iso8601;
};

PackageBuilder::PackageBuilder(std::filesystem::path project_path, CatalogSource* catalog,
                               PackageOptions options, std::string application_version)
    : application_version_(std::move(application_version)),
      catalog_(catalog),
      options_(std::move(options)) {
    std::error_code ec;
    project_path_ = std::filesystem::weakly_canonical(project_path, ec);
    if (ec) project_path_ = std::filesystem::absolute(project_path);
    const std::string name = project_path_.filename().string();
    if (name.size() < 11 || name.compare(name.size() - 11, 11, ".paleo.json") != 0) {
        throw std::invalid_argument("不是工程文件: " + name);
    }
    project_name_ = name.substr(0, name.size() - 11);
    impl_ = std::make_unique<Impl>();
}

PackageBuilder::~PackageBuilder() = default;

void PackageBuilder::set_created_at_provider(std::function<std::string()> provider) {
    if (provider) impl_->created_at_provider = std::move(provider);
}

namespace {

std::string source_path_string(const std::filesystem::path& path) {
    return path.string();
}

}  // namespace

PackagePlan PackageBuilder::plan() {
    PackagePlan out;
    out.project_file = project_path_.filename().string();
    out.excluded_dirs = kExcludeArtifactDirs;

    std::error_code stat_ec;
    const auto project_stat = std::filesystem::file_size(project_path_, stat_ec);
    if (stat_ec) {
        // Python's plan() stats the project file directly (builder.py:128):
        // a missing/unreadable project aborts the build, never ships size 0.
        throw std::runtime_error("cannot stat project file: " +
                                 project_path_.string() + ": " + stat_ec.message());
    }
    const auto project_size = [&](const std::filesystem::path& path) {
        std::error_code ec;
        const auto size = std::filesystem::file_size(path, ec);
        return ec ? 0 : static_cast<long long>(size);
    };
    out.estimated_bytes += static_cast<long long>(project_stat);
    out.items.push_back(PackageItem{
        "", out.project_file, source_path_string(project_path_),
        project_size(project_path_), "project", "included", ""});

    std::vector<VersionItem> versions;
    if (catalog_ != nullptr) {
        versions = iter_catalog_versions();
    } else {
        versions = iter_project_resources();
    }
    for (auto& entry : versions) {
        const CatalogVersionRef& version = entry.version;
        const std::string& asset_name = entry.asset_name;
        const std::filesystem::path& payload_path = entry.payload;
        const std::string& stage = version.stage;
        if (!version.managed) {
            std::error_code ec;
            const bool is_file = std::filesystem::is_regular_file(payload_path, ec);
            out.items.push_back(PackageItem{
                version.id, asset_name, source_path_string(payload_path),
                is_file ? project_size(payload_path) : 0, stage, "external",
                "外部引用（按策略处理）"});
            continue;
        }
        if (!std::filesystem::is_regular_file(payload_path)) {
            out.items.push_back(PackageItem{
                version.id, asset_name, source_path_string(payload_path), 0, stage,
                "missing", "managed payload 不存在"});
            continue;
        }
        const long long size = project_size(payload_path);
        if (options_.include_outputs_only && stage != "output") {
            out.items.push_back(PackageItem{
                version.id, asset_name, source_path_string(payload_path), size, stage,
                "excluded", "include_outputs_only 策略"});
            continue;
        }
        if (options_.include_formats &&
            std::find(options_.include_formats->begin(), options_.include_formats->end(),
                      version.format) == options_.include_formats->end()) {
            out.items.push_back(PackageItem{
                version.id, asset_name, source_path_string(payload_path), size, stage,
                "excluded",
                "format 策略（" + (version.format.empty() ? "unknown" : version.format) +
                    " 不在清单）"});
            continue;
        }
        const bool stale = version.size_bytes >= 0 && version.size_bytes != size;
        if (stale) {
            // one honest record per version (still shipped, flagged)
            out.items.push_back(PackageItem{
                version.id, asset_name, source_path_string(payload_path), size, stage,
                "stale", "size 与 catalog 记录不一致（内容可能被改动）；仍打包并保留证据"});
            out.estimated_bytes += size;
        } else {
            out.items.push_back(PackageItem{version.id, asset_name,
                                            source_path_string(payload_path), size, stage,
                                            "included", ""});
            out.estimated_bytes += size;
        }
    }
    return out;
}

BuildResult PackageBuilder::build(const std::filesystem::path& output_dir,
                                  const CancelToken& cancel, ProgressCallback progress) {
    if (!progress) progress = [](double, std::string) {};
    std::filesystem::create_directories(output_dir);
    const std::filesystem::path package_dir = output_dir / project_name_;
    if (std::filesystem::exists(package_dir)) {
        throw std::runtime_error("包目录已存在: " + package_dir.string());
    }
    const std::filesystem::path staging = output_dir / ("." + project_name_ + ".staging");
    remove_tree_best_effort(staging);
    std::filesystem::create_directories(staging);
    try {
        const PackagePlan current_plan = plan();
        PackageManifest manifest;
        manifest.project_name = project_name_;
        manifest.project_file = project_path_.filename().string();
        manifest.created_at = impl_->created_at_provider();
        manifest.application_version = application_version_;
        manifest.options = Json::object();
        manifest.options["external_policy"] = std::string(to_string(options_.external_policy));
        manifest.options["include_outputs_only"] = options_.include_outputs_only;
        manifest.options["include_formats"] =
            options_.include_formats ? Json(*options_.include_formats) : Json();

        // 1) project file
        cancel.checkpoint();
        progress(0.05, "打包工程文件");
        manifest.entries.push_back(
            copy_payload(project_path_, project_path_.filename().string(), staging, "project"));

        // 2) managed artifacts directory (payloads + portable catalog manifest)
        const std::filesystem::path artifacts_dir =
            project_path_.parent_path() / (project_name_ + ".artifacts");
        if (std::filesystem::is_directory(artifacts_dir)) {
            progress(0.15, "打包受管数据");
            if (catalog_ != nullptr) {
                // Checkpoint the portable truth so the package never ships a
                // stale manifest while the live catalog is still open.
                catalog_->export_manifest();
            }
            const std::size_t copied = copy_artifacts_tree(staging, manifest, cancel);
            progress(0.7, "已复制 " + std::to_string(copied) + " 个受管文件");
        }

        // 3) external references per policy
        progress(0.8, "处理外部引用");
        handle_externals(current_plan, staging, manifest);

        // 4) missing deps / generated outputs / provenance
        for (const auto& item : current_plan.items) {
            if (item.status == "missing") {
                Json record = Json::object();
                record["version_id"] = item.version_id;
                record["asset"] = item.asset_name;
                record["path"] = item.path;
                record["reason"] = item.detail;
                manifest.missing_dependencies.push_back(std::move(record));
            }
        }
        record_provenance(manifest);

        long long total = 0;
        for (const auto& entry : manifest.entries) total += entry.size_bytes;
        manifest.total_size_bytes = total;
        cancel.checkpoint();
        progress(0.95, "写入 manifest");
        (void)write_manifest(manifest, staging);
        // single atomic publish: staging tree → final name
        os_replace_atomic(staging, package_dir);
        progress(1.0, "打包完成");
        BuildResult result;
        result.package_dir = package_dir;
        result.manifest_path = package_dir / kManifestFilename;
        result.project_path = package_dir / project_path_.filename().string();
        result.manifest = std::move(manifest);
        result.plan = current_plan;
        return result;
    } catch (...) {
        remove_tree_best_effort(staging);
        throw;
    }
}

std::filesystem::path PackageBuilder::build_zip(const std::filesystem::path& output_dir,
                                                const CancelToken& cancel,
                                                ProgressCallback progress) {
    const BuildResult result = build(output_dir, cancel, std::move(progress));
    const std::filesystem::path zip_path =
        result.package_dir.parent_path() / (result.package_dir.filename().string() + ".paleopkg.zip");
    return zip_package_dir(result.package_dir, zip_path, cancel);
}

PackageEntry PackageBuilder::copy_payload(const std::filesystem::path& source,
                                          const std::string& rel_name,
                                          const std::filesystem::path& staging,
                                          const std::string& kind) {
    // Copy first, then hash the STAGED bytes — the manifest must describe
    // exactly what shipped, never what the source was at some earlier moment
    // (TOCTOU-safe).
    const std::filesystem::path target = staging / rel_name;
    std::filesystem::create_directories(target.parent_path());
    std::error_code ec;
    std::filesystem::copy_file(source, target,
                               std::filesystem::copy_options::overwrite_existing, ec);
    if (ec) throw std::runtime_error("cannot copy payload " + source.string() + ": " + ec.message());
    PackageEntry entry;
    entry.path = rel_name;
    auto digest = sha256_file(target);
    if (!digest) {
        // builder.py uses the RAISING sha256_file: an unreadable staged file
        // aborts the build (staging cleanup runs), never ships a blind entry.
        throw std::runtime_error("cannot hash payload: " + target.string());
    }
    entry.sha256 = *digest;
    entry.size_bytes = static_cast<long long>(std::filesystem::file_size(target));
    entry.kind = kind;
    return entry;
}

std::size_t PackageBuilder::copy_artifacts_tree(const std::filesystem::path& staging,
                                                PackageManifest& manifest,
                                                const CancelToken& cancel) {
    const std::filesystem::path artifacts_dir =
        project_path_.parent_path() / (project_name_ + ".artifacts");
    std::size_t copied = 0;
    for (const auto& dir_name : kIncludeArtifactDirs) {
        const std::filesystem::path source_dir = artifacts_dir / dir_name;
        if (!std::filesystem::is_directory(source_dir)) continue;
        std::vector<std::filesystem::path> sources;
        std::error_code ec;
        for (auto it = std::filesystem::recursive_directory_iterator(source_dir);
             it != std::filesystem::recursive_directory_iterator(); it.increment(ec)) {
            if (ec) throw std::runtime_error("cannot scan artifacts tree: " + ec.message());
            sources.push_back(it->path());
        }
        std::sort(sources.begin(), sources.end(), PathPartsLess());
        for (const auto& source : sources) {
            cancel.checkpoint();
            // symlink check BEFORE is_dir(): a symlinked directory must be
            // rejected loudly, never skipped silently (nothing-silent rule)
            if (std::filesystem::is_symlink(source)) {
                throw std::invalid_argument("受管数据中出现符号链接: " + source.string());
            }
            if (std::filesystem::is_directory(source)) continue;
            if (dir_name == "metadata" &&
                std::find(kExcludedMetadataFiles.begin(), kExcludedMetadataFiles.end(),
                          source.filename().string()) != kExcludedMetadataFiles.end()) {
                continue;
            }
            const std::string rel =
                source.lexically_relative(artifacts_dir.parent_path()).generic_string();
            (void)safe_relative_path(rel, "artifact path");
            const std::filesystem::path target = staging / rel;
            std::filesystem::create_directories(target.parent_path());
            std::error_code copy_ec;
            std::filesystem::copy_file(source, target,
                                       std::filesystem::copy_options::overwrite_existing, copy_ec);
            if (copy_ec) {
                throw std::runtime_error("cannot copy artifact " + source.string() + ": " +
                                         copy_ec.message());
            }
            PackageEntry entry;
            entry.path = rel;
            auto digest = sha256_file(target);
            if (!digest) {
                throw std::runtime_error("cannot hash payload: " + target.string());
            }
            entry.sha256 = *digest;
            entry.size_bytes = static_cast<long long>(std::filesystem::file_size(target));
            entry.kind = (dir_name == "metadata") ? "metadata" : "artifact";
            manifest.entries.push_back(std::move(entry));
            copied += 1;
        }
    }
    return copied;
}

void PackageBuilder::handle_externals(const PackagePlan& plan,
                                      const std::filesystem::path& staging,
                                      PackageManifest& manifest) {
    const ExternalPolicy policy = options_.external_policy;
    for (const auto& item : plan.items) {
        if (item.status != "external") continue;
        Json record = Json::object();
        record["version_id"] = item.version_id;
        record["asset"] = item.asset_name;
        record["path"] = item.path;
        record["size_bytes"] = item.size_bytes;
        if (policy == ExternalPolicy::KEEP) {
            record["policy"] = "keep";
            manifest.external_dependencies.push_back(std::move(record));
        } else if (policy == ExternalPolicy::EXCLUDE) {
            record["policy"] = "exclude";
            manifest.external_dependencies.push_back(std::move(record));
        } else {  // VENDOR
            const std::filesystem::path source(item.path);
            if (!std::filesystem::is_regular_file(source)) {
                record["policy"] = "missing";
                manifest.missing_dependencies.push_back(std::move(record));
                continue;
            }
            // version_id in the path: two external versions may share the
            // same asset name and source basename without colliding
            const std::string rel = "artifacts/external/" + item.asset_name + "/" +
                                    (item.version_id.empty() ? "unknown" : item.version_id) +
                                    "/" + source.filename().string();
            (void)safe_relative_path(rel, "vendored external");
            manifest.entries.push_back(copy_payload(source, rel, staging, "artifact"));
            record["policy"] = "vendor";
            record["packaged_path"] = rel;
            manifest.external_dependencies.push_back(std::move(record));
        }
    }
}

void PackageBuilder::record_provenance(PackageManifest& manifest) {
    if (!options_.include_provenance || catalog_ == nullptr) return;
    std::vector<Json> runs;
    std::vector<std::string> outputs;
    try {
        for (const auto& run : catalog_->list_runs()) {
            runs.push_back(Json{
                {"id", run.id}, {"operation", run.operation}, {"status", run.status}});
        }
        for (const auto& asset : catalog_->list_assets()) {
            for (const auto& version : catalog_->list_versions(asset.id)) {
                if (version.stage == "output") outputs.push_back(version.id);
            }
        }
    } catch (const std::exception&) {
        return;
    }
    Json runs_json = Json::array();
    const std::size_t run_cap = runs.size() < 1000 ? runs.size() : 1000;
    for (std::size_t i = 0; i < run_cap; ++i) runs_json.push_back(runs[i]);
    manifest.provenance = Json::object();
    manifest.provenance["runs"] = std::move(runs_json);
    manifest.provenance["run_count"] = runs.size();
    const std::size_t out_cap = outputs.size() < 1000 ? outputs.size() : 1000;
    manifest.generated_outputs.assign(outputs.begin(),
                                      outputs.begin() + static_cast<long>(out_cap));
}

std::vector<PackageBuilder::VersionItem> PackageBuilder::iter_catalog_versions() {
    std::vector<VersionItem> out;
    for (const auto& asset : catalog_->list_assets()) {
        for (const auto& version : catalog_->list_versions(asset.id)) {
            std::filesystem::path payload;
            try {
                payload = catalog_->resolve_path(version);
            } catch (const std::exception&) {
                payload = project_path_.parent_path() / version.path;
            }
            out.push_back(VersionItem{version, asset.name, std::move(payload)});
        }
    }
    return out;
}

std::vector<PackageBuilder::VersionItem> PackageBuilder::iter_project_resources() {
    // Catalog-less fallback: external resources straight from the project
    // JSON so external references are still declared (never silent).
    std::vector<VersionItem> out;
    std::ifstream in(project_path_, std::ios::binary);
    if (!in) return out;
    std::string text((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
    if (!strict_utf8_valid(text)) {
        // builder.py reads the project with encoding="utf-8": a decode error
        // (UnicodeDecodeError) propagates and aborts the build — never a
        // silent package without the declared external resources.
        throw std::runtime_error("project file is not valid utf-8: " +
                                 project_path_.string());
    }
    Json payload;
    try {
        payload = parse_json_text(text);
    } catch (const std::exception&) {
        return out;  // json.JSONDecodeError is caught by Python too
    }
    if (!payload.is_object() || !payload.contains("resources") ||
        !payload["resources"].is_array()) {
        return out;
    }
    for (const auto& resource : payload["resources"]) {
        if (!resource.is_object()) continue;
        const std::string raw_path =
            resource.contains("path") ? detail::py_str(resource["path"]) : std::string();
        if (raw_path.empty()) continue;
        std::filesystem::path candidate(raw_path);
        if (candidate.is_relative()) candidate = project_path_.parent_path() / candidate;
        CatalogVersionRef shim;
        shim.id = resource.contains("id") ? detail::py_str(resource["id"]) : std::string();
        // managed = not bool(resource.get("external", False)) — Python
        // truthiness (any non-empty string/number counts as external).
        const bool external = resource.contains("external") &&
                              python_truth(resource["external"]);
        shim.managed = !external;
        shim.stage = "input";
        shim.size_bytes = -1;
        shim.path = resource.contains("path") ? detail::py_str(resource["path"]) : std::string();
        const std::string asset_name =
            resource.contains("name") ? detail::py_str(resource["name"]) : raw_path;
        out.push_back(VersionItem{std::move(shim), asset_name, std::move(candidate)});
    }
    return out;
}

std::filesystem::path zip_package_dir(const std::filesystem::path& package_dir,
                                      const std::filesystem::path& zip_path,
                                      const CancelToken& cancel) {
    // Zip an existing package directory atomically (temp + os.replace).
    const std::filesystem::path zip_tmp =
        zip_path.parent_path() / ("." + zip_path.filename().string() + ".tmp");
    try {
        ZipWriter writer(zip_tmp);
        std::vector<std::filesystem::path> paths;
        std::error_code ec;
        for (auto it = std::filesystem::recursive_directory_iterator(package_dir);
             it != std::filesystem::recursive_directory_iterator(); it.increment(ec)) {
            if (ec) throw std::runtime_error("cannot scan package dir: " + ec.message());
            paths.push_back(it->path());
        }
        std::sort(paths.begin(), paths.end(), PathPartsLess());
        for (const auto& path : paths) {
            cancel.checkpoint();
            if (std::filesystem::is_symlink(path)) {
                throw std::invalid_argument("包内出现符号链接: " + path.string());
            }
            if (std::filesystem::is_regular_file(path)) {
                writer.add_file(path,
                                path.lexically_relative(package_dir).generic_string());
            }
        }
        writer.finish();
        os_replace_atomic(zip_tmp, zip_path);
    } catch (...) {
        std::error_code rm_ec;
        std::filesystem::remove(zip_tmp, rm_ec);
        throw;
    }
    return zip_path;
}

}  // namespace pwb::interchange
