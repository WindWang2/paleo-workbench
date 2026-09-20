// workspace.layer_control_scale — structural scale/performance contracts
// (V14 contracts 03 §8): complexity is asserted via op counts and bounded
// work, not wall time only.
#include "pwb_test.hpp"

#include "pwb/workspace/layer_order.hpp"
#include "pwb/workspace/layer_tree.hpp"
#include "pwb/workspace/layer_tree_diff.hpp"
#include "pwb/workspace/source_usage.hpp"

#include <chrono>
#include <random>

namespace {

using pwb::workspace::LayerTreeSnapshot;
using pwb::workspace::TreeNode;

std::vector<std::string> ids_n(std::size_t count, const std::string& prefix) {
    std::vector<std::string> out;
    out.reserve(count);
    for (std::size_t i = 0; i < count; ++i) {
        out.push_back(prefix + std::to_string(i));
    }
    return out;
}

LayerTreeSnapshot flat_tree(const std::vector<std::string>& order) {
    LayerTreeSnapshot snapshot;
    for (const std::string& id : order) {
        snapshot.children.push_back(TreeNode::layer(id));
    }
    return snapshot;
}

}  // namespace

PWB_TEST(assign_keys_thousand_layers_bounded) {
    // Fresh 1000-layer container: fixed-width keys, unique, sorted,
    // no rebalance needed.
    const std::vector<std::string> order = ids_n(1000, "layer_");
    const auto keys = pwb::workspace::assign_keys_for_order(order, nullptr);
    PWB_CHECK(keys.size() == 1000);
    std::string prev;
    std::size_t max_len = 0;
    for (const std::string& id : order) {  // positional order, not map order
        const std::string& key = keys.at(id);
        PWB_CHECK(!key.empty());
        PWB_CHECK(prev.empty() || prev < key);
        max_len = std::max(max_len, key.size());
        prev = key;
    }
    PWB_CHECK(max_len == 8);  // fixed width, no growth for fresh containers

    // Single drag inside a keyed 1000-layer container: at most 1 key
    // changes (the moved node's midpoint).
    std::map<std::string, std::string> existing = keys;
    std::vector<std::string> dragged = order;
    std::rotate(dragged.begin(), dragged.begin() + 500, dragged.begin() + 501);
    const auto rekeyed =
        pwb::workspace::assign_keys_for_order(dragged, &existing);
    std::size_t changed = 0;
    for (const auto& [id, key] : rekeyed) {
        auto it = existing.find(id);
        if (it == existing.end() || it->second != key) ++changed;
    }
    PWB_CHECK(changed <= 1);

    // Full reversal (worst case): LIS keeps exactly 1 key; the rest are
    // re-keyed, and the result stays a valid total order without
    // exploding key lengths (rebalance threshold guards).
    std::vector<std::string> reversed = order;
    std::reverse(reversed.begin(), reversed.end());
    const auto reversed_keys =
        pwb::workspace::assign_keys_for_order(reversed, &existing);
    std::size_t max_rev_len = 0;
    for (const auto& entry : reversed_keys) {
        max_rev_len = std::max(max_rev_len, entry.second.size());
    }
    PWB_CHECK(max_rev_len <= 64 + 1);  // rebalance threshold respected
}

