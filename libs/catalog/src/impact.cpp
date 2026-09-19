#include "pwb/catalog/impact.hpp"

#include <algorithm>
#include <deque>
#include <functional>
#include <map>

namespace pwb::catalog {

namespace {
std::string stage_wire(domain::DataStage stage) {
    return std::string(domain::to_string(stage));
}

bool version_is_pinned(const DataVersion& version) {
    return version.metadata.is_object() && version.metadata.contains("pin") &&
           version.metadata["pin"].is_object() && !version.metadata["pin"].empty();
}
}  // namespace

std::optional<std::size_t> ImpactService::cache_key(
    const std::set<std::string>& changed, bool include_trashed) const {
    // Python key: (id(document), revision, mutation_serial, fingerprint,
    // include_trashed) — the first three are constant per instance, so the
    // remaining observable key is (fingerprint, include_trashed).
    std::size_t hash = std::hash<std::string>{}(std::to_string(include_trashed));
    for (const auto& id : changed) {
        hash = hash * 1000003u ^ std::hash<std::string>{}(id);
    }
    hash ^= document_.catalog_revision * 31u;
    return hash;
}

std::vector<StaleItem> ImpactService::downstream_stale(
    const std::optional<std::set<std::string>>& changed_version_ids,
    bool include_trashed) {
    const std::set<std::string> changed = changed_version_ids.value_or(std::set<std::string>());
    if (auto key = cache_key(changed, include_trashed)) {
        for (const auto& entry : cache_) {
            if (entry.key_hash == *key && entry.include_trashed == include_trashed) {
                return entry.items;  // hit (document identity is per-instance)
            }
        }
    }

    // Candidates: descendants of the trigger set. Without an explicit
    // trigger set, the triggers are every non-current version of every
    // multi-version asset, plus every trashed version.
    std::set<std::string> triggers = changed;
    if (changed.empty()) {
        for (const auto& asset : document_.assets) {
            const std::vector<const DataVersion*>* versions =
                index_.versions_of_asset(asset.id.str());
            if (versions == nullptr) continue;
            if (asset.current_version_id.has_value() && versions->size() > 1) {
                for (const DataVersion* version : *versions) {
                    if (!(version->id == *asset.current_version_id)) {
                        triggers.insert(version->id.str());
                    }
                }
            }
            for (const DataVersion* version : *versions) {
                if (version->trashed) triggers.insert(version->id.str());
            }
        }
    }

    auto remember = [&](std::vector<StaleItem> items) {
        if (auto key = cache_key(changed, include_trashed)) {
            CacheEntry entry;
            entry.key_hash = *key;
            entry.include_trashed = include_trashed;
            entry.items = items;
            // LRU: erase same-key entry, push back, trim front.
            cache_.erase(std::remove_if(cache_.begin(), cache_.end(),
                                        [&](const CacheEntry& e) {
                                            return e.key_hash == *key &&
                                                   e.include_trashed == include_trashed;
                                        }),
                         cache_.end());
            cache_.push_back(std::move(entry));
            while (cache_.size() > kCacheMax) cache_.erase(cache_.begin());
        }
        return items;
    };

    if (triggers.empty()) {
        return remember({});
    }

    std::map<std::string, int> depth;
    std::deque<std::pair<std::string, int>> queue;
    for (const auto& trigger : triggers) {
        if (!depth.count(trigger)) {
            depth[trigger] = 0;
            queue.push_back({trigger, 0});
        }
    }
    int walked = 0;
    bool truncated = false;
    while (!queue.empty()) {
        auto [node, d] = queue.front();
        queue.pop_front();
        if (const auto* children = index_.children_of(node)) {
            for (const DataVersion* child : *children) {
                const std::string child_id = child->id.str();
                if (depth.count(child_id)) continue;
                ++walked;
                if (walked > kMaxImpactNodes) {
                    truncated = true;
                    break;
                }
                depth[child_id] = d + 1;
                queue.push_back({child_id, d + 1});
            }
        }
        if (truncated) break;
    }

    std::vector<StaleItem> items;
    for (const auto& [version_id, d] : depth) {
        if (d == 0) continue;  // the trigger versions themselves
        const DataVersion* version = index_.version(version_id);
        if (version == nullptr) continue;
        if (version->trashed && !include_trashed) continue;
        auto nearest = nearest_changed_ancestor(version_id, triggers);
        if (!nearest.has_value()) continue;
        auto [asset_id, old_id, current_id] = *nearest;
        const DataRun* run =
            version->run_id ? index_.run(version->run_id->str()) : nullptr;
        bool pinned = version_is_pinned(*version);
        const DataVersion* old_version = index_.version(old_id);
        const bool reason_trashed = old_version != nullptr && old_version->trashed;
        StaleItem item;
        item.version_id = version_id;
        item.asset_id = version->asset_id.str();
        item.direct = d == 1;
        item.via_run_id =
            version->run_id.has_value()
                ? std::optional<std::string>(version->run_id->str())
                : std::nullopt;
        item.nearest_changed_ancestor = nearest;
        item.reason = reason_trashed
                          ? "上游 " + asset_id + " 的版本 " + old_id +
                                " 已被删除（回收站），本版本基于该输入"
                          : "上游 " + asset_id + " 已从 " + old_id + " 演进到 " +
                                current_id + "，本版本仍基于旧输入";
        item.pinned = pinned;
        item.reproducible = run != nullptr;
        item.stage = stage_wire(version->stage);
        item.trashed = version->trashed;
        items.push_back(std::move(item));
        if (static_cast<int>(items.size()) >= kMaxStaleItems) {
            truncated = true;
            break;
        }
    }
    // key: (not direct, version_id) — direct items first, then id order.
    std::stable_sort(items.begin(), items.end(), [](const StaleItem& a, const StaleItem& b) {
        if (a.direct != b.direct) return !a.direct && b.direct;
        return a.version_id < b.version_id;
    });
    if (truncated && !items.empty()) {
        items.back().reason += "（结果已截断：影响面超出节点上限）";
    }
    return remember(std::move(items));
}

std::optional<std::tuple<std::string, std::string, std::string>>
ImpactService::nearest_changed_ancestor(
    const std::string& version_id, const std::set<std::string>& triggers) const {
    std::optional<std::pair<int, std::tuple<std::string, std::string, std::string>>> best;
    std::set<std::string> visited{version_id};
    std::deque<std::pair<std::string, int>> queue{{version_id, 0}};
    while (!queue.empty()) {
        auto [node, d] = queue.front();
        queue.pop_front();
        const DataVersion* version = index_.version(node);
        if (version == nullptr) continue;
        for (const auto& parent_id_raw : version->parent_version_ids) {
            const std::string parent_id = parent_id_raw.str();
            if (visited.count(parent_id)) continue;
            visited.insert(parent_id);
            const DataVersion* parent = index_.version(parent_id);
            if (parent == nullptr) continue;
            if (parent->trashed) {
                auto candidate = std::make_pair(
                    d + 1, std::make_tuple(parent->asset_id.str(), parent_id, parent_id));
                if (!best.has_value() || candidate.first < best->first) best = candidate;
                continue;  // keep walking for a possibly nearer trigger
            }
            const DataAsset* asset = index_.asset(parent->asset_id.str());
            const std::string current =
                asset != nullptr && asset->current_version_id.has_value()
                    ? asset->current_version_id->str()
                    : std::string();
            const bool evolved = !current.empty() && current != parent_id &&
                                 !(asset != nullptr && asset->trashed);
            if (evolved || triggers.count(parent_id)) {
                const std::string current_ref = !current.empty() ? current : parent_id;
                auto candidate = std::make_pair(
                    d + 1, std::make_tuple(parent->asset_id.str(), parent_id, current_ref));
                if (!best.has_value() || candidate.first < best->first) best = candidate;
                continue;
            }
            queue.push_back({parent_id, d + 1});
        }
    }
    if (!best.has_value()) return std::nullopt;
    return best->second;
}

std::pair<bool, std::string> ImpactService::is_stale(const std::string& version_id) {
    auto nearest = nearest_changed_ancestor(version_id, std::set<std::string>());
    if (!nearest.has_value()) return {false, ""};
    auto [asset_id, old_id, current_id] = *nearest;
    return {true, "上游 " + asset_id + " 已演进（" + old_id + " → " + current_id +
                      "），本版本仍基于旧输入"};
}

UpstreamImpact ImpactService::upstream_impact(const std::string& version_id) {
    UpstreamImpact impact;
    impact.version_id = version_id;
    const DataVersion* start = index_.version(version_id);
    if (start == nullptr) return impact;
    std::set<std::string> seen{version_id};
    std::deque<std::string> queue;
    for (const auto& parent : start->parent_version_ids) {
        queue.push_back(parent.str());
        seen.insert(parent.str());
    }
    std::set<std::string> runs;
    int walked = 0;
    bool truncated = false;
    while (!queue.empty()) {
        if (walked > kMaxImpactNodes) {
            truncated = true;
            break;
        }
        const std::string node = queue.front();
        queue.pop_front();
        ++walked;
        const DataVersion* version = index_.version(node);
        if (version == nullptr) {
            impact.missing_ancestors.push_back(node);
            continue;
        }
        impact.ancestor_version_ids.push_back(node);
        impact.ancestor_asset_ids.push_back(version->asset_id.str());
        if (version->run_id) runs.insert(version->run_id->str());
        if (version->trashed) impact.trashed_ancestors.push_back(node);
        for (const auto& parent : version->parent_version_ids) {
            if (!seen.count(parent.str())) {
                seen.insert(parent.str());
                queue.push_back(parent.str());
            }
        }
    }
    for (const auto& run : document_.runs) {
        if (runs.count(run.id.str())) continue;
        for (const auto& input : run.input_version_ids) {
            if (seen.count(input.str())) {
                runs.insert(run.id.str());
                break;
            }
        }
    }
    impact.runs_involved.assign(runs.begin(), runs.end());
    if (truncated) {
        // Python appends the marker BEFORE sorted(set(...)), so it lands at
        // its lexicographic position ('<' sorts before id digits/letters).
        impact.ancestor_version_ids.push_back(
            "<truncated: upstream closure exceeded " + std::to_string(kMaxImpactNodes) +
            " nodes>");
    }
    std::set<std::string> unique_versions(impact.ancestor_version_ids.begin(),
                                          impact.ancestor_version_ids.end());
    impact.ancestor_version_ids.assign(unique_versions.begin(), unique_versions.end());
    std::set<std::string> unique_assets(impact.ancestor_asset_ids.begin(),
                                        impact.ancestor_asset_ids.end());
    impact.ancestor_asset_ids.assign(unique_assets.begin(), unique_assets.end());
    return impact;
}

DeleteImpact ImpactService::delete_impact(
    const std::optional<std::string>& version_id,
    const std::optional<std::string>& asset_id,
    const std::vector<EntityLink>* entity_links) {
    DeleteImpact impact;
    if (version_id.has_value()) {
        impact.target_version_ids.push_back(*version_id);
        const DataVersion* version = index_.version(*version_id);
        if (version != nullptr) {
            impact.target_asset_ids.push_back(version->asset_id.str());
        }
    } else if (asset_id.has_value()) {
        impact.target_asset_ids.push_back(*asset_id);
        if (const auto* versions = index_.versions_of_asset(*asset_id)) {
            for (const DataVersion* version : *versions) {
                impact.target_version_ids.push_back(version->id.str());
            }
        }
    }
    std::set<std::string> target_set(impact.target_version_ids.begin(),
                                     impact.target_version_ids.end());

    std::map<std::string, int> depth;
    std::deque<std::pair<std::string, int>> queue;
    for (const auto& target : target_set) {
        depth[target] = 0;
        queue.push_back({target, 0});
    }
    int broken_edges = 0;
    int walked = 0;
    while (!queue.empty()) {
        if (walked > kMaxImpactNodes) break;  // informational, not exhaustive
        auto [node, d] = queue.front();
        queue.pop_front();
        ++walked;
        if (const auto* children = index_.children_of(node)) {
            for (const DataVersion* child : *children) {
                if (!depth.count(child->id.str())) ++broken_edges;
                const std::string child_id = child->id.str();
                if (depth.count(child_id)) continue;
                depth[child_id] = d + 1;
                queue.push_back({child_id, d + 1});
            }
        }
    }
    for (const auto& [vid, d] : depth) {
        if (d == 0) continue;
        const DataVersion* version = index_.version(vid);
        if (version == nullptr ||
            (version->trashed && target_set.count(vid) == 0)) {
            continue;
        }
        StaleItem item;
        item.version_id = vid;
        item.asset_id = version->asset_id.str();
        item.direct = d == 1;
        item.via_run_id = version->run_id.has_value()
                              ? std::optional<std::string>(version->run_id->str())
                              : std::nullopt;
        item.reason = "删除目标位于其上游依赖链（距离 " + std::to_string(d) + "）";
        item.pinned = version_is_pinned(*version);
        item.reproducible =
            version->run_id ? index_.run(version->run_id->str()) != nullptr : false;
        item.stage = stage_wire(version->stage);
        item.trashed = version->trashed;
        impact.live_descendants.push_back(std::move(item));
    }
    impact.broken_lineage_edges = broken_edges;

    for (const auto& run : document_.runs) {
        bool consumes = false;
        for (const auto& input : run.input_version_ids) {
            if (target_set.count(input.str())) consumes = true;
        }
        if (consumes) impact.runs_consuming.push_back(run.id.str());
        bool produces = false;
        for (const auto& output : run.output_version_ids) {
            if (target_set.count(output.str())) produces = true;
        }
        if (produces) impact.runs_producing.push_back(run.id.str());
    }

    if (entity_links != nullptr) {
        std::set<std::string> linked(impact.target_asset_ids.begin(),
                                     impact.target_asset_ids.end());
        linked.insert(target_set.begin(), target_set.end());
        for (const auto& link : *entity_links) {
            if (linked.count(link.asset_id)) {
                impact.linked_entities.emplace_back(link.entity_type, link.entity_id);
            }
        }
    }

    std::size_t non_pinned = 0;
    std::size_t pinned = 0;
    for (const auto& item : impact.live_descendants) {
        item.pinned ? ++pinned : ++non_pinned;
    }
    if (non_pinned > 0) {
        impact.cascade_advice.push_back(
            std::to_string(non_pinned) +
            " 个下游成果将基于残缺 lineage：建议先重算或固定（pin）这些下游版本，再执行删除。");
    }
    if (pinned > 0) {
        impact.cascade_advice.push_back(
            std::to_string(pinned) +
            " 个下游版本已 pin：删除不会改变其科学结论标记，但 lineage 解析将显示缺失上游。");
    }
    if (!impact.runs_consuming.empty()) {
        impact.cascade_advice.push_back(std::to_string(impact.runs_consuming.size()) +
                                        " 个 run 以其为输入（历史溯源保留，不阻塞删除）。");
    }
    return impact;
}

std::vector<StaleItem> ImpactService::entity_staleness(
    const std::set<std::string>& asset_ids) {
    if (asset_ids.empty()) return {};
    std::vector<StaleItem> scoped;
    for (const auto& item : downstream_stale()) {
        if (has_ancestor_in_assets(item.version_id, asset_ids)) {
            scoped.push_back(item);
        }
    }
    return scoped;
}

bool ImpactService::has_ancestor_in_assets(const std::string& version_id,
                                            const std::set<std::string>& asset_ids,
                                            int budget) const {
    std::set<std::string> seen{version_id};
    std::vector<std::string> stack{version_id};
    int walked = 0;
    while (!stack.empty()) {
        const std::string node = stack.back();
        stack.pop_back();
        ++walked;
        if (walked > budget) return false;  // bounded, pessimistic-quiet
        const DataVersion* version = index_.version(node);
        if (version == nullptr) continue;
        if (asset_ids.count(version->asset_id.str())) return true;
        for (const auto& parent : version->parent_version_ids) {
            if (!seen.count(parent.str())) {
                seen.insert(parent.str());
                stack.push_back(parent.str());
            }
        }
    }
    return false;
}

}  // namespace pwb::catalog
