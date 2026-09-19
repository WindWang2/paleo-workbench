// preview_disk_cache.py port — see preview_disk_cache.hpp.

#include "pwb/ui_data_core/preview_disk_cache.hpp"

#include "pwb/domain/sha256.hpp"
#include "pwb/ui_data_core/json_util.hpp"
#include "pwb/ui_data_core/preview_cache.hpp"  // safe_file_stat

#include <algorithm>
#include <cctype>
#include <fstream>
#include <random>

namespace pwb::ui_data_core {

const std::vector<std::string>& disk_cacheable_resource_types() {
    static const std::vector<std::string> types = {
        "horizon", "well_stratification", "well_head"};
    return types;
}

bool is_disk_cacheable(const ResourceItem& asset) {
    const auto& types = disk_cacheable_resource_types();
    if (std::find(types.begin(), types.end(), asset.type) == types.end()) {
        return false;
    }
    // asset.format.strip().lower().lstrip(".") == "dat"
    std::string fmt = asset.format;
    const auto first = fmt.find_first_not_of(" \t\n\r");
    fmt = first == std::string::npos ? "" : fmt.substr(first);
    const auto last = fmt.find_last_not_of(" \t\n\r");
    fmt = last == std::string::npos ? "" : fmt.substr(0, last + 1);
    for (auto& c : fmt) {
        c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    }
    const auto dot = fmt.find_first_not_of('.');
    fmt = dot == std::string::npos ? "" : fmt.substr(dot);
    return fmt == "dat";
}

// ---------------------------------------------------------------------------
// _entry_key_material
// ---------------------------------------------------------------------------

std::string preview_disk_entry_key(
    const ResourceItem& asset, const GeovizPreviewOptions* options,
    const std::optional<std::string>& comparison_crs) {
    const std::filesystem::path resolved =
        std::filesystem::weakly_canonical(std::filesystem::path(asset.path));
    const auto stat = safe_file_stat(resolved);
    const domain::Json& metadata =
        asset.parsed_summary.is_object() ? asset.parsed_summary
                                         : domain::Json::object();

    domain::Json material = domain::Json::object();
    material["source_path"] = resolved.generic_string();
    material["resource_id"] = asset.id;
    material["semantic_type"] = asset.type;
    material["format"] = asset.format;
    if (stat.has_value()) {
        material["source_stat"] = domain::Json::array({stat->first, stat->second});
    } else {
        material["source_stat"] = nullptr;
    }
    material["checksum"] = asset.checksum.value_or("");
    material["source_crs"] = asset.crs.value_or("");
    // str(metadata.get("coordinate_units") or metadata.get("units") or "")
    std::string units;
    if (metadata.is_object() && metadata.contains("coordinate_units") &&
        json_truthy(metadata.at("coordinate_units"))) {
        units = json_str(metadata.at("coordinate_units"));
    } else if (metadata.is_object() && metadata.contains("units") &&
               json_truthy(metadata.at("units"))) {
        units = json_str(metadata.at("units"));
    }
    material["coordinate_units"] = units;
    std::string comparison;
    if (comparison_crs.has_value()) {
        comparison = *comparison_crs;
    } else if (metadata.is_object() && metadata.contains("comparison_crs") &&
               json_truthy(metadata.at("comparison_crs"))) {
        comparison = json_str(metadata.at("comparison_crs"));
    }
    material["comparison_crs"] = comparison;
    const GeovizPreviewOptions default_options;
    material["options"] = options != nullptr ? options->fingerprint()
                                             : default_options.fingerprint();

    // json.dumps(material, ensure_ascii=False, sort_keys=True, separators).
    std::map<std::string, domain::Json> sorted;
    for (auto it = material.begin(); it != material.end(); ++it) {
        sorted.emplace(it.key(), it.value());
    }
    domain::Json sorted_json = domain::Json::object();
    for (const auto& [k, v] : sorted) {
        sorted_json[k] = v;
    }
    const std::string raw = sorted_json.dump();  // ensure_ascii=False
    return domain::Sha256::of_bytes(raw).substr(0, 32);
}

// ---------------------------------------------------------------------------
// PreviewDiskCache
// ---------------------------------------------------------------------------

namespace {

void discard_entry(const std::filesystem::path& entry) {
    std::error_code ec;
    if (std::filesystem::exists(entry, ec)) {
        std::filesystem::remove_all(entry, ec);
    }
}

bool read_file(const std::filesystem::path& path, std::string& out) {
    std::ifstream stream(path, std::ios::binary);
    if (!stream) {
        return false;
    }
    out.assign(std::istreambuf_iterator<char>(stream),
               std::istreambuf_iterator<char>());
    return stream.good() || stream.eof();
}

bool write_file(const std::filesystem::path& path, const std::string& bytes) {
    std::ofstream stream(path, std::ios::binary | std::ios::trunc);
    if (!stream) {
        return false;
    }
    stream.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
    return stream.good();
}

// uuid4().hex stand-in for staging dir names.
std::string staging_suffix() {
    static std::mt19937_64 rng{std::random_device{}()};
    char buf[33];
    std::snprintf(buf, sizeof(buf), "%016llx%016llx",
                  static_cast<unsigned long long>(rng()),
                  static_cast<unsigned long long>(rng()));
    return buf;
}

}  // namespace

PreviewDiskCache::PreviewDiskCache(
    std::optional<std::filesystem::path> project_root,
    const GeovizPreviewOptions* options,
    std::optional<std::string> comparison_crs)
    : comparison_crs_(std::move(comparison_crs)) {
    if (project_root.has_value()) {
        project_root_ =
            std::filesystem::weakly_canonical(*project_root);
    }
    if (options != nullptr) {
        options_ = *options;
    }
}

void PreviewDiskCache::set_project_root(std::optional<std::filesystem::path> root) {
    if (root.has_value()) {
        project_root_ = std::filesystem::weakly_canonical(*root);
    } else {
        project_root_ = std::nullopt;
    }
}

std::optional<std::filesystem::path> PreviewDiskCache::entries_dir() const {
    if (!project_root_.has_value()) {
        return std::nullopt;
    }
    return *project_root_ / kPreviewDiskCacheDir / "entries";
}

std::optional<PreviewResult> PreviewDiskCache::try_load(
    const ResourceItem& asset) {
    if (!project_root_.has_value() || !is_disk_cacheable(asset)) {
        return std::nullopt;
    }
    const auto entries = entries_dir();
    if (!entries.has_value()) {
        return std::nullopt;
    }
    std::string key;
    try {
        key = preview_disk_entry_key(asset, &options_, comparison_crs_);
    } catch (...) {
        return std::nullopt;
    }
    const std::filesystem::path entry = *entries / key;
    const std::filesystem::path meta_path = entry / "meta.json";
    const std::filesystem::path payload_path = entry / "payload.npz";
    std::error_code ec;
    if (!std::filesystem::is_regular_file(meta_path, ec) || ec ||
        !std::filesystem::is_regular_file(payload_path, ec) || ec) {
        return std::nullopt;
    }
    try {
        std::string meta_text, payload_bytes;
        if (!read_file(meta_path, meta_text) ||
            !read_file(payload_path, payload_bytes)) {
            throw std::runtime_error("read failed");
        }
        const domain::Json meta = domain::Json::parse(meta_text);
        // Re-validate the live key against the stored key.
        if (!meta.is_object() || json_get_string(meta, "key") != key) {
            discard_entry(entry);
            return std::nullopt;
        }
        if (codec_ == nullptr) {
            // geoviz absent → the Python ImportError path: corrupt-class
            // failure, entry discarded, miss.
            throw std::runtime_error("no codec");
        }
        const auto decoded =
            codec_->decode(meta.is_object() && meta.contains("prepared")
                               ? meta.at("prepared")
                               : domain::Json(nullptr),
                           payload_bytes);
        if (!decoded.has_value()) {
            throw std::runtime_error("decode failed");
        }
        PreviewResult result;
        result.mode = preview_mode::kGeoviz;
        result.title = asset.name;
        result.path = asset.path;
        result.format = asset.format;
        result.status = asset.status;
        result.type_label = asset.type;
        result.warning = decoded->warning;
        result.summary_rows = decoded->summary_rows;
        result.engine_preview = decoded->engine_preview;
        result.estimated_bytes = decoded->estimated_bytes;
        return result;
    } catch (...) {
        discard_entry(entry);
        return std::nullopt;
    }
}

void PreviewDiskCache::store(const ResourceItem& asset,
                             const PreviewResult& result,
                             const std::function<bool()>* commit_guard) {
    if (!project_root_.has_value() || !is_disk_cacheable(asset)) {
        return;
    }
    if (result.mode != preview_mode::kGeoviz || result.engine_preview == nullptr) {
        return;
    }
    if (codec_ == nullptr) {
        return;  // geoviz ImportError → silent no-op
    }
    const auto entries = entries_dir();
    if (!entries.has_value()) {
        return;
    }
    try {
        const std::string key =
            preview_disk_entry_key(asset, &options_, comparison_crs_);
        const auto encoded = codec_->encode(result.engine_preview);
        if (!encoded.has_value()) {
            return;
        }
        std::error_code ec;
        std::filesystem::create_directories(*entries, ec);
        if (ec) {
            return;
        }
        // Stage under a unique sibling dir, then replace the entry.
        const std::filesystem::path staging =
            *entries / (".tmp-" + key + "-" + staging_suffix());
        std::filesystem::create_directories(staging, ec);
        if (ec) {
            return;
        }
        try {
            domain::Json meta = domain::Json::object();
            meta["key"] = key;
            meta["source_path"] =
                std::filesystem::weakly_canonical(
                    std::filesystem::path(asset.path))
                    .generic_string();
            meta["semantic_type"] = asset.type;
            meta["prepared"] = encoded->prepared_meta;
            if (!write_file(staging / "meta.json", meta.dump(2)) ||
                !write_file(staging / "payload.npz", encoded->payload_bytes)) {
                throw std::runtime_error("write failed");
            }
            const bool allowed =
                commit_guard == nullptr || (*commit_guard)();
            if (!allowed) {
                discard_entry(staging);
                return;
            }
            const std::filesystem::path entry = *entries / key;
            if (std::filesystem::exists(entry, ec)) {
                std::filesystem::remove_all(entry, ec);
            }
            std::filesystem::rename(staging, entry, ec);
            if (ec) {
                throw std::runtime_error("replace failed");
            }
        } catch (...) {
            discard_entry(staging);
            throw;
        }
    } catch (...) {
        // Preview must still succeed without disk — log-and-continue.
        return;
    }
}

void PreviewDiskCache::clear() {
    if (!project_root_.has_value()) {
        return;
    }
    const std::filesystem::path root = *project_root_ / kPreviewDiskCacheDir;
    std::error_code ec;
    if (std::filesystem::exists(root, ec)) {
        std::filesystem::remove_all(root, ec);
    }
}

}  // namespace pwb::ui_data_core
