// Entity list pagination over the catalog document (conv-15). Pins the
// Python paged-query contract: service.py `_paged_rows_from_document` /
// `_asset_page_row` + db.py `_paged_predicates` / `_PAGE_ORDER_COLUMNS` —
// 20-key rows, stable sort keys (always id-tailed, ASC NULLs first for the
// current-version columns), name keyset cursor, clamped limit/offset.
//
// Text/tag normalization is the bounded fold declared on the C++ write path
// (search_fold in repository.cpp): ASCII case folding, non-ASCII verbatim —
// identical to Python for caseless scripts (CJK) and for ASCII names; a full
// NFKC port is not carried (see 15-decisions.md D6).
#pragma once

#include "pwb/catalog/models.hpp"
#include "pwb/domain/json.hpp"

#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace pwb::catalog {

// Python normalize_asset_search_name parity (bounded): ASCII case fold,
// non-ASCII verbatim, WHITESPACE PRESERVED (db.py:287 — the collapse lives
// only in normalize_tag_name).
std::string normalize_search_name(std::string_view name);

// Python normalize_tag_name parity (bounded): ASCII case fold + whitespace
// collapse, non-ASCII verbatim (models.py:272).
std::string normalize_tag_name(std::string_view name);

struct EntityPageQuery {
    std::string text;                       // "" = no filter
    std::optional<std::string> stage;       // lowercase stage value
    std::vector<std::string> tags;          // normalized before matching
    std::string tag_op = "and";             // "and" | "or"
    std::optional<std::string> type;        // nullopt = no filter
    std::string asset_id;                   // "" = no filter
    std::vector<std::string> asset_ids;     // empty = no filter; a non-empty
                                            // set filters to exact membership
    bool include_trashed = false;
    bool trashed_only = false;
    std::string order_by;                   // "" | name|name_desc|type|stage|
                                            // size|modified|version; unknown → name
    std::int64_t limit = 500;
    std::int64_t offset = 0;
    // Keyset cursor (name, id); honored only for the name order.
    std::optional<std::pair<std::string, std::string>> after;
};

// One paged-shape row: the 20 keys of Python `_asset_page_row` (asset columns
// plus current_* facts), `metadata` as a JSON TEXT field (compact dump — the
// Python row text uses json.dumps spacing; parity is compared semantically).
domain::Json asset_page_row(const DataAsset& asset, const DataVersion* current);

// Deterministic page + matching count (filters without order/paging).
std::vector<domain::Json> search_assets_page(const CatalogDocument& document,
                                             const EntityPageQuery& query);
std::int64_t count_assets(const CatalogDocument& document,
                          const EntityPageQuery& query);

}  // namespace pwb::catalog
