#include "pwb/ui_ribbon/ribbon_spec.hpp"

#include <algorithm>
#include <set>

namespace pwb::ui_ribbon {

namespace {

// Chinese display labels — the prototype's five page titles verbatim
// (prototypes/qt_ribbon_native/main.cpp:10); they double as the stage
// labels for the middle three (tool_policy::stage_label parity).
constexpr const char* kLabelDataManagement = "数据管理";
constexpr const char* kLabelIntelligentPrediction = "1 智能预测";
constexpr const char* kLabelConstraintFactor = "2 约束与单因素";
constexpr const char* kLabelIntegratedCompilation = "3 综合编图";
constexpr const char* kLabelValidation = "验证";

struct WorkspaceRow {
    Workspace workspace;
    const char* id;
    const char* label;
    // nullopt for 数据管理/验证 (D1: no stage).
    std::optional<tool_policy::MappingStage> stage;
};

constexpr std::array<WorkspaceRow, 5> kWorkspaceRows = {{
    {Workspace::DataManagement, "data_management", kLabelDataManagement,
     std::nullopt},
    {Workspace::IntelligentPrediction, "intelligent_prediction",
     kLabelIntelligentPrediction,
     tool_policy::MappingStage::FaciesCalibration},
    {Workspace::ConstraintFactor, "constraint_factor", kLabelConstraintFactor,
     tool_policy::MappingStage::ConstraintFactor},
    {Workspace::IntegratedCompilation, "integrated_compilation",
     kLabelIntegratedCompilation,
     tool_policy::MappingStage::IntegratedCompilation},
    {Workspace::Validation, "validation", kLabelValidation, std::nullopt},
}};

// ---------------------------------------------------------------------------
// The command group table. Group structure per prototype page
// (prototypes/qt_ribbon_native/main.cpp:200-205): 数据管理 5 groups,
// 智能预测 4, 约束与单因素 5, 综合编图 5, 验证 5. Command ids are
// semantic placeholders (M4 rebinds them to the real CommandRegistry
// ids); icon names reference the repo SVG assets resolved through
// ui_widgets::workstation_icon (dev tree: paleo_workbench/ui/assets/icons
// via the platform_services resource locator; M6 closed the declared
// map.opacity gap with rb-opacity.svg in the same linear style).
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
                      cmd("data.plan", "导入计划", "menu-properties.svg"),
                  }),
            // 稿：整理 = 关联到井/设置角色/标签（独立组）。
            group("data_organize", "整理",
                  {
                      cmd("data.link_well", "关联到井", "rb-link.svg"),
                      cmd("data.set_role", "设置角色", "rb-settings.svg"),
                      cmd("data.tags", "标签", "menu-new.svg"),
                  }),
            group("data_quality", "质量检查",
                  {
                      cmd("data.check", "检查数据", "rb-qc.svg"),
                      cmd("data.units", "单位与坐标", "rb-grid.svg"),
                  }),
            group("data_version", "版本与关联",
                  {
                      cmd("data.history", "版本历史", "refresh-cw.svg"),
                      cmd("data.lineage", "来源关系", "rb-auto-link.svg"),
                      cmd("data.impact", "影响分析", "rb-analysis.svg"),
                  }),
            group("data_output", "输出",
                  {
                      cmd("data.export_table", "导出", "rb-export.svg"),
                      cmd("data.trash", "回收站", "map/cancel.svg"),
                  }),
        }});

    // ---- 1 智能预测 — primary: 运行预测 ------------------------------------
    specs.push_back(RibbonWorkspaceSpec{
        Workspace::IntelligentPrediction,
        "predict.run",
        {
            group("predict_input", "输入与模型",
                  {
                      cmd("predict.select_well", "选择井数据", "well-log.svg"),
                      cmd("predict.select_seismic", "选择地震", "seismic.svg"),
                      // 稿：模型版本下拉（相预测 v2 ▼）——命令表无
                      // combo 类型，以带 ▾ 的次级命令呈现。
                      cmd("predict.model_params", "相预测 v2 ▾",
                          "rb-settings.svg"),
                  }),
            group("predict_run", "预测运行",
                  {
                      cmd("predict.run", "运行预测", "rb-run.svg",
                          CommandKind::Primary),
                      cmd("predict.cancel", "取消", "map/cancel.svg"),
                      cmd("predict.params", "参数", "menu-preview-settings.svg"),
                  }),
            group("predict_overlay", "叠加对照",
                  {
                      cmd("predict.overlay_seismic", "地震叠加", "rb-slice.svg"),
                      cmd("predict.overlay_well", "测井叠加", "rb-dtw.svg"),
                      cmd("predict.link", "联动", "rb-link.svg",
                          CommandKind::Toggle),
                  }),
            group("predict_result", "结果",
                  {
                      cmd("predict.save", "保存结果", "menu-save.svg"),
                      cmd("predict.submit", "送交验证", "rb-send.svg"),
                  }),
        }});

    // ---- 2 约束与单因素 — primary: 计算单因素 ------------------------------
    specs.push_back(RibbonWorkspaceSpec{
        Workspace::ConstraintFactor,
        "factor.compute",
        {
            group("factor_constraints", "约束编辑",
                  {
                      cmd("factor.edit_sourcing", "编辑物源线", "rb-fence.svg"),
                      cmd("factor.edit_trend", "展布线", "rb-analysis.svg"),
                      // 稿：约束点与捕捉并列于约束编辑组。
                      cmd("factor.constraint_point", "约束点",
                          "map/add_point.svg"),
                      cmd("factor.snap", "捕捉", "map/snapping.svg",
                          CommandKind::Toggle),
                  }),
            group("factor_interpolate", "插值计算",
                  {
                      // 稿：方法下拉（约束IDW ▼）+ 参数 + 计算单因素；
                      // 命令表无 combo 类型，以带 ▾ 的次级命令呈现。
                      cmd("factor.method", "约束IDW ▾", "rb-generate.svg",
                          CommandKind::Secondary),
                      cmd("factor.compute", "计算单因素", "rb-generate.svg",
                          CommandKind::Primary),
                      cmd("factor.params", "参数", "menu-preview-settings.svg",
                          CommandKind::Secondary),
                  }),
            group("factor_crosswell", "连井分析",
                  {
                      cmd("factor.select_wells", "选井", "well-log.svg"),
                      // 稿：连井剖面（原「连井路径」措辞与稿不符）。
                      cmd("factor.crosswell_path", "连井剖面", "sequence.svg"),
                      cmd("factor.link", "联动", "rb-link.svg",
                          CommandKind::Toggle),
                  }),
            group("factor_contour", "等值线",
                  {
                      cmd("factor.contour", "生成等值线",
                          "map/btn-contour-draft.svg"),
                      // 稿：间距数值控件（20 m）——以禁用的次级
                      // 命令占位呈现。
                      cmd("factor.contour_interval", "间距 20 m",
                          "map/btn-contour-draft.svg",
                          CommandKind::Secondary),
                  }),
            group("factor_result", "结果",
                  {
                      cmd("factor.save", "保存版本", "map/btn-save-draft.svg"),
                      cmd("factor.submit", "送交验证", "rb-send.svg"),
                  }),
        }});

    // ---- 3 综合编图 — primary: 导出图件 ------------------------------------
    specs.push_back(RibbonWorkspaceSpec{
        Workspace::IntegratedCompilation,
        "map.export",
        {
            group("map_facies", "相界编辑",
                  {
                      cmd("map.select", "选择", "map/select_rectangle.svg"),
                      cmd("map.edit_facies", "编辑相界", "map/change_facies.svg"),
                      // 稿：撤消并列于相界编辑。
                      cmd("map.undo", "撤消", "map/undo.svg"),
                  }),
            group("map_reference", "参考图",
                  {
                      cmd("map.show_reference", "显示参考图", "preparation.svg",
                          CommandKind::Toggle),
                      // 稿：参考图与主图联动开关。
                      cmd("map.ref_link", "联动", "rb-link.svg",
                          CommandKind::Toggle),
                      cmd("map.opacity", "透明度", "rb-opacity.svg"),
                  }),
            group("map_decorate", "图件整饰",
                  {
                      cmd("map.annotate", "标注", "menu-new.svg"),
                      cmd("map.north_arrow", "指北针", "map/panel-chrome.svg"),
                      cmd("map.legend", "图例", "rb-colorbar.svg"),
                  }),
            group("map_layout", "版式",
                  {
                      cmd("map.template", "模板", "menu-properties.svg"),
                      cmd("map.paper", "纸张", "pane-maximize.svg"),
                      cmd("map.preview", "预览", "menu-preview-settings.svg"),
                  }),
            group("map_output", "输出",
                  {
                      cmd("map.export", "导出图件", "rb-export.svg",
                          CommandKind::Primary),
                      cmd("map.save_plan", "保存方案", "map/btn-save-draft.svg"),
                      cmd("map.submit", "送交验证", "rb-send.svg"),
                  }),
        }});

    // ---- 验证 — primary: 运行验证 ------------------------------------------
    specs.push_back(RibbonWorkspaceSpec{
        Workspace::Validation,
        "verify.run",
        {
            group("verify_objects", "对象与基准",
                  {
                      // 稿：两个带 ▾ 的字段选择下拉（对象/基准）——
                      // 命令表无 combo，以 ▾ 次级命令呈现。
                      cmd("verify.select_object", "对象 ▾", "inbox.svg"),
                      cmd("verify.select_baseline", "基准 ▾", "data.svg"),
                  }),
            group("verify_compare", "联动对比",
                  {
                      // 稿：◀◀ 上一处问题导航 + 联动光标 + 并排/叠加/差异。
                      cmd("verify.prev_issue", "上一处", "map/previous_extent.svg",
                          CommandKind::Secondary),
                      cmd("verify.link", "联动光标", "rb-link.svg",
                          CommandKind::Toggle),
                      cmd("verify.side_by_side", "并排", "pane-restore.svg"),
                      cmd("verify.overlay", "叠加", "rb-slice.svg"),
                      cmd("verify.difference", "差异", "rb-demo.svg"),
                  }),
            group("verify_check", "检查",
                  {
                      cmd("verify.run", "运行验证", "rb-run.svg",
                          CommandKind::Primary),
                      cmd("verify.settings", "检查设置", "rb-settings.svg"),
                      cmd("verify.cancel", "取消", "map/cancel.svg"),
                  }),
            group("verify_review", "复核",
                  {
                      cmd("verify.locate", "定位问题", "menu-search.svg"),
                      cmd("verify.record", "记录结论", "review.svg"),
                  }),
            group("verify_report", "报告",
                  {
                      cmd("verify.save_record", "保存记录", "menu-save.svg"),
                      cmd("verify.export_report", "导出报告",
                          "rb-export.svg"),
                  }),
        }});

    return specs;
}

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
    for (const auto& row : kWorkspaceRows) {
        if (row.stage == stage) return row.workspace;
    }
    return std::nullopt;
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

const RibbonCommand* find_command(const std::string& command_id) {
    for (const auto& spec : specs_ref()) {
        for (const auto& group : spec.groups) {
            for (const auto& command : group.commands) {
                if (command.id == command_id) return &command;
            }
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
    std::sort(problems.begin(), problems.end());
    return problems;
}

std::vector<std::string> commands_without_icon() {
    std::vector<std::string> missing;
    for (const auto& spec : specs_ref()) {
        for (const auto& group : spec.groups) {
            for (const auto& command : group.commands) {
                if (command.icon.empty()) missing.push_back(command.id);
            }
        }
    }
    return missing;
}

}  // namespace pwb::ui_ribbon
