// preview_cache.py port — the UI-thread LRU for PreviewResult plus the
// stable cache-key builder. Keys are opaque strings built from the same
// material the Python tuple carries (canonical-joined, so collision-free).
#pragma once

#include "pwb/ui_data_core/asset_view.hpp"
#include "pwb/ui_data_core/preview_types.hpp"

#include <cstdint>
#include <list>
#include <optional>
#include <string>
#include <unordered_map>

namespace pwb::ui_data_core {

inline constexpr long long kDefaultPreviewCacheBytes = 128 * 1024 * 1024;

// preview_result_weight(value): estimated_bytes when >0 else utf8(text) +
// image_bytes + pdf_bytes lengths.
long long preview_result_weight(const PreviewResult& value);

// safe_file_stat(path) → (size, mtime_ns) or nullopt (project/paths.py).
std::optional<std::pair<long long, long long>> safe_file_stat(
    const std::filesystem::path& path);

// make_preview_cache_key(asset, settings_fingerprint, comparison_crs).
//
// The Python tuple ("resource", id, path, type, format, checksum, stat,
// crs, units, comparison, fingerprint) becomes a canonical string built by
// joining json.dumps-encoded fields on \x1f (unit separator) — tuple parity
// for equality/hash purposes.
std::string make_preview_cache_key(
    const ResourceItem& asset,
    std::optional<std::string> settings_fingerprint = std::nullopt,
    std::optional<std::string> comparison_crs = std::nullopt);
std::string make_preview_cache_key(
    const ExportArtifact& asset,
    std::optional<std::string> settings_fingerprint = std::nullopt,
    std::optional<std::string> comparison_crs = std::nullopt);
// AssetView-backed overload for paged/catalog rows: the key material reads
// the same fields off the view (id/path/type/format/checksum/crs/
// parsed_summary) — the SqlCatalogAssetRef row identity.
std::string make_preview_cache_key_for_view(
    const AssetView& view,
    std::optional<std::string> settings_fingerprint = std::nullopt,
    std::optional<std::string> comparison_crs = std::nullopt);

class PreviewCache {
public:
    explicit PreviewCache(long long max_size = 32,
                          long long max_bytes = kDefaultPreviewCacheBytes);
    // Python: non-int / bool → TypeError; <= 0 → ValueError. Both map to
    // std::invalid_argument (the oracle only distinguishes pass/fail).

    const PreviewResult* get(const std::string& key);
    void put(const std::string& key, const PreviewResult& value);
    // Move overload (#1392): PreviewResult carries image/pdf payloads up
    // to MB scale — rvalue callers move straight into the list node.
    void put(const std::string& key, PreviewResult&& value);
    void clear();

    long long current_bytes() const { return current_bytes_; }
    long long max_size() const { return max_size_; }
    long long max_bytes() const { return max_bytes_; }
    std::size_t size() const { return map_.size(); }

private:
    // OrderedDict: list keeps LRU order (front = oldest), map gives O(1).
    std::list<std::pair<std::string, std::pair<PreviewResult, long long>>> lru_;
    std::unordered_map<std::string,
                       typename decltype(lru_)::iterator> map_;
    long long max_size_;
    long long max_bytes_;
    long long current_bytes_ = 0;
};

}  // namespace pwb::ui_data_core
