// platform.toolpolicy.* — parameterized matrix over the canonical evaluator
// (Oracle 3): active/current/edit agreement, no-project, read-only provider,
// RAW/frozen gates, stage gating incl. fail-closed, dirty/capture/commit,
// undo/redo, selection facts, cancel exemption, checked derivation, and the
// QAction parity (pwb::ui::ToolActionSet projects the same verdicts).

#include <cstdio>

#include <QApplication>
#include <QString>

#include <pwb/tool_policy/tool_availability.hpp>
#include <pwb/tool_policy/stages.hpp>
#include <pwb/ui/tool_actions.hpp>

#include "test_framework.hpp"

using pwb::tool_policy::ToolContextSnapshot;
using pwb::tool_policy::ToolAvailability;
using pwb::tool_policy::evaluate_tool;
using pwb::tool_policy::evaluate_all;
using pwb::tool_policy::tool_ids;

namespace {

ToolContextSnapshot happy_editing_context() {
    ToolContextSnapshot ctx;
    ctx.project_open = true;
    ctx.qgis_available = true;
    ctx.native_canvas_available = true;
    ctx.backend_mode = "native";
    ctx.active_layer_id = "layer-1";
    ctx.active_layer_kind = "polygon";
    ctx.qgis_layer_type = "vector";
    ctx.vector_writable = true;
    ctx.edit_gate_open = true;
    ctx.editing = true;
    ctx.dirty = true;
    ctx.can_undo = true;
    ctx.selection_count = 1;
    ctx.provider_writable = true;
    ctx.provider_name = "ogr";
    ctx.capability_flags = {
        "qgis.native_tool.identify", "qgis.native_tool.select",
        "qgis.native_tool.addPoint", "qgis.native_tool.addLine",
        "qgis.native_tool.addPolygon", "qgis.native_tool.move",
        "qgis.native_tool.vertex", "qgis.geometry_op.validate",
        "qgis.geometry_op.reshape", "qgis.geometry_op.add_part",
    };
    return ctx;
}

void check_invariants(const ToolAvailability& verdict) {
    try {
        verdict.validate();
    } catch (const std::logic_error& e) {
        PWB_CHECK_MSG(false, e.what());
    }
}

}  // namespace

