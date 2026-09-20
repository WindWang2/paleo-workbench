#include <pwb/mapping_document/render_snapshot.hpp>

#include "python_compat.hpp"

#include <pwb/domain/sha256.hpp>
#include <pwb/mapping_document/document_io.hpp>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include <list>
#include <map>
#include <memory>
#include <string>
#include <utility>
#include <vector>

namespace pwb::mapping_document {

namespace {

constexpr const char* kLayerKinds[] = {"facies", "well", "line", "label"};

const char* layer_name_for(const std::string& kind) {
    if (kind == "facies") return "Facies";
    if (kind == "well") return "Wells";
    if (kind == "line") return "Lines";
    return "Labels";
}

// Python: float(coordinates[0]), float(coordinates[1]) inside try/except —
// bools count as 0/1, numeric strings parse, anything else raises → skip.
bool is_finite_pair(const Json& value, double& x, double& y) {
    if (!value.is_array() || value.size() < 2) return false;
    try {
        x = detail::py_float(value[0]);
        y = detail::py_float(value[1]);
    } catch (const std::exception&) {
        return false;
    }
    return std::isfinite(x) && std::isfinite(y);
}

// map_document_snapshot._geometry_from_record: kind → GeoJSON geometry, or
// null when the record cannot render for its kind.
Json geometry_from_record(const Json& record) {
    const auto kind_it = record.find("kind");
    const std::string kind =
        kind_it != record.end() && detail::py_truthy(*kind_it)
            ? detail::py_str(*kind_it)
            : std::string();
    if (kind == "facies") {
        const auto it = record.find("geometry");
        if (it != record.end() && it->is_object()) {
            const std::string type = it->value("type", "");
            if (type == "Polygon" || type == "MultiPolygon") {
                Json geometry = Json::object();
                geometry["type"] = type;
                const auto coords = it->find("coordinates");
                geometry["coordinates"] =
                    coords != it->end() && coords->is_array() ? *coords
                                                              : Json::array();
                return geometry;
            }
        }
        return Json();
    }
    if (kind == "well" || kind == "label") {
        double x = 0.0;
        double y = 0.0;
        const auto it = record.find("coordinates");
        if (it != record.end() && is_finite_pair(*it, x, y)) {
            Json geometry = Json::object();
            geometry["type"] = "Point";
            Json coords = Json::array();
            coords.push_back(x);
            coords.push_back(y);
            geometry["coordinates"] = std::move(coords);
            return geometry;
        }
        return Json();
    }
    if (kind == "line") {
        Json coords = Json::array();
        const auto it = record.find("coordinates");
        if (it != record.end() && it->is_array()) {
            for (const Json& point : *it) {
                double x = 0.0;
                double y = 0.0;
                if (is_finite_pair(point, x, y)) {
                    Json pair = Json::array();
                    pair.push_back(x);
                    pair.push_back(y);
                    coords.push_back(std::move(pair));
                }
            }
        }
        if (coords.size() >= 2) {
            Json geometry = Json::object();
            geometry["type"] = "LineString";
            geometry["coordinates"] = std::move(coords);
            return geometry;
        }
        return Json();
    }
    return Json();
}

// The record properties carried into a render feature: the record's
// properties payload plus the whitelisted top-level keys when present.
constexpr const char* kPropertyKeys[] = {"name", "facies", "text",
                                         "topology_status"};

Json properties_for_record(const Json& record) {
    Json properties = Json::object();
    const auto it = record.find("properties");
    if (it != record.end() && it->is_object()) properties = *it;
    for (const char* key : kPropertyKeys) {
        const auto top = record.find(key);
        if (top != record.end() && !top->is_null()) {
            properties[key] = *top;
        }
    }
    return properties;
}

Json feature_for_record(const Json& record, const Json& geometry) {
    Json feature = Json::object();
    const auto id_it = record.find("id");
    feature["id"] = id_it != record.end() && detail::py_truthy(*id_it)
                        ? detail::py_str(*id_it)
                        : std::string();
    feature["geometry"] = geometry;
    feature["properties"] = properties_for_record(record);
    return feature;
}

// ---------------------------------------------------------------------------
// Deterministic content revision (C++ contract — D-27d-07)
// ---------------------------------------------------------------------------

void hash_json(pwb::domain::Sha256& hash, const Json& value) {
    // Canonical frozen form: objects in key-sorted byte order, arrays in
    // order, scalars in payload text; the type tag prevents int/float and
    // string/number confusion across the digest.
    switch (value.type()) {
        case Json::value_t::object: {
            std::vector<std::string> keys;
            keys.reserve(value.size());
            for (auto it = value.begin(); it != value.end(); ++it) {
                keys.push_back(it.key());
            }
            std::sort(keys.begin(), keys.end());
            hash.update("O");
            for (const std::string& key : keys) {
                hash.update(key);
                hash.update("\x1f");
                hash_json(hash, value.at(key));
            }
            break;
        }
        case Json::value_t::array:
            hash.update("A");
            for (const Json& item : value) hash_json(hash, item);
            break;
        case Json::value_t::string:
            hash.update("S");
            hash.update(value.get<std::string>());
            break;
        case Json::value_t::number_integer:
        case Json::value_t::number_unsigned:
            hash.update("I");
            hash.update(value.dump());
            break;
        case Json::value_t::number_float:
            hash.update("F");
            hash.update(value.dump());
            break;
        case Json::value_t::boolean:
            hash.update(value.get<bool>() ? "T" : "N");
            break;
        default:
            hash.update("Z");  // null
            break;
    }
    hash.update("\x1e");
}

}  // namespace

long long stable_content_revision(const Json& value) {
    pwb::domain::Sha256 hash;
    hash_json(hash, value);
    // First 8 digest bytes, big-endian, into the positive long long range.
    const std::string hex = hash.hex_digest();
    std::uint64_t packed = 0;
    for (int i = 0; i < 16; ++i) {
        const char c = hex[static_cast<std::size_t>(i)];
        const int digit = c <= '9' ? c - '0' : (c | 0x20) - 'a' + 10;
        packed = (packed << 4) | static_cast<std::uint64_t>(digit & 0xF);
    }
    return static_cast<long long>(packed >> 1);
}

Extent positive_extent(const Extent& extent) {
    const double xmin = extent[0];
    const double ymin = extent[1];
    const double xmax = extent[2];
    const double ymax = extent[3];
    const double pad = std::max({1.0, std::abs(xmin), std::abs(ymin),
                                 std::abs(xmax), std::abs(ymax)}) *
                       1e-9;
    return {
        xmax > xmin ? xmin : xmin - pad, ymax > ymin ? ymin : ymin - pad,
        xmax > xmin ? xmax : xmax + pad, ymax > ymin ? ymax : ymax + pad,
    };
}

namespace {

struct Bucket {
    std::vector<Json> features;
    double bounds[4] = {std::numeric_limits<double>::infinity(),
                        std::numeric_limits<double>::infinity(),
                        -std::numeric_limits<double>::infinity(),
                        -std::numeric_limits<double>::infinity()};
    bool has_bounds = false;
};

void expand_bounds(Bucket& bucket, const Json& coordinates) {
    // Python shape: a 2-length numeric leaf is consumed as a point and the
    // walk RETURNS regardless of finiteness (a non-finite pair is discarded
    // without recursing); a non-numeric first pair falls through to the
    // child loop.
    if (coordinates.is_array() && coordinates.size() >= 2) {
        double x = 0.0;
        double y = 0.0;
        const bool converts = [&] {
            try {
                x = detail::py_float(coordinates[0]);
                y = detail::py_float(coordinates[1]);
                return true;
            } catch (const std::exception&) {
                return false;
            }
        }();
        if (converts) {
            if (std::isfinite(x) && std::isfinite(y)) {
                if (x < bucket.bounds[0]) bucket.bounds[0] = x;
                if (y < bucket.bounds[1]) bucket.bounds[1] = y;
                if (x > bucket.bounds[2]) bucket.bounds[2] = x;
                if (y > bucket.bounds[3]) bucket.bounds[3] = y;
                bucket.has_bounds = true;
            }
            return;
        }
    }
    if (!coordinates.is_array()) return;
    for (const Json& child : coordinates) {
        expand_bounds(bucket, child);
    }
}

// map_document_snapshot._grouped_features — one pass over the records,
// bucketing only the requested kinds, accumulating bounds inline.
void grouped_features(const Json& records, const std::vector<std::string>& needed,
                      std::map<std::string, Bucket>& buckets) {
    if (!records.is_array()) return;
    for (const Json& record : records) {
        if (!record.is_object()) continue;
        const std::string kind = record.value("kind", "");
        if (std::find(needed.begin(), needed.end(), kind) == needed.end()) {
            continue;
        }
        const Json geometry = geometry_from_record(record);
        if (geometry.is_null()) continue;
        Bucket& bucket = buckets[kind];
        bucket.features.push_back(feature_for_record(record, geometry));
        const auto coords = geometry.find("coordinates");
        if (coords != geometry.end()) expand_bounds(bucket, *coords);
    }
}

Extent extent_from_bounds(const Bucket& bucket) {
    if (!bucket.has_bounds) return Extent{0.0, 0.0, 1.0, 1.0};
    return positive_extent(
        {bucket.bounds[0], bucket.bounds[1], bucket.bounds[2], bucket.bounds[3]});
}

// map_document_snapshot._authoring_style — merge the persisted unified-canvas
// style without changing legacy geometry data.
Json authoring_style(const Json& document, const std::string& kind) {
    Json style = Json::object();
    const auto state = document.find("layer_state");
    if (state == document.end() || !state->is_object()) return style;
    const auto entries = state->find("vector_layers");
    if (entries == state->end() || !entries->is_array()) return style;
    for (const Json& entry : *entries) {
        if (!entry.is_object()) continue;
        const auto kind_it = entry.find("kind");
        const std::string entry_kind =
            kind_it != entry.end() && detail::py_truthy(*kind_it)
                ? detail::py_str(*kind_it)
                : std::string();
        if (entry_kind != kind) continue;
        const auto style_it = entry.find("style");
        if (style_it != entry.end() && style_it->is_object()) {
            for (auto member = style_it->begin(); member != style_it->end();
                 ++member) {
                style[member.key()] = member.value();
            }
        }
        const auto labels = entry.find("labels");
        if (labels != entry.end() && labels->is_object() && !labels->empty()) {
            style["labels"] = *labels;
        }
        return style;
    }
    return style;
}

// map_document_snapshot._FEATURE_CACHE: bounded owner-scoped LRU. Entries are
// identity-checked against the owning authoring object, so entries from a
// replaced owner can never leak into a new one.
constexpr std::size_t kFeatureCacheLimit = 24;

struct CacheKey {
    const void* owner;
    std::string document_id;
    std::string kind;
    long long revision;

