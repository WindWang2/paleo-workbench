#include "pwb/catalog/entity_view.hpp"

#include "pwb/catalog/document_index.hpp"

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <map>
#include <numeric>
#include <set>

namespace pwb::catalog {

using pwb::domain::Json;

namespace {

std::string fold_ascii(std::string_view text) {
    std::string folded;
    folded.reserve(text.size());
    for (const char c : text) {
        if (c >= 'A' && c <= 'Z') {
            folded.push_back(static_cast<char>(c - 'A' + 'a'));
        } else {
            folded.push_back(c);
        }
    }
    return folded;
}

// Python normalize_tag_name collapses whitespace first; applying the collapse
// after the fold yields the same string for the vocabularies in scope.
void collapse_spaces(std::string* text) {
    std::string out;
    out.reserve(text->size());
    bool pending_space = false;
    for (const char c : *text) {
        if (std::isspace(static_cast<unsigned char>(c)) != 0) {
            pending_space = !out.empty();
            continue;
        }
        if (pending_space) {
            out.push_back(' ');
            pending_space = false;
        }
        out.push_back(c);
    }
    *text = out;
}

std::string current_stage_value(const DataVersion* version) {
    return version != nullptr ? std::string(domain::to_string(version->stage))
                              : std::string();
}

// Line-14 perf: version lookups go through DocumentIndex (O(1) per asset).
// emplace keeps the FIRST entry on a duplicate id — the same first-match
// CatalogDocument::find_version's linear scan returns, so semantics hold.
const DataVersion* current_version_of(const DocumentIndex& index,
                                      const DataAsset& asset) {
    if (!asset.current_version_id.has_value()) return nullptr;
    return index.version(asset.current_version_id->str());
}

// The shared filter core of Python `_paged_fallback_rows` (db.py
// `_paged_predicates` semantics on document rows).
std::vector<const DataAsset*> filtered_assets(const CatalogDocument& document,
                                              const EntityPageQuery& query,
                                              const DocumentIndex& index) {
    std::set<std::string> wanted_tags;
    for (const std::string& tag : query.tags) {
        std::string normalized = normalize_tag_name(tag);
        if (!normalized.empty()) wanted_tags.insert(normalized);
    }
    const bool or_op = query.tag_op == "or";
    std::multimap<std::string, std::string> tags_of_asset;
    for (const auto& [asset_id, tag_id] : document.asset_tags) {
        tags_of_asset.emplace(asset_id, tag_id);
    }
    std::map<std::string, std::string> name_of_tag;
    for (const auto& tag : document.tags) {
        name_of_tag.emplace(tag.id, tag.name);
    }
    std::set<std::string> asset_id_set;
    for (const std::string& id : query.asset_ids) {
        asset_id_set.insert(id);
    }
    const std::string needle =
        query.text.empty() ? std::string() : normalize_search_name(query.text);

    std::vector<const DataAsset*> rows;
    for (const DataAsset& asset : document.assets) {
        if (query.trashed_only) {
            if (!asset.trashed) continue;
        } else if (!query.include_trashed && asset.trashed) {
            continue;
        }
        if (!query.asset_id.empty() && asset.id.str() != query.asset_id) {
            continue;
        }
        if (!asset_id_set.empty() && asset_id_set.count(asset.id.str()) == 0) {
            continue;
        }
        if (query.type.has_value() && asset.type != *query.type) {
            continue;
        }
        if (!wanted_tags.empty()) {
            std::set<std::string> owned;
            const auto range = tags_of_asset.equal_range(asset.id.str());
            for (auto it = range.first; it != range.second; ++it) {
                const auto name = name_of_tag.find(it->second);
                if (name != name_of_tag.end()) owned.insert(name->second);
            }
            if (or_op) {
                std::set<std::string> intersection;
                std::set_intersection(owned.begin(), owned.end(),
                                      wanted_tags.begin(), wanted_tags.end(),
                                      std::inserter(intersection,
                                                    intersection.begin()));
                if (intersection.empty()) continue;
            } else if (!std::includes(owned.begin(), owned.end(),
                                      wanted_tags.begin(), wanted_tags.end())) {
                continue;
            }
        }
        const DataVersion* version = current_version_of(index, asset);
        if (query.stage.has_value()) {
            if (version == nullptr ||
                current_stage_value(version) != *query.stage) {
                continue;
            }
        }
        if (!needle.empty()) {
            const std::string haystack = normalize_search_name(asset.name);
            if (haystack.find(needle) == std::string::npos) continue;
        }
        rows.push_back(&asset);
    }
    return rows;
}

// ASC NULLs first (catalog-scale-v5 Review 1 alignment): the null flag sorts
// before any value, so a missing current version leads its group.
enum class NullOrder { kFirst = 0, kValue = 1 };

}  // namespace

std::string normalize_search_name(std::string_view name) {
    return fold_ascii(name);
}

std::string normalize_tag_name(std::string_view name) {
    std::string folded = fold_ascii(name);
    collapse_spaces(&folded);
    return folded;
}

Json asset_page_row(const DataAsset& asset, const DataVersion* current) {
    Json row = Json::object();
    row["id"] = asset.id.str();
    row["name"] = asset.name;
    row["name_search"] = normalize_search_name(asset.name);
    row["type"] = asset.type;
    row["description"] = asset.description;
    row["current_version_id"] = asset.current_version_id.has_value()
        ? Json(asset.current_version_id->str())
        : Json(nullptr);
    row["legacy_resource_id"] = asset.legacy_resource_id.has_value()
        ? Json(*asset.legacy_resource_id)
        : Json(nullptr);
    // A NULL metadata column would serialize "null" in Python; unreachable
    // today (the model defaults to an object) but guarded honestly here.
    row["metadata"] = asset.metadata.is_null() ? std::string("{}")
                                               : asset.metadata.dump();
    row["created_at"] = asset.created_at;
    row["updated_at"] = asset.updated_at;
    row["trashed"] = asset.trashed ? 1 : 0;
    row["trashed_at"] = asset.trashed_at.has_value() ? Json(*asset.trashed_at)
                                                     : Json(nullptr);
    row["current_stage"] = current != nullptr
        ? Json(current_stage_value(current))
        : Json(nullptr);
    row["current_version_number"] = current != nullptr
        ? Json(static_cast<std::int64_t>(current->version_number))
        : Json(nullptr);
    row["current_size_bytes"] =
        current != nullptr && current->size_bytes.has_value()
            ? Json(*current->size_bytes)
            : Json(nullptr);
    row["current_sha256"] =
        current != nullptr && current->sha256.has_value()
            ? Json(*current->sha256)
            : Json(nullptr);
    row["current_managed"] = current != nullptr
        ? Json(current->managed ? 1 : 0)
        : Json(nullptr);
    row["current_format"] =
        current != nullptr ? Json(current->format) : Json(nullptr);
    row["current_path"] =
        current != nullptr ? Json(current->path) : Json(nullptr);
    row["current_created_at"] =
        current != nullptr ? Json(current->created_at) : Json(nullptr);
    return row;
}

std::vector<Json> search_assets_page(const CatalogDocument& document,
                                     const EntityPageQuery& query) {
    // Line-14 perf (measured at 100k assets): the previous shape did two
    // linear find_version scans per asset (O(N^2), ~4 min/call), built a
    // full 20-key Json row for every match (~52M heap allocs), and ran the
    // sort comparator on per-comparison JSON member lookups. Now the
    // DocumentIndex is built once (O(N), first-match parity), the sort runs
    // on per-entry keys extracted once, and asset_page_row materializes
    // only the returned slice.
    const DocumentIndex index(document);
    struct Entry {
        const DataAsset* asset;
        const DataVersion* version;
    };
    std::vector<Entry> entries;
    for (const DataAsset* asset : filtered_assets(document, query, index)) {
        entries.push_back({asset, current_version_of(index, *asset)});
    }

    const std::string& order =
        query.order_by.empty() ? std::string("name") : query.order_by;

    // One sort key per entry, extracted once. `text` carries the order's
    // string key (name/type/updated_at/stage value), `numeric` the
    // size/version_number key, `null_order` the per-column NULLs-first flag.
    // The (name, id) tail is the universal tiebreak — same ordering the
    // previous row["name"]/row["id"] JSON reads produced.
    struct Key {
        // `text` may view `owned` (stage keys): `keys` is sized once below
        // and only `ord` is permuted — never reallocate/move `keys` while
        // sorting, or stage keys dangle.
        std::string_view text;
        std::string owned;      // stage value is computed, not a field
        std::int64_t numeric = 0;
        NullOrder null_order = NullOrder::kValue;
        std::string_view name;
        std::string_view id;
    };
    std::vector<Key> keys(entries.size());
    for (std::size_t i = 0; i < entries.size(); ++i) {
        const Entry& e = entries[i];
        Key& k = keys[i];
        k.name = e.asset->name;
        k.id = e.asset->id.str();
        if (order == "type") {
            k.text = e.asset->type;
        } else if (order == "modified") {
            k.text = e.asset->updated_at;
        } else if (order == "stage" || order == "size"
                   || order == "version") {
            // NULLs-first is PER COLUMN (Python keys on the row value): a
            // present version with size_bytes NULL also leads the size
            // order.
            if (e.version == nullptr) {
                k.null_order = NullOrder::kFirst;
            } else if (order == "size" && !e.version->size_bytes.has_value()) {
                k.null_order = NullOrder::kFirst;
            }
            if (order == "stage") {
                k.owned = current_stage_value(e.version);
                k.text = k.owned;
            } else if (order == "size") {
                k.numeric = e.version != nullptr
                                && e.version->size_bytes.has_value()
                                ? *e.version->size_bytes
                                : 0;
            } else {
                k.numeric = e.version != nullptr
                                ? e.version->version_number
                                : 0;
            }
        }
        // "name"/"name_desc"/"" leave `text` unused: the tail alone keys.
    }

    std::vector<std::size_t> ord(entries.size());
    std::iota(ord.begin(), ord.end(), 0);
    const auto tail_of = [&keys](std::size_t i) {
        return std::pair<const std::string_view&, const std::string_view&>(
            keys[i].name, keys[i].id);
    };
    if (order == "name_desc") {
        // (name DESC, id ASC) — identical to the previous stable two-pass
        // sort (id ASC first, then name DESC stable): a stable sort on the
        // combined key produces the same order.
        std::stable_sort(ord.begin(), ord.end(),
                         [&](std::size_t a, std::size_t b) {
                             const Key& ka = keys[a];
                             const Key& kb = keys[b];
                             if (ka.name != kb.name) return ka.name > kb.name;
                             return ka.id < kb.id;
                         });
    } else if (order == "type" || order == "modified") {
        std::stable_sort(ord.begin(), ord.end(),
                         [&](std::size_t a, std::size_t b) {
                             const Key& ka = keys[a];
                             const Key& kb = keys[b];
                             if (ka.text != kb.text) return ka.text < kb.text;
                             return tail_of(a) < tail_of(b);
                         });
    } else if (order == "stage" || order == "size" || order == "version") {
        std::stable_sort(ord.begin(), ord.end(),
                         [&](std::size_t a, std::size_t b) {
                             const Key& ka = keys[a];
                             const Key& kb = keys[b];
                             if (ka.null_order != kb.null_order) {
                                 return ka.null_order < kb.null_order;
                             }
                             if (order == "stage") {
                                 if (ka.text != kb.text) {
                                     return ka.text < kb.text;
                                 }
                             } else if (ka.numeric != kb.numeric) {
                                 return ka.numeric < kb.numeric;
                             }
                             return tail_of(a) < tail_of(b);
                         });
    } else {
        std::stable_sort(ord.begin(), ord.end(),
                         [&](std::size_t a, std::size_t b) {
                             return tail_of(a) < tail_of(b);
                         });
    }

    if (query.after.has_value()
        && (query.order_by.empty() || query.order_by == "name")) {
        const auto& [cursor_name, cursor_id] = *query.after;
        // Keep only rows strictly after the cursor; stable_partition parks
        // them at the front and returns the boundary.
        const auto boundary = std::stable_partition(
            ord.begin(), ord.end(), [&](std::size_t i) {
                const Key& k = keys[i];
                return k.name > cursor_name
                       || (k.name == cursor_name && k.id > cursor_id);
            });
        ord.erase(boundary, ord.end());
    }

    const std::int64_t start = std::max<std::int64_t>(0, query.offset);
    const std::int64_t limit = std::max<std::int64_t>(0, query.limit);
    const std::int64_t available = static_cast<std::int64_t>(ord.size());
    if (start >= available || limit == 0) return {};
    const std::int64_t take = std::min(limit, available - start);
    // Row materialization happens only for the requested page — the JSON
    // shape is unchanged, the unseen rows simply never get built.
    std::vector<Json> rows;
    rows.reserve(static_cast<std::size_t>(take));
    for (std::int64_t i = start; i < start + take; ++i) {
        const Entry& e = entries[ord[static_cast<std::size_t>(i)]];
        rows.push_back(asset_page_row(*e.asset, e.version));
    }
    return rows;
}

std::int64_t count_assets(const CatalogDocument& document,
                          const EntityPageQuery& query) {
    // The stage predicate resolves the current version per asset — the same
    // O(N) index build that search_assets_page pays (was O(N^2)).
    const DocumentIndex index(document);
    return static_cast<std::int64_t>(
        filtered_assets(document, query, index).size());
}

}  // namespace pwb::catalog