int main(int argc, char** argv) {
    QApplication app(argc, argv);

    // -- invariant sweep: every tool keeps the availability invariants -----
    {
        const ToolContextSnapshot ctx = happy_editing_context();
        const auto all = evaluate_all(ctx);
        PWB_CHECK(all.size() == tool_ids().size());
        for (const auto& [id, verdict] : all) check_invariants(verdict);
    }

    // -- happy editing: core edit surface enabled --------------------------
    {
        const ToolContextSnapshot ctx = happy_editing_context();
        PWB_CHECK(evaluate_tool("vertex", ctx).enabled);
        PWB_CHECK(evaluate_tool("move_feature", ctx).enabled);
        PWB_CHECK(evaluate_tool("add_polygon", ctx).enabled);
        PWB_CHECK(evaluate_tool("save_edits", ctx).enabled);
        PWB_CHECK(evaluate_tool("undo", ctx).enabled);
        PWB_CHECK(evaluate_tool("merge", ctx).enabled == false);  // merge_ready=false
        PWB_CHECK(evaluate_tool("toggle_editing", ctx).checked);  // editing
        PWB_CHECK(evaluate_tool("vertex", ctx).checked == false);  // current_tool=pan
    }

    // -- no project: everything structural is closed -----------------------
    {
        ToolContextSnapshot ctx = happy_editing_context();
        ctx.project_open = false;
        PWB_CHECK(!evaluate_tool("pan", ctx).enabled);
        PWB_CHECK(evaluate_tool("pan", ctx).disabled_reason == "未打开工程");
        PWB_CHECK(evaluate_tool("cancel", ctx).enabled);  // escape hatch
        PWB_CHECK(!evaluate_tool("toggle_editing", ctx).enabled);
    }

    // -- active/current/edit agreement: no active layer --------------------
    {
        ToolContextSnapshot ctx = happy_editing_context();
        ctx.active_layer_id.clear();
        PWB_CHECK(!evaluate_tool("toggle_editing", ctx).enabled);
        PWB_CHECK(evaluate_tool("toggle_editing", ctx).disabled_reason
                  == "没有活动的矢量图层");
        PWB_CHECK(!evaluate_tool("vertex", ctx).enabled);
        // layer/symbology groups hidden entirely
        PWB_CHECK(!evaluate_tool("layer_properties", ctx).visible);
        PWB_CHECK(!evaluate_tool("symbology", ctx).visible);
        PWB_CHECK(evaluate_tool("layer_new", ctx).visible);
        PWB_CHECK(evaluate_tool("layer_new", ctx).enabled);
    }

    // -- read-only provider: fail-closed with the provider wording --------
    {
        ToolContextSnapshot ctx = happy_editing_context();
        ctx.provider_writable = false;
        const ToolAvailability verdict = evaluate_tool("toggle_editing", ctx);
        PWB_CHECK(!verdict.enabled);
        PWB_CHECK(verdict.disabled_reason.find("图层 provider（ogr）不支持编辑")
                  != std::string::npos);
        PWB_CHECK(verdict.severity.has_value() && *verdict.severity == "warning");
        ctx.provider_writable_approximate = true;
        const ToolAvailability approx = evaluate_tool("toggle_editing", ctx);
        PWB_CHECK(approx.disabled_reason.find("判据为近似") != std::string::npos);
    }

    // -- RAW / frozen role gates -------------------------------------------
    {
        ToolContextSnapshot ctx = happy_editing_context();
        ctx.edit_gate_open = false;
        ctx.raw_locked = true;
        const ToolAvailability verdict = evaluate_tool("toggle_editing", ctx);
        PWB_CHECK(!verdict.enabled);
        PWB_CHECK(verdict.disabled_reason
                  == "RAW 图层不可变，请创建 DERIVED 草稿后编辑");
        PWB_CHECK(verdict.severity.has_value() && *verdict.severity == "warning");
        PWB_CHECK(verdict.remediation.has_value()
                  && *verdict.remediation == "创建 DERIVED 草稿后编辑");
        ctx.raw_locked = false;
        ctx.layer_frozen = true;
        PWB_CHECK(evaluate_tool("toggle_editing", ctx).disabled_reason
                  == "当前结果已冻结——需先解除冻结或另存草稿");
    }

    // -- editing session states ---------------------------------------------
    {
        ToolContextSnapshot ctx = happy_editing_context();
        ctx.editing = false;
        PWB_CHECK(!evaluate_tool("save_edits", ctx).enabled);
        PWB_CHECK(evaluate_tool("save_edits", ctx).disabled_reason
                  == "需要先开始编辑");
        ctx.editing = true;
        ctx.dirty = false;
        PWB_CHECK(evaluate_tool("save_edits", ctx).disabled_reason
                  == "编辑会话没有未保存的修改");
        PWB_CHECK(evaluate_tool("rollback", ctx).disabled_reason
                  == "编辑会话没有可回滚的修改");
        ctx.dirty = true;
        ctx.can_undo = false;
        PWB_CHECK(evaluate_tool("undo", ctx).disabled_reason == "没有可撤销的操作");
        ctx.can_undo = true;
        ctx.can_redo = false;
        PWB_CHECK(evaluate_tool("redo", ctx).disabled_reason == "没有可重做的操作");
    }

    // -- capture kind gating + stage restriction ----------------------------
    {
        ToolContextSnapshot ctx = happy_editing_context();
        ctx.active_layer_kind = "line";
        PWB_CHECK(evaluate_tool("add_polygon", ctx).disabled_reason.find(
            "仅对面图层有效") != std::string::npos);
        ctx.active_layer_kind.clear();
        PWB_CHECK(evaluate_tool("add_line", ctx).disabled_reason
                  == "活动图层几何类型未知——不能确定可用的捕获工具");

        // stage gating: facies_calibration has no add_line in edit_actions
        ToolContextSnapshot staged = happy_editing_context();
        staged.mapping_stage = "facies_calibration";
        PWB_CHECK(!evaluate_tool("add_line", staged).visible);   // governed + filtered
        PWB_CHECK(evaluate_tool("add_polygon", staged).visible);
        staged.mapping_stage = "constraint_factor";
        PWB_CHECK(evaluate_tool("add_line", staged).visible);
        staged.mapping_stage = "unknown_stage";
        PWB_CHECK(!evaluate_tool("add_line", staged).visible);
        PWB_CHECK(evaluate_tool("add_line", staged).disabled_reason
                  == "当前编图阶段未知——仅保留基础工具组");
        PWB_CHECK(evaluate_tool("cancel", staged).visible);      // cancel exempt
        PWB_CHECK(evaluate_tool("pan", staged).enabled);
        // factor group hidden on facies_calibration; whitelist words
        staged.mapping_stage = "facies_calibration";
        const ToolAvailability fw = evaluate_tool("factor_workbench", staged);
        PWB_CHECK(!fw.enabled);
        PWB_CHECK(fw.disabled_reason.find("当前阶段不允许该操作（限 ② 约束与单因素）")
                  == 0);
        staged.mapping_stage = "";   // explicit unknown: fail closed too
        PWB_CHECK(!evaluate_tool("add_line", staged).visible);
    }

    // -- blocking task / topology errors / committing -----------------------
    {
        ToolContextSnapshot ctx = happy_editing_context();
        ctx.blocking_task = "importing";
        PWB_CHECK(!evaluate_tool("vertex", ctx).enabled);
        PWB_CHECK(evaluate_tool("vertex", ctx).disabled_reason
                  == "后台任务进行中：importing");
        PWB_CHECK(evaluate_tool("cancel", ctx).enabled);
        ctx.blocking_task.clear();
        ctx.topology_error_count = 2;
        PWB_CHECK(evaluate_tool("merge", ctx).disabled_reason
                  == "当前编辑会话存在拓扑错误，不能合并");
        ctx.topology_error_count = 0;
        ctx.selection_count = 0;
        PWB_CHECK(evaluate_tool("delete_selected", ctx).disabled_reason
                  == "没有选中的要素");
    }

    // -- checked derivation ---------------------------------------------------
    {
        ToolContextSnapshot ctx = happy_editing_context();
        ctx.current_tool = "vertex";
        PWB_CHECK(evaluate_tool("vertex", ctx).checked);
        PWB_CHECK(!evaluate_tool("move_feature", ctx).checked);
        ctx.snapping_enabled = true;
        PWB_CHECK(evaluate_tool("snapping", ctx).checked);
        ctx.vertex_all_layers = false;
        PWB_CHECK(!evaluate_tool("vertex_scope", ctx).checked);
        ctx.topology_enabled = true;
        PWB_CHECK(evaluate_tool("topology", ctx).checked);
    }

    // -- unknown tool + QAction parity (Oracle 3) -----------------------------
    {
        const ToolContextSnapshot ctx = happy_editing_context();
        const ToolAvailability unknown = evaluate_tool("no_such_tool", ctx);
        PWB_CHECK(!unknown.visible);
        PWB_CHECK(!unknown.enabled);
        PWB_CHECK(unknown.disabled_reason.find("未知工具") == 0);

        pwb::ui::ToolActionSet action_set;
        const auto all = evaluate_all(ctx);
        action_set.apply(all);
        int parity_failures = 0;
        for (const std::string& id : tool_ids()) {
            const QAction* act = action_set.action(id);
            if (act == nullptr) { ++parity_failures; continue; }
            const ToolAvailability& verdict = all.at(id);
            if (act->isEnabled() != verdict.enabled) ++parity_failures;
            if (act->isChecked() != verdict.checked) ++parity_failures;
            const QString tooltip = act->toolTip();
            if (verdict.disabled_reason.empty()
                ? !tooltip.isEmpty()
                : tooltip.toStdString() != verdict.disabled_reason) {
                ++parity_failures;
            }
        }
        PWB_CHECK_MSG(parity_failures == 0,
            "QAction state diverged from policy output");
    }

    return ::pwb::test::report("platform.toolpolicy.matrix");
}
