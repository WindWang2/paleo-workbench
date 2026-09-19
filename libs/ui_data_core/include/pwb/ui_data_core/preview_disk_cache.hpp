// preview_disk_cache.py port — project-scoped ``.preview_cache/`` entries
// for horizon / well_stratification / well_head DAT resources.
//
// The npz/prepared-payload codec is geoviz-bound in Python; here it is a
// seam. Without a codec, try_load behaves like the Python ImportError path
// (entry discarded, miss) and store is a silent no-op.
#pragma once

#include "pwb/ui_data_core/asset_view.hpp"
#include "pwb/ui_data_core/preview_types.hpp"

#include <filesystem>
#include <functional>
#include <memory>
#include <optional>
#include <string>

namespace pwb::ui_data_core {

// CACHEABLE_RESOURCE_TYPES / DIR_NAME.
inline constexpr const char* kPreviewDiskCacheDir = ".preview_cache";
const std::vector<std::string>& disk_cacheable_resource_types();

// is_disk_cacheable(asset): ResourceItem + cacheable type + .dat format.
bool is_disk_cacheable(const ResourceItem& asset);

// _entry_key_material(asset, options, comparison_crs) → sha256[:32] of the
// canonical json.dumps(material, sort_keys, separators) payload.
std::string preview_disk_entry_key(const ResourceItem& asset,
                                   const GeovizPreviewOptions* options = nullptr,
                                   const std::optional<std::string>& comparison_crs =
                                       std::nullopt);

// Codec seam for the geoviz PreparedPreview payload (encode_prepared_preview
// / decode_prepared_preview). The disk cache stores meta.json + payload
// bytes; the codec owns their formats.
class PreparedPreviewCodec {
public:
    virtual ~PreparedPreviewCodec() = default;
    struct Encoded {
        domain::Json prepared_meta;  // meta["prepared"]
        std::string payload_bytes;   // payload.npz bytes
    };
    struct Decoded {
        std::shared_ptr<void> engine_preview;
        std::string warning;
        std::vector<std::pair<std::string, std::string>> summary_rows;
        long long estimated_bytes = 0;
    };
    virtual std::optional<Encoded> encode(const std::shared_ptr<void>& engine_preview) = 0;
    virtual std::optional<Decoded> decode(const domain::Json& prepared_meta,
                                          const std::string& payload_bytes) = 0;
};

class PreviewDiskCache {
public:
    explicit PreviewDiskCache(
        std::optional<std::filesystem::path> project_root = std::nullopt,
        const GeovizPreviewOptions* options = nullptr,
        std::optional<std::string> comparison_crs = std::nullopt);

    const std::optional<std::filesystem::path>& project_root() const {
        return project_root_;
    }
    const GeovizPreviewOptions& options() const { return options_; }
    const std::optional<std::string>& comparison_crs() const {
        return comparison_crs_;
    }

    void set_options(const GeovizPreviewOptions& options) { options_ = options; }
    void set_project_root(std::optional<std::filesystem::path> root);
    void set_comparison_crs(std::optional<std::string> crs) {
        comparison_crs_ = std::move(crs);
    }
    void set_codec(std::shared_ptr<PreparedPreviewCodec> codec) {
        codec_ = std::move(codec);
    }
    const std::shared_ptr<PreparedPreviewCodec>& codec() const {
        return codec_;
    }

    // project_root / .preview_cache / entries (nullopt when no root).
    std::optional<std::filesystem::path> entries_dir() const;

    // try_load(asset): miss → nullopt; corrupt/mismatched → entry deleted.
    std::optional<PreviewResult> try_load(const ResourceItem& asset);

    // store(asset, result, commit_guard): silent no-op on any failure or
    // guard refusal. commit_guard → bool (write_if_current semantics).
    void store(const ResourceItem& asset, const PreviewResult& result,
               const std::function<bool()>* commit_guard = nullptr);

    void clear();

private:
    std::optional<std::filesystem::path> project_root_;
    GeovizPreviewOptions options_;
    std::optional<std::string> comparison_crs_;
    std::shared_ptr<PreparedPreviewCodec> codec_;
};

}  // namespace pwb::ui_data_core
