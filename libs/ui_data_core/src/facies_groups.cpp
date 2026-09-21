// CONV-35 — see header for provenance; mirrors
// paleo_workbench/resources/geojson_layers.py line-for-line.

#include "pwb/ui_data_core/facies_groups.hpp"

#include <algorithm>
#include <array>
#include <set>
#include <unordered_set>

#include <pwb/domain/sha256.hpp>
#include <pwb/domain/text.hpp>

namespace pwb::ui_data_core {
namespace {

using domain::Json;

// _ROLE_ALIASES — order is load-bearing (longest/most-specific first so
// "microfacies" wins over "facies" substring matching, same as Python).
constexpr std::array<std::pair<std::string_view, std::array<std::string_view, 4>>,
                     3>
    kRoleAliases = {{
        {"microfacies",
         {"microfacies", "micro_facies", "micro-facies", "微相"}},
        {"subfacies",
         {"subfacies", "sub_facies", "sub-facies", "亚相"}},
        {"facies", {"facies", "相图", "相", ""}},
    }};

constexpr std::array<std::string_view, 4> kExplicitRoleKeys = {
    "layer_role", "facies_level", "hierarchy_level", "level"};
constexpr std::array<std::string_view, 3> kExplicitProductKeys = {
    "product_id", "result_id", "facies_product_id"};

// FACIES_LAYER_SPECS — role -> (label, level); nullptr for unknown.
constexpr std::array<std::pair<std::string_view,
                               std::pair<std::string_view, int>>,
                   3>
    kSpecs = {{
        {"facies", {"相", 1}},
        {"subfacies", {"亚相", 2}},
        {"microfacies", {"微相", 3}},
    }};

// Python truthiness over Json (or "" / `or` chains / `is not False`).
[[nodiscard]] bool py_truthy(const Json& v) {
    if (v.is_null()) return false;
    if (v.is_boolean()) return v.get<bool>();
    if (v.is_number()) return v.get<double>() != 0.0;
    if (v.is_string()) return !v.get_ref<const std::string&>().empty();
    return !v.empty();  // containers: non-empty is truthy
}

// str(value) for scalars; containers use JSON dump — the text differs from
// Python repr but is non-empty either way, and only presence is read.
[[nodiscard]] std::string py_str(const Json& v) {
    if (v.is_string()) return v.get<std::string>();
    if (v.is_boolean()) return v.get<bool>() ? "True" : "False";
    if (v.is_null()) return "";
    return v.dump();
}

// value or fallback — first truthy.
[[nodiscard]] const Json* py_or(const Json* a, const Json* b) {
    if (a != nullptr && py_truthy(*a)) return a;
    return b;
}

[[nodiscard]] const Json* json_get(const Json& obj, std::string_view key) {
    if (!obj.is_object()) return nullptr;
    const auto it = obj.find(std::string(key));
    return it == obj.end() ? nullptr : &*it;
}

// pathlib.PurePosixPath subset: collapse '/' runs, drop "." segments,
// trailing slashes never matter. (The Python source calls
// Path(name).stem / Path(path).parent.as_posix() — POSIX-flavoured
// because the fixtures and deployments are POSIX paths.)
[[nodiscard]] std::string_view last_segment(std::string_view path) {
    while (!path.empty() && path.back() == '/') path.remove_suffix(1);
    const std::size_t slash = path.rfind('/');
    return slash == std::string_view::npos ? path : path.substr(slash + 1);
}

[[nodiscard]] std::string py_stem(std::string_view filename) {
    std::string_view name = last_segment(filename);
    // pathlib stem: strip the LAST extension only when the dot is neither
    // leading nor trailing (0 < i < len-1): "a." stems to "a.", ".h" to
    // ".h", "a.b" to "a".
    const std::size_t dot = name.rfind('.');
    if (dot != std::string_view::npos && dot > 0 && dot < name.size() - 1) {
        name = name.substr(0, dot);
    }
    return std::string(name);
}

[[nodiscard]] std::string py_parent_posix(std::string_view path) {
    while (path.size() > 1 && path.back() == '/') path.remove_suffix(1);
    const std::size_t slash = path.rfind('/');
    if (slash == std::string_view::npos) return ".";
    std::string_view parent = path.substr(0, slash);
    while (parent.size() > 1 && parent.back() == '/') {
        parent.remove_suffix(1);  // collapse interior "//" tails
    }
    if (parent.empty()) return "/";
    return std::string(parent);
}

[[nodiscard]] std::string stem_lower(std::string_view filename) {
    return domain::lowercase_utf8(py_stem(filename));
}

[[nodiscard]] bool contains_alias(const std::string& stem,
                                  std::string_view alias) {
    return !alias.empty() && stem.find(alias) != std::string::npos;
}

void replace_all(std::string& text, std::string_view needle) {
    if (needle.empty()) return;
    std::size_t pos = 0;
    while ((pos = text.find(needle, pos)) != std::string::npos) {
        text.erase(pos, needle.size());
    }
}

// re.sub(r"(?:图层|layer|map|result|成果|图)$", "", stem) — alternation
// order matters ("图层" beats the shorter "图"); at most one suffix match.
void strip_suffix_word(std::string& stem) {
    static constexpr std::string_view kSuffixes[] = {
        "图层", "layer", "map", "result", "成果", "图"};
    for (const std::string_view suffix : kSuffixes) {
        if (stem.size() >= suffix.size() && stem.ends_with(suffix)) {
            stem.erase(stem.size() - suffix.size());
            return;
        }
    }
}

// re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "-", stem) — runs of disallowed
// code points collapse to a single '-'.
[[nodiscard]] bool allowed_stem_cp(char32_t cp) {
    return (cp >= U'0' && cp <= U'9') || (cp >= U'a' && cp <= U'z') ||
           (cp >= 0x4E00 && cp <= 0x9FFF);
}

[[nodiscard]] std::string sanitize_stem(std::string_view stem) {
    std::string out;
    bool in_dash = false;
    std::size_t i = 0;
    while (i < stem.size()) {
        const domain::Utf8CodePoint d = domain::decode_utf8_at(stem, i);
        if (d.valid && allowed_stem_cp(d.cp)) {
            out.append(stem.substr(i, d.size));
            in_dash = false;
        } else if (!in_dash) {
            out.push_back('-');
            in_dash = true;
        }
        i += d.valid ? d.size : 1;
    }
    // .strip("-")
    std::size_t begin = out.find_first_not_of('-');
    if (begin == std::string::npos) return {};
    const std::size_t end = out.find_last_not_of('-');
    return out.substr(begin, end - begin + 1);
}

[[nodiscard]] std::string stable_group_id(const std::string& key) {
    return "facies_product_" + domain::Sha256::of_bytes(key).substr(0, 16);
}

// _effective_layer_summary — parsed summary with the filename-inferred
// role folded in (only when the summary carries no role and is not an
// explicit parse failure).
[[nodiscard]] Json effective_summary(const ResourceItem& resource) {
    Json summary =
        resource.parsed_summary.is_object() ? resource.parsed_summary
                                            : Json::object();
    const Json* role = json_get(summary, "geojson_layer_role");
    const Json* valid = json_get(summary, "geojson_valid");
    const bool explicit_failure =
        valid != nullptr && valid->is_boolean() && !valid->get<bool>();
    const bool has_role =
        role != nullptr &&
        normalize_facies_layer_role(*role).has_value();
    if (!has_role && !explicit_failure) {
        summary.update(facies_layer_summary_from_name(resource.name));
    }
    return summary;
}

[[nodiscard]] std::string group_stem(const std::string& filename,
                                     std::string_view role) {
    std::string stem = stem_lower(filename);
    for (const auto& [name, aliases] : kRoleAliases) {
        if (name != role) continue;
        for (const std::string_view alias : aliases) {
            replace_all(stem, alias);
        }
        break;
    }
    strip_suffix_word(stem);
    stem = sanitize_stem(stem);
    return stem.empty() ? "facies-product" : stem;
}

[[nodiscard]] std::optional<std::string> group_key(const ResourceItem& res) {
    const Json summary = effective_summary(res);
    const Json* role_json = json_get(summary, "geojson_layer_role");
    const std::optional<std::string> role =
        role_json != nullptr ? normalize_facies_layer_role(*role_json)
                             : std::nullopt;
    if (!role.has_value()) return std::nullopt;
    const Json* id_json = json_get(summary, "facies_product_source_id");
    const std::string explicit_id =
        id_json != nullptr ? domain::python_strip(py_str(*id_json)) : "";
    if (!explicit_id.empty()) return "id:" + explicit_id;
    const std::string_view path_text =
        res.path.empty() ? std::string_view(res.name)
                         : std::string_view(res.path);
    return "path:" + py_parent_posix(path_text) + ":" +
           group_stem(res.name, *role);
}

[[nodiscard]] bool is_geojson_resource(const ResourceItem& res) {
    if (res.type != "geojson") return false;
    const std::string fmt = domain::lower_ascii(res.format);
    return fmt == "geojson" || fmt == "json";
}

// member_gid — group identity: annotated facies_product_group_id when
// present, else the stable digest of the group key.
[[nodiscard]] std::optional<std::string> member_gid(const ResourceItem& res) {
    const std::optional<std::string> key = group_key(res);
    if (!key.has_value()) return std::nullopt;
    const Json& summary = res.parsed_summary;
    const Json* annotated = json_get(summary, "facies_product_group_id");
    const std::string explicit_id =
        annotated != nullptr ? domain::python_strip(py_str(*annotated)) : "";
    return !explicit_id.empty() ? explicit_id : stable_group_id(*key);
}

}  // namespace

const std::pair<std::string, int>* facies_layer_spec(std::string_view role) {
    static const std::array<std::pair<std::string, int>, 3> kOut = {{
        {std::string(kSpecs[0].second.first), kSpecs[0].second.second},
        {std::string(kSpecs[1].second.first), kSpecs[1].second.second},
        {std::string(kSpecs[2].second.first), kSpecs[2].second.second},
    }};
    for (std::size_t i = 0; i < kSpecs.size(); ++i) {
        if (kSpecs[i].first == role) return &kOut[i];
    }
    return nullptr;
}

std::optional<std::string> normalize_facies_layer_role(const Json& value) {
    // str(value or "").strip().lower() — a non-string scalar str() can
    // never equal an alias (Python parity: same None result either way).
    if (!value.is_string()) return std::nullopt;
    const std::string text =
        domain::lowercase_utf8(domain::python_strip(value.get<std::string>()));
    if (text.empty()) return std::nullopt;
    for (const auto& [role, aliases] : kRoleAliases) {
        if (text == role) return std::string(role);
        for (const std::string_view alias : aliases) {
            if (!alias.empty() && text == alias) return std::string(role);
        }
    }
    return std::nullopt;
}

std::optional<std::string> facies_group_key(const ResourceItem& resource) {
    return group_key(resource);
}

std::string facies_group_id(const std::string& group_key_text) {
    return stable_group_id(group_key_text);
}

std::optional<std::string>
facies_layer_role_from_name(std::string_view filename) {
    const std::string stem = stem_lower(filename);
    for (const auto& [role, aliases] : kRoleAliases) {
        for (const std::string_view alias : aliases) {
            if (contains_alias(stem, alias)) return std::string(role);
        }
    }
    return std::nullopt;
}

Json facies_layer_summary_from_name(std::string_view filename) {
    const std::optional<std::string> role =
        facies_layer_role_from_name(filename);
    if (!role.has_value()) return Json::object();
    const auto* spec = facies_layer_spec(*role);
    return Json{{"geojson_layer_role", *role},
                {"geojson_layer_label", spec->first},
                {"geojson_layer_level", spec->second}};
}

Json geojson_document_summary(const Json& payload, std::string_view filename) {
    if (!payload.is_object()) {
        return Json{{"geojson_valid", false},
                    {"geojson_error", "根节点不是对象"}};
    }
    const Json* features = json_get(payload, "features");
    const Json* type = json_get(payload, "type");
    const bool valid = type != nullptr && *type == "FeatureCollection" &&
                       features != nullptr && features->is_array();
    Json summary = Json::object();
    summary["geojson_valid"] = valid;
    if (!valid) {
        summary["geojson_error"] = "根节点必须是 FeatureCollection";
        return summary;
    }

    std::set<std::string> geometry_types;
    for (const auto& feature : *features) {
        const Json* geometry = json_get(feature, "geometry");
        if (geometry == nullptr || !geometry->is_object()) continue;
        const Json* gtype = json_get(*geometry, "type");
        if (gtype != nullptr && py_truthy(*gtype)) {
            geometry_types.insert(py_str(*gtype));
        }
    }
    Json types = Json::array();
    for (const std::string& t : geometry_types) types.push_back(t);
    summary["geometry_types"] = std::move(types);

    const Json* metadata = json_get(payload, "metadata");
    const Json empty_meta = Json::object();
    const Json& meta =
        (metadata != nullptr && metadata->is_object()) ? *metadata
                                                       : empty_meta;
    std::optional<std::string> explicit_role;
    for (const std::string_view key : kExplicitRoleKeys) {
        const Json* value = py_or(json_get(meta, key),
                                  json_get(payload, key));
        explicit_role = value != nullptr
                            ? normalize_facies_layer_role(*value)
                            : std::nullopt;
        if (explicit_role.has_value()) break;
    }
    const std::optional<std::string> role =
        explicit_role.has_value() ? explicit_role
                                  : facies_layer_role_from_name(filename);
    if (role.has_value()) {
        const auto* spec = facies_layer_spec(*role);
        summary["geojson_layer_role"] = *role;
        summary["geojson_layer_label"] = spec->first;
        summary["geojson_layer_level"] = spec->second;
    }

    std::string product_source_id;
    for (const std::string_view key : kExplicitProductKeys) {
        const Json* value = py_or(json_get(meta, key),
                                  json_get(payload, key));
        const std::string text =
            value != nullptr ? domain::python_strip(py_str(*value)) : "";
        if (!text.empty()) {
            product_source_id = text;
            break;
        }
    }
    if (!product_source_id.empty()) {
        summary["facies_product_source_id"] = product_source_id;
    }
    return summary;
}

std::optional<std::string> facies_layer_role(const ResourceItem& resource) {
    const Json summary = effective_summary(resource);
    const Json* role = json_get(summary, "geojson_layer_role");
    return role != nullptr ? normalize_facies_layer_role(*role)
                           : std::nullopt;
}

std::vector<const ResourceItem*> facies_group_members(
    const ResourceItem& resource,
    const std::vector<const ResourceItem*>& resources) {
    const std::optional<std::string> target = member_gid(resource);
    if (!target.has_value()) return {&resource};
    std::vector<const ResourceItem*> members;
    for (const ResourceItem* res : resources) {
        if (!is_geojson_resource(*res)) continue;
        const std::optional<std::string> gid = member_gid(*res);
        if (gid.has_value() && *gid == *target) members.push_back(res);
    }
    std::stable_sort(members.begin(), members.end(),
                     [](const ResourceItem* a, const ResourceItem* b) {
                         const std::optional<std::string> ra =
                             facies_layer_role(*a);
                         const std::optional<std::string> rb =
                             facies_layer_role(*b);
                         const auto* sa =
                             facies_layer_spec(ra.value_or("facies"));
                         const auto* sb =
                             facies_layer_spec(rb.value_or("facies"));
                         return sa->second < sb->second;
                     });
    return members.empty() ? std::vector<const ResourceItem*>{&resource}
                           : members;
}

std::vector<std::string> annotate_facies_product_groups(
    const std::vector<ResourceItem*>& added,
    const std::vector<ResourceItem*>& existing) {
    std::unordered_set<const ResourceItem*> added_ids(added.begin(),
                                                      added.end());
    // Insertion-ordered groups (Python dict parity).
    std::vector<std::pair<std::string, std::vector<ResourceItem*>>> groups;
    auto append = [&](const std::string& key, ResourceItem* res) {
        for (auto& [k, members] : groups) {
            if (k == key) {
                members.push_back(res);
                return;
            }
        }
        groups.push_back({key, {res}});
    };

    const auto fold_and_collect = [&](ResourceItem* res) {
        if (!is_geojson_resource(*res)) return;
        Json summary = res->parsed_summary.is_object() ? res->parsed_summary
                                                       : Json::object();
        const Json* role = json_get(summary, "geojson_layer_role");
        const Json* valid = json_get(summary, "geojson_valid");
        const bool explicit_failure = valid != nullptr &&
                                      valid->is_boolean() &&
                                      !valid->get<bool>();
        const bool has_role =
            role != nullptr && py_truthy(*role);
        if (!has_role && !explicit_failure) {
            summary.update(facies_layer_summary_from_name(res->name));
            res->parsed_summary = summary;
        }
        const std::optional<std::string> key = group_key(*res);
        if (key.has_value()) append(*key, res);
    };
    for (ResourceItem* res : existing) fold_and_collect(res);
    for (ResourceItem* res : added) fold_and_collect(res);

    static const std::array<std::string_view, 3> kRequired = {
        "facies", "subfacies", "microfacies"};
    std::vector<std::string> warnings;
    for (auto& [key, members] : groups) {
        std::vector<std::pair<std::string, std::vector<ResourceItem*>>>
            by_role;
        for (ResourceItem* res : members) {
            const Json& summary = res->parsed_summary;
            const Json* role_json = json_get(summary, "geojson_layer_role");
            const std::optional<std::string> role =
                role_json != nullptr
                    ? normalize_facies_layer_role(*role_json)
                    : std::nullopt;
            if (!role.has_value()) continue;
            bool placed = false;
            for (auto& [r, list] : by_role) {
                if (r == *role) {
                    list.push_back(res);
                    placed = true;
                    break;
                }
            }
            if (!placed) by_role.push_back({*role, {res}});
        }
        std::set<std::string> roles_seen;
        bool complete = true;
        for (const std::string_view required : kRequired) {
            bool found = false;
            for (const auto& [r, list] : by_role) {
                if (r == required) {
                    found = true;
                    if (list.size() != 1) complete = false;
                }
            }
            if (found) roles_seen.insert(std::string(required));
            else complete = false;
        }
        complete = complete && by_role.size() == kRequired.size();
        const std::string group_id = stable_group_id(key);
        for (ResourceItem* res : members) {
            Json summary = res->parsed_summary.is_object()
                               ? res->parsed_summary
                               : Json::object();
            summary["facies_product_group_id"] = group_id;
            summary["facies_product_complete"] = complete;
            summary["facies_product_layer_count"] =
                static_cast<std::int64_t>(by_role.size());
            res->parsed_summary = summary;
            if (complete) {
                const Json* role_json =
                    json_get(summary, "geojson_layer_role");
                const std::string role =
                    role_json != nullptr && role_json->is_string()
                        ? role_json->get<std::string>()
                        : "";
                const auto* spec = facies_layer_spec(role);
                const std::string& label =
                    spec != nullptr ? spec->first : role;
                res->artifact_role = "output";
                std::vector<std::string> tags;
                const std::unordered_set<std::string_view> role_tags = {
                    "input", "reference", "output"};
                for (const std::string& tag : res->tags) {
                    if (!role_tags.contains(tag)) tags.push_back(tag);
                }
                // dict.fromkeys — first occurrence order, deduped.
                std::unordered_set<std::string> seen;
                std::vector<std::string> merged;
                const std::string head_tags[] = {"output", "facies-map",
                                                 label};
                for (const std::string& tag : head_tags) {
                    if (seen.insert(tag).second) merged.push_back(tag);
                }
                for (const std::string& tag : tags) {
                    if (seen.insert(tag).second) merged.push_back(tag);
                }
                res->tags = std::move(merged);
            }
        }

        const bool touches_added =
            std::any_of(members.begin(), members.end(),
                        [&](const ResourceItem* r) {
                            return added_ids.contains(r);
                        });
        if (!complete && members.size() >= 2 && touches_added) {
            std::vector<std::string> missing;
            for (const std::string_view required : kRequired) {
                bool found = false;
                for (const auto& [r, list] : by_role) {
                    if (r == required) found = true;
                }
                if (!found) {
                    missing.push_back(facies_layer_spec(required)->first);
                }
            }
            std::vector<std::string> duplicates;
            for (const auto& [r, list] : by_role) {
                if (list.size() > 1) {
                    duplicates.push_back(facies_layer_spec(r)->first);
                }
            }
            std::sort(duplicates.begin(), duplicates.end());
            std::vector<std::string> detail;
            if (!missing.empty()) {
                std::string text = "缺少";
                for (std::size_t i = 0; i < missing.size(); ++i) {
                    if (i) text += "、";
                    text += missing[i];
                }
                detail.push_back(std::move(text));
            }
            if (!duplicates.empty()) {
                std::string text = "重复";
                for (std::size_t i = 0; i < duplicates.size(); ++i) {
                    if (i) text += "、";
                    text += duplicates[i];
                }
                detail.push_back(std::move(text));
            }
            std::string joined;
            for (std::size_t i = 0; i < detail.size(); ++i) {
                if (i) joined += "；";
                joined += detail[i];
            }
            warnings.push_back("GeoJSON 相图成果组不完整（" +
                               (joined.empty() ? "层级无法识别" : joined) +
                               "）");
        }
    }
    return warnings;
}

}  // namespace pwb::ui_data_core
