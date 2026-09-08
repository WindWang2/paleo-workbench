"""M4 — 工具帮助静态登记处（纯数据，无 Qt）。

``TOOL_LABELS`` / ``TOOL_SHORTCUTS`` / ``TOOL_HELP`` 是 45 个工具的名称、
快捷键与帮助事实的唯一登记处。放在 mapping 层的叶子模块（而不是
``ui.workstation`` 包内）是因为该包的 ``__init__`` 饿加载 shell →
composite_document → map_action_controller——controller 从包内取词表会
成环（review 后全量套件抓到的 import cycle）。

动态派生（explain/format_*）在 ``ui.workstation.action_help``。
"""
from __future__ import annotations

from dataclasses import dataclass

from paleo_workbench.mapping.tool_availability import TOOL_IDS  # noqa: F401 — 完整性由测试钉

__all__ = ["TOOL_HELP", "TOOL_LABELS", "TOOL_SHORTCUTS", "ToolHelpSpec"]


#: 工具名（唯一词表；MapActionController 的标签从此派生）。
TOOL_LABELS: dict[str, str] = {
    "pan": "平移", "zoom_in": "放大", "zoom_out": "缩小",
    "full_extent": "全图", "previous_extent": "上一视图", "next_extent": "下一视图",
    "refresh": "刷新", "identify": "识别", "select": "选择",
    "select_rectangle": "框选", "measure_distance": "测距",
    "clear_selection": "清除选择", "select_all": "全选", "invert_selection": "反选",
    "toggle_editing": "开始编辑", "save_edits": "保存编辑", "rollback": "回滚",
    "add_point": "添加点", "add_line": "添加线", "add_polygon": "添加面",
    "move_feature": "移动要素", "vertex": "节点编辑", "delete_selected": "删除所选",
    "reshape": "重塑",
    "undo": "撤销", "redo": "重做", "split": "分割", "merge": "合并",
    "repair_geometry": "修复几何",
    "snapping": "捕捉", "topology": "拓扑编辑", "cancel": "取消",
    "layer_new": "新建图层", "reference_import": "导入参考图层",
    "layer_properties": "图层属性", "attribute_table": "属性表",
    "layer_zoom": "缩放到图层", "layer_export": "导出图层",
    "symbology": "符号系统", "style_manager": "样式库",
    "factor_workbench": "单因素工作台", "factor_overlay": "叠加等值线",
    "qa_run": "运行 QC", "map_product_assemble": "生成成果",
    "map_export": "导出图面",
}

#: 快捷键（真源在 QAction 注册处；此处为帮助文本的镜像，测试钉一致）。
TOOL_SHORTCUTS: dict[str, str] = {
    "save_edits": "Ctrl+S",
    "delete_selected": "Delete",
    "undo": "Ctrl+Z",
    "redo": "Ctrl+Shift+Z",
    "cancel": "Esc",
}


@dataclass(frozen=True, slots=True)
class ToolHelpSpec:
    """一个工具的静态帮助事实（登记处；不包含任何可用性判断）。"""

    label: str
    requirements: str          # 所需前置条件（人类可读）
    impact: str                # 执行影响
    modifies_data: bool        # 是否修改图层/工程数据
    creates_version: bool      # 是否生成新版本工件
    background_task: bool      # 是否进入后台任务
    stages: str                # 适用阶段（呈现词；"全部" = 不限）
    layer_kinds: str           # 适用图层类型（呈现词）


_ALL = "全部"
_VECTOR = "矢量图层"
_ANY_LAYER = "任意图层"
_NAV = "导航/查看；不修改数据"


def _spec(label: str, requirements: str, impact: str, *, modifies=False,
          version=False, task=False, stages=_ALL, kinds=_VECTOR) -> ToolHelpSpec:
    return ToolHelpSpec(label, requirements, impact, modifies, version, task, stages, kinds)


