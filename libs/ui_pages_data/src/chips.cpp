// UI-06 — filter_chips_bar dimensions + data_asset_table dimension
// removal + QSettings saved-filter payload.
#include <pwb/ui_pages_data/chips.hpp>

#include <algorithm>
#include <map>

namespace pwb::ui_pages_data {
namespace {

using pwb::domain::Json;

// _NODE_LABELS.get(node_type, node_type).
std::string_view node_label(std::string_view node_type) {
    if (node_type == "all") return "全部";
    if (node_type == "trash") return "回收站";
    if (node_type == "review_status") return "审查";
    if (node_type == "integrity") return "完整性";
    return node_type;
}

// s[:16] in CHARACTERS (code points), not bytes.
std::string first_chars(const std::string& s, std::size_t max_chars) {
    std::size_t pos = 0, chars = 0;
    while (pos < s.size() && chars < max_chars) {
        const unsigned char c = static_cast<unsigned char>(s[pos]);
        int len = 1;
        if (c >= 0xF0) len = 4;
        else if (c >= 0xE0) len = 3;
        else if (c >= 0xC0) len = 2;
        if (pos + len > s.size()) len = 1;
        pos += len;
        ++chars;
    }
    return s.substr(0, pos);
}

std::string jstr(const Json& v) {
    return v.is_string() ? v.get<std::string>() : std::string();
}

std::optional<std::string> jopt(const Json& dict, const char* key) {
    if (!dict.is_object() || !dict.contains(key) || dict.at(key).is_null())
        return std::nullopt;
    return jstr(dict.at(key));
}

}  // namespace

std::vector<std::pair<std::string, std::string>>
filter_dimensions(const FilterQuery& query) {
    std::vector<std::pair<std::string, std::string>> dims;
    const std::string node_type =
        query.node_type.empty() ? "all" : query.node_type;
    if (node_type != "all") {
        const std::string value = query.node_value.value_or("");
        std::string label = "视图: " + std::string(node_label(node_type));
        if (!value.empty()) label += " · " + value;
        dims.emplace_back("view", label);
    }
    if (!query.search_text.empty())
        dims.emplace_back("text", "搜索: " + query.search_text);
    if (query.stage)
        dims.emplace_back("stage", "阶段: " + *query.stage);
    if (query.data_type)
        dims.emplace_back("type", "类型: " + *query.data_type);
    for (const auto& tag : query.tags)
        dims.emplace_back("tag:" + tag, "标签: " + tag);
    if (query.tags.size() > 1) {
        dims.emplace_back("tag_operator",
                          query.tag_operator == "and" ? "全部满足"
                                                      : "任一满足");
    }
    if (query.asset_id) {
        dims.emplace_back("view",
                          "资产: " + first_chars(*query.asset_id, 16) + "…");
    }
    return dims;
}

std::optional<FilterQuery>
remove_filter_dimension(const FilterQuery& query, const std::string& key) {
    FilterQuery out = query;
    if (key == "view") {
        out.node_type = "all";
        out.node_value.reset();
        out.asset_id.reset();
    } else if (key == "text") {
        out.search_text.clear();
    } else if (key == "stage") {
        out.stage.reset();
    } else if (key == "type") {
        out.data_type.reset();
    } else if (key == "tag_operator") {
        out.tag_operator = "and";
    } else if (key.rfind("tag:", 0) == 0) {
        const std::string tag = key.substr(4);
        auto& tags = out.tags;
        tags.erase(std::remove(tags.begin(), tags.end(), tag), tags.end());
    } else {
        return std::nullopt;
    }
    return out;
}

Json filter_query_to_dict(const FilterQuery& query) {
    // The save payload (only these 7 fields are persisted).
    Json dict = Json::object();
    dict["node_type"] = query.node_type;
    dict["node_value"] =
        query.node_value ? Json(*query.node_value) : Json(nullptr);
    dict["search_text"] = query.search_text;
    dict["stage"] = query.stage ? Json(*query.stage) : Json(nullptr);
    dict["data_type"] =
        query.data_type ? Json(*query.data_type) : Json(nullptr);
    dict["tags"] = Json::array();
    for (const auto& tag : query.tags) dict["tags"].push_back(tag);
    dict["tag_operator"] = query.tag_operator;
    return dict;
}

FilterQuery filter_query_from_dict(const Json& dict) {
    // FilterQuery(node_type=stored.get("node_type","all"), ...) — only the
    // 7 saved fields are restored; everything else defaults.
    FilterQuery query;
    if (!dict.is_object()) return query;
    query.node_type =
        dict.contains("node_type") && dict.at("node_type").is_string()
            ? jstr(dict.at("node_type"))
            : "all";
    query.node_value = jopt(dict, "node_value");
    query.search_text =
        dict.contains("search_text") && dict.at("search_text").is_string()
            ? jstr(dict.at("search_text"))
            : "";
    query.stage = jopt(dict, "stage");
    query.data_type = jopt(dict, "data_type");
    if (dict.contains("tags") && dict.at("tags").is_array()) {
        for (const auto& tag : dict.at("tags"))
            if (tag.is_string()) query.tags.push_back(tag.get<std::string>());
    }
    query.tag_operator =
        dict.contains("tag_operator") && dict.at("tag_operator").is_string()
            ? jstr(dict.at("tag_operator"))
            : "and";
    return query;
}

std::vector<std::pair<std::string, Json>>
saved_filters_load(const std::string& payload) {
    std::vector<std::pair<std::string, Json>> out;
    if (payload.empty()) return out;
    Json value;
    try {
        value = Json::parse(payload);
    } catch (...) {
        return out;
    }
    if (!value.is_array()) return out;
    // {entry["name"]: entry["query"] for entry in value if isinstance(entry,
    // dict)} — first-occurrence position, last-duplicate value.
    std::map<std::string, std::size_t> index;
    for (const auto& entry : value) {
        if (!entry.is_object()) continue;
        if (!entry.contains("name") || !entry.at("name").is_string() ||
            !entry.contains("query"))
            continue;  // Python would KeyError; the port skips.
        const std::string name = jstr(entry.at("name"));
        const auto it = index.find(name);
        if (it != index.end())
            out[it->second].second = entry.at("query");
        else {
            index[name] = out.size();
            out.emplace_back(name, entry.at("query"));
        }
    }
    return out;
}

std::string saved_filters_dump(
    const std::vector<std::pair<std::string, Json>>& filters) {
    // [{"name": k, "query": v} for k, v in filters.items()] →
    // json.dumps(payload, ensure_ascii=False).
    Json payload = Json::array();
    for (const auto& [name, query] : filters) {
        Json entry = Json::object();
        entry["name"] = name;
        entry["query"] = query;
        payload.push_back(std::move(entry));
    }
    return payload.dump();  // nlohmann default: ensure_ascii=false.
}

std::vector<std::string> saved_filter_names_sorted(
    const std::vector<std::pair<std::string, Json>>& filters) {
    std::vector<std::string> names;
    names.reserve(filters.size());
    for (const auto& [name, _] : filters) names.push_back(name);
    std::stable_sort(names.begin(), names.end(), [](const auto& a, const auto& b) {
        // str.casefold ≈ ASCII lower for realistic names.
        auto fold = [](const std::string& s) {
            std::string out = s;
            for (auto& c : out)
                if (c >= 'A' && c <= 'Z') c = static_cast<char>(c + 32);
            return out;
        };
        return fold(a) < fold(b);
    });
    return names;
}

}  // namespace pwb::ui_pages_data
