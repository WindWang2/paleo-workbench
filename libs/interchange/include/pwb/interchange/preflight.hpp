#pragma once

// pwb::interchange — import preflight decision core, a faithful C++ port of
// the pure decision tree in paleo_workbench/interchange/preflight.py
// (conv-14).
//
// Content sniffing and heavy format parsing (rasterio/segyio/geoviz/GDAL)
// stay out of this kernel: they arrive through two seams —
//   * Sniffer:   std::function<SniffResult(path)> (the not-yet-ported
//                registry.sniff_format; the oracle freezes its outputs),
//   * inspect:   std::function<InspectionResult(path)> on each AdapterSpec.
// Everything else — aliasing, extension/adapter selection, confidence
// branching, issue codes and their exact Chinese messages, recommendation
// and estimated-bytes policy — is ported here branch-for-branch.

#include <pwb/domain/json.hpp>

#include <array>
#include <filesystem>
#include <functional>
#include <optional>
#include <string>
#include <vector>

namespace pwb::interchange {

using pwb::domain::Json;

struct SniffResult {
    std::string format_id;  // best-effort candidate, "" when undetermined
    std::string confidence;  // "high" | "medium" | "low"
    std::string evidence;
    std::string extension;

    bool determined() const { return !format_id.empty(); }
};

struct InspectionResult {
    bool ok = true;
    long long size_bytes = 0;
    Json metadata = Json::object();
    std::optional<std::string> crs;
    Json units = Json::object();
    std::string object_type;
    std::optional<std::array<double, 4>> bounds;
    std::vector<std::string> warnings;
    std::vector<std::string> errors;

    // Python InspectionResult.summary() layout (key order preserved).
    Json summary(const std::string& format_id) const;
};

struct AdapterSpec {
    std::string format_id;
    std::string display_name;
    std::vector<std::string> extensions;
    bool import_data = false;
    std::string notes;  // capability notes (used by import-unavailable)
    std::function<InspectionResult(const std::string& path)> inspect;
};

// Registry of AdapterSpec keyed by format_id, preserving insertion order
// (extension lookup takes the FIRST registered adapter that matches).
class Registry {
public:
    void register_adapter(AdapterSpec spec, bool replace = false);
    const AdapterSpec* get(const std::string& format_id) const;
    // Python-surface mirror (registry.py adapters()); registry() below
    // mirrors ImportPreflightService.registry().
    const std::vector<AdapterSpec>& adapters() const { return adapters_; }
    const AdapterSpec* adapter_for_extension(const std::string& extension) const;

private:
    std::vector<AdapterSpec> adapters_;
};

struct PreflightIssue {
    std::string severity;  // "info" | "warning" | "error"
    std::string code;
    std::string message;

    Json to_dict() const;
};

struct PreflightReport {
    std::string path;
    SniffResult sniff;
    std::optional<std::string> adapter_id;
    std::optional<Json> inspection;  // InspectionResult::summary() payload
    std::vector<PreflightIssue> issues;
    std::string recommendation = "unavailable";  // managed_copy | link_external | unavailable
    long long estimated_disk_bytes = 0;

    bool ok() const;
    Json to_dict() const;
};

struct ImportPlan {
    std::string format_id;
    std::string source_path;
    std::string action;  // "managed_copy" | "link_external" | "transform_import" | "unsupported"
    std::string asset_name;
    std::vector<std::string> warnings;
    long long estimated_bytes = 0;
    std::optional<std::string> transform;
    Json metadata = Json::object();
    Json options = Json::object();

    Json to_dict() const;
};

// Python Path.suffix ("" when no dot / leading dot / trailing dot), lowered,
// leading dot stripped.
std::string path_suffix_lower(const std::filesystem::path& path);

class ImportPreflightService {
public:
    using Sniffer = std::function<SniffResult(const std::filesystem::path&)>;

    // sniff may be null only when every inspected file is missing/dir.
    explicit ImportPreflightService(Registry registry, Sniffer sniffer = nullptr)
        : registry_(std::move(registry)), sniffer_(std::move(sniffer)) {}

    // Read-only; never creates assets. Branch-for-branch port of
    // ImportPreflightService.inspect.
    PreflightReport inspect(const std::filesystem::path& path) const;

    // "callers get a plan or an exception, never both": throws
    // std::runtime_error with the joined error messages (Python
    // PreflightFailedError text) when the report failed.
    ImportPlan plan(const std::filesystem::path& path,
                    std::optional<bool> managed = std::nullopt,
                    std::optional<std::string> asset_name = std::nullopt,
                    Json options = Json::object()) const;

    // Python-surface mirror (preflight.py registry()).
    const Registry& registry() const { return registry_; }

private:
    Registry registry_;
    Sniffer sniffer_;
};

}  // namespace pwb::interchange
