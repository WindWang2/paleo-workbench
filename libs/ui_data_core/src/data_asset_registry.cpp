// CONV-36 — resources/data_asset_registry.py port. See header.

#include "pwb/ui_data_core/data_asset_registry.hpp"

#include <algorithm>
#include <cctype>

#include <pwb/domain/text.hpp>
#include <pwb/interchange/exporters.hpp>

namespace pwb::ui_data_core {

void DataAssetRegistry::register_format(FormatSpec spec) {
    format_specs_[domain::lower_ascii(spec.format_id)] = spec;
    for (const auto& ext : spec.extensions) {
        format_specs_[domain::lower_ascii(ext)] = spec;
    }
}

std::tuple<std::string, std::string, std::string>
DataAssetRegistry::classify_path(const fs::path& path) const {
    std::string ext = path.extension().string();
    if (!ext.empty() && ext.front() == '.') ext.erase(ext.begin());
    ext = domain::lower_ascii(ext);
    if (const auto it = format_specs_.find(ext); it != format_specs_.end()) {
        return {it->second.resource_type, ext, it->second.status};
    }
    const ingest::Classification cls =
        ingest::classify_path(path.generic_string());
    return {cls.type, cls.format, cls.status};
}

std::vector<ResourceItem> DataAssetRegistry::scan_directory(
    const fs::path& root, const fs::path* project_path,
    std::int64_t skip_checksum_over_bytes, int max_workers,
    int io_slots) const {
    const ClassifyFn classify = [this](const fs::path& p) {
        return classify_path(p);
    };
    return scan_resources(root, project_path, skip_checksum_over_bytes,
                          max_workers, io_slots, classify);
}

ingest::preview::PreviewResult DataAssetRegistry::parse_preview(
    const ResourceItem& asset,
    const ingest::preview::PreviewSettings& settings,
    const std::optional<std::string>& project_root) const {
    const std::string fmt = domain::lower_ascii(asset.format);
    if (const auto it = format_specs_.find(fmt);
        it != format_specs_.end() && it->second.preview_parser) {
        return it->second.preview_parser(asset, settings);
    }

    ingest::preview::ResourceRef ref;
    ref.id = asset.id;
    ref.name = asset.name;
    ref.path = asset.path;
    ref.type = asset.type;
    ref.format = asset.format;
    ref.status = asset.status;
    if (asset.checksum.has_value()) ref.checksum = *asset.checksum;
    return ingest::preview::build_preview(ref, settings, project_root);
}

bool DataAssetRegistry::export_asset(const ResourceItem& asset,
                                     std::string_view format_id,
                                     const fs::path& output_path) const {
    const std::string fmt = domain::lower_ascii(format_id);
    if (const auto it = format_specs_.find(fmt);
        it != format_specs_.end() && it->second.exporter) {
        return it->second.exporter(asset, format_id, output_path);
    }

    // Shared converter table (same one behind get_available_formats).
    const std::string label = [&] {
        std::string up(fmt);
        for (char& c : up)
            c = static_cast<char>(std::toupper(static_cast<unsigned char>(c)));
        return up;
    }();
    for (const auto& [available, convert] :
         interchange::get_available_formats(asset.format)) {
        if (available == label) {
            convert(fs::path(asset.path), output_path);
            return true;
        }
    }
    throw interchange::ExportError("没有可用于 " + label +
                                   " 的导出器: " + asset.format);
}

DataAssetRegistry& data_asset_registry() {
    static DataAssetRegistry instance;
    return instance;
}

}  // namespace pwb::ui_data_core