TOOL_HELP: dict[str, ToolHelpSpec] = {
    "pan": _spec("平移", "已打开工程", _NAV, kinds=_ANY_LAYER),
    "zoom_in": _spec("放大", "已打开工程", _NAV, kinds=_ANY_LAYER),
    "zoom_out": _spec("缩小", "已打开工程", _NAV, kinds=_ANY_LAYER),
    "full_extent": _spec("全图", "已打开工程", "视图回到工区全幅；不修改数据", kinds=_ANY_LAYER),
    "previous_extent": _spec("上一视图", "存在可回退的视图历史", "视图回退一步；不修改数据", kinds=_ANY_LAYER),
    "next_extent": _spec("下一视图", "存在可前进的视图历史", "视图前进一步；不修改数据", kinds=_ANY_LAYER),
    "refresh": _spec("刷新", "已打开工程", "重绘画布；不修改数据", kinds=_ANY_LAYER),
    "identify": _spec("识别", "有活动图层", "点击查询要素属性（只读）；不修改数据", kinds=_ANY_LAYER),
    "select": _spec("选择", "有活动矢量图层", "点选要素；只改选择集，不改数据", kinds=_VECTOR),
    "select_rectangle": _spec("框选", "有活动矢量图层", "框选要素；只改选择集，不改数据", kinds=_VECTOR),
    "measure_distance": _spec("测距", "有活动图层", "量测距离（原生椭球或降级平面）；不修改数据", kinds=_ANY_LAYER),
    "clear_selection": _spec("清除选择", "有选中的要素", "清空选择集；不修改数据", kinds=_VECTOR),
    "select_all": _spec("全选", "有活动矢量图层", "全选要素；只改选择集，不改数据", kinds=_VECTOR),
    "invert_selection": _spec("反选", "有选中的要素", "反选要素；只改选择集，不改数据", kinds=_VECTOR),
    "toggle_editing": _spec(
        "开始编辑", "活动矢量图层可写且通过角色门禁（RAW/冻结/锁定不可编辑）",
        "开启/结束编辑会话（结束即保存）", modifies=True),
    "save_edits": _spec(
        "保存编辑", "编辑会话中有未保存修改",
        "提交本会话修改到图层（生成会话撤销记录）", modifies=True, version=True),
    "rollback": _spec(
        "回滚", "编辑会话中有可回滚修改",
        "丢弃本会话全部未保存修改", modifies=True),
    "add_point": _spec(
        "添加点", "编辑会话中 + 点图层 + 角色门禁通过",
        "在画布采点写入活动图层", modifies=True),
    "add_line": _spec(
        "添加线", "编辑会话中 + 线图层 + 角色门禁通过",
        "在画布采线写入活动图层", modifies=True),
    "add_polygon": _spec(
        "添加面", "编辑会话中 + 面图层 + 角色门禁通过",
        "在画布采面写入活动图层", modifies=True),
    "move_feature": _spec(
        "移动要素", "编辑会话中 + 已选中要素",
        "拖动改变要素位置", modifies=True),
    "vertex": _spec(
        "节点编辑", "编辑会话中 + 已选中要素",
        "增删移要素节点", modifies=True),
    "delete_selected": _spec(
        "删除所选", "编辑会话中 + 已选中要素",
        "删除选中要素（会话内可撤销）", modifies=True),
    "reshape": _spec(
        "重塑", "原生 QGIS 画布 + 线/面图层 + 恰好选中 1 个要素 + 编辑会话",
        "用数字化线重塑选中要素边界（QGIS 原生算子）", modifies=True),
    "split": _spec(
        "分割", "编辑会话中的面图层 + 选中多边形 + 选中的切割线",
        "沿切割线分割多边形（QGIS/shapely 双引擎）", modifies=True),
    "merge": _spec(
        "合并", "同一可编辑面图层至少选中 2 个兼容多边形 + 无拓扑错误",
        "合并选中面要素（QGIS/shapely 双引擎）", modifies=True),
    "repair_geometry": _spec(
        "修复几何", "可写面图层 + 角色门禁通过",
        "对面图层执行 make-valid 修复（可撤销）", modifies=True),
    "undo": _spec("撤销", "编辑会话中有可撤销操作", "撤销上一步编辑", modifies=True),
    "redo": _spec("重做", "编辑会话中有可重做操作", "重做被撤销的编辑", modifies=True),
    "snapping": _spec(
        "捕捉", "有活动图层",
        "开关采点/编辑捕捉（endpoint/intersection 由桥能力决定）", kinds=_VECTOR),
    "topology": _spec(
        "拓扑编辑", "有活动图层 + 工程 CRS 有效",
        "开关拓扑编辑；保存时执行拓扑校验", modifies=True, kinds=_VECTOR),
    "cancel": _spec("取消", "无", "取消当前工具/Esc 数字化", kinds=_ANY_LAYER),
    "layer_new": _spec("新建图层", "已打开工程", "新建空白矢量图层（按模板）", modifies=True),
    "reference_import": _spec(
        "导入参考图层", "已打开工程",
        "导入外部 GDAL 参考层（只读；不修改源文件）", stages=_ALL, kinds=_ANY_LAYER),
    "layer_properties": _spec(
        "图层属性", "有活动图层", "打开图层属性/符号编辑", stages=_ALL, kinds=_ANY_LAYER),
    "attribute_table": _spec(
        "属性表", "有活动图层", "打开只读/编辑属性表", stages=_ALL, kinds=_ANY_LAYER),
    "layer_zoom": _spec(
        "缩放到图层", "有活动图层", "视图缩放到图层范围", stages=_ALL, kinds=_ANY_LAYER),
    "layer_export": _spec(
        "导出图层", "有活动图层", "导出图层为 GeoJSON/Shapefile", stages=_ALL, kinds=_ANY_LAYER),
    "symbology": _spec(
        "符号系统", "有活动图层", "打开符号系统设置（不改几何数据）", stages=_ALL, kinds=_ANY_LAYER),
    "style_manager": _spec(
        "样式库", "QGIS 原生后端 + 有活动图层",
        "打开 QGIS 原生样式库管理", stages=_ALL, kinds=_ANY_LAYER),
    "factor_workbench": _spec(
        "单因素工作台", "阶段② 约束与因素", "打开单因素图生成工作台（后台任务）",
        task=True, stages="② 约束与因素", kinds=_ANY_LAYER),
    "factor_overlay": _spec(
        "叠加等值线", "阶段② 约束与因素", "把因素结果叠加为参考层", modifies=True,
        stages="② 约束与因素", kinds=_ANY_LAYER),
    "qa_run": _spec(
        "运行 QC", "已打开工程", "运行图面质量检查（只读诊断）", stages=_ALL, kinds=_ANY_LAYER),
    "map_product_assemble": _spec(
        "生成成果", "阶段③ 综合编图", "组装综合编图成果（生成新版本工件）",
        modifies=True, version=True, task=True, stages="③ 综合编图", kinds=_ANY_LAYER),
    "map_export": _spec(
        "导出图面", "阶段③ 综合编图", "进入图面组装与导出（review 页）",
        stages="③ 综合编图", kinds=_ANY_LAYER),
}


