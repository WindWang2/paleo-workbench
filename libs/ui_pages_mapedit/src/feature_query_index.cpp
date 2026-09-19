#include "pwb/ui_pages_mapedit/feature_query_index.hpp"

#include "pwb/ui_data_core/json_util.hpp"
#include "pwb/ui_data_core/map_edit_geometry.hpp"

#include <algorithm>
#include <cmath>
#include <limits>

namespace pwb::ui_pages_mapedit {
namespace {

using ui_data_core::MapPoint;

// _point(value) → (x, y) for a 2-element numeric pair; skips non-finite.
std::optional<MapPoint> point_of(const domain::Json& value) {
    if (!value.is_array() || value.size() < 2) {
        return std::nullopt;
    }
    const auto x = ui_data_core::json_float(value[0]);
    const auto y = ui_data_core::json_float(value[1]);
    if (!x || !y || !std::isfinite(*x) || !std::isfinite(*y)) {
        return std::nullopt;
    }
    return MapPoint{*x, *y};
}

// _points(value): yield positions from arbitrarily nested coordinates.
void collect_points(const domain::Json& value, std::vector<MapPoint>& out) {
    if (const auto point = point_of(value)) {
        out.push_back(*point);
        return;
    }
    if (value.is_array()) {
        for (const auto& child : value) {
            collect_points(child, out);
        }
    }
}

void iter_cells(const std::array<long long, 4>& range,
                const std::function<void(long long, long long)>& fn) {
    for (long long cx = range[0]; cx <= range[2]; ++cx) {
        for (long long cy = range[1]; cy <= range[3]; ++cy) {
            fn(cx, cy);
        }
    }
}

}  // namespace

bool bounds_intersect(const Bounds& a, const Bounds& b, double tolerance) {
    const double tol = std::max(0.0, tolerance);
    return !(a[2] < b[0] - tol || b[2] < a[0] - tol || a[3] < b[1] - tol ||
             b[3] < a[1] - tol);
}

std::optional<Bounds> extent_of_coordinates(const domain::Json& coordinates) {
    std::vector<MapPoint> points;
    collect_points(coordinates, points);
    if (points.empty()) {
        return std::nullopt;
    }
    Bounds b{std::numeric_limits<double>::infinity(),
             std::numeric_limits<double>::infinity(),
             -std::numeric_limits<double>::infinity(),
             -std::numeric_limits<double>::infinity()};
    for (const auto& p : points) {
        b[0] = std::min(b[0], p[0]);
        b[1] = std::min(b[1], p[1]);
        b[2] = std::max(b[2], p[0]);
        b[3] = std::max(b[3], p[1]);
    }
    return b;
}

Bounds record_bounds(const domain::Json& record) {
    const domain::Json* coordinates = nullptr;
    const auto geom_it = record.find("geometry");
    if (geom_it != record.end() && geom_it->is_object()) {
        const auto coords_it = geom_it->find("coordinates");
        if (coords_it != geom_it->end()) {
            coordinates = &*coords_it;
        }
    }
    if (coordinates == nullptr) {
        const auto it = record.find("coordinates");
        if (it != record.end()) {
            coordinates = &*it;
        }
    }
    if (coordinates == nullptr) {
        return Bounds{0.0, 0.0, 0.0, 0.0};
    }
    const auto extent = extent_of_coordinates(*coordinates);
    return extent ? *extent : Bounds{0.0, 0.0, 0.0, 0.0};
}

void FeatureQueryIndex::clear() {
    entries_.clear();
    cells_.clear();
    overflow_.clear();
    next_order_ = 0;
}

void FeatureQueryIndex::rebuild(const std::vector<IndexedItem>& items) {
    clear();
    if (!items.empty()) {
        double xmin = std::numeric_limits<double>::infinity();
        double ymin = std::numeric_limits<double>::infinity();
        double xmax = -std::numeric_limits<double>::infinity();
        double ymax = -std::numeric_limits<double>::infinity();
        for (const auto& item : items) {
            const Bounds b = record_bounds(item.record);
            xmin = std::min(xmin, b[0]);
            ymin = std::min(ymin, b[1]);
            xmax = std::max(xmax, b[2]);
            ymax = std::max(ymax, b[3]);
        }
        const double span = std::max(xmax - xmin, ymax - ymin);
        cell_size_ = std::max(span / 64.0, 1e-9);
    } else {
        cell_size_ = 1.0;
    }
    for (const auto& item : items) {
        insert(item, /*preserve_order=*/false);
    }
    record_build_count_ += static_cast<int>(items.size());
    ++rebuild_count_;
}

void FeatureQueryIndex::upsert(const IndexedItem& item) {
    insert(item, /*preserve_order=*/true);
    ++record_build_count_;
}

void FeatureQueryIndex::remove(std::string_view feature_id) {
    const auto it = entries_.find(std::string(feature_id));
    if (it == entries_.end()) {
        return;
    }
    const Entry entry = std::move(it->second);
    entries_.erase(it);
    overflow_.erase(entry.feature_id);
    for (const auto& cell : entry.cells) {
        const auto bucket = cells_.find(cell);
        if (bucket == cells_.end()) {
            continue;
        }
        bucket->second.erase(entry.feature_id);
        if (bucket->second.empty()) {
            cells_.erase(bucket);
        }
    }
}

std::vector<domain::Json> FeatureQueryIndex::query(
    double x, double y, double tolerance,
    const std::function<bool(std::string_view)>& visible) {
    const double tol = std::max(0.0, tolerance);
    const Bounds bounds{x - tol, y - tol, x + tol, y + tol};
    std::set<std::string> ids = overflow_;
    const CellRange range = cell_range(bounds);
    if (cell_count(range) > kMaxQueryCells) {
        for (const auto& [id, _entry] : entries_) {
            ids.insert(id);
        }
    } else {
        iter_cells(range, [&](long long cx, long long cy) {
            const auto it = cells_.find({cx, cy});
            if (it != cells_.end()) {
                ids.insert(it->second.begin(), it->second.end());
            }
        });
    }
    std::vector<const Entry*> candidates;
    for (const auto& id : ids) {
        const auto it = entries_.find(id);
        if (it == entries_.end()) {
            continue;
        }
        const Entry& entry = it->second;
        if (visible(entry.kind) && bounds_intersect(entry.bounds, bounds)) {
            candidates.push_back(&entry);
        }
    }
    // Descending insertion order: the top-most (later-added) feature is
    // returned first, matching Qt item stacking and the unified canvas.
    std::sort(candidates.begin(), candidates.end(),
              [](const Entry* a, const Entry* b) { return a->order > b->order; });
    ++query_count_;
    candidate_count_ += static_cast<int>(candidates.size());
    std::vector<domain::Json> out;
    out.reserve(candidates.size());
    for (const Entry* entry : candidates) {
        out.push_back(entry->record);
    }
    return out;
}

std::map<std::string, int> FeatureQueryIndex::diagnostics() const {
    return {
        {"entries", static_cast<int>(entries_.size())},
        {"cells", static_cast<int>(cells_.size())},
        {"query_count", query_count_},
        {"candidate_count", candidate_count_},
        {"record_build_count", record_build_count_},
        {"rebuild_count", rebuild_count_},
    };
}

void FeatureQueryIndex::insert(const IndexedItem& item, bool preserve_order) {
    // str(getattr(item, "feature_id", record.get("id") or "")): an empty
    // item field maps to the getattr-default — record id resolved with
    // ``or ""`` truthiness (falsy id → "", not "0").
    std::string feature_id = item.feature_id;
    if (feature_id.empty() && item.record.is_object()) {
        const auto it = item.record.find("id");
        if (it != item.record.end() && ui_data_core::json_truthy(*it)) {
            feature_id = ui_data_core::python_str(*it);
        }
    }
    if (feature_id.empty()) {
        return;
    }
    const auto prev_it = entries_.find(feature_id);
    const std::optional<long long> previous_order =
        prev_it != entries_.end()
            ? std::optional<long long>(prev_it->second.order)
            : std::nullopt;
    remove(feature_id);
    const Bounds bounds = record_bounds(item.record);
    const CellRange range = cell_range(bounds);
    const bool overflow = cell_count(range) > kMaxCellsPerEntry;
    Entry entry;
    entry.feature_id = feature_id;
    // str(getattr(item, "kind", record.get("kind") or "")) — same
    // getattr-default + or-truthiness mapping as feature_id.
    entry.kind = item.kind;
    if (entry.kind.empty() && item.record.is_object()) {
        const auto kit = item.record.find("kind");
        if (kit != item.record.end() && ui_data_core::json_truthy(*kit)) {
            entry.kind = ui_data_core::python_str(*kit);
        }
    }
    entry.record = item.record;
    entry.bounds = bounds;
    entry.overflow = overflow;
    if (preserve_order && previous_order) {
        entry.order = *previous_order;
    } else {
        entry.order = next_order_++;
    }
    if (overflow) {
        overflow_.insert(feature_id);
    } else {
        iter_cells(range, [&](long long cx, long long cy) {
            entry.cells.push_back({cx, cy});
            cells_[{cx, cy}].insert(feature_id);
        });
    }
    entries_[feature_id] = std::move(entry);
}

FeatureQueryIndex::CellRange FeatureQueryIndex::cell_range(
    const Bounds& bounds) const {
    return CellRange{
        static_cast<long long>(std::floor(bounds[0] / cell_size_)),
        static_cast<long long>(std::floor(bounds[1] / cell_size_)),
        static_cast<long long>(std::floor(bounds[2] / cell_size_)),
        static_cast<long long>(std::floor(bounds[3] / cell_size_)),
    };
}

long long FeatureQueryIndex::cell_count(const CellRange& range) {
    return (range[2] - range[0] + 1) * (range[3] - range[1] + 1);
}

}  // namespace pwb::ui_pages_mapedit
