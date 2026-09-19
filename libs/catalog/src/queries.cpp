#include "pwb/catalog/queries.hpp"
#include "pwb/catalog/entity_view.hpp"

#include <algorithm>
#include <set>

namespace pwb::catalog {

std::string metadata_search_value(const domain::Json& value) {
    if (value.is_boolean()) return value.get<bool>() ? "1" : "0";
    if (value.is_string()) return value.get<std::string>();
    if (value.is_null()) return "None";
    return value.dump();
}

std::string IntegrityReport::status_for(const std::string& version_id) const {
    auto it = statuses.find(version_id);
    return it == statuses.end() ? "unknown" : it->second;
}

bool IntegrityReport::ok() const {
    return std::all_of(statuses.begin(), statuses.end(),
                       [](const auto& entry) { return entry.second == "verified"; });
}

IntegrityReport verify_integrity(
    const CatalogDocument& document, const std::optional<std::string>& version_id,
    const std::function<std::filesystem::path(const DataVersion&)>& resolve,
    const CancelPoll& cancel) {
    IntegrityReport report;
    std::vector<const DataVersion*> versions;
    if (version_id.has_value()) {
        const DataVersion* one = document.find_version(domain::VersionId(*version_id));
        if (one == nullptr) {
            // Python _version_or_raise raises; the report carries it as an
            // error-shaped empty result via the caller's Result discipline.
            return report;
        }
        versions.push_back(one);
    } else {
        for (const auto& version : document.versions) versions.push_back(&version);
    }
    for (const DataVersion* version : versions) {
        if (cancel && cancel()) {
            report.cancelled = true;
            return report;
        }
        if (version->trashed) continue;  // payloads live in trash/, skipped
        std::filesystem::path payload =
            resolve ? resolve(*version) : std::filesystem::path(version->path);
        std::error_code ec;
        if (!std::filesystem::is_regular_file(payload, ec)) {
            report.statuses[version->id.str()] = "missing";
            continue;
        }
        if (!version->sha256.has_value() || version->sha256->empty()) {
            report.statuses[version->id.str()] = "unknown";
            continue;
        }
        auto digest = sha256_file(payload, kChecksumChunkSize, cancel);
        if (!digest.is_ok()) {
            report.cancelled = true;
            return report;
        }
        report.statuses[version->id.str()] =
            digest.value() == *version->sha256 ? "verified" : "modified";
    }
    return report;
}

std::vector<std::string> search_assets_scan(const CatalogDocument& document,
                                             const DocumentIndex& index,
                                             const AssetSearchQuery& query) {
    if (query.tag_op != "and" && query.tag_op != "or") {
        return {};  // Python raises ValueError; callers validate first
    }
    std::vector<std::string> tag_list;
    for (const auto& tag : query.tags) {
        std::string normalized = normalize_tag_name(tag);
        if (!normalized.empty()) tag_list.push_back(normalized);
    }
    std::vector<std::pair<std::string, std::string>> metadata_pairs;
    for (const auto& [key, value] : query.metadata) {
        const std::string text = metadata_search_value(value);
        if (!text.empty()) metadata_pairs.emplace_back(key, text);
    }

    std::vector<const DataAsset*> results;
    for (const auto& asset : document.assets) results.push_back(&asset);
    if (!query.include_trashed) {
        results.erase(std::remove_if(results.begin(), results.end(),
                                     [](const DataAsset* a) { return a->trashed; }),
                      results.end());
    }
    if (!query.text.empty()) {
        // Same fold as the index path's name_search column (#897): scan
        // and index must agree for non-ASCII case variants (bounded fold).
        const std::string needle = normalize_search_name(query.text);
        results.erase(std::remove_if(results.begin(), results.end(),
                                     [&](const DataAsset* a) {
                                         return normalize_search_name(a->name)
                                                    .find(needle) == std::string::npos;
                                     }),
                      results.end());
    }
    if (query.type.has_value()) {
        results.erase(std::remove_if(results.begin(), results.end(),
                                     [&](const DataAsset* a) {
                                         return a->type != *query.type;
                                     }),
                      results.end());
    }
    if (!metadata_pairs.empty()) {
        results.erase(std::remove_if(results.begin(), results.end(),
                                     [&](const DataAsset* a) {
                                         if (!a->metadata.is_object()) return true;
                                         for (const auto& [key, expected] :
                                              metadata_pairs) {
                                             if (!a->metadata.contains(key)) return true;
                                             if (metadata_search_value(
                                                     a->metadata[key]) != expected) {
                                                 return true;
                                             }
                                         }
                                         return false;
                                     }),
                      results.end());
    }
    if (query.stage.has_value()) {
        std::set<std::string> with_stage;
        for (const auto& version : document.versions) {
            if (version.stage == *query.stage) {
                with_stage.insert(version.asset_id.str());
            }
        }
        results.erase(std::remove_if(results.begin(), results.end(),
                                     [&](const DataAsset* a) {
                                         return !with_stage.count(a->id.str());
                                     }),
                      results.end());
    }
    if (!tag_list.empty()) {
        std::vector<std::set<std::string>> per_tag;
        for (const auto& tag : tag_list) {
            // CONV-31b Wave3 fix: the two-iterator range constructor must
            // span ONE object — calling find_assets_by_tag twice handed
            // begin/end from two DIFFERENT temporaries (the first died
            // mid-construction; UB, crashed on the first tag-filtered
            // scan). Materialize once, then build the set.
            const std::vector<std::string> owned =
                find_assets_by_tag(document, tag);
            std::set<std::string> ids(owned.begin(), owned.end());
            per_tag.push_back(std::move(ids));
        }
        std::set<std::string> tagged;
        if (query.tag_op == "and") {
            bool first = true;
            for (const auto& ids : per_tag) {
                if (first) {
                    tagged = ids;
                    first = false;
                } else {
                    std::set<std::string> intersection;
                    std::set_intersection(tagged.begin(), tagged.end(), ids.begin(),
                                          ids.end(),
                                          std::inserter(intersection,
                                                        intersection.begin()));
                    tagged = std::move(intersection);
                }
            }
        } else {
            for (const auto& ids : per_tag) tagged.insert(ids.begin(), ids.end());
        }
        results.erase(std::remove_if(results.begin(), results.end(),
                                     [&](const DataAsset* a) {
                                         return !tagged.count(a->id.str());
                                     }),
                      results.end());
    }
    std::vector<std::string> out;
    for (const DataAsset* asset : results) out.push_back(asset->id.str());
    (void)index;
    return out;
}

std::vector<std::string> find_assets_by_tag(const CatalogDocument& document,
                                             const std::string& name) {
    const std::string normalized = normalize_tag_name(name);
    const Tag* tag = nullptr;
    for (const auto& candidate : document.tags) {
        if (candidate.name == normalized) {
            tag = &candidate;
            break;
        }
    }
    if (tag == nullptr) return {};
    std::set<std::string> ids;
    for (const auto& [owner, tag_id] : document.asset_tags) {
        if (tag_id == tag->id) ids.insert(owner);
    }
    return std::vector<std::string>(ids.begin(), ids.end());
}

std::vector<std::string> find_versions_by_tag(const CatalogDocument& document,
                                               const std::string& name) {
    const std::string normalized = normalize_tag_name(name);
    const Tag* tag = nullptr;
    for (const auto& candidate : document.tags) {
        if (candidate.name == normalized) {
            tag = &candidate;
            break;
        }
    }
    if (tag == nullptr) return {};
    std::set<std::string> ids;
    for (const auto& [owner, tag_id] : document.version_tags) {
        if (tag_id == tag->id) ids.insert(owner);
    }
    return std::vector<std::string>(ids.begin(), ids.end());
}

}  // namespace pwb::catalog
