#include "pwb/catalog/lineage_graph.hpp"

#include <deque>
#include <set>

namespace pwb::catalog {

namespace {

std::map<std::string, std::vector<std::string>> version_tag_ids(
    const CatalogDocument& document) {
    std::map<std::string, std::vector<std::string>> out;
    for (const auto& [owner, tag_id] : document.version_tags) {
        out[owner].push_back(tag_id);
    }
    return out;
}

LineageChainNode make_node(const CatalogDocument& document,
                           const DocumentIndex& index, const DataVersion& version,
                           int depth,
                           const std::map<std::string, std::vector<std::string>>& tags_by_owner) {
    LineageChainNode node;
    node.version_id = version.id.str();
    node.asset_id = version.asset_id.str();
    const DataAsset* asset = index.asset(node.asset_id);
    node.asset_name = asset != nullptr ? asset->name : node.asset_id;
    node.stage = version.stage;
    node.version_number = version.version_number;
    node.depth = depth;
    node.managed = version.managed;
    node.trashed = version.trashed;
    node.path = version.path;
    node.sha256 = version.sha256;
    node.created_at = version.created_at;
    auto tags = tags_by_owner.find(node.version_id);
    if (tags != tags_by_owner.end()) {
        for (const auto& tag_id : tags->second) {
            for (const auto& tag : document.tags) {
                if (tag.id == tag_id) {
                    node.tags.push_back(tag.display_name.value_or(tag.name));
                    break;
                }
            }
        }
    }
    node.run_id = version.run_id.has_value()
                      ? std::optional<std::string>(version.run_id->str())
                      : std::nullopt;
    if (version.run_id.has_value()) {
        const DataRun* run = index.run(version.run_id->str());
        if (run != nullptr) {
            node.run_operation = run->operation;
            node.run_status = run->status;
            node.run_generator = run->generator;
        }
    }
    return node;
}

}  // namespace

domain::Result<LineageChain> build_lineage_chain(
    const CatalogDocument& document, const DocumentIndex& index,
    const std::string& version_id, const std::string& direction,
    std::optional<int> max_depth, int max_nodes) {
    if (direction != "ancestors" && direction != "descendants") {
        // ValueError text parity: f"direction must be 'ancestors' or
        // 'descendants', got {direction!r}"
        std::string repr = "'" + direction + "'";
        return domain::DataError(
            domain::ErrorCode::InvalidArgument,
            "direction must be 'ancestors' or 'descendants', got " + repr);
    }
    const DataVersion* start = index.version(version_id);
    if (start == nullptr) {
        return domain::DataError(domain::ErrorCode::NotFound,
                                 "Unknown version: " + version_id);
    }
    const auto tags_by_owner = version_tag_ids(document);

    LineageChain chain;
    chain.start_version_id = start->id.str();
    chain.direction = direction;
    chain.root = make_node(document, index, *start, 0, tags_by_owner);

    std::set<std::string> seen{start->id.str()};
    std::deque<LineageChainNode*> queue;
    queue.push_back(&chain.root);
    bool truncated = false;
    while (!queue.empty()) {
        LineageChainNode* node = queue.front();
        queue.pop_front();
        const DataVersion* version = index.version(node->version_id);
        if (version == nullptr) continue;
        std::vector<std::string> next_ids;
        if (direction == "ancestors") {
            for (const auto& parent : version->parent_version_ids) {
                next_ids.push_back(parent.str());
            }
        } else {
            if (const auto* children = index.children_of(node->version_id)) {
                for (const DataVersion* child : *children) {
                    next_ids.push_back(child->id.str());
                }
            }
        }
        if (max_depth.has_value() && node->depth >= *max_depth) {
            truncated = truncated || !next_ids.empty();
            continue;
        }
        for (const auto& next_id : next_ids) {
            const DataVersion* child_version = index.version(next_id);
            if (child_version == nullptr || seen.count(next_id)) continue;
            if (static_cast<int>(seen.size()) >= max_nodes) {
                truncated = true;
                break;
            }
            seen.insert(next_id);
            node->children.push_back(
                make_node(document, index, *child_version, node->depth + 1, tags_by_owner));
            queue.push_back(&node->children.back());
        }
    }
    chain.node_count = static_cast<int>(seen.size());
    chain.truncated = truncated;
    return chain;
}

std::map<std::string, LineageSummary> compute_lineage_summaries(
    const CatalogDocument& document, const DocumentIndex& index) {
    std::map<std::string, std::optional<int>> memo;
    std::set<std::string> broken;
    std::map<std::string, LineageSummary> summaries;

    for (const auto& version : document.versions) {
        const std::string start_id = version.id.str();
        if (memo.count(start_id)) continue;
        // Iterative post-order DFS: (id, phase) with phase 0 = enter,
        // 1 = merge children — the Python structure verbatim.
        std::vector<std::pair<std::string, int>> stack{{start_id, 0}};
        std::set<std::string> on_path;
        std::map<std::string, std::optional<int>> local_results;
        while (!stack.empty()) {
            auto [vid, phase] = stack.back();
            stack.pop_back();
            if (memo.count(vid)) {
                local_results[vid] = memo[vid];
                continue;
            }
            const DataVersion* version_ptr = index.version(vid);
            if (version_ptr == nullptr) {
                local_results[vid] = std::nullopt;
                memo[vid] = std::nullopt;
                continue;
            }
            if (phase == 0) {
                if (on_path.count(vid)) {
                    // Cycle: treat as no-path-through-here.
                    local_results[vid] = std::nullopt;
                    continue;
                }
                if (version_ptr->parent_version_ids.empty()) {
                    memo[vid] = version_ptr->stage == domain::DataStage::Raw
                                    ? std::optional<int>(0)
                                    : std::nullopt;
                    local_results[vid] = memo[vid];
                    continue;
                }
                on_path.insert(vid);
                stack.push_back({vid, 1});
                for (const auto& pid : version_ptr->parent_version_ids) {
                    if (index.version(pid.str()) == nullptr) {
                        broken.insert(vid);
                    }
                    stack.push_back({pid.str(), 0});
                }
                continue;
            }
            on_path.erase(vid);
            std::optional<int> best;
            if (version_ptr->stage == domain::DataStage::Raw) best = 0;
            for (const auto& pid : version_ptr->parent_version_ids) {
                std::optional<int> child_depth;
                auto local = local_results.find(pid.str());
                if (local != local_results.end()) {
                    child_depth = local->second;
                } else {
                    auto global = memo.find(pid.str());
                    if (global != memo.end()) child_depth = global->second;
                }
                if (!child_depth.has_value()) continue;
                int candidate = version_ptr->stage == domain::DataStage::Raw
                                    ? *child_depth
                                    : *child_depth + 1;
                if (!best.has_value() || candidate < *best) best = candidate;
            }
            memo[vid] = best;
            local_results[vid] = best;
        }
    }
    for (const auto& version : document.versions) {
        LineageSummary summary;
        auto it = memo.find(version.id.str());
        summary.to_raw = it != memo.end() ? it->second : std::nullopt;
        summary.broken = broken.count(version.id.str()) != 0;
        summary.has_parents = !version.parent_version_ids.empty();
        summaries[version.id.str()] = summary;
    }
    return summaries;
}

}  // namespace pwb::catalog
