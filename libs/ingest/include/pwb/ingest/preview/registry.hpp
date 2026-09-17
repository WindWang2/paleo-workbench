// Preview dispatch — port of resources/preview_parsers/registry.build_preview
// (hardcoded routing chain over the ported parse cores; format-registered
// parsers and the rasterio/pandas/lasio/docx/segyio-backed branches surface
// as their dependency-missing fallbacks, see decisions D4/D8).
#pragma once

#include <optional>
#include <string>
#include <string_view>

#include "pwb/ingest/preview/models.hpp"

namespace pwb::ingest::preview {

// Reads the asset file (bytes + existence) so the registry owns the only
// filesystem touch points, mirroring build_preview's `path.exists()` /
// read order.
struct AssetFile {
    bool exists = false;
    long long size = 0;
    std::string bytes;
};
AssetFile read_asset(const std::string& path);

// resource_revision_token(asset) with the standard safe_file_stat.
Revision resource_revision_token(const ResourceRef& asset, bool file_stat_ok,
                                 long long stat_size, long long stat_mtime_ns);

// artifact_preview(artifact)
PreviewResult artifact_preview(const std::string& output_path,
                               const std::string& format, const std::string& linked_id);

// build_preview over already-resolved resource fields. `sibling_dir_entries`
// feeds dfb_preview's same-directory sibling scan (name -> bytes).
PreviewResult build_preview(
    const ResourceRef& asset, const PreviewSettings& settings,
    const std::optional<std::string>& project_root = std::nullopt,
    const std::vector<std::pair<std::string, std::string>>& sibling_dir_entries = {});

}  // namespace pwb::ingest::preview
