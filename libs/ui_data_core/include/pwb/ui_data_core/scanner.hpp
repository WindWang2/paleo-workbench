#pragma once

// resources/scanner.py port: scan_resources flat directory scan producing
// ResourceItems (classify → stat → checksum → relativize), plus the shared
// default_workers thread budget.
//
// Parity notes:
//   * rglob("*") sorted, files only, macOS "._" forks skipped
//   * stat OSError → the file is dropped (returns None in Python)
//   * checksum: sha256_file; skipped over skip_checksum_over_bytes
//     (checksum=None + checksum_skipped flag); OSError → checksum=None +
//     checksum_error flag
//   * ThreadPoolExecutor.map preserves input order — the C++ pool keeps the
//     same ordering guarantee

#include <cstdint>
#include <filesystem>
#include <functional>
#include <optional>
#include <string_view>
#include <tuple>
#include <vector>

#include "pwb/ui_data_core/asset_view.hpp"

namespace pwb::ui_data_core {

namespace fs = std::filesystem;

// resources/classifier.classify_path seam: (type, format, status).
using ClassifyFn =
    std::function<std::tuple<std::string, std::string, std::string>(
        const fs::path&)>;

// scanner.default_workers parity: governor io_slots+2 clamped [2,32] when a
// governor-derived count is supplied (io_slots >= 0); otherwise the
// cpu_count+4 fallback (clamped [2,32] — Python clamps the governor branch
// and floors the fallback at 2 via max(workers,2)).
int default_scan_workers(int io_slots = -1);

// scan_resources parity. `project_path` non-null → stored paths relativize.
// skip_checksum_over_bytes >= 0 enables the skip path (Python None = never
// skip). max_workers <= 0 → default_scan_workers(io_slots).
std::vector<ResourceItem> scan_resources(
    const fs::path& root, const fs::path* project_path = nullptr,
    std::int64_t skip_checksum_over_bytes = -1, int max_workers = 0,
    int io_slots = -1, const ClassifyFn& classify = nullptr);

}  // namespace pwb::ui_data_core