PWB_TEST(diff_thousand_layers_minimal_ops) {
    // Identical trees: zero ops (no re-placement churn).
    const std::vector<std::string> order = ids_n(1000, "l_");
    const LayerTreeSnapshot current = flat_tree(order);
    const pwb::workspace::TreeDiff same =
        pwb::workspace::diff_trees(current, current);
    PWB_CHECK(same.is_empty());

    // One swap far apart: exactly the moved nodes leave the LCS.
    std::vector<std::string> swapped = order;
    std::swap(swapped[10], swapped[990]);
    const pwb::workspace::TreeDiff diff =
        pwb::workspace::diff_trees(current, flat_tree(swapped));
    // A single swap breaks the LIS into at most 2 moves out of place…
    // patience LIS on the swap keeps everything else; the two swapped
    // nodes move.
    PWB_CHECK(diff.layer_moves.size() <= 2);
    PWB_CHECK(diff.layer_moves.size() >= 1);
    PWB_CHECK(diff.group_creates.empty() && diff.group_removes.empty());

    // Full reversal of 1000: bounded move set (LIS keeps the longest
    // increasing run; everything else moves once — no quadratic repeat).
    std::vector<std::string> reversed = order;
    std::reverse(reversed.begin(), reversed.end());
    const pwb::workspace::TreeDiff rev_diff =
        pwb::workspace::diff_trees(current, flat_tree(reversed));
    PWB_CHECK(rev_diff.layer_moves.size() <= 999);
    PWB_CHECK(rev_diff.layer_moves.size() >= 998);

    // Wall-time sanity for the whole 1000-layer pipeline (structural
    // budget; generous CI ceiling, not a perf record).
    const auto t0 = std::chrono::steady_clock::now();
    for (int round = 0; round < 10; ++round) {
        std::vector<std::string> shuffled = order;
        std::mt19937 rng(static_cast<unsigned>(round));
        std::shuffle(shuffled.begin(), shuffled.end(), rng);
        const auto tree = flat_tree(shuffled);
        pwb::workspace::diff_trees(current, tree);
        pwb::workspace::assign_keys_for_order(shuffled, nullptr);
    }
    const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
                             std::chrono::steady_clock::now() - t0)
                             .count();
    PWB_CHECK(elapsed < 5000);
}

PWB_TEST(tree_indexing_linear_no_index_hotspot) {
    // find_layer_parent / find_group over 1000 layers × 20 groups answer
    // within a bounded work budget (structural: traversal is linear per
    // query; the whole batch stays comfortably interactive).
    LayerTreeSnapshot snapshot;
    const std::size_t groups = 20;
    const std::size_t per_group = 50;
    for (std::size_t g = 0; g < groups; ++g) {
        TreeNode node = TreeNode::group("group_" + std::to_string(g),
                                        "G" + std::to_string(g));
        for (std::size_t i = 0; i < per_group; ++i) {
            node.children.push_back(
                TreeNode::layer("layer_" + std::to_string(g) + "_" +
                                std::to_string(i)));
        }
        snapshot.children.push_back(std::move(node));
    }
    const auto t0 = std::chrono::steady_clock::now();
    std::size_t found = 0;
    for (std::size_t g = 0; g < groups; ++g) {
        for (std::size_t i = 0; i < per_group; ++i) {
            const std::string id = "layer_" + std::to_string(g) + "_" +
                                   std::to_string(i);
            if (snapshot.find_layer_parent(id) != nullptr) ++found;
        }
    }
    PWB_CHECK(found == groups * per_group);
    const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
                             std::chrono::steady_clock::now() - t0)
                             .count();
    PWB_CHECK(elapsed < 3000);
    PWB_CHECK(snapshot.layer_ids_top_first().size() == 1000);
    PWB_CHECK(snapshot.group_ids().size() == groups);
}

PWB_TEST(usage_query_run_cap_bounded) {
    // run usage is capped at kMaxRunUsageEntries with an honest truncated
    // flag; layer/factor/product scans are linear in their sections.
    class BigRunCatalog : public pwb::workspace::UsageCatalog {
    public:
        std::optional<std::vector<std::string>> run_input_version_ids(
            const std::string&) const override {
            return std::vector<std::string>{"v1"};
        }
        std::vector<pwb::workspace::RunSummary> runs_consuming(
            const std::string&) const override {
            std::vector<pwb::workspace::RunSummary> out;
            out.reserve(10000);
            for (int i = 0; i < 10000; ++i) {
                pwb::workspace::RunSummary summary;
                summary.id = "run_" + std::to_string(i);
                summary.operation = "op";
                summary.status = "finished";
                out.push_back(std::move(summary));
            }
            return out;
        }
        std::vector<std::string> versions_of_asset(
            const std::string&) const override {
            return {};
        }
    };
    BigRunCatalog catalog;
    const auto report =
        pwb::workspace::usages_of_version("v1", nullptr, nullptr, &catalog);
    PWB_CHECK(report.usages.size() == pwb::workspace::kMaxRunUsageEntries);
    PWB_CHECK(report.truncated);

    // Empty id: honest empty report without touching any source.
    const auto empty =
        pwb::workspace::usages_of_version("", nullptr, nullptr, &catalog);
    PWB_CHECK(empty.usages.empty() && !empty.truncated);
}
