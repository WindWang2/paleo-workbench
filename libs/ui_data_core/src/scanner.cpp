#include "pwb/ui_data_core/scanner.hpp"

#include <algorithm>
#include <future>
#include <system_error>
#include <thread>

#include <pwb/catalog/checksum.hpp>
#include <pwb/ingest/classifier.hpp>
#include <pwb/project/paths.hpp>

namespace pwb::ui_data_core {

namespace {

std::optional<ResourceItem> process_file(
    const fs::path& path, const fs::path* project_path,
    std::int64_t skip_checksum_over_bytes, const ClassifyFn& classify) {
    const auto [resource_type, resource_format, status] = classify(path);
    std::error_code ec;
    const fs::path resolved = fs::weakly_canonical(path, ec);
    const fs::path& resolved_path = ec ? path : resolved;
    const auto size = fs::file_size(resolved_path, ec);
    if (ec) return std::nullopt;  // vanished — caller filters

    std::string stored = resolved_path.generic_string();
    bool external = false;
    if (project_path != nullptr) {
        const auto rel = project::relativize_path(path, *project_path);
        stored = rel.stored;
        external = rel.external;
    }

    domain::Json summary = domain::Json::object();
    summary["size_bytes"] = static_cast<long long>(size);
    std::optional<std::string> checksum;
    if (skip_checksum_over_bytes >= 0 &&
        size > static_cast<std::uintmax_t>(skip_checksum_over_bytes)) {
        summary["checksum_skipped"] = true;
    } else {
        auto digest = catalog::sha256_file(path);
        if (digest.is_ok()) {
            checksum = digest.value();
        } else {
            summary["checksum_error"] = true;
        }
    }

    ResourceItem item;
    item.name = path.filename().string();
    item.path = stored;
    item.type = resource_type;
    item.format = resource_format;
    item.status = status;
    item.source = "scan";
    item.parsed_summary = std::move(summary);
    item.checksum = std::move(checksum);
    item.external = external;
    return item;
}

}  // namespace

int default_scan_workers(int io_slots) {
    if (io_slots >= 0) {
        return std::max(2, std::min(32, io_slots + 2));
    }
    const unsigned hw = std::thread::hardware_concurrency();
    const int fallback = std::min(
        32, static_cast<int>(hw == 0 ? 1 : hw) + 4);
    return std::max(fallback, 2);
}

std::vector<ResourceItem> scan_resources(
    const fs::path& root, const fs::path* project_path,
    std::int64_t skip_checksum_over_bytes, int max_workers, int io_slots,
    const ClassifyFn& classify_fn) {
    const ClassifyFn classify = classify_fn
                                    ? classify_fn
                                    : ClassifyFn([](const fs::path& p) {
                                          const auto c =
                                              ingest::classify_path(
                                                  p.generic_string());
                                          return std::make_tuple(
                                              c.type, c.format, c.status);
                                      });

    std::vector<fs::path> candidates;
    std::error_code ec;
    for (fs::recursive_directory_iterator it(root, ec), end;
         !ec && it != end; it.increment(ec)) {
        if (it->is_regular_file(ec) &&
            !it->path().filename().string().starts_with("._")) {
            candidates.push_back(it->path());
        }
    }
    std::sort(candidates.begin(), candidates.end());
    if (candidates.empty()) return {};

    const int workers = max_workers > 0 ? max_workers
                                        : default_scan_workers(io_slots);

    // ThreadPoolExecutor.map parity: results keep input order regardless of
    // completion order — futures are collected in candidate order.
    std::vector<std::optional<ResourceItem>> processed(candidates.size());
    for (std::size_t base = 0; base < candidates.size();
         base += static_cast<std::size_t>(workers)) {
        const std::size_t limit =
            std::min(candidates.size(),
                     base + static_cast<std::size_t>(workers));
        std::vector<std::future<std::optional<ResourceItem>>> batch;
        batch.reserve(limit - base);
        for (std::size_t i = base; i < limit; ++i) {
            batch.push_back(std::async(
                std::launch::async, [&, i]() {
                    return process_file(candidates[i], project_path,
                                        skip_checksum_over_bytes, classify);
                }));
        }
        for (std::size_t i = 0; i < batch.size(); ++i) {
            processed[base + i] = batch[i].get();
        }
    }

    std::vector<ResourceItem> out;
    for (auto& item : processed) {
        if (item.has_value()) out.push_back(std::move(*item));
    }
    return out;
}

}  // namespace pwb::ui_data_core
