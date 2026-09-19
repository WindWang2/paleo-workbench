#include "pwb/ui_shell/navigation.hpp"

#include <array>
#include <map>

namespace pwb::ui_shell {

const std::vector<std::string>& hub_names() {
    static const std::vector<std::string> names = {
        "数据", "井", "地震", "编图", "可视化"};
    return names;
}

const std::vector<Submodule>& submodules(int hub_index) {
    static const std::array<std::vector<Submodule>, kHubCount> registry = {{
        {{"overview", "项目概述"}, {"management", "数据管理"}},
        {{"well_log", "测井预测"},
         {"sequence", "层序格架"},
         {"stratigraphy", "地层对比"}},
        {{"seismic", "地震预测"}, {"geomodel", "井震联合 3D"}},
        {{"canvas", "编图画布"},
         {"preparation", "数据制备"},
         {"review", "成图审核"}},
        {{"viz", "可视化"}},
    }};
    static const std::vector<Submodule> empty;
    if (hub_index < 0 || hub_index >= kHubCount) {
        return empty;
    }
    return registry[static_cast<std::size_t>(hub_index)];
}

std::vector<std::string> submodule_keys(int hub_index) {
    std::vector<std::string> keys;
    for (const auto& sm : submodules(hub_index)) {
        keys.push_back(sm.key);
    }
    return keys;
}

std::string submodule_title(int hub_index, const std::string& key) {
    for (const auto& sm : submodules(hub_index)) {
        if (sm.key == key) {
            return sm.title;
        }
    }
    return "";
}

const std::string& default_submodule(int hub_index) {
    static const std::array<std::string, kHubCount> defaults = {
        "overview", "well_log", "seismic", "canvas", "viz"};
    static const std::string empty;
    if (hub_index < 0 || hub_index >= kHubCount) {
        return empty;
    }
    return defaults[static_cast<std::size_t>(hub_index)];
}

std::optional<std::pair<int, std::string>> legacy_page_to_hub(int legacy_index) {
    static const std::map<int, std::pair<int, std::string>> map = {
        {0, {kPageIndexData, "overview"}},
        {1, {kPageIndexData, "management"}},
        {2, {kPageIndexWell, "well_log"}},
        {3, {kPageIndexSeismic, "seismic"}},
        {4, {kPageIndexWell, "sequence"}},
        {5, {kPageIndexWell, "stratigraphy"}},
        {6, {kPageIndexVisualization, "viz"}},
        {7, {kPageIndexMapping, "preparation"}},
        {8, {kPageIndexMapping, "canvas"}},
        {9, {kPageIndexMapping, "review"}},
        {10, {kPageIndexSeismic, "geomodel"}},
    };
    const auto it = map.find(legacy_index);
    if (it == map.end()) {
        return std::nullopt;
    }
    return it->second;
}

}  // namespace pwb::ui_shell
