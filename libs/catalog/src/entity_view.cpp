#include "pwb/catalog/entity_view.hpp"

#include <algorithm>
#include <cctype>
#include <map>
#include <set>
#include <tuple>

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

const DataVersion* current_version_of(const CatalogDocument& document,
                                      const DataAsset& asset) {
    if (!asset.current_version_id.has_value()) return nullptr;
    return document.find_version(*asset.current_version_id);
}

// The shared filter core of Python `_paged_fallback_rows` (db.py
// `_paged_predicates` semantics on document rows).
std::vector<const DataAsset*> filtered_assets(const CatalogDocument& document,
                                              const EntityPageQuery& query) {
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
        const DataVersion* version = current_version_of(document, asset);
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
    struct Entry {
        Json row;
        const DataVersion* version = nullptr;
    };
    std::vector<Entry> entries;
    for (const DataAsset* asset : filtered_assets(document, query)) {
        const DataVersion* version = current_version_of(document, *asset);
        entries.push_back({asset_page_row(*asset, version), version});
    }

    const std::string& order =
        query.order_by.empty() ? std::string("name") : query.order_by;
    auto tail = [](const Entry& e) {
        return std::pair<std::string, std::string>(
            e.row["name"].get<std::string>(), e.row["id"].get<std::string>());
    };
    if (order == "name_desc") {
        // Stable two-pass sort: (name DESC, id ASC), matching the SQL tail.
        std::stable_sort(entries.begin(), entries.end(),
                         [](const Entry& a, const Entry& b) {
                             return a.row["id"].get<std::string>() <
                                    b.row["id"].get<std::string>();
                         });
        std::stable_sort(entries.begin(), entries.end(),
                         [](const Entry& a, const Entry& b) {
                             return a.row["name"].get<std::string>() >
                                    b.row["name"].get<std::string>();
                         });
    } else if (order == "type") {
        std::stable_sort(entries.begin(), entries.end(),
                         [&](const Entry& a, const Entry& b) {
                             const auto ka = std::make_tuple(
                                 a.row["type"].get<std::string>(), tail(a));
                             const auto kb = std::make_tuple(
                                 b.row["type"].get<std::string>(), tail(b));
                             return ka < kb;
                         });
    } else if (order == "modified") {
        std::stable_sort(entries.begin(), entries.end(),
                         [&](const Entry& a, const Entry& b) {
                             const auto ka = std::make_tuple(
                                 a.row["updated_at"].get<std::string>(),
                                 tail(a));
                             const auto kb = std::make_tuple(
                                 b.row["updated_at"].get<std::string>(),
                                 tail(b));
                             return ka < kb;
                         });
    } else if (order == "stage" || order == "size" || order == "version") {
        // NULLs-first is PER COLUMN (Python keys on the row value): a
        // present version with size_bytes NULL also leads the size order.
        auto null_flag = [&](const Entry& e) {
            if (e.version == nullptr) return NullOrder::kFirst;
            if (order == "size") {
                return e.version->size_bytes.has_value() ? NullOrder::kValue
                                                         : NullOrder::kFirst;
            }
            return NullOrder::kValue;  // stage/version_number are non-null
        };
        std::stable_sort(entries.begin(), entries.end(),
                         [&](const Entry& a, const Entry& b) {
                             if (null_flag(a) != null_flag(b)) {
                                 return null_flag(a) < null_flag(b);
                             }
                             if (order == "stage") {
                                 const auto va = current_stage_value(a.version);
                                 const auto vb = current_stage_value(b.version);
                                 if (va != vb) return va < vb;
                             } else if (order == "size") {
                                 const std::int64_t va =
                                     a.version != nullptr &&
                                             a.version->size_bytes.has_value()
                                         ? *a.version->size_bytes
                                         : 0;
                                 const std::int64_t vb =
                                     b.version != nullptr &&
                                             b.version->size_bytes.has_value()
                                         ? *b.version->size_bytes
                                         : 0;
                                 if (va != vb) return va < vb;
                             } else {
                                 const int va = a.version != nullptr
                                     ? a.version->version_number : 0;
                                 const int vb = b.version != nullptr
                                     ? b.version->version_number : 0;
                                 if (va != vb) return va < vb;
                             }
                             return tail(a) < tail(b);
                         });
    } else {
        std::stable_sort(entries.begin(), entries.end(),
                         [&](const Entry& a, const Entry& b) {
                             return tail(a) < tail(b);
                         });
    }

    std::vector<Json> rows;
    if (query.after.has_value() && (query.order_by.empty() ||
                                    query.order_by == "name")) {
        const auto& [cursor_name, cursor_id] = *query.after;
        // Keep only rows strictly after the cursor; stable_partition parks
        // them at the front and returns the boundary.
        const auto boundary = std::stable_partition(
            entries.begin(), entries.end(),
            [&](const Entry& e) {
                const std::string& name = e.row["name"].get<std::string>();
                const std::string& id = e.row["id"].get<std::string>();
                return name > cursor_name ||
                       (name == cursor_name && id > cursor_id);
            });
        for (auto it = entries.begin(); it != boundary; ++it) {
            rows.push_back(it->row);
        }
    } else {
        for (const Entry& entry : entries) {
            rows.push_back(entry.row);
        }
    }
    const std::int64_t start = std::max<std::int64_t>(0, query.offset);
    const std::int64_t limit = std::max<std::int64_t>(0, query.limit);
    const std::int64_t available = static_cast<std::int64_t>(rows.size());
    if (start >= available || limit == 0) return {};
    const std::int64_t take = std::min(limit, available - start);
    return std::vector<Json>(rows.begin() + static_cast<std::ptrdiff_t>(start),
                             rows.begin()
                                 + static_cast<std::ptrdiff_t>(start + take));
}

std::int64_t count_assets(const CatalogDocument& document,
                          const EntityPageQuery& query) {
    return static_cast<std::int64_t>(filtered_assets(document, query).size());
}

}  // namespace pwb::catalog
