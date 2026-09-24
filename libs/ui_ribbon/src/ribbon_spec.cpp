#include "pwb/ui_ribbon/ribbon_spec.hpp"

#include <algorithm>
#include <set>

namespace pwb::ui_ribbon {

namespace {

// Chinese display labels — two-page shell
// (docs/ui-redesign/two-page-shell-2026-09-24/README.md): the former
// 智能预测/约束与单因素/综合编图 stage workspaces are modes inside 编图.
constexpr const char* kLabelDataManagement = "数据管理";
constexpr const char* kLabelAuthoring = "编图";

struct WorkspaceRow {
    Workspace workspace;
    const char* id;
    const char* label;
    // Always nullopt (D1): page entry never rewrites the stage — the
    // 编图模式 toggle commands are the stage write surface.
    std::optional<tool_policy::MappingStage> stage;
};

constexpr std::array<WorkspaceRow, 2> kWorkspaceRows = {{
    {Workspace::DataManagement, "data_management", kLabelDataManagement,
     std::nullopt},
    {Workspace::Authoring, "authoring", kLabelAuthoring, std::nullopt},
}};

// ---------------------------------------------------------------------------
// The command group table (two-page shell): 数据管理 keeps its five
// groups; 编图's static band carries the 编图模式 toggle group plus the
// shared 输出 group — the three stage-mode command sets moved to
// authoring_mode_groups() and are injected per mode as context groups.
// Command ids are semantic placeholders (the host rebinds them to the
// real CommandRegistry ids); icon names reference the repo SVG assets
// resolved through ui_widgets::workstation_icon.
// ---------------------------------------------------------------------------

// Shorthand builders keep the table below readable.
RibbonCommand cmd(const char* id, const char* text, const char* icon,
                  CommandKind kind = CommandKind::Secondary,
                  bool overflow = false) {
    return RibbonCommand{id, text, icon, kind, overflow};
}

RibbonGroup group(const char* id, const char* label,
                  std::vector<RibbonCommand> commands) {
    return RibbonGroup{id, label, std::move(commands)};
}

std::vector<RibbonWorkspaceSpec> build_workspace_specs() {
    std::vector<RibbonWorkspaceSpec> specs;
    specs.reserve(kWorkspaceRows.size());

    // ---- 数据管理 — primary: 导入数据 --------------------------------------
    specs.push_back(RibbonWorkspaceSpec{
        Workspace::DataManagement,
        "data.import",
        {
            group("data_import", "数据导入",
                  {
                      cmd("data.import", "导入数据", "map/btn-import.svg",
                          CommandKind::Primary),
                      cmd("data.scan", "扫描目录", "map/btn-rescan.svg"),
                      cmd("data.plan", "导入计划", "menu-properties.svg",
                          CommandKind::Secondary, /*overflow=*/true),
                  }),
            group("data_organize", "整理",
                  {
                      cmd("data.link_well", "关联到井", "rb-link.svg"),
                      cmd("data.set_role", "设置角色", "rb-settings.svg",
                          CommandKind::Secondary, /*overflow=*/true),
                  }),
            group("data_quality", "质量检查",
                  {
                      cmd("data.check", "检查数据", "rb-qc.svg"),
                      cmd("data.units", "单位与坐标", "rb-grid.svg",
                          CommandKind::Secondary, /*overflow=*/true),
                  }),
            group("data_version", "版本与关联",
                  {
                      cmd("data.history", "版本历史", "refresh-cw.svg"),
                      cmd("data.lineage", "来源关系", "rb-auto-link.svg",
                          CommandKind::Secondary, /*overflow=*/true),
                  }),
            group("data_output", "输出",
                  {
                      cmd("data.export_table", "导出表格", "rb-export.svg"),
                  }),
        }});

    // ---- 编图 — primary: 导出图件 ------------------------------------------
    // 静态带 = 模式切换组 + 常驻输出组；三个模式的命令集经
    // authoring_mode_groups() 作为上下文组按模式注入（组尾追加，
    // 静态组不跳位 —— R:33 布局稳定）。
    specs.push_back(RibbonWorkspaceSpec{
        Workspace::Authoring,
        "map.export",
        {
            group("author_mode", "编图模式",
                  {
                      cmd("mode.predict", "智能预测", "rb-run.svg",
                          CommandKind::Toggle),
                      cmd("mode.factor", "单因素图", "rb-generate.svg",
                          CommandKind::Toggle),
                      cmd("mode.author", "编图", "map/change_facies.svg",
                          CommandKind::Toggle),
                  }),
            group("map_output", "输出",
                  {
                      cmd("map.export", "导出图件", "rb-export.svg",
                          CommandKind::Primary),
                      cmd("map.save_plan", "保存方案", "map/btn-save-draft.svg",
                          CommandKind::Secondary, /*overflow=*/true),
                      cmd("map.submit", "送交验证", "rb-send.svg"),
                  }),
        }});

    return specs;
}

// ---------------------------------------------------------------------------
// 编图模式命令组（页内三模式 ⇄ MappingStage；原三个工作区的组结构
// 原样迁移，命令 id 不变）。模式主命令保留 Primary 形态 —— 模式组的
// 主动作与常驻「导出图件」并列是刻意的（模式上下文主动作 + 常驻输出）。
// ---------------------------------------------------------------------------

std::vector<RibbonGroup> predict_mode_groups() {
    return {
        group("predict_input", "输入与模型",
              {
                  cmd("predict.select_well", "选择井数据", "well-log.svg"),
                  cmd("predict.select_seismic", "选择地震", "seismic.svg"),
                  cmd("predict.model_params", "模型参数", "rb-settings.svg",
                      CommandKind::Secondary, /*overflow=*/true),
              }),
        group("predict_run", "预测运行",
              {
                  cmd("predict.run", "运行预测", "rb-run.svg",
                      CommandKind::Primary),
                  cmd("predict.cancel", "取消", "map/cancel.svg",
                      CommandKind::Secondary, /*overflow=*/true),
                  cmd("predict.params", "参数", "menu-preview-settings.svg",
                      CommandKind::Secondary, /*overflow=*/true),
              }),
        group("predict_overlay", "叠加对照",
              {
                  cmd("predict.overlay_seismic", "地震叠加", "rb-slice.svg"),
                  cmd("predict.overlay_well", "测井叠加", "rb-dtw.svg",
                      CommandKind::Secondary, /*overflow=*/true),
                  cmd("predict.link", "联动", "rb-link.svg",
                      CommandKind::Toggle),
              }),
        group("predict_result", "结果",
              {
                  cmd("predict.save", "保存结果", "menu-save.svg"),
                  cmd("predict.submit", "送交验证", "rb-send.svg"),
              }),
    };
}

std::vector<RibbonGroup> factor_mode_groups() {
    return {
        group("factor_constraints", "约束编辑",
              {
                  cmd("factor.edit_sourcing", "编辑物源线", "rb-fence.svg"),
                  cmd("factor.edit_trend", "展布线", "rb-analysis.svg",
                      CommandKind::Secondary, /*overflow=*/true),
                  cmd("factor.snap", "捕捉", "map/snapping.svg",
                      CommandKind::Toggle),
              }),
        group("factor_interpolate", "插值计算",
              {
                  cmd("factor.compute", "计算单因素", "rb-generate.svg",
                      CommandKind::Primary),
                  cmd("factor.params", "参数", "menu-preview-settings.svg",
                      CommandKind::Secondary, /*overflow=*/true),
                  cmd("factor.cancel", "取消", "map/cancel.svg",
                      CommandKind::Secondary, /*overflow=*/true),
              }),
        group("factor_crosswell", "连井分析",
              {
                  cmd("factor.select_wells", "选井", "well-log.svg"),
                  cmd("factor.crosswell_path", "连井路径", "sequence.svg",
                      CommandKind::Secondary, /*overflow=*/true),
                  cmd("factor.link", "联动", "rb-link.svg",
                      CommandKind::Toggle),
              }),
        group("factor_contour", "等值线",
              {
                  cmd("factor.contour", "生成等值线",
                      "map/btn-contour-draft.svg"),
              }),
        group("factor_result", "结果",
              {
                  cmd("factor.save", "保存版本", "map/btn-save-draft.svg"),
                  cmd("factor.submit", "送交验证", "rb-send.svg"),
              }),
    };
}

std::vector<RibbonGroup> author_mode_groups() {
    // 「输出」组是编图带的常驻静态组（声明的主命令 map.export）——
    // 这里不含它。
    return {
        group("map_facies", "相界编辑",
              {
                  cmd("map.select", "选择", "map/select_rectangle.svg"),
                  cmd("map.edit_facies", "编辑相界", "map/change_facies.svg"),
              }),
        group("map_reference", "参考图",
              {
                  cmd("map.show_reference", "显示参考图", "preparation.svg",
                      CommandKind::Toggle),
                  cmd("map.opacity", "透明度", "rb-opacity.svg",
                      CommandKind::Secondary, /*overflow=*/true),
              }),
        group("map_decorate", "图件整饰",
              {
                  cmd("map.annotate", "标注", "menu-new.svg"),
                  cmd("map.legend", "图例", "rb-colorbar.svg",
                      CommandKind::Secondary, /*overflow=*/true),
              }),
        group("map_layout", "版式",
              {
                  cmd("map.template", "模板", "menu-properties.svg"),
                  cmd("map.paper", "纸张", "pane-maximize.svg",
                      CommandKind::Secondary, /*overflow=*/true),
                  cmd("map.preview", "预览", "menu-preview-settings.svg",
                      CommandKind::Secondary, /*overflow=*/true),
              }),
    };
}

// 验证不再是顶层工作区 —— 其命令词汇（verify.*）经命令注册表/面板
// dock 可达，不进编图静态带。

const std::vector<RibbonWorkspaceSpec>& specs_ref() {
    static const std::vector<RibbonWorkspaceSpec> specs =
        build_workspace_specs();
    return specs;
}

}  // namespace

const char* workspace_id(Workspace workspace) {
    for (const auto& row : kWorkspaceRows) {
        if (row.workspace == workspace) return row.id;
    }
    return "";
}

const char* workspace_label(Workspace workspace) {
    for (const auto& row : kWorkspaceRows) {
        if (row.workspace == workspace) return row.label;
    }
    return "";
}

std::optional<Workspace> workspace_from_id(const std::string& id) {
    for (const auto& row : kWorkspaceRows) {
        if (id == row.id) return row.workspace;
    }
    return std::nullopt;
}

std::optional<Workspace> workspace_from_label(const std::string& label) {
    for (const auto& row : kWorkspaceRows) {
        if (label == row.label) return row.workspace;
    }
    return std::nullopt;
}

std::optional<tool_policy::MappingStage> workspace_stage(
    Workspace workspace) {
    for (const auto& row : kWorkspaceRows) {
        if (row.workspace == workspace) return row.stage;
    }
    return std::nullopt;
}

std::optional<Workspace> workspace_for_stage(
    tool_policy::MappingStage stage) {
    // Two-page shell: every stage lives inside 编图 as a mode.
    for (const auto& known : tool_policy::kStageOrder) {
        if (known == stage) return Workspace::Authoring;
    }
    return std::nullopt;
}

const char* authoring_mode_command_id(tool_policy::MappingStage stage) {
    switch (stage) {
        case tool_policy::MappingStage::FaciesCalibration:
            return "mode.predict";
        case tool_policy::MappingStage::ConstraintFactor:
            return "mode.factor";
        case tool_policy::MappingStage::IntegratedCompilation:
            return "mode.author";
    }
    return nullptr;
}

std::optional<tool_policy::MappingStage> authoring_mode_for_command(
    const std::string& command_id) {
    for (const auto& stage : tool_policy::kStageOrder) {
        if (command_id == authoring_mode_command_id(stage)) return stage;
    }
    return std::nullopt;
}

std::vector<RibbonGroup> authoring_mode_groups(
    tool_policy::MappingStage stage) {
    switch (stage) {
        case tool_policy::MappingStage::FaciesCalibration:
            return predict_mode_groups();
        case tool_policy::MappingStage::ConstraintFactor:
            return factor_mode_groups();
        case tool_policy::MappingStage::IntegratedCompilation:
            return author_mode_groups();
    }
    return {};
}

const std::vector<RibbonWorkspaceSpec>& workspace_specs() {
    return specs_ref();
}

const RibbonWorkspaceSpec& workspace_spec(Workspace workspace) {
    const auto& specs = specs_ref();
    const auto index = static_cast<size_t>(workspace);
    return specs[index < specs.size() ? index : 0];
}

const RibbonWorkspaceSpec* find_workspace_spec(const std::string& id) {
    for (const auto& spec : specs_ref()) {
        if (id == workspace_id(spec.workspace)) return &spec;
    }
    return nullptr;
}

const RibbonCommand* find_command(Workspace workspace,
                                  const std::string& command_id) {
    for (const auto& group : workspace_spec(workspace).groups) {
        for (const auto& command : group.commands) {
            if (command.id == command_id) return &command;
        }
    }
    return nullptr;
}

// Every group the ribbon can render: the static workspace bands plus the
// three authoring-mode group sets (injected as context groups per mode).
std::vector<const RibbonGroup*> all_groups() {
    std::vector<const RibbonGroup*> groups;
    for (const auto& spec : specs_ref()) {
        for (const auto& group : spec.groups) {
            groups.push_back(&group);
        }
    }
    for (const auto& stage : tool_policy::kStageOrder) {
        // Static storage: the mode tables are constexpr-shaped constant
        // data — cache once so the pointers stay stable for callers.
        static const std::vector<RibbonGroup> mode_cache[] = {
            predict_mode_groups(), factor_mode_groups(),
            author_mode_groups()};
        for (const auto& group : mode_cache[static_cast<size_t>(stage)]) {
            groups.push_back(&group);
        }
    }
    return groups;
}

const RibbonCommand* find_command(const std::string& command_id) {
    for (const auto* group : all_groups()) {
        for (const auto& command : group->commands) {
            if (command.id == command_id) return &command;
        }
    }
    return nullptr;
}

const RibbonGroup* find_group(Workspace workspace,
                              const std::string& group_id) {
    for (const auto& group : workspace_spec(workspace).groups) {
        if (group.id == group_id) return &group;
    }
    return nullptr;
}

std::vector<std::string> table_integrity_problems() {
    std::vector<std::string> problems;
    std::set<std::string> seen_ids;
    for (const auto& spec : specs_ref()) {
        int primaries = 0;
        for (const auto& group : spec.groups) {
            for (const auto& command : group.commands) {
                if (!seen_ids.insert(command.id).second) {
                    problems.push_back("duplicate command id: " + command.id);
                }
                if (command.kind == CommandKind::Primary) ++primaries;
                if (command.text.empty()) {
                    problems.push_back("command without text: " + command.id);
                }
            }
            if (group.label.empty()) {
                problems.push_back("group without label: " + group.id);
            }
        }
        if (primaries != 1) {
            problems.push_back("workspace " +
                               std::string(workspace_id(spec.workspace)) +
                               " declares " + std::to_string(primaries) +
                               " primary commands (expected 1)");
        }
        const auto* primary = find_command(spec.primary_command_id);
        if (primary == nullptr) {
            problems.push_back("workspace " +
                               std::string(workspace_id(spec.workspace)) +
                               " primary '" + spec.primary_command_id +
                               "' does not resolve");
        } else if (primary->kind != CommandKind::Primary) {
            problems.push_back("workspace " +
                               std::string(workspace_id(spec.workspace)) +
                               " primary '" + spec.primary_command_id +
                               "' is not a Primary-kind command");
        }
    }
    // 编图模式组：id 与静态带同池唯一；每模式至多一个 Primary（编图模式
    // 的主动作是静态带的 map.export，不在模式组里重复声明）。
    for (const auto& stage : tool_policy::kStageOrder) {
        int mode_primaries = 0;
        for (const auto& group : authoring_mode_groups(stage)) {
            for (const auto& command : group.commands) {
                if (!seen_ids.insert(command.id).second) {
                    problems.push_back("duplicate command id: " +
                                       command.id);
                }
                if (command.kind == CommandKind::Primary) {
                    ++mode_primaries;
                }
                if (command.text.empty()) {
                    problems.push_back("command without text: " +
                                       command.id);
                }
            }
            if (group.label.empty()) {
                problems.push_back("group without label: " + group.id);
            }
        }
        if (mode_primaries > 1) {
            problems.push_back("authoring mode " +
                               std::string(tool_policy::stage_value(stage)) +
                               " declares " + std::to_string(mode_primaries) +
                               " primary commands (expected at most 1)");
        }
    }
    std::sort(problems.begin(), problems.end());
    return problems;
}

std::vector<std::string> commands_without_icon() {
    std::vector<std::string> missing;
    for (const auto* group : all_groups()) {
        for (const auto& command : group->commands) {
            if (command.icon.empty()) missing.push_back(command.id);
        }
    }
    return missing;
}

}  // namespace pwb::ui_ribbon
