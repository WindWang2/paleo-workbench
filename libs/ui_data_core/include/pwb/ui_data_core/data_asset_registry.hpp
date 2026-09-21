#pragma once

// CONV-36 — resources/data_asset_registry.py port: the deep-module facade
// binding format specs → path classification, directory scanning, preview
// parsing and format exports into one registry. All underlying machinery is
// already ported (ingest::classify_path, scanner::scan_resources,
// ingest::preview::build_preview, interchange converters); this class is
// the single-point registration surface over them.
//
// Python parity notes:
//   * register_format indexes specs by format_id AND every extension
//     (lowercased); classify_path hits the spec table on extension before
//     falling back to ingest::classify_path.
//   * export() prefers a spec-registered exporter, else dispatches through
//     the shared converter table (same one behind get_available_formats);
//     no converter → ExportError("没有可用于 <LABEL> 的导出器: <fmt>").
//   * parse_preview prefers a spec-registered preview_parser, else the
//     ported build_preview routing chain.

#include <filesystem>
#include <functional>
#include <optional>
#include <string>
#include <string_view>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include <pwb/ingest/classifier.hpp>
#include <pwb/ingest/preview/models.hpp>
#include <pwb/ingest/preview/registry.hpp>
#include <pwb/ui_data_core/asset_view.hpp>
#include <pwb/ui_data_core/scanner.hpp>

namespace pwb::ui_data_core {

namespace fs = std::filesystem;

// FormatSpec parity — single-point registration spec for one format.
struct FormatSpec {
    std::string format_id;
    std::unordered_set<std::string> extensions;
    std::string resource_type = "unknown";
    std::string status = "indexed";
    // (asset, settings) → PreviewResult
    std::function<ingest::preview::PreviewResult(
        const ResourceItem&, const ingest::preview::PreviewSettings&)>
        preview_parser;
    // (asset, format_id, output_path) → bool
    std::function<bool(const ResourceItem&, std::string_view,
                       const fs::path&)>
        exporter;
};

class DataAssetRegistry {
public:
    void register_format(FormatSpec spec);

    // classify_path parity: spec table on extension first, then the ported
    // ingest classifier. Returns (resource_type, format, status).
    std::tuple<std::string, std::string, std::string>
    classify_path(const fs::path& path) const;

    // inspect() — alias for classify_path.
    std::tuple<std::string, std::string, std::string>
    inspect(const fs::path& path) const {
        return classify_path(path);
    }

    // scan_directory parity: scan_resources with this registry's classify.
    std::vector<ResourceItem> scan_directory(
        const fs::path& root, const fs::path* project_path = nullptr,
        std::int64_t skip_checksum_over_bytes = -1, int max_workers = 0,
        int io_slots = -1) const;

    // parse_preview parity.
    ingest::preview::PreviewResult parse_preview(
        const ResourceItem& asset,
        const ingest::preview::PreviewSettings& settings,
        const std::optional<std::string>& project_root = std::nullopt) const;

    // export() parity: spec exporter wins; else the shared converter table.
    // Throws interchange::ExportError when nothing can serve the format.
    bool export_asset(const ResourceItem& asset, std::string_view format_id,
                      const fs::path& output_path) const;

private:
    std::unordered_map<std::string, FormatSpec> format_specs_;
};

// data_asset_registry module-level singleton parity.
DataAssetRegistry& data_asset_registry();

}  // namespace pwb::ui_data_core
