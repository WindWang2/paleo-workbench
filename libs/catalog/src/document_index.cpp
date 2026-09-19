#include "pwb/catalog/document_index.hpp"

#include <utility>

namespace pwb::catalog {

std::optional<std::pair<std::string, std::string>> managed_raw_dedup_key(
    const DataVersion& version) {
    if (version.managed && version.stage == domain::DataStage::Raw &&
        !version.trashed && version.source_uri.has_value() &&
        version.sha256.has_value() && !version.source_uri->empty() &&
        !version.sha256->empty()) {
        return std::make_pair(*version.source_uri, *version.sha256);
    }
    return std::nullopt;
}

std::optional<std::string> external_dedup_key(const DataVersion& version) {
    if (!version.managed && !version.trashed && !version.path.empty()) {
        return version.path;
    }
    return std::nullopt;
}

void DocumentIndex::rebuild(const CatalogDocument& document) {
    asset_by_id_.clear();
    version_by_id_.clear();
    run_by_id_.clear();
    versions_by_asset_.clear();
    children_by_parent_.clear();
    legacy_by_id_.clear();
    managed_raw_by_key_.clear();
    external_by_path_.clear();

    for (const auto& asset : document.assets) {
        asset_by_id_.emplace(asset.id.str(), &asset);
    }
    for (const auto& run : document.runs) {
        run_by_id_.emplace(run.id.str(), &run);
    }
    for (const auto& version : document.versions) {
        version_by_id_.emplace(version.id.str(), &version);
        versions_by_asset_[version.asset_id.str()].push_back(&version);
        for (const auto& parent : version.parent_version_ids) {
            children_by_parent_[parent.str()].push_back(&version);
        }
        if (auto key = managed_raw_dedup_key(version)) {
            managed_raw_by_key_.emplace(key->first + "\x1f" + key->second,
                                        version.id.str());
        }
        if (auto key = external_dedup_key(version)) {
            external_by_path_.emplace(*key, version.id.str());
        }
    }
    // Legacy-bridge resolution order mirrors _find_asset_by_legacy_id:
    // exact id first, then first bridged via legacy_resource_id.
    for (const auto& asset : document.assets) {
        legacy_by_id_.emplace(asset.id.str(), &asset);
    }
    for (const auto& asset : document.assets) {
        if (asset.legacy_resource_id.has_value()) {
            legacy_by_id_.emplace(*asset.legacy_resource_id, &asset);
        }
    }
}

const DataAsset* DocumentIndex::asset(const std::string& id) const {
    auto it = asset_by_id_.find(id);
    return it == asset_by_id_.end() ? nullptr : it->second;
}

const DataVersion* DocumentIndex::version(const std::string& id) const {
    auto it = version_by_id_.find(id);
    return it == version_by_id_.end() ? nullptr : it->second;
}

const DataRun* DocumentIndex::run(const std::string& id) const {
    auto it = run_by_id_.find(id);
    return it == run_by_id_.end() ? nullptr : it->second;
}

const std::vector<const DataVersion*>* DocumentIndex::versions_of_asset(
    const std::string& asset_id) const {
    auto it = versions_by_asset_.find(asset_id);
    return it == versions_by_asset_.end() ? nullptr : &it->second;
}

const std::vector<const DataVersion*>* DocumentIndex::children_of(
    const std::string& parent_id) const {
    auto it = children_by_parent_.find(parent_id);
    return it == children_by_parent_.end() ? nullptr : &it->second;
}

const DataAsset* DocumentIndex::asset_by_legacy_id(
    const std::string& legacy_id) const {
    auto it = legacy_by_id_.find(legacy_id);
    return it == legacy_by_id_.end() ? nullptr : it->second;
}

std::optional<std::string> DocumentIndex::managed_raw_for(
    const std::string& source_uri, const std::string& sha256) const {
    auto it = managed_raw_by_key_.find(source_uri + "\x1f" + sha256);
    return it == managed_raw_by_key_.end() ? std::nullopt
                                           : std::optional<std::string>(it->second);
}

std::optional<std::string> DocumentIndex::external_for(
    const std::string& path) const {
    auto it = external_by_path_.find(path);
    return it == external_by_path_.end() ? std::nullopt
                                         : std::optional<std::string>(it->second);
}

}  // namespace pwb::catalog
