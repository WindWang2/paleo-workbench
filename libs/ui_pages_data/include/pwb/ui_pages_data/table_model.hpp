// UI-06 — asset table query helpers (data_asset_table.py) +
// resource table status token (resource_table.py).
#pragma once

#include <optional>
#include <string>
#include <utility>
#include <vector>

#include <pwb/ui_pages_data/filter_query.hpp>
#include <pwb/ui_pages_data/vocab.hpp>

namespace pwb::ui_pages_data {

// resource_table._status_token: parsed→SUCCESS, error→ERROR_RED, else
// TEXT_SECONDARY (a token NAME — the Qt shell resolves it via style).
std::string_view status_color_token(std::string_view status);

// data_asset_table.set_visible_columns: requested keys re-ordered to
// COLUMN_DEFINITIONS order with required columns always present;
// empty result → ["name"].
std::vector<std::string>
ordered_column_keys(const std::vector<std::string>& requested);

// data_asset_table._asset_key: ("artifact"|"resource", id).
// Asset-kind discriminator is explicit here (Python used isinstance).
enum class RowKind { Resource, Artifact };
inline std::pair<std::string, std::string>
asset_key(RowKind kind, const std::string& id) {
    return {kind == RowKind::Artifact ? "artifact" : "resource", id};
}

// data_asset_table.set_search_text / apply_saved_filter normalization:
// strip().lower() — Unicode-aware for the CJK case (ASCII-only lowercasing
// is exact: Python .lower() only differs on non-ASCII; tag/search text here
// is effectively ASCII+CJK, and CJK has no case).
std::string normalize_search_text(const std::string& text);

}  // namespace pwb::ui_pages_data
