// UI-08 — paleo_workbench/mapping/feature_query_index.py port: the
// persistent host-owned spatial candidate index for map-edit hit testing.
//
// Items are serialized only on load or on a feature-level create/delete/
// geometry edit (record_for_item runs at index time — pointer queries never
// call to_record() on every item). Visibility stays a query-time predicate
// so toggling a layer cannot expose stale hidden geometry. Top-most result
// is later insertion order (descending ``order``), matching Qt item
// stacking and the unified canvas.
//
// C++ shape: Python's duck-typed ``item`` (``item.feature_id`` /
// ``item.kind`` / ``record_for_item(item)``) materializes into
// IndexedItem{feature_id, kind, record} at the call site — the index only
// ever needed those three fields (the Python getattr fallbacks read the
// same values). Qt-free; records are domain::Json dicts.
#pragma once

#include "pwb/domain/json.hpp"

#include <array>
#include <functional>
#include <map>
#include <set>
#include <string>
#include <string_view>
#include <vector>

namespace pwb::ui_pages_mapedit {

// extent_of_coordinates equivalent over arbitrarily nested GeoJSON
// coordinates; also serves _record_bounds. Nullopt when no positions.
using Bounds = std::array<double, 4>;  // (xmin, ymin, xmax, ymax)

// One materialized index input — (item.feature_id, item.kind,
// record_for_item(item)) in Python terms.
struct IndexedItem {
    std::string feature_id;
    std::string kind;
    domain::Json record;
};

// bbox_intersects (geometry_operations.py): closed-interval AABB overlap.
bool bounds_intersect(const Bounds& a, const Bounds& b, double tolerance = 0.0);

// extent_of_coordinates over arbitrarily nested coordinates Json.
std::optional<Bounds> extent_of_coordinates(const domain::Json& coordinates);

// _record_bounds: geometry.coordinates → coordinates → (0,0,0,0) sentinel.
Bounds record_bounds(const domain::Json& record);

class FeatureQueryIndex {
public:
    static constexpr int kMaxCellsPerEntry = 256;
    static constexpr int kMaxQueryCells = 4096;

    void clear();

    void rebuild(const std::vector<IndexedItem>& items);
    void upsert(const IndexedItem& item);
    void remove(std::string_view feature_id);

    // Records of candidate entries in descending insertion order, filtered
    // by bounds + the query-time ``visible`` predicate on kind.
    std::vector<domain::Json> query(
        double x, double y, double tolerance,
        const std::function<bool(std::string_view)>& visible);

    std::map<std::string, int> diagnostics() const;

private:
    struct Entry {
        std::string feature_id;
        std::string kind;
        domain::Json record;
        Bounds bounds{0.0, 0.0, 0.0, 0.0};
        long long order = 0;
        std::vector<std::pair<long long, long long>> cells;
        bool overflow = false;
    };

    using CellRange = std::array<long long, 4>;

    void insert(const IndexedItem& item, bool preserve_order);
    CellRange cell_range(const Bounds& bounds) const;
    static long long cell_count(const CellRange& range);

    std::map<std::string, Entry> entries_;
    std::map<std::pair<long long, long long>, std::set<std::string>> cells_;
    std::set<std::string> overflow_;
    double cell_size_ = 1.0;
    long long next_order_ = 0;
    int query_count_ = 0;
    int candidate_count_ = 0;
    int record_build_count_ = 0;
    int rebuild_count_ = 0;
};

}  // namespace pwb::ui_pages_mapedit
