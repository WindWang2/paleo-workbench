// SQL-level paged asset reads over the canonical catalog.sqlite (conv-26;
// db.py _search_assets_page / _count_assets parity). The paging SELECT
// deliberately joins nothing by default — a join defeats the assets-index
// order for name/type/modified — and version-dependent keys get a targeted
// LEFT JOIN, exactly like Python. Current-version columns are batch-fetched
// for the page's rows afterwards (100-id IN chunks over the versions PK).
//
// Rows come back in the service-level `asset_page_row` shape (entity_view.hpp
// pins the 20-key contract), so the SQL path and the document path agree
// key-for-key on identical data — the oracle replays and the cross-path test
// both rely on that agreement. Serves deep pages without materializing the
// full CatalogDocument (the v6 lazy-browse contract).
#pragma once

#include "pwb/catalog/entity_view.hpp"
#include "pwb/catalog/sqlite.hpp"

#include <cstdint>
#include <vector>

namespace pwb::catalog {

// One deterministic page of assets joined with the current version, read
// straight from the store. `db` must be open (read-only is fine) against a
// v5 store; a store missing the assets table yields an empty page, matching
// the Python `_safe` degradation.
std::vector<domain::Json> search_assets_page_sql(Database& db,
                                                  const EntityPageQuery& query);

// Count of assets matching the paged-path predicates (index-backed, no
// version join — stage goes through the IN-subquery like `_count_assets`).
std::int64_t count_assets_sql(Database& db, const EntityPageQuery& query);

}  // namespace pwb::catalog
