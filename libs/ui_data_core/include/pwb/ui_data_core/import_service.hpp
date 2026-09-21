#pragma once

// resources/import_service.py port: the collection half of asset import —
// probe summaries, path dedup, ImportReport, import_files/import_folder.
//
// The collected ResourceItems feed DataLifecycleCore::
// register_imported_resources (the catalog registration half, already
// ported). Classification uses ingest::classify_import_path (XML content
// sniff); preferred-only filtering uses the io_registry tables.
//
// Threading parity: _map_collect keeps serial-loop result order (the
// Python ThreadPoolExecutor.map contract) regardless of worker count.

#include <cstdint>
#include <filesystem>
#include <map>
#include <string>
#include <vector>

#include "pwb/ui_data_core/asset_view.hpp"

namespace pwb::ui_data_core {

namespace fs = std::filesystem;

struct ImportReport {
    std::vector<ResourceItem> added;
    std::vector<fs::path> skipped_path;
    std::vector<fs::path> skipped_checksum;
    std::vector<fs::path> skipped_filter;
    std::vector<std::string> warnings;

    [[nodiscard]] std::size_t added_count() const { return added.size(); }
    [[nodiscard]] std::size_t skipped_count() const {
        return skipped_path.size() + skipped_checksum.size() +
               skipped_filter.size();
    }
    // {type: count} over added, Counter order (first-seen).
    [[nodiscard]] std::map<std::string, int> by_type() const;
    // Distinct complete facies-product group ids over added.
    [[nodiscard]] std::size_t facies_product_count() const;
    // "新增 N · 路径重复跳过 M · ..." summary vocabulary parity.
    [[nodiscard]] std::string summary_text() const;
};

// ImportService collect options.
struct ImportOptions {
    // Worker count for per-file collection; <= 0 → default_scan_workers.
    int workers = 0;
    // Governor io_slots feeding default_scan_workers (-1 → fallback).
    int io_slots = -1;
    // Only PREFERRED_IMPORT_EXTENSIONS members are collected.
    bool preferred_only = false;
};

// import_files parity: explicit user-picked paths (non-files warn,
// "._" forks are NOT silently dropped).
ImportReport import_files(const std::vector<fs::path>& paths,
                          const std::vector<ResourceItem>& existing,
                          const fs::path* project_path = nullptr,
                          const ImportOptions& options = {});

// import_folder parity: recursive collect (non-files + "._" skipped
// silently).
ImportReport import_folder(const fs::path& root,
                           const std::vector<ResourceItem>& existing,
                           const fs::path* project_path = nullptr,
                           const ImportOptions& options = {});

}  // namespace pwb::ui_data_core
