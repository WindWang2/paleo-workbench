#pragma once

// pwb::interchange — package runtime (conv-14b): faithful C++ port of
// paleo_workbench/interchange/package/verifier.py,
// package/verifier_zip.py and package/builder.py.
//
// verify_package checks structure, integrity and safety of a package
// directory or .paleopkg.zip container (manifest present/parseable/supported,
// every entry exists + size + sha256, symlinks rejected, project/catalog
// parse, unknown extras reported). materialize_package / open_package
// extract fail-closed: every zip member name is validated before a single
// byte is written. PackageBuilder streams every payload once, hashes the
// STAGED bytes (TOCTOU-safe) and publishes with one atomic rename. Payloads
// are copied/hashed one file at a time; the zip container materializes a
// payload once in memory (bounded by the writer's 4 GiB entry guard —
// medium-scale policy, see ledgers/14b-decisions.md D14b-1).
//
// The Python builder takes the live catalog object; C++ consumes a
// CatalogSource seam (list_assets / list_versions / resolve_path /
// export_manifest / list_runs) so the sqlite-backed service can plug in once
// the catalog kernel grows that surface. Without a catalog the builder falls
// back to the project JSON "resources" list exactly like Python.

#include <pwb/domain/json.hpp>
#include <pwb/interchange/contracts.hpp>
#include <pwb/interchange/manifest.hpp>
#include <pwb/interchange/path_safety.hpp>

#include <filesystem>
#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <vector>

namespace pwb::interchange {

// --- verification -----------------------------------------------------------

struct VerifyIssue {
    std::string severity;  // "error" | "warning" | "info"
    std::string code;
    std::string message;

    Json to_dict() const;
};

struct PackageVerifyReport {
    std::string package_path;
    std::optional<PackageManifest> manifest;
    std::vector<VerifyIssue> issues;
    long long checked_entries = 0;
    long long total_size_bytes = 0;

    bool ok() const;  // no error-severity issue
    std::vector<VerifyIssue> errors() const;
    std::vector<VerifyIssue> warnings() const;
    Json to_dict() const;  // Python PackageVerifyReport.to_dict() key order
};

// Delivery report files live inside the package but are not manifest entries;
// treat them as known so re-verification doesn't warn about them.
extern const std::vector<std::string> kKnownPackageExtraFiles;

// Read-only verification of a package directory or .paleopkg.zip container.
// deep=false skips sha256 re-hashing (sizes only).
PackageVerifyReport verify_package(const std::filesystem::path& package_path,
                                   bool deep = true);

// Verify a .paleopkg.zip container without extracting it.
PackageVerifyReport verify_zip_container(const std::filesystem::path& zip_path,
                                         bool deep = true);

// Materialize a package container at dest_dir; returns the package dir.
// Fail-closed: for zip containers every member name is validated (traversal,
// symlinks, collisions) before any byte is written; a plain directory is
// copied with symlink rejection. Raises UnsafePathError / std::runtime_error
// ("目标已存在: ..." / "无法识别的包: ...").
std::filesystem::path materialize_package(const std::filesystem::path& package_path,
                                          const std::filesystem::path& dest_dir);

// Materialize + verify; returns (package_dir, report). Raises on unsafe
// materialization; a failing verify leaves the extracted directory in place
// but the report says exactly why it is not openable.
std::pair<std::filesystem::path, PackageVerifyReport> open_package(
    const std::filesystem::path& package_path, const std::filesystem::path& dest_dir,
    bool deep = true);

// --- builder ----------------------------------------------------------------

enum class ExternalPolicy { KEEP, VENDOR, EXCLUDE };

std::string_view to_string(ExternalPolicy policy);  // "keep" | "vendor" | "exclude"

struct PackageOptions {
    ExternalPolicy external_policy = ExternalPolicy::KEEP;
    bool include_outputs_only = false;  // true: only OUTPUT-stage payloads
    std::optional<std::vector<std::string>> include_formats;  // version.format filter
    bool include_provenance = true;
};

struct PackageItem {
    std::string version_id;  // "" when not catalog-backed (project file)
    std::string asset_name;
    std::string path;  // source absolute path
    long long size_bytes = 0;
    std::string stage;
    std::string status;  // "included" | "external" | "missing" | "stale" | "excluded"
    std::string detail;
};

struct PackagePlan {
    std::string project_file;
    std::vector<PackageItem> items;
    std::vector<std::string> excluded_dirs;
    long long estimated_bytes = 0;

