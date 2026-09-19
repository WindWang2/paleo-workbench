#include "pwb/ui_widgets/core/epoch_switching.hpp"

#include <algorithm>
#include <cctype>
#include <set>

namespace pwb::ui_widgets::core {

namespace {

std::string trim_copy(const std::string& s) {
    std::size_t first = 0, last = s.size();
    while (first < last && std::isspace(static_cast<unsigned char>(s[first])))
        ++first;
    while (last > first && std::isspace(static_cast<unsigned char>(s[last - 1])))
        --last;
    return s.substr(first, last - first);
}

std::string metadata_value(const LayerSnapshot& layer, const char* key) {
    const auto it = layer.metadata.find(key);
    return it == layer.metadata.end() ? "" : trim_copy(it->second);
}

// 参与洋葱皮的图层角色（相带面/相带边界类；00-decisions D2）。
const std::set<std::string>& facies_layer_roles() {
    static const std::set<std::string> roles = {
        "initial_facies_source", "initial_facies_draft", "integrated_facies",
        "integrated_boundary",   "pending_review_area",
        // 模板键（旧工程/快照 metadata 惯用字符串）。
        "facies",                "facies_polygon",       "facies_boundary",
        "facies_sub",            "facies_micro",
    };
    return roles;
}

// 名称兜底词表（review P3 收窄）：明确相带词，避免吞"相干体切片"等。
const std::vector<std::string>& facies_name_words() {
    static const std::vector<std::string> words = {
        "相带", "沉积相", "相面", "亚相", "微相",
    };
    return words;
}

}  // namespace

std::string epoch_group_id(const std::string& epoch_key) {
    std::string sanitized = trim_copy(epoch_key);
    std::replace(sanitized.begin(), sanitized.end(), ' ', '_');
    return sanitized.empty() ? ""
                             : std::string(kEpochGroupPrefix) + sanitized;
}

bool is_epoch_group(const std::string& group_id) {
    return group_id.rfind(kEpochGroupPrefix, 0) == 0;
}

std::optional<std::string> epoch_key_of_group(const std::string& group_id) {
    if (!is_epoch_group(group_id)) return std::nullopt;
    std::string key = group_id.substr(std::string(kEpochGroupPrefix).size());
    std::replace(key.begin(), key.end(), '_', ' ');
    return key;
}

std::optional<std::string> tag_only_classifier(const LayerSnapshot& layer) {
    std::string tag = metadata_value(layer, "epoch");
    if (!tag.empty()) return tag;
    tag = metadata_value(layer, "horizon");
    if (!tag.empty()) return tag;
    const std::string group = metadata_value(layer, "group");
    if (!group.empty()) return epoch_key_of_group(group);
    return std::nullopt;
}

EpochClassifier default_epoch_classifier(
    const std::vector<EpochInfo>& epochs) {
    std::vector<std::pair<std::string, std::string>> patterns;
    for (const EpochInfo& e : epochs) {
        if (!e.key.empty()) patterns.emplace_back(e.key, e.label);
    }
    // Longest (key+label) first so prefixes cannot swallow matches.
    std::sort(patterns.begin(), patterns.end(),
              [](const auto& a, const auto& b) {
                  return a.first.size() + a.second.size() >
                         b.first.size() + b.second.size();
              });

    return [patterns](const LayerSnapshot& layer)
               -> std::optional<std::string> {
        for (const char* field : {"epoch", "horizon"}) {
            const std::string tag = metadata_value(layer, field);
            if (!tag.empty()) {
                for (const auto& [key, label] : patterns) {
                    if (tag == key) return key;
                }
            }
        }
        const std::string group = metadata_value(layer, "group");
        if (!group.empty()) {
            const auto epoch_key = epoch_key_of_group(group);
            if (epoch_key) {
                for (const auto& [key, label] : patterns) {
                    if (*epoch_key == key) return key;
                }
            }
        }
        if (!layer.name.empty()) {
            for (const auto& [key, label] : patterns) {
                // 单字符键的子串匹配误命中率高——键/标签长度 ≥2 才走名称兜底。
                const bool key_hit =
                    key.size() >= 2 && layer.name.find(key) != std::string::npos;
                const bool label_hit =
                    label.size() >= 2 &&
                    layer.name.find(label) != std::string::npos;
                if (key_hit || label_hit) return key;
            }
        }
        return std::nullopt;
    };
}

bool is_facies_layer(const LayerSnapshot& layer) {
    const std::string role = metadata_value(layer, "layer_role");
    if (!role.empty()) return facies_layer_roles().count(role) != 0;
    for (const std::string& word : facies_name_words()) {
        if (layer.name.find(word) != std::string::npos) return true;
    }
    return false;
}

EpochSwitchPlan build_epoch_switch_plan(
    const std::vector<LayerSnapshot>& layers, const std::string* current,
    const std::string& target, const EpochClassifier& classifier) {
    if (current != nullptr && target == *current) {
        return EpochSwitchPlan{target, {}, {}};
    }
    const EpochClassifier classify =
        classifier ? classifier : EpochClassifier(tag_only_classifier);
    EpochSwitchPlan plan;
    plan.target = target;
    for (const LayerSnapshot& layer : layers) {
        const auto key = classify(layer);
        if (!key) continue;  // 无归属层不随期次切换
        if (*key == target && !layer.visible) {
            plan.show.push_back(layer.id);
        } else if (*key != target && layer.visible) {
            plan.hide.push_back(layer.id);
        }
    }
    return plan;
}

std::vector<std::string> build_onion_layers(
    const std::vector<LayerSnapshot>& layers,
    const std::vector<EpochInfo>& epochs, const std::string& current,
    const EpochClassifier& classifier) {
    std::vector<std::string> keys;
    keys.reserve(epochs.size());
    for (const EpochInfo& e : epochs) keys.push_back(e.key);
    const auto it = std::find(keys.begin(), keys.end(), current);
    if (keys.empty() || it == keys.end() || it == keys.begin()) {
        return {};  // 最老期次无前一期
    }
    const std::string prev = *(it - 1);
    const EpochClassifier classify =
        classifier ? classifier : EpochClassifier(tag_only_classifier);
    std::vector<std::string> out;
    for (const LayerSnapshot& layer : layers) {
        const auto key = classify(layer);
        if (key && *key == prev && is_facies_layer(layer)) {
            out.push_back(layer.id);
        }
    }
    return out;
}

}  // namespace pwb::ui_widgets::core
