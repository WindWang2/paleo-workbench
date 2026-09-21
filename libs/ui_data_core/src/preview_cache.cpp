// preview_cache.py port — see preview_cache.hpp.

#include <chrono>
#include "pwb/ui_data_core/preview_cache.hpp"

#include "pwb/ui_data_core/json_util.hpp"

#include <stdexcept>
#include <sys/stat.h>

namespace pwb::ui_data_core {

long long preview_result_weight(const PreviewResult& value) {
    if (value.estimated_bytes > 0) {
        return value.estimated_bytes;
    }
    return static_cast<long long>(value.text.size()) +
           static_cast<long long>(value.image_bytes.size()) +
           static_cast<long long>(value.pdf_bytes.size());
}

std::optional<std::pair<long long, long long>> safe_file_stat(
    const std::filesystem::path& path) {
#if defined(_WIN32)
    // MSVC stat() takes narrow paths only; fs probes give the same facts.
    std::error_code ec{};
    if (!std::filesystem::is_regular_file(path, ec) || ec) {
        return std::nullopt;
    }
    const long long size =
        static_cast<long long>(std::filesystem::file_size(path, ec));
    if (ec) return std::nullopt;
    const auto written = std::filesystem::last_write_time(path, ec);
    if (ec) return std::nullopt;
    const long long mtime_ns = std::chrono::duration_cast<
        std::chrono::nanoseconds>(written.time_since_epoch())
        .count();
    return std::make_pair(size, mtime_ns);
#else
    struct stat st {};
    if (::stat(path.c_str(), &st) != 0) {
        return std::nullopt;
    }
    long long mtime_ns;
#ifdef st_mtime  // glibc macro → st_mtim.tv_sec
    mtime_ns = static_cast<long long>(st.st_mtim.tv_sec) * 1000000000LL +
               static_cast<long long>(st.st_mtim.tv_nsec);
#else
    mtime_ns = static_cast<long long>(st.st_mtime) * 1000000000LL;
#endif
    return std::make_pair(static_cast<long long>(st.st_size), mtime_ns);
#endif
}

namespace {

// Join tuple fields into one canonical key string. json.dumps(value,
// ensure_ascii=True) gives an unambiguous encoding per field; "\x1f"
// separates fields (it cannot appear inside a dumps-encoded string).
std::string key_join(std::initializer_list<domain::Json> fields) {
    std::string out;
    bool first = true;
    for (const auto& field : fields) {
        if (!first) {
            out += '\x1f';
        }
        first = false;
        out += field.dump(-1, ' ', true);
    }
    return out;
}

domain::Json stat_json(
    const std::optional<std::pair<long long, long long>>& stat) {
    if (!stat.has_value()) {
        return domain::Json(nullptr);
    }
    return domain::Json::array({stat->first, stat->second});
}

// metadata.get("coordinate_units") or metadata.get("units") or "" — the
// raw value (any JSON type) goes into the key tuple, not str(value).
domain::Json metadata_units(const domain::Json& metadata) {
    if (!metadata.is_object()) {
        return "";
    }
    if (const auto it = metadata.find("coordinate_units");
        it != metadata.end() && json_truthy(*it)) {
        return *it;
    }
    if (const auto it = metadata.find("units");
        it != metadata.end() && json_truthy(*it)) {
        return *it;
    }
    return "";
}

// metadata.get("comparison_crs") or "" — raw value or "".
domain::Json metadata_comparison(const domain::Json& metadata) {
    if (!metadata.is_object()) {
        return "";
    }
    if (const auto it = metadata.find("comparison_crs");
        it != metadata.end() && json_truthy(*it)) {
        return *it;
    }
    return "";
}

std::string fingerprint_or_default(
    const std::optional<std::string>& fingerprint) {
    if (fingerprint.has_value()) {
        return *fingerprint;
    }
    return PreviewSettings::defaults().fingerprint();
}

}  // namespace

std::string make_preview_cache_key(
    const ExportArtifact& asset,
    std::optional<std::string> settings_fingerprint,
    std::optional<std::string> /*comparison_crs*/) {
    const auto stat = safe_file_stat(std::filesystem::path(asset.output_path));
    return key_join({
        "artifact",
        asset.id,
        asset.output_path,
        asset.format,
        "",
        stat_json(stat),
        fingerprint_or_default(settings_fingerprint),
    });
}

std::string make_preview_cache_key(
    const ResourceItem& asset,
    std::optional<std::string> settings_fingerprint,
    std::optional<std::string> comparison_crs) {
    const auto stat = safe_file_stat(std::filesystem::path(asset.path));
    const domain::Json& metadata =
        asset.parsed_summary.is_object() ? asset.parsed_summary
                                         : domain::Json::object();
    domain::Json comparison;
    if (comparison_crs.has_value()) {
        comparison = *comparison_crs;
    } else {
        comparison = metadata_comparison(metadata);
    }
    return key_join({
        "resource",
        asset.id,
        asset.path,
        asset.type,
        asset.format,
        asset.checksum.value_or(""),
        stat_json(stat),
        asset.crs.value_or(""),
        metadata_units(metadata),
        comparison,
        fingerprint_or_default(settings_fingerprint),
    });
}

std::string make_preview_cache_key_for_view(
    const AssetView& view,
    std::optional<std::string> settings_fingerprint,
    std::optional<std::string> comparison_crs) {
    const auto stat = safe_file_stat(std::filesystem::path(view.path));
    const domain::Json& metadata =
        view.parsed_summary.is_object() ? view.parsed_summary
                                        : domain::Json::object();
    domain::Json comparison;
    if (comparison_crs.has_value()) {
        comparison = *comparison_crs;
    } else {
        comparison = metadata_comparison(metadata);
    }
    return key_join({
        "resource",
        view.id,
        view.path,
        view.type,
        view.format,
        view.checksum.value_or(""),
        stat_json(stat),
        view.crs.value_or(""),
        metadata_units(metadata),
        comparison,
        fingerprint_or_default(settings_fingerprint),
    });
}

// ---------------------------------------------------------------------------
// PreviewCache
// ---------------------------------------------------------------------------

PreviewCache::PreviewCache(long long max_size, long long max_bytes)
    : max_size_(max_size), max_bytes_(max_bytes) {
    if (max_size <= 0) {
        throw std::invalid_argument("max_size must be positive");
    }
    if (max_bytes <= 0) {
        throw std::invalid_argument("max_bytes must be positive");
    }
}

const PreviewResult* PreviewCache::get(const std::string& key) {
    const auto it = map_.find(key);
    if (it == map_.end()) {
        return nullptr;
    }
    lru_.splice(lru_.end(), lru_, it->second);  // move_to_end
    return &it->second->second.first;
}

void PreviewCache::put(const std::string& key, const PreviewResult& value) {
    put(key, PreviewResult(value));
}

void PreviewCache::put(const std::string& key, PreviewResult&& value) {
    if (const auto it = map_.find(key); it != map_.end()) {
        current_bytes_ -= it->second->second.second;
        lru_.erase(it->second);
        map_.erase(it);
    }
    const long long weight = preview_result_weight(value);
    if (weight > max_bytes_) {
        return;
    }
    lru_.emplace_back(key, std::make_pair(std::move(value), weight));
    map_[key] = std::prev(lru_.end());
    current_bytes_ += weight;
    while (static_cast<long long>(map_.size()) > max_size_ ||
           current_bytes_ > max_bytes_) {
        auto& oldest = lru_.front();
        current_bytes_ -= oldest.second.second;
        map_.erase(oldest.first);
        lru_.pop_front();
    }
}

void PreviewCache::clear() {
    lru_.clear();
    map_.clear();
    current_bytes_ = 0;
}

}  // namespace pwb::ui_data_core