    Json summary() const;  // Python PackagePlan.summary() key order
};

struct BuildResult {
    std::filesystem::path package_dir;
    std::filesystem::path manifest_path;
    std::filesystem::path project_path;
    PackageManifest manifest;
    PackagePlan plan;
};

// Read-only view of the catalog surface the builder consumes. Mirrors the
// Python catalog service calls (list_assets / list_versions / resolve_path /
// export_manifest / list_runs); resolve_path may throw — the builder then
// falls back to project_dir / version.path exactly like Python.
struct CatalogAssetRef {
    std::string id;
    std::string name;
    std::string type;
};

struct CatalogVersionRef {
    std::string id;
    std::string asset_id;
    std::string stage;  // "input" | "output" | ...
    bool managed = true;
    long long size_bytes = -1;  // Python None -> -1
    std::string format;
    std::string path;  // catalog-relative payload path
    Json metadata = Json::object();
};

struct CatalogRunRef {
    std::string id;
    std::string operation;
    std::string status;
};

class CatalogSource {
public:
    virtual ~CatalogSource() = default;
    virtual std::vector<CatalogAssetRef> list_assets() = 0;
    virtual std::vector<CatalogVersionRef> list_versions(const std::string& asset_id) = 0;
    virtual std::filesystem::path resolve_path(const CatalogVersionRef& version) = 0;
    virtual void export_manifest() {}  // portable-truth checkpoint (default: no-op)
    virtual std::vector<CatalogRunRef> list_runs() { return {}; }
};

// Artifacts subdirs copied into packages, and those excluded by policy.
extern const std::vector<std::string> kIncludeArtifactDirs;
extern const std::vector<std::string> kExcludeArtifactDirs;
// The sqlite index is machine-buildable state, not portable truth: on reopen
// the service rebuilds it from catalog.json (documented resolution order).
extern const std::vector<std::string> kExcludedMetadataFiles;

class PackageBuilder {
public:
    // application_version: Python reads paleo_workbench.__version__; the C++
    // kernel receives it explicitly so it stays Python-free.
    explicit PackageBuilder(std::filesystem::path project_path,
                            CatalogSource* catalog = nullptr,
                            PackageOptions options = {},
                            std::string application_version = "");
    ~PackageBuilder();

    const std::string& project_name() const { return project_name_; }

    // Python freezes created_at by monkeypatching builder.datetime; C++
    // replaces the provider instead (defaults to domain::now_iso8601).
    void set_created_at_provider(std::function<std::string()> provider);

    // Nothing is silently omitted: the plan records every catalog version as
    // included / external / missing / stale / excluded.
    PackagePlan plan();

    // Build the package directory under output_dir (staging tree + single
    // atomic rename). Raises std::runtime_error("包目录已存在: ...") when the
    // target name exists; removes the staging tree on any failure.
    BuildResult build(const std::filesystem::path& output_dir,
                      const CancelToken& cancel = null_cancel(),
                      ProgressCallback progress = {});

    // Build the package directory and zip it next to it (atomic publish).
    std::filesystem::path build_zip(const std::filesystem::path& output_dir,
                                    const CancelToken& cancel = null_cancel(),
                                    ProgressCallback progress = {});

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
    std::filesystem::path project_path_;
    std::string project_name_;
    std::string application_version_;
    CatalogSource* catalog_ = nullptr;
    PackageOptions options_;

    PackageEntry copy_payload(const std::filesystem::path& source,
                              const std::string& rel_name,
                              const std::filesystem::path& staging,
                              const std::string& kind);
    std::size_t copy_artifacts_tree(const std::filesystem::path& staging,
                                    PackageManifest& manifest, const CancelToken& cancel);
    void handle_externals(const PackagePlan& plan, const std::filesystem::path& staging,
                          PackageManifest& manifest);
    void record_provenance(PackageManifest& manifest);
    struct VersionItem {
        CatalogVersionRef version;
        std::string asset_name;
        std::filesystem::path payload;
    };
    std::vector<VersionItem> iter_catalog_versions();
    std::vector<VersionItem> iter_project_resources();
};

// Zip an existing package directory atomically (temp + os.replace). Rejects
// symlinks ("包内出现符号链接: ..."). Deterministic content (fixed entry
// timestamps) but not byte-reproducible across zlib versions.
std::filesystem::path zip_package_dir(const std::filesystem::path& package_dir,
                                      const std::filesystem::path& zip_path,
                                      const CancelToken& cancel = null_cancel());

// sha256 of a file streamed in 1 MiB chunks (hex). Empty when unreadable —
// mirrors paleo_workbench.catalog.checksum.sha256_file's None.
std::optional<std::string> sha256_file(const std::filesystem::path& file);

}  // namespace pwb::interchange
