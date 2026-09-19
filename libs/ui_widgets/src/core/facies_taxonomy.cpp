#include "pwb/ui_widgets/core/facies_taxonomy.hpp"

#include "pwb/ui_widgets/core/tree_sync.hpp"  // py_str / py_truthy

#include <algorithm>
#include <fstream>
#include <set>

namespace pwb::ui_widgets::core {

namespace {

std::string trim_copy(const std::string& s) {
    const auto first = s.find_first_not_of(" \t\r\n");
    if (first == std::string::npos) return "";
    const auto last = s.find_last_not_of(" \t\r\n");
    return s.substr(first, last - first + 1);
}

int level_depth(const std::string& level) {
    for (std::size_t i = 0; i < kFaciesLevelKeys.size(); ++i) {
        if (kFaciesLevelKeys[i] == level) return static_cast<int>(i);
    }
    return -1;
}

// _normalize_tree: strip non-dict leaves, drop empty/"_"-prefixed keys,
// merge same-name siblings (subtree union).
nlohmann::ordered_json normalize_tree(const nlohmann::json& tree) {
    nlohmann::ordered_json normalized = nlohmann::ordered_json::object();
    if (!tree.is_object()) return normalized;
    for (auto it = tree.begin(); it != tree.end(); ++it) {
        const std::string name = trim_copy(it.key());
        if (name.empty() || name.front() == '_') continue;
        const nlohmann::ordered_json children = normalize_tree(it.value());
        if (normalized.contains(name) && !children.empty()) {
            // Same-name sibling merge: subtree union.
            for (auto cit = children.begin(); cit != children.end(); ++cit) {
                if (!normalized[name].contains(cit.key())) {
                    normalized[name][cit.key()] = nlohmann::ordered_json::object();
                }
                for (auto git = cit.value().begin(); git != cit.value().end();
                     ++git) {
                    normalized[name][cit.key()][git.key()] = git.value();
                }
            }
        } else {
            normalized[name] = children;
        }
    }
    return normalized;
}

void collect_level(const nlohmann::ordered_json& node, int depth,
                   std::set<std::string>* out) {
    if (depth == 0) {
        for (auto it = node.begin(); it != node.end(); ++it) out->insert(it.key());
        return;
    }
    for (auto it = node.begin(); it != node.end(); ++it) {
        if (it.value().is_object()) collect_level(it.value(), depth - 1, out);
    }
}

}  // namespace

std::string resolve_facies_field(const std::string& level,
                                 const std::vector<std::string>& available) {
    std::set<std::string> names;
    for (const std::string& name : available) {
        if (!name.empty()) names.insert(name);
    }
    const auto alias_it = kFaciesFieldAliases.find(level);
    const std::vector<std::string> candidates =
        alias_it != kFaciesFieldAliases.end() ? alias_it->second
                                              : std::vector<std::string>{level};
    for (const std::string& candidate : candidates) {
        if (names.count(candidate)) return candidate;
    }
    return "";
}

FaciesTaxonomy::FaciesTaxonomy(const nlohmann::ordered_json& tree,
                               std::string source)
    : tree_(normalize_tree(tree)),
      source(source.empty() ? "builtin" : std::move(source)) {}

FaciesTaxonomy FaciesTaxonomy::builtin(const std::string& resources_dir) {
    std::ifstream in(resources_dir + "/facies_taxonomy.json");
    if (!in) return FaciesTaxonomy{};
    nlohmann::ordered_json payload = nlohmann::ordered_json::parse(in, nullptr, false);
    if (payload.is_discarded()) return FaciesTaxonomy{};
    const auto tree = payload.value("tree", nlohmann::ordered_json{});
    return FaciesTaxonomy(tree.is_object() ? tree : nlohmann::ordered_json::object(),
                          "builtin");
}

FaciesTaxonomy FaciesTaxonomy::from_project(
    const nlohmann::json& override_section, const std::string& resources_dir) {
    if (override_section.is_object()) {
        const auto tree = override_section.value("tree", nlohmann::ordered_json{});
        if (tree.is_object() && !tree.empty()) {
            const auto source = override_section.value(
                "source", nlohmann::ordered_json("project"));
            return FaciesTaxonomy(tree,
                                  source.is_string() ? source.get<std::string>()
                                                     : "project");
        }
    }
    return builtin(resources_dir);
}

FaciesTaxonomy FaciesTaxonomy::from_geojson_features(
    const nlohmann::json& features) {
    struct Entry {
        std::string name;
        std::string level;
        std::string parent_id;
    };
    std::map<std::string, Entry> by_id;
    if (features.is_array()) {
        for (const auto& feature : features) {
            if (!feature.is_object()) continue;
            const auto props = feature.value("properties", nlohmann::ordered_json{});
            if (!props.is_object()) continue;
            const std::string fid = props.contains("id") ? py_str(props["id"]) : "";
            const std::string level =
                props.contains("level") ? py_str(props["level"]) : "";
            const std::string name =
                trim_copy(props.contains("facies") ? py_str(props["facies"]) : "");
            const std::string parent_id =
                props.contains("parent_id") ? py_str(props["parent_id"]) : "";
            if (fid.empty() || name.empty() ||
                std::find(kFaciesLevelKeys.begin(), kFaciesLevelKeys.end(),
                          level) == kFaciesLevelKeys.end()) {
                continue;
            }
            by_id[fid] = Entry{name, level, parent_id};
        }
    }

    nlohmann::ordered_json tree = nlohmann::ordered_json::object();
    // Pass 1: facies roots.
    for (const auto& [fid, e] : by_id) {
        if (e.level == "facies" && !tree.contains(e.name)) {
            tree[e.name] = nlohmann::ordered_json::object();
        }
    }
    // Pass 2: sub_facies under a facies parent.
    for (const auto& [fid, e] : by_id) {
        if (e.level != "sub_facies") continue;
        const auto parent = by_id.find(e.parent_id);
        if (parent != by_id.end() && parent->second.level == "facies") {
            if (!tree.contains(parent->second.name)) {
                tree[parent->second.name] = nlohmann::ordered_json::object();
            }
            if (!tree[parent->second.name].contains(e.name)) {
                tree[parent->second.name][e.name] = nlohmann::ordered_json::object();
            }
        }
    }
    // Pass 3: micro_facies under sub_facies under facies.
    for (const auto& [fid, e] : by_id) {
        if (e.level != "micro_facies") continue;
        const auto parent = by_id.find(e.parent_id);
        if (parent == by_id.end() || parent->second.level != "sub_facies") {
            continue;
        }
        const auto top = by_id.find(parent->second.parent_id);
        if (top == by_id.end() || top->second.level != "facies") continue;
        if (!tree.contains(top->second.name) ||
            !tree[top->second.name].contains(parent->second.name)) {
            continue;  // Python: tree[top][parent] would KeyError — skip orphan.
        }
        tree[top->second.name][parent->second.name][e.name] =
            nlohmann::ordered_json::object();
    }
    return FaciesTaxonomy(tree, "project");
}

std::vector<std::string> FaciesTaxonomy::names(
    const std::string& level, const std::vector<std::string>& parents) const {
    const int depth = level_depth(level);
    if (depth < 0) return {};

    auto all_names = [&]() -> std::vector<std::string> {
        std::set<std::string> names_set;
        collect_level(tree_, depth, &names_set);
        return {names_set.begin(), names_set.end()};
    };

    std::vector<std::string> chain;
    for (std::size_t i = 0; i < parents.size() && i < static_cast<std::size_t>(depth);
         ++i) {
        const std::string stripped = trim_copy(parents[i]);
        if (!stripped.empty()) chain.push_back(stripped);
    }
    if (static_cast<int>(chain.size()) < depth) return all_names();

    const nlohmann::ordered_json* node = &tree_;
    for (const std::string& parent : chain) {
        const auto it = node->find(parent);
        if (it == node->end() || !it->is_object() || it->empty()) {
            return all_names();
        }
        node = &(*it);
    }
    std::vector<std::string> out;
    for (auto it = node->begin(); it != node->end(); ++it) out.push_back(it.key());
    std::sort(out.begin(), out.end());
    return out;
}

bool FaciesTaxonomy::has(const std::string& name, const std::string& level,
                         const std::vector<std::string>& parents) const {
    const auto options = names(level, parents);
    return std::find(options.begin(), options.end(), name) != options.end();
}

std::string FaciesTaxonomy::selection_level(
    const std::map<std::string, std::string>& selection) {
    auto trimmed = [&](const char* key) -> std::string {
        const auto it = selection.find(key);
        return it == selection.end() ? "" : trim_copy(it->second);
    };
    if (!trimmed("micro_facies").empty()) return "micro_facies";
    if (!trimmed("sub_facies").empty()) return "sub_facies";
    return "facies";
}

std::map<std::string, std::string> FaciesTaxonomy::selection_from_attributes(
    const nlohmann::json& attributes) {
    auto field = [&](const char* key) -> std::string {
        if (!attributes.is_object() || !attributes.contains(key)) return "";
        const auto& v = attributes[key];
        return py_truthy(v) ? py_str(v) : "";
    };
    return {{"facies", field("facies")},
            {"sub_facies", field("sub_facies")},
            {"micro_facies", field("micro_facies")}};
}

nlohmann::ordered_json FaciesTaxonomy::to_project_dict() const {
    nlohmann::ordered_json out = nlohmann::ordered_json::object();
    out["source"] = source;
    out["tree"] = tree_;
    return out;
}

std::tuple<int, int, int> FaciesTaxonomy::counts() const {
    int sub = 0, micro = 0;
    for (auto it = tree_.begin(); it != tree_.end(); ++it) {
        sub += static_cast<int>(it->size());
        for (auto sit = it->begin(); sit != it->end(); ++sit) {
            micro += static_cast<int>(sit->size());
        }
    }
    return {static_cast<int>(tree_.size()), sub, micro};
}

}  // namespace pwb::ui_widgets::core