    bool operator<(const CacheKey& other) const {
        if (owner != other.owner) return owner < other.owner;
        if (document_id != other.document_id) {
            return document_id < other.document_id;
        }
        if (kind != other.kind) return kind < other.kind;
        return revision < other.revision;
    }
};

struct CacheEntry {
    CacheKey key;
    const void* owner;
    std::vector<Json> features;
    Extent extent;
};

class FeatureCache {
public:
    const CacheEntry* find(const CacheKey& key) {
        auto it = index_.find(key);
        if (it == index_.end()) return nullptr;
        CacheEntry& entry = *it->second;
        if (entry.owner != key.owner) return nullptr;  // identity check
        order_.splice(order_.begin(), order_, it->second);  // move to front
        return &entry;
    }

    void store(const CacheKey& key, std::vector<Json> features, Extent extent) {
        auto it = index_.find(key);
        if (it != index_.end()) {
            order_.erase(it->second);
            index_.erase(it);
        }
        order_.emplace_front(
            CacheEntry{key, key.owner, std::move(features), extent});
        index_[key] = order_.begin();
        while (order_.size() > kFeatureCacheLimit) {
            index_.erase(order_.back().key);
            order_.pop_back();
        }
    }

private:
    std::list<CacheEntry> order_;  // front = most recently used
    std::map<CacheKey, std::list<CacheEntry>::iterator> index_;
};

FeatureCache& feature_cache() {
    static FeatureCache cache;
    return cache;
}

}  // namespace

RenderSnapshot document_render_snapshot(
    const Json& paleo_doc, const RenderSnapshotOptions& options,
    const StyleDefaultProvider& default_style_for) {
    RenderSnapshot snapshot;
    snapshot.project_crs = options.project_crs;
    if (paleo_doc.is_null()) {
        // Python: document None → MapRenderSnapshot(project_crs=...) — no layers.
        return snapshot;
    }
    const Json empty_document = Json::object();
    const Json& document = paleo_doc.is_object() ? paleo_doc : empty_document;

    // Bridge the layer-id-keyed counters (#461 API): strip the
    // "<document_id>:" prefix down to the compatibility kind.
    // Python: str(getattr(document, "id", "map") or "map") — falsy/absent →
    // "map"; non-string ids cannot occur in the persisted model, but stay
    // defensive rather than throwing on value().
    std::string document_id = "map";
    if (document.contains("id")) {
        const Json& id = document["id"];
        if (id.is_string() && !id.get<std::string>().empty()) {
            document_id = id.get<std::string>();
        }
    }
    std::map<std::string, long long> revisions = options.data_revisions;
    if (revisions.empty() && !options.layer_revisions.empty()) {
        const std::string prefix = document_id + ":";
        for (const auto& [key, value] : options.layer_revisions) {
            if (key.rfind(prefix, 0) == 0) {
                revisions[key.substr(prefix.size())] = value;
            }
        }
    }
    const bool use_cache = options.cache_owner != nullptr && !revisions.empty();

    // Source records: the unsaved scene override, else the document import —
    // resolved LAZILY on the first bucket that actually needs a walk (the
    // Python grouped_features closure): an all-caches-hit refresh must not
    // re-import the document (#941/#461).
    std::map<std::string, Bucket> buckets;
    std::map<std::string, std::vector<Json>> grouped;
    std::map<std::string, Extent> extents;
    Json source_records = Json();
    bool source_resolved = false;
    auto resolve_source = [&]() {
        if (source_resolved) return;
        source_resolved = true;
        if (options.records.has_value()) {
            source_records = *options.records;
        } else {
            DocumentIoDiagnostics diagnostics;
            FeatureIdGenerator ids;
            source_records = features_from_document(document, &diagnostics, ids);
        }
    };
    auto ensure_group = [&](const std::string& kind) {
        if (grouped.count(kind) != 0) return;
        resolve_source();
        std::vector<std::string> needed{kind};
        grouped_features(source_records, needed, buckets);
        Bucket& bucket = buckets[kind];
        grouped[kind] = bucket.features;
        extents[kind] = extent_from_bounds(bucket);
    };

    // facies style = registry default ⊕ document.facies_style.
    Json facies_style =
        default_style_for ? default_style_for("facies") : Json::object();
    if (!facies_style.is_object()) facies_style = Json::object();
    const auto doc_facies = document.find("facies_style");
    if (doc_facies != document.end() && doc_facies->is_object()) {
        for (auto member = doc_facies->begin(); member != doc_facies->end();
             ++member) {
            facies_style[member.key()] = member.value();
        }
    }

    for (const std::string& kind : kLayerKinds) {
        const std::string layer_id = document_id + ":" + kind;
        const RenderLayerSnapshot* previous = nullptr;
        if (options.previous_layers != nullptr) {
            for (const RenderLayerSnapshot& layer : options.previous_layers->layers) {
                if (layer.id == layer_id) {
                    previous = &layer;
                    break;
                }
            }
        }
        long long revision = 0;
        bool has_revision = false;
        {
            auto it = revisions.find(kind);
            if (it != revisions.end()) {
                revision = it->second;
                has_revision = true;
            } else {
                auto alias = options.layer_revisions.find(layer_id);
                if (alias != options.layer_revisions.end()) {
                    revision = alias->second;
                    has_revision = true;
                }
            }
        }

        std::vector<Json> features;
        Extent extent{0.0, 0.0, 1.0, 1.0};
        long long data_revision = 0;
        bool built = false;
        if (previous != nullptr && has_revision &&
            previous->data_revision == revision) {
            features = previous->features;
            extent = previous->extent;
            data_revision = revision;
            built = true;
        }
        if (!built) {
            std::optional<CacheKey> cache_key;
            if (use_cache && has_revision) {
                cache_key = CacheKey{options.cache_owner, document_id, kind,
                                     revision};
            }
            const CacheEntry* cached =
                cache_key ? feature_cache().find(*cache_key) : nullptr;
            if (cached != nullptr) {
                features = cached->features;
                extent = cached->extent;
                data_revision = revision;
            } else {
                ensure_group(kind);
                features = grouped[kind];
                extent = extents[kind];
                data_revision =
                    has_revision ? revision : stable_content_revision(features);
                if (cache_key) {
                    feature_cache().store(*cache_key, features, extent);
                }
            }
        }

        Json style = kind == "facies" ? facies_style
                                      : (default_style_for
                                             ? default_style_for(kind)
                                             : Json::object());
        if (!style.is_object()) style = Json::object();
        const Json merged_authoring = authoring_style(document, kind);
        for (auto member = merged_authoring.begin();
             member != merged_authoring.end(); ++member) {
            style[member.key()] = member.value();
        }

        RenderLayerSnapshot layer;
        layer.id = layer_id;
        layer.name = layer_name_for(kind);
        layer.layer_type = "vector";
        layer.extent = extent;
        layer.crs = options.project_crs;
        layer.data_revision = data_revision;
        layer.style_revision = stable_content_revision(style);
        layer.features = std::move(features);
        layer.style = std::move(style);
        auto visible = options.visibility.find(kind);
        layer.visible = visible == options.visibility.end() || visible->second;
        layer.opacity = 1.0;
        snapshot.layers.push_back(std::move(layer));
    }
    return snapshot;
}

Extent extent_for_snapshot(const RenderSnapshot& snapshot) {
    bool populated = false;
    double xmin = 0.0;
    double ymin = 0.0;
    double xmax = 0.0;
    double ymax = 0.0;
    for (const RenderLayerSnapshot& layer : snapshot.layers) {
        if (layer.features.empty()) continue;
        if (!populated) {
            xmin = layer.extent[0];
            ymin = layer.extent[1];
            xmax = layer.extent[2];
            ymax = layer.extent[3];
            populated = true;
            continue;
        }
        xmin = std::min(xmin, layer.extent[0]);
        ymin = std::min(ymin, layer.extent[1]);
        xmax = std::max(xmax, layer.extent[2]);
        ymax = std::max(ymax, layer.extent[3]);
    }
    if (!populated) return Extent{0.0, 0.0, 1.0, 1.0};
    return positive_extent({xmin, ymin, xmax, ymax});
}

}  // namespace pwb::mapping_document
