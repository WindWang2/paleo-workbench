#include "pwb/ui_workstation/action_help.hpp"

#include <pwb/tool_policy/stages.hpp>

namespace pwb::ui_workstation {

std::string stage_caption(const std::optional<std::string>& stage_value) {
    if (!stage_value.has_value()) {
        return "无阶段语义（legacy 表面）";
    }
    const auto stage = tool_policy::stage_from_value(*stage_value);
    if (stage.has_value()) {
        return tool_policy::stage_label(*stage);
    }
    return "未知阶段（'" + *stage_value + "'）";
}

ActionExplanation explain(const std::string& tool_id,
                          const tool_policy::ToolContextSnapshot& ctx,
                          const std::string& layer_name) {
    static const ToolHelpSpec kUnknownSpec{
        /*label=*/"",
        /*requirements=*/"未知工具",
        /*impact=*/"—",
        /*modifies_data=*/false,
        /*creates_version=*/false,
        /*background_task=*/false,
        /*stages=*/"—",
        /*layer_kinds=*/"—",
    };
    const ToolHelpSpec* found = tool_help_for(tool_id);
    ToolHelpSpec unknown = kUnknownSpec;
    unknown.label = tool_id;
    const ToolHelpSpec& spec = found != nullptr ? *found : unknown;

    ActionExplanation out;
    out.tool_id = tool_id;
    out.label = spec.label;
    out.availability = tool_policy::evaluate_tool(tool_id, ctx);
    out.requirements = spec.requirements;
    out.missing = out.availability.disabled_reason;
    out.impact = spec.impact;
    out.modifies_data = spec.modifies_data;
    out.creates_version = spec.creates_version;
    out.background_task = spec.background_task;
    out.shortcut = tool_shortcut(tool_id);
    out.stages = spec.stages;
    out.layer_kinds = spec.layer_kinds;
    out.current_layer = !layer_name.empty() ? layer_name : ctx.layer_name;
    out.current_stage = stage_caption(ctx.mapping_stage);
    return out;
}

std::string format_tooltip(const ActionExplanation& explanation) {
    std::string head = explanation.label;
    if (!explanation.shortcut.empty()) {
        head += "（" + explanation.shortcut + "）";
    }
    std::string out = head;
    if (!explanation.available()) {
        out += "\n不可用：" + explanation.missing;
        out += "\n需要：" + explanation.requirements;
    }
    return out;
}

std::string format_status(const ActionExplanation& explanation) {
    if (explanation.available()) {
        return explanation.label + "：" + explanation.impact;
    }
    return explanation.label + "（不可用：" + explanation.missing + "）";
}

std::string format_details(const ActionExplanation& explanation) {
    std::string out = explanation.label + " —— " +
                      (explanation.available() ? "可用" : "不可用");
    out += "\n影响：" + explanation.impact;
    out += "\n前置条件：" + explanation.requirements;
    if (!explanation.available()) {
        out += "\n当前缺失：" + explanation.missing;
    }
    out += "\n适用阶段：" + explanation.stages +
           "｜图层：" + explanation.layer_kinds;
    std::string flags;
    if (explanation.modifies_data) flags += "修改数据";
    if (explanation.creates_version) {
        if (!flags.empty()) flags += "、";
        flags += "生成新版本";
    }
    if (explanation.background_task) {
        if (!flags.empty()) flags += "、";
        flags += "后台任务";
    }
    out += "\n属性：" + (flags.empty() ? std::string("只读操作") : flags);
    if (!explanation.current_layer.empty()) {
        out += "\n当前图层：" + explanation.current_layer;
    }
    out += "\n当前阶段：" + explanation.current_stage;
    if (!explanation.shortcut.empty()) {
        out += "\n快捷键：" + explanation.shortcut;
    }
    return out;
}

}  // namespace pwb::ui_workstation
