// V14 layer ordering engine — 1:1 port of
// paleo_workbench/mapping_workspace/layer_order.py (V11 design,
// docs/development/qgis-cartography-runtime-v11/04-ordering.md).
//
// * Sort keys are strings over the "a"-"z" alphabet; total order == plain
//   lexicographic order. The key space exhausts at pathological adjacent
//   pairs ("x" vs "xa") — the generator throws KeySpaceExhausted and the
//   caller rebalances the whole container (rebalanced_keys, inside one
//   tree transaction). Default keys are fixed-width 8-digit base-26
//   integers (value domain starts at 2, leaving 0/1 as manual-insert
//   headroom; same index -> same key, one spare slot between neighbors).
// * ROLE_BANDS give the default scientific order inside a container /
//   for root-level loose layers, audited against the 33-role registry
//   (machine names, no display names). Factor containers use
//   FACTOR_ROLE_RANK (O(1) rank lookup).
// * assign_keys_for_order converts an observed position order into stable
//   keys: nodes whose existing keys already agree with the observed order
//   (longest increasing subsequence) keep their keys; the rest get
//   midpoint keys between their neighbors. One user drag changes the
//   minimum number of keys.
//
// Pure functions, no Qt: everything is O(N log N) except the midpoint
// chain in key assignment (worst O(N*L), L bounded by the rebalance
// threshold). Roles are plain strings on the wire (tool_policy contract).
#pragma once

#include <map>
#include <stdexcept>
#include <string>
#include <string_view>
#include <tuple>
#include <vector>

namespace pwb::workspace {

// Two keys are lexicographically adjacent (no string in between) — the
// caller should rebalance the container and retry (design path, not a
// defect).
class KeySpaceExhausted : public std::runtime_error {
public:
    explicit KeySpaceExhausted(const std::string& detail)
        : std::runtime_error("KeySpaceExhausted: " + detail) {}
};

// Index key fixed width (26^7 ~= 8e9 slots; midpoint insertion may grow
// past the width — see the module comment).
inline constexpr int kOrderIndexWidth = 8;
// Per-key rebalance threshold: repeated same-point inserts inflate key
// length.
inline constexpr int kOrderRebalanceLength = 64;

// Key alphabet validation (empty string = no key, legacy).
bool valid_key(std::string_view key);

// Index -> fixed-width default key (same index -> same key; lexicographic
// == index order). Value domain starts at 2 (key_for_index(0) ends in
// "b"); 0/1 stay free for manual before/after inserts; the tail stays
// non-"a" so a key never becomes adjacent to its own prefix.
// Throws std::invalid_argument on negative index or width overflow.
std::string key_for_index(long long index);

// The first `count` default keys (step 1; at least one spare midpoint
// slot between neighbors).
std::vector<std::string> key_sequence(std::size_t count);

// A key strictly between a and b (requires non-empty a < b). Prefers the
// short key (a + "b"); throws KeySpaceExhausted on adjacent pairs.
std::string key_between(const std::string& a, const std::string& b);

// A near key greater than a (tail append; for unbounded-above inserts).
std::string key_after(const std::string& a);

// A near key smaller than b (for unbounded-below inserts; throws
// KeySpaceExhausted when adjacent). Callers that hit exhaustion rebalance
// the whole container — the design path taken by assign_keys_for_order.
std::string key_before(const std::string& b);

// Convert a position order into stable keys with minimal disturbance to
// existing keys. Existing keys whose relative order agrees with the
// observed order (LIS) are kept verbatim; the other nodes get midpoint
// chains between their neighbors. Any key-space exhaustion rebalances the
// whole container to fixed-width default keys (order-preserving,
// deterministic). Returns id -> key, complete for ordered_ids.
// (`existing` entries with empty/non-string values count as "no key" —
// Python str(None) injection hazard ported as explicit filtering.)
std::map<std::string, std::string> assign_keys_for_order(
    const std::vector<std::string>& ordered_ids,
    const std::map<std::string, std::string>* existing = nullptr);

bool key_needs_rebalance(const std::vector<std::string>& keys);
bool key_needs_rebalance(
    const std::map<std::string, std::string>& keys);

// Whole-container rebalance: re-derive fixed-width default keys in order
// (use inside one transaction).
std::map<std::string, std::string> rebalanced_keys(
    const std::vector<std::string>& ordered_ids);

// Longest strictly-increasing subsequence of `keys` (kept index set),
// O(K log K) patience sorting. Exposed for tests/plan reuse.
std::vector<std::size_t> longest_increasing_indices(
    const std::vector<std::string>& keys);

// ---------------------------------------------------------------------------
// Scientific role bands (audit conclusion over the 33-role registry)
// ---------------------------------------------------------------------------

// Smaller band = higher on screen (rendered on top). Coarse ordering
// between groups is carried by the SYSTEM_GROUP_TEMPLATES declaration
// order; this table drives the default scientific order INSIDE a
// container and for root-level loose layers.
int role_band(std::string_view role);
const std::map<std::string, int>& role_bands();

// Factor container scientific order
// (input->grid->contour->classification->uncertainty->QC; same source as
// layer_groups.FACTOR_CHILD_ORDER, O(1) rank here).
int factor_role_rank(std::string_view role);

// Default in-container sort key: band -> scientific sub-order -> stable
// id (total order, deterministic).
using BandSortKey = std::tuple<int, long long, std::string>;
BandSortKey band_sort_key(std::string_view role, long long sub_order = 0,
                          std::string node_id = "");

}  // namespace pwb::workspace
