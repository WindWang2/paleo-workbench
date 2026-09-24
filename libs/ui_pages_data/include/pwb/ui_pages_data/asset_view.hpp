// UI-06 — AssetView seam (UI-03 stand-in).
//
// pages/data_view_models.py :: AssetView / asset_view_from_object — the
// display row contract the table, context menu and inspector consume.
// Field subset = exactly what UI-06's files read. When UI-03 lands, swap
// this POD for its type.
#pragma once

#include <optional>
#include <string>
#include <vector>

namespace pwb::ui_pages_data {

// pages/data_view_models.py :: AssetView — normalized display row.
struct AssetView {
    std::string id;
    std::string name;
    std::string type;          // resource type vocabulary
    std::string format;
    std::string status;        // "parsed" | "error" | ...
    std::string path;          // may be empty / remote URL
    std::string stage;         // stage::kRaw | kDerived | kIntermediate | kOutput
    std::string integrity;     // integrity_state::*
    std::string review_status;
    std::string role;
    std::string version_label;
    std::string lineage_label;
    std::string managed_label;
    std::string modified_label;
    std::string source_label;
    std::string size_label;
    std::string checksum;    // ResourceItem.checksum ("" → "—" in detail rows)
    std::string linked_id;   // ExportArtifact.linked_id ("关联" detail row)
    // 稿式列：关联对象 = entity_asset_links 解析出的实体名；层位 =
    // 资产 metadata.horizon（未登记 → "—"，诚实空值不编数）。
    std::string linked_label;
    std::string horizon_label;
    std::string description;   // DataAsset.description（稿式「描述」行）
    std::vector<std::string> tags;
    bool is_trashed = false;
    bool managed = true;
};

// asset kind discriminator — Python used isinstance(asset, ResourceItem)
// vs ExportArtifact. The seam carries the discriminator explicitly.
enum class AssetKind { Resource, Artifact, Other };

// Wraps a raw row object for the seams that need kind + view together.
struct AssetRow {
    AssetKind kind = AssetKind::Resource;
    AssetView view;
};

}  // namespace pwb::ui_pages_data
