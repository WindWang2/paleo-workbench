// V14 layer ordering engine — port of layer_order.py (see layer_order.hpp).
#include "pwb/workspace/layer_order.hpp"

#include <algorithm>
#include <cstdint>

namespace pwb::workspace {

namespace {

constexpr char kAlphabet[] = "abcdefghijklmnopqrstuvwxyz";

int digit_of(char ch) {
    if (ch < 'a' || ch > 'z') return -1;
    return ch - 'a';
}

std::size_t common_prefix_len(const std::string& a, const std::string& b) {
    std::size_t i = 0;
    const std::size_t limit = std::min(a.size(), b.size());
    while (i < limit && a[i] == b[i]) ++i;
    return i;
}

// A non-empty string s with s < rest (throws KeySpaceExhausted when rest
// is all "a"s and nothing shorter fits below).
std::string str_below(const std::string& rest) {
    if (!rest.empty() && rest.back() > 'a') {
        return rest.substr(0, rest.size() - 1) +
               static_cast<char>(rest.back() - 1);
    }
    const std::size_t stripped_len = rest.find_last_not_of('a');
    if (stripped_len == std::string::npos) {
        // rest == "a"*k: only shorter a-strings fit below ("a"*(k-1)).
        if (rest.size() >= 2) return rest.substr(0, rest.size() - 1);
        throw KeySpaceExhausted("no key below \"" + rest + "\"");
    }
    // rest == P + "a"*k with P ending in a non-"a" char: decrement P's
    // last char and pad back to the original length with "z"s (Python:
    // stripped[:-1] + chr(ord(stripped[-1])-1) + "z"*k).
    std::string out = rest.substr(0, stripped_len + 1);
    out.back() = static_cast<char>(out.back() - 1);
    out.append(rest.size() - stripped_len - 1, 'z');
    return out;
}

// Flush helper for assign_keys_for_order: give consecutive pending nodes
// midpoint keys inside the open interval (prev_key, next_key). Empty
// optional means unbounded on that side.
void flush_pending(const std::vector<std::string>& pending,
                   std::map<std::string, std::string>& out,
                   const std::string* prev_key,
                   const std::string* next_key) {
    if (pending.empty()) return;
    std::string low;
    if (prev_key != nullptr && !prev_key->empty()) {
        low = *prev_key;
    } else if (next_key != nullptr) {
        low = key_before(*next_key);  // may throw (caller rebalances)
    } else {
        low = key_for_index(0);
    }
    std::vector<std::string> keys;
    keys.reserve(pending.size());
    for (std::size_t i = 0; i < pending.size(); ++i) {
        std::string nxt;
        if (next_key == nullptr) {
            nxt = key_after(low);
        } else {
            try {
                nxt = key_between(low, *next_key);
            } catch (const KeySpaceExhausted&) {
                nxt.clear();
            } catch (const std::invalid_argument&) {
                nxt.clear();
            }
        }
        if (nxt.empty()) {
            throw KeySpaceExhausted("no slot between \"" + low + "\" and \"" +
                                    (next_key ? *next_key : std::string()) +
                                    "\"");
        }
        keys.push_back(nxt);
        low = nxt;
    }
    for (std::size_t i = 0; i < pending.size(); ++i) {
        out[pending[i]] = keys[i];
    }
}

}  // namespace

bool valid_key(std::string_view key) {
    for (const char ch : key) {
        if (digit_of(ch) < 0) return false;
    }
    return true;
}

std::string key_for_index(long long index) {
    if (index < 0) {
        throw std::invalid_argument("index must be >= 0");
    }
    long long value = index + 2;
    std::string digits(kOrderIndexWidth, 'a');
    int pos = kOrderIndexWidth - 1;
    while (value > 0 && pos >= 0) {
        const int rem = static_cast<int>(value % 26);
        digits[static_cast<std::size_t>(pos)] = kAlphabet[rem];
        value /= 26;
        --pos;
    }
    if (value > 0) {
        throw std::invalid_argument("index " + std::to_string(index) +
                                    " overflows key width " +
                                    std::to_string(kOrderIndexWidth));
    }
    return digits;
}

std::vector<std::string> key_sequence(std::size_t count) {
    std::vector<std::string> out;
    out.reserve(count);
    for (std::size_t i = 0; i < count; ++i) {
        out.push_back(key_for_index(static_cast<long long>(i)));
    }
    return out;
}

std::string key_between(const std::string& a, const std::string& b) {
    if (a.empty() || b.empty() || !(a < b)) {
        throw std::invalid_argument(
            "key_between requires non-empty a < b (got \"" + a + "\", \"" +
            b + "\")");
    }
    const std::string candidate = a + "b";
    if (candidate < b) return candidate;
    // a is a prefix of b and rest <= "b" head: descend inside rest.
    const std::size_t prefix = common_prefix_len(a, b);
    return a + str_below(b.substr(prefix));
}

std::string key_after(const std::string& a) {
    if (a.empty()) return key_for_index(0);
    return a + "b";
}

std::string key_before(const std::string& b) {
    if (b.empty()) {
        throw std::invalid_argument("key_before requires a non-empty upper bound");
    }
    return str_below(b);
}

std::vector<std::size_t> longest_increasing_indices(
    const std::vector<std::string>& keys) {
    std::vector<std::string> tails;
    std::vector<std::size_t> tails_pos;
    std::vector<std::int64_t> prev(static_cast<std::size_t>(keys.size()), -1);
    for (std::size_t idx = 0; idx < keys.size(); ++idx) {
        const std::string& key = keys[idx];
        auto pos_it = std::lower_bound(tails.begin(), tails.end(), key);
        const std::size_t pos =
            static_cast<std::size_t>(pos_it - tails.begin());
        if (pos == tails.size()) {
            tails.push_back(key);
            tails_pos.push_back(idx);
        } else {
            tails[pos] = key;
            tails_pos[pos] = idx;
        }
        prev[idx] = pos > 0 ? static_cast<std::int64_t>(tails_pos[pos - 1]) : -1;
    }
    std::vector<std::size_t> keep;
    std::int64_t node =
        tails_pos.empty() ? -1
                          : static_cast<std::int64_t>(tails_pos.back());
    while (node >= 0) {
        keep.push_back(static_cast<std::size_t>(node));
        node = prev[static_cast<std::size_t>(node)];
    }
    std::sort(keep.begin(), keep.end());
    return keep;
}

std::map<std::string, std::string> assign_keys_for_order(
    const std::vector<std::string>& ordered_ids,
    const std::map<std::string, std::string>* existing) {
    if (ordered_ids.empty()) return {};
    std::map<std::string, std::string> clean;
    if (existing != nullptr) {
        for (const auto& [node_id, key] : *existing) {
            if (!key.empty()) clean.emplace(node_id, key);
        }
    }
    bool any_present = false;
    for (const auto& node_id : ordered_ids) {
        auto it = clean.find(node_id);
        if (it != clean.end()) {
            any_present = true;
            break;
        }
    }
    if (!any_present) {
        // Brand-new container: fixed-width default keys (O(1) key length
        // instead of a linearly growing midpoint chain).
        return rebalanced_keys(ordered_ids);
    }
    std::vector<std::string> present;
    present.reserve(ordered_ids.size());
    for (const auto& node_id : ordered_ids) {
        auto it = clean.find(node_id);
        present.push_back(it == clean.end() ? std::string() : it->second);
    }
    std::vector<std::size_t> keyed_positions;
    for (std::size_t j = 0; j < present.size(); ++j) {
        if (!present[j].empty()) keyed_positions.push_back(j);
    }
    std::vector<std::string> keyed_keys;
    keyed_keys.reserve(keyed_positions.size());
    for (const std::size_t j : keyed_positions) keyed_keys.push_back(present[j]);
    const std::vector<std::size_t> keep =
        keyed_positions.empty() ? std::vector<std::size_t>{}
                                : longest_increasing_indices(keyed_keys);
    std::vector<bool> keep_flag(ordered_ids.size(), false);
    for (const std::size_t j : keep) {
        keep_flag[keyed_positions[j]] = true;
    }
    std::map<std::string, std::string> out;
    try {
        std::string prev_key;  // empty = none yet
        std::vector<std::string> pending;
        for (std::size_t i = 0; i < ordered_ids.size(); ++i) {
            const std::string& node_id = ordered_ids[i];
            const std::string& key = present[i];
            if (!key.empty() && keep_flag[i]) {
                const std::string* next_key_ptr = key.empty() ? nullptr : &key;
                flush_pending(pending, out,
                              prev_key.empty() ? nullptr : &prev_key,
                              next_key_ptr);
                pending.clear();
                out[node_id] = key;
                prev_key = key;
            } else {
                pending.push_back(node_id);
            }
        }
        flush_pending(pending, out, prev_key.empty() ? nullptr : &prev_key,
                      nullptr);
    } catch (const KeySpaceExhausted&) {
        return rebalanced_keys(ordered_ids);
    }
    if (key_needs_rebalance(out)) {
        return rebalanced_keys(ordered_ids);
    }
    return out;
}

bool key_needs_rebalance(const std::vector<std::string>& keys) {
    for (const auto& key : keys) {
        if (static_cast<int>(key.size()) > kOrderRebalanceLength) return true;
    }
    return false;
}

bool key_needs_rebalance(const std::map<std::string, std::string>& keys) {
    for (const auto& entry : keys) {
        if (static_cast<int>(entry.second.size()) > kOrderRebalanceLength) {
            return true;
        }
    }
    return false;
}

std::map<std::string, std::string> rebalanced_keys(
    const std::vector<std::string>& ordered_ids) {
    std::map<std::string, std::string> out;
    const std::vector<std::string> keys = key_sequence(ordered_ids.size());
    for (std::size_t i = 0; i < ordered_ids.size(); ++i) {
        out[ordered_ids[i]] = keys[i];
    }
    return out;
}

// ---------------------------------------------------------------------------
// Role bands
// ---------------------------------------------------------------------------

const std::map<std::string, int>& role_bands() {
    static const std::map<std::string, int> bands = {
        // 020 selection/topology/QC overlays
        {"qc_warning", 20},
        {"qc_conflict", 21},
        // 030 map annotation
        {"map_annotation", 30},
        // 040 cartographic features
        {"map_symbol", 40},
        {"map_reference", 41},
        // 050 integrated interpretation
        {"integrated_facies", 50},
        {"integrated_boundary", 51},
        // 060 geological boundaries/symbols
        {"facies_boundary", 60},
        {"fault_constraint", 61},
        // 070 manual interpretation
        {"initial_facies_draft", 70},
        {"interpretation_annotation", 71},
        {"pending_review_area", 79},
        // 080 constraint lines
        {"provenance_direction", 80},
        {"provenance_line", 81},
        {"distribution_line", 82},
        {"paleo_shoreline", 83},
        {"interpolation_boundary", 84},
        {"mask_boundary", 85},
        // 090-100 factor pipeline order (render stack = pipeline downstream
        // on top, same order as FACTOR_CHILD_ORDER)
        {"factor_input", 90},
        {"factor_grid", 92},
        {"factor_contour", 94},
        {"factor_classification", 96},
        {"factor_uncertainty", 98},
        {"factor_qc", 100},
        // 120 prediction layers
        {"well_facies_prediction", 120},
        {"well_facies_confidence", 122},
        {"seismic_facies_prediction", 124},
        {"seismic_facies_confidence", 126},
        // 130 initial facies
        {"initial_facies_source", 130},
        // 140 well/seismic footprint & analysis aids
        {"analysis_aid", 140},
        // 150 reference/basemap
        {"base_reference", 150},
        {"user_general", 155},
        {"legacy_unclassified", 158},
    };
    return bands;
}

int role_band(std::string_view role) {
    const auto& bands = role_bands();
    const auto it = bands.find(std::string(role));
    // Unknown role -> reference band; never throws.
    return it == bands.end() ? 150 : it->second;
}

int factor_role_rank(std::string_view role) {
    static const std::map<std::string, int> ranks = {
        {"factor_input", 0},        {"factor_grid", 1},
        {"factor_contour", 2},      {"factor_classification", 3},
        {"factor_uncertainty", 4},  {"factor_qc", 5},
    };
    const auto it = ranks.find(std::string(role));
    return it == ranks.end() ? 99 : it->second;  // unknown -> tail
}

BandSortKey band_sort_key(std::string_view role, long long sub_order,
                          std::string node_id) {
    return BandSortKey(role_band(role), sub_order, std::move(node_id));
}

}  // namespace pwb::workspace
