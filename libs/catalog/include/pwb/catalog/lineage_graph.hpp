// Full-chain lineage walks (conv-31; catalog/lineage_graph.py parity).
//
// build_lineage_chain: BFS from any version towards RAW roots (ancestors,
// over parent_version_ids) or downstream products (descendants, over the
// child index), cycle-safe, with honest truncation flags for
// max_depth/max_nodes. compute_summaries: per-version {"to_raw", "broken",
// "has_parents"} in one memoized iterative DFS — to_raw is the minimum hop
// count to a RAW ancestor (None when unreachable), broken flags dangling
// parent references, and a cycle member reports unreachable-from-there.
#pragma once

#include "pwb/catalog/document_index.hpp"
#include "pwb/catalog/models.hpp"
#include "pwb/domain/errors.hpp"

#include <map>
#include <optional>
#include <string>
#include <vector>

namespace pwb::catalog {

inline constexpr int kDefaultLineageMaxNodes = 5000;  // DEFAULT_MAX_NODES

struct LineageChainNode {
    std::string version_id;
    std::string asset_id;
    std::string asset_name;
    domain::DataStage stage = domain::DataStage::Raw;
    int version_number = 0;
    int depth = 0;  // hops from the start version
    bool managed = true;
    bool trashed = false;
    std::string path;
    std::optional<std::string> sha256;
    std::string created_at;
    std::vector<std::string> tags;
    std::optional<std::string> run_id;
    std::optional<std::string> run_operation;
    std::optional<std::string> run_status;
    std::optional<std::string> run_generator;
    std::vector<LineageChainNode> children;
};

struct LineageChain {
    std::string start_version_id;
    std::string direction;  // "ancestors" | "descendants"
    LineageChainNode root;
    int node_count = 1;
    bool truncated = false;
};

// direction must be "ancestors" or "descendants" (error text parity);
// *max_depth counts hops from the start version.
domain::Result<LineageChain> build_lineage_chain(
    const CatalogDocument& document, const DocumentIndex& index,
    const std::string& version_id, const std::string& direction = "ancestors",
    std::optional<int> max_depth = std::nullopt, int max_nodes = kDefaultLineageMaxNodes);

struct LineageSummary {
    std::optional<int> to_raw;  // min hops to a RAW ancestor
    bool broken = false;        // references a parent id not in the document
    bool has_parents = false;
};

std::map<std::string, LineageSummary> compute_lineage_summaries(
    const CatalogDocument& document, const DocumentIndex& index);

}  // namespace pwb::catalog