@dataclass(frozen=True, slots=True)
class ActionExplanation:
    """某上下文下某动作的完整可解释记录（全部字段可渲染）。"""

    tool_id: str
    label: str
    availability: ToolAvailability
    requirements: str
    missing: str            # 当前缺失条件（= evaluator 判词；可用时空）
    impact: str
    modifies_data: bool
    creates_version: bool
    background_task: bool
    shortcut: str
    stages: str
    layer_kinds: str
    current_layer: str      # 当前活动图层名（呈现）
    current_stage: str      # 当前阶段（呈现）

    @property
    def available(self) -> bool:
        return self.availability.enabled


def _stage_caption(value: str | None) -> str:
    if value is None:
        return "无阶段语义（legacy 表面）"
    from paleo_workbench.mapping_workspace.stages import stage_from_value

    stage = stage_from_value(value)
    return stage.label if stage is not None else f"未知阶段（{value!r}）"


def explain(tool_id: str, ctx: ToolContext, *, layer_name: str = "") -> ActionExplanation:
    """组装一个动作的上下文帮助（动态结论全部来自 canonical evaluator）。"""
    spec = TOOL_HELP.get(tool_id)
    if spec is None:
        spec = ToolHelpSpec(
            label=tool_id, requirements="未知工具", impact="—",
            modifies_data=False, creates_version=False, background_task=False,
            stages="—", layer_kinds="—",
        )
    availability = evaluate_tool(tool_id, ctx)
    return ActionExplanation(
        tool_id=tool_id,
        label=spec.label,
        availability=availability,
        requirements=spec.requirements,
        missing=availability.disabled_reason,
        impact=spec.impact,
        modifies_data=spec.modifies_data,
        creates_version=spec.creates_version,
        background_task=spec.background_task,
        shortcut=TOOL_SHORTCUTS.get(tool_id, ""),
        stages=spec.stages,
        layer_kinds=spec.layer_kinds,
        current_layer=layer_name or ctx.layer_name,
        current_stage=_stage_caption(ctx.mapping_stage),
    )


