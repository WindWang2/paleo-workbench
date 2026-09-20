// pwb::interchange — delivery profiles + QA reports, a faithful C++ port of
// paleo_workbench/interchange/delivery.py (I15/I16).
//
// A delivery profile is a serializable *configuration*, not scattered export
// parameters: what to include, which formats, how external references are
// treated, whether the package is verified, and which report files are
// generated. The QA report is generated from observed facts only (package
// manifest, verify report, dependency audit, catalog counts) and written as
// machine-readable JSON and human-readable Markdown INTO the package, so
// even the zip container ships with it. Qt-free, Python-free; the
// application version is injected (the kernel stays Python-free).
#pragma once

#include <pwb/domain/json.hpp>
#include <pwb/interchange/contracts.hpp>
#include <pwb/interchange/dependency_audit.hpp>
#include <pwb/interchange/package_runtime.hpp>

#include <filesystem>
#include <optional>
#include <string>
#include <vector>

namespace pwb::interchange {

using Json = pwb::domain::Json;

// Python KeyError("未知交付配置: ...") — raised by get_profile.
class UnknownDeliveryProfileError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

struct DeliveryProfile {
    std::string profile_id;
    std::string display_name;
    std::string description;
    ExternalPolicy external_policy = ExternalPolicy::KEEP;
    bool include_outputs_only = false;
    std::optional<std::vector<std::string>> include_formats;
    bool include_provenance = true;
    std::string container = "directory";  // "directory" | "zip"
    bool verify_package = true;
    std::vector<std::string> report_formats{"json", "md"};

    Json to_json() const;
    static DeliveryProfile from_json(const Json& data);
};

// The five built-in profiles, insertion order preserved.
const std::vector<DeliveryProfile>& builtin_profiles();
DeliveryProfile get_profile(const std::string& profile_id);

struct DeliveryResult {
    std::string profile_id;
    std::optional<std::filesystem::path> package_dir;
    std::optional<std::filesystem::path> container_path;
    std::optional<std::filesystem::path> report_path;
    std::optional<std::filesystem::path> report_markdown_path;
    bool verify_ok = false;
    Json plan_summary = Json::object();
    Json report = Json::object();
};

// Assemble the delivery QA report from observed facts.
class DeliveryReportBuilder {
public:
    DeliveryReportBuilder(std::filesystem::path project_path,
                          ILinkableCatalog* catalog = nullptr,
                          std::string application_version = "")
        : project_path_(std::move(project_path)),
          catalog_(catalog),
          application_version_(std::move(application_version)) {}

    Json build(const DeliveryProfile& profile,
               const std::optional<std::filesystem::path>& package_dir,
               const Json& plan_summary,
               const std::optional<DependencyAuditReport>& audit = std::nullopt);

private:
    Json asset_inventory() const;
    std::vector<std::string> collect_crs() const;

    std::filesystem::path project_path_;
    ILinkableCatalog* catalog_;
    std::string application_version_;
};

// Human-readable rendering. UNVERIFIED/FAILED states are shown as-is.
std::string render_report_markdown(const Json& report);

// Build a delivery package per profile and write QA reports into it.
class DeliveryService {
public:
    DeliveryService(std::filesystem::path project_path,
                    ILinkableCatalog* catalog = nullptr,
                    std::string application_version = "")
        : project_path_(std::move(project_path)),
          catalog_(catalog),
          application_version_(std::move(application_version)) {}

    // profile may be a built-in profile id (resolved via get_profile).
    DeliveryResult build(const DeliveryProfile& profile,
                         const std::filesystem::path& output_dir,
                         const CancelToken& cancel = null_cancel(),
                         ProgressCallback progress = {}) const;

private:
    std::filesystem::path project_path_;
    ILinkableCatalog* catalog_;
    std::string application_version_;
};

}  // namespace pwb::interchange
