// UI-06 — filter chips model (filter_chips_bar.py) + the table's shared
// dimension-removal vocabulary (data_asset_table._remove_filter_dimension).
#pragma once

#include <optional>
#include <string>
#include <utility>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/ui_pages_data/filter_query.hpp>

namespace pwb::ui_pages_data {

// Chip dimension keys (filter_chips_bar._DIM_*).
inline constexpr std::string_view kDimView = "view";
inline constexpr std::string_view kDimText = "text";
inline constexpr std::string_view kDimStage = "stage";
inline constexpr std::string_view kDimType = "type";
inline constexpr std::string_view kDimTagPrefix = "tag:";   // "tag:<name>"
inline constexpr std::string_view kDimOperator = "tag_operator";

// (dimension key, label) pairs in Python's _dimensions order.
// Note: a query carrying asset_id produces a SECOND "view" chip
// ("资产: {id[:16]}…") — removing "view" clears node + asset together.
std::vector<std::pair<std::string, std::string>>
filter_dimensions(const FilterQuery& query);

// data_asset_table._remove_filter_dimension: returns the updated query, or
// nullopt when the key is unknown (Python: ``else: return`` keeps query).
// The `text` dimension additionally clears the caller's search text —
// callers mirror the signal emission themselves.
std::optional<FilterQuery> remove_filter_dimension(const FilterQuery& query,
                                                   const std::string& key);

// --- saved filters (QSettings JSON payload) -----------------------------------
// Stored shape: [{"name": str, "query": {field→value}}, ...]; ensure_ascii=False.
pwb::domain::Json filter_query_to_dict(const FilterQuery& query);
// #1391: nullopt when the stored dict is malformed (non-object or a field
// with a mismatched type) — Python's _apply_saved catches the constructor
// failure and warns; a silently-defaulted "all" query must not be applied.
std::optional<FilterQuery> filter_query_from_dict(
    const pwb::domain::Json& dict);

// Parse the stored JSON payload into {name → query-dict} preserving
// Python dict semantics: first-occurrence position kept, later duplicate
// names overwrite the value. Non-list payloads, parse failures and
// non-dict entries degrade to empty/skipped (Python returns {} on
// json.loads failure; malformed dict entries would KeyError upstream —
// the port skips them defensively instead, noted in the ledger).
std::vector<std::pair<std::string, pwb::domain::Json>>
saved_filters_load(const std::string& payload);
std::string saved_filters_dump(
    const std::vector<std::pair<std::string, pwb::domain::Json>>& filters);

// reload_saved's combo ordering: sorted(names, key=str.casefold).
// Full Unicode casefold via the generated table in Pwb::Domain (same
// Unicode data CPython uses).
std::vector<std::string> saved_filter_names_sorted(
    const std::vector<std::pair<std::string, pwb::domain::Json>>& filters);

}  // namespace pwb::ui_pages_data
