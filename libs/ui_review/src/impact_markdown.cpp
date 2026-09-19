#include "pwb/ui_review/impact_markdown.hpp"

#include <algorithm>
#include <sstream>

namespace pwb::ui_review {

namespace {

template <typename T>
std::vector<T> first_n(const std::vector<T>& items, std::size_t n) {
    const std::size_t take = std::min(items.size(), n);
    return std::vector<T>(items.begin(), items.begin() + take);
}

}  // namespace

bool TrashImpactSummary::has_downstream() const {
    return descendant_count != 0 || !runs_consuming.empty() ||
           !map_usages.empty() || broken_edges != 0 ||
           computation_errors != 0;
}

std::string TrashImpactSummary::render_markdown() const {
    std::vector<std::string> lines;
    if (computation_errors) {
        lines.push_back(
            "⚠ " + std::to_string(computation_errors) +
            " 项资产的影响计算失败——无法确认是否安全，请按存在影响处理");
    }
    if (descendant_count) {
        lines.push_back(
            "**" + std::to_string(descendant_count) +
            " 个活跃下游版本依赖所选资产**"
            "（删除后这些成果的谱系将指向回收站对象）");
        for (const auto& name : first_n(descendant_names, 8)) {
            lines.push_back("- " + name);
        }
    }
    if (!map_usages.empty()) {
        std::vector<std::string> layer_usages;
        std::vector<std::string> product_usages;
        for (const auto& [kind, label] : map_usages) {
            if (kind == "layer") {
                layer_usages.push_back(label);
            } else {
                product_usages.push_back(label);
            }
        }
        if (!layer_usages.empty()) {
            lines.push_back("**" + std::to_string(layer_usages.size()) +
                            " 个编图图层正在引用**：");
            for (const auto& label : first_n(layer_usages, 8)) {
                lines.push_back("- 图层 " + label);
            }
        }
        if (!product_usages.empty()) {
            lines.push_back("**" + std::to_string(product_usages.size()) +
                            " 个地图产品/输入集引用**：");
            for (const auto& label : first_n(product_usages, 8)) {
                lines.push_back("- " + label);
            }
        }
    }
    if (!runs_consuming.empty()) {
        lines.push_back("**" + std::to_string(runs_consuming.size()) +
                        " 个 run 以其为输入**"
                        "（run 保留为历史 provenance，不删除）");
    }
    if (!linked_entities.empty()) {
        std::string names;
        for (const auto& [etype, eid] : first_n(linked_entities, 6)) {
            if (!names.empty()) {
                names += ", ";
            }
            names += etype + ":" + eid.substr(0, 8);
        }
        lines.push_back("关联实体：" + names);
    }
    if (broken_edges) {
        lines.push_back("将产生 " + std::to_string(broken_edges) +
                        " 条血缘断链");
    }
    for (const auto& advice : first_n(cascade_advice, 3)) {
        lines.push_back("建议：" + advice);
    }
    if (lines.empty()) {
        lines.push_back(
            "未发现下游依赖或地图引用——可以安全移出（回收站可随时还原）。");
    }
    std::string out;
    for (const auto& line : lines) {
        if (!out.empty()) {
            out += "\n";
        }
        out += line;
    }
    return out;
}

TrashImpactSummary collect_trash_impact(
    IDeleteImpact& impact, IMapUsageSource* map_usages,
    const std::vector<std::string>& asset_ids) {
    TrashImpactSummary summary;
    for (const auto& asset_id : asset_ids) {
        catalog::DeleteImpact hop;
        try {
            hop = impact.delete_impact(asset_id);
        } catch (const std::exception&) {
            ++summary.computation_errors;
            continue;
        }
        summary.descendant_count += int(hop.live_descendants.size());
        // Python appends item.asset_name for live_descendants[:20] — the
        // StaleItem has no asset_name (see header); the list stays empty.
        const auto runs = first_n(hop.runs_consuming, 20);
        summary.runs_consuming.insert(summary.runs_consuming.end(),
                                      runs.begin(), runs.end());
        const auto linked = first_n(hop.linked_entities, 20);
        summary.linked_entities.insert(summary.linked_entities.end(),
                                       linked.begin(), linked.end());
        summary.broken_edges += hop.broken_lineage_edges;
        const auto advice = first_n(hop.cascade_advice, 5);
        summary.cascade_advice.insert(summary.cascade_advice.end(),
                                      advice.begin(), advice.end());
        if (map_usages != nullptr) {
            std::vector<std::pair<std::string, std::string>> usages;
            try {
                usages = map_usages->usages_of_asset(asset_id);
            } catch (const std::exception&) {
                ++summary.computation_errors;
                continue;
            }
            const auto usages_limited = first_n(usages, 30);
            summary.map_usages.insert(summary.map_usages.end(),
                                      usages_limited.begin(),
                                      usages_limited.end());
        }
    }
    return summary;
}

}  // namespace pwb::ui_review
