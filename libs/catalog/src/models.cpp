#include "pwb/catalog/models.hpp"
#include "pwb/domain/sha256.hpp"

#include <algorithm>

namespace pwb::catalog {

const DataAsset* CatalogDocument::find_asset(
    const domain::AssetId& id) const {
    for (const auto& asset : assets) {
        if (asset.id == id) return &asset;
    }
    return nullptr;
}

const DataVersion* CatalogDocument::find_version(
    const domain::VersionId& id) const {
    for (const auto& version : versions) {
        if (version.id == id) return &version;
    }
    return nullptr;
}

const DataRun* CatalogDocument::find_run(const domain::RunId& id) const {
    for (const auto& run : runs) {
        if (run.id == id) return &run;
    }
    return nullptr;
}

DataAsset* CatalogDocument::find_asset_mut(const domain::AssetId& id) {
    for (auto& asset : assets) {
        if (asset.id == id) return &asset;
    }
    return nullptr;
}

DataVersion* CatalogDocument::find_version_mut(
    const domain::VersionId& id) {
    for (auto& version : versions) {
        if (version.id == id) return &version;
    }
    return nullptr;
}

int CatalogDocument::next_version_number(
    const domain::AssetId& asset_id) const {
    int next = 1;
    for (const auto& version : versions) {
        if (version.asset_id == asset_id) {
            next = std::max(next, version.version_number + 1);
        }
    }
    return next;
}

std::optional<std::string> aggregate_member_sha256(
    const std::vector<VersionMember>& members) {
    std::vector<const VersionMember*> ordered;
    ordered.reserve(members.size());
    for (const auto& member : members) ordered.push_back(&member);
    std::sort(ordered.begin(), ordered.end(),
              [](const VersionMember* a, const VersionMember* b) {
                  if (a->ordinal != b->ordinal) return a->ordinal < b->ordinal;
                  return a->name < b->name;
              });
    std::string text;
    for (const VersionMember* member : ordered) {
        if (!member->sha256.has_value()) return std::nullopt;
        text += member->rel_path + ":" + *member->sha256 + "\n";
    }
    if (text.empty()) return std::nullopt;
    // models.py joins with "\n" WITHOUT a trailing newline.
    if (!text.empty() && text.back() == '\n') text.pop_back();
    return domain::Sha256::of_bytes(text);
}

}  // namespace pwb::catalog
