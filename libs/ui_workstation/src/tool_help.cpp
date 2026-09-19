#include "pwb/ui_workstation/tool_help.hpp"

namespace pwb::ui_workstation {

namespace {

constexpr const char* kAll = "全部";
constexpr const char* kVector = "矢量图层";
constexpr const char* kAnyLayer = "任意图层";
constexpr const char* kNav = "导航/查看；不修改数据";

ToolHelpSpec spec(std::string label, std::string requirements,
                  std::string impact, bool modifies = false,
                  bool version = false, bool task = false,
                  std::string stages = kAll, std::string kinds = kVector) {
    return ToolHelpSpec{std::move(label), std::move(requirements),
                        std::move(impact), modifies, version, task,
                        std::move(stages), std::move(kinds)};
}

}  // namespace

const std::map<std::string, std::string>& tool_labels() {
    static const std::map<std::string, std::string> labels = {
        {"pan", "平移"}, {"zoom_in", "放大"}, {"zoom_out", "缩小"},
        {"full_extent", "全图"}, {"previous_extent", "上一视图"},
        {"next_extent", "下一视图"},
        {"refresh", "刷新"}, {"identify", "识别"}, {"select", "选择"},
        {"select_rectangle", "框选"}, {"measure_distance", "测距"},
        {"clear_selection", "清除选择"}, {"select_all", "全选"},
        {"invert_selection", "反选"},
        {"toggle_editing", "开始编辑"}, {"save_edits", "保存编辑"},
        {"rollback", "回滚"},
        {"add_point", "添加点"}, {"add_line", "添加线"},
        {"add_polygon", "添加面"},
        {"move_feature", "移动要素"}, {"vertex", "节点编辑"},
        {"delete_selected", "删除所选"}, {"reshape", "重塑"},
        {"undo", "撤销"}, {"redo", "重做"}, {"split", "分割"},
        {"merge", "合并"},
        // V10 complex-geometry/feature command family.
        {"duplicate_selected", "复制要素"}, {"add_ring", "添加内环"},
        {"add_part", "添加部件"}, {"explode_multipart", "拆分多部件"},
        {"collect_multipart", "组合多部件"},
        {"repair_geometry", "修复几何"},
        {"snapping", "捕捉"}, {"topology", "拓扑编辑"},
        {"cancel", "取消"},
        {"avoid_intersections", "避免重叠"}, {"tracing", "追踪"},
        {"vertex_scope", "顶点范围"},
        {"fault_cut", "断层切割"}, {"boundary_reshape", "共边重塑"},
        {"delete_ring", "删除内环"}, {"delete_part", "删除部件"},
        {"reverse_line", "反转方向"}, {"simplify_feature", "简化要素"},
        {"smooth_feature", "平滑要素"}, {"offset_curve", "偏移曲线"},
        {"rotate_feature", "旋转要素"}, {"scale_feature", "缩放要素"},
        {"cut_features", "剪切"}, {"copy_features", "复制"},
        {"paste_features", "粘贴"},
        {"add_rectangle", "添加矩形"}, {"add_circle", "添加圆"},
        {"snap_geometries", "吸附对齐"},
        {"add_arc", "添加圆弧"},
        {"add_regular_polygon", "添加正多边形"},
        {"trim_line", "修剪线"}, {"extend_line", "延伸线"},
        {"fill_ring", "填充内环"}, {"add_ellipse", "添加椭圆"},
        {"add_sector", "添加扇形"}, {"change_facies", "更改相"},
        {"layer_new", "新建图层"},
        {"reference_import", "导入参考图层"},
        {"layer_properties", "图层属性"},
        {"attribute_table", "属性表"},
        {"layer_zoom", "缩放到图层"}, {"layer_export", "导出图层"},
        {"symbology", "符号系统"}, {"style_manager", "样式库"},
        {"factor_workbench", "单因素工作台"},
        {"factor_overlay", "叠加等值线"},
        {"qa_run", "运行 QC"}, {"map_product_assemble", "生成成果"},
        {"map_export", "导出图面"},
    };
    return labels;
}

const std::map<std::string, std::string>& tool_shortcuts() {
    static const std::map<std::string, std::string> shortcuts = {
        {"save_edits", "Ctrl+S"},
        {"delete_selected", "Delete"},
        {"undo", "Ctrl+Z"},
        {"redo", "Ctrl+Shift+Z"},
        {"cancel", "Esc"},
    };
    return shortcuts;
}

const std::map<std::string, ToolHelpSpec>& tool_help() {
    static const std::map<std::string, ToolHelpSpec> help = {
        {"pan", spec("平移", "已打开工程", kNav, false, false, false, kAll, kAnyLayer)},
        {"zoom_in", spec("放大", "已打开工程", kNav, false, false, false, kAll, kAnyLayer)},
        {"zoom_out", spec("缩小", "已打开工程", kNav, false, false, false, kAll, kAnyLayer)},
        {"full_extent", spec("全图", "已打开工程", "视图回到工区全幅；不修改数据", false, false, false, kAll, kAnyLayer)},
        {"previous_extent", spec("上一视图", "存在可回退的视图历史", "视图回退一步；不修改数据", false, false, false, kAll, kAnyLayer)},
        {"next_extent", spec("下一视图", "存在可前进的视图历史", "视图前进一步；不修改数据", false, false, false, kAll, kAnyLayer)},
        {"refresh", spec("刷新", "已打开工程", "重绘画布；不修改数据", false, false, false, kAll, kAnyLayer)},
        {"identify", spec("识别", "有可查询图层（工程已打开）", "点击查询要素属性（只读）；不修改数据", false, false, false, kAll, kAnyLayer)},
        {"select", spec("选择", "有活动矢量图层", "点选要素；只改选择集，不改数据")},
        {"select_rectangle", spec("框选", "有活动矢量图层", "框选要素；只改选择集，不改数据")},
        {"measure_distance", spec("测距", "有活动图层", "量测距离（原生椭球或降级平面）；不修改数据", false, false, false, kAll, kAnyLayer)},
        {"clear_selection", spec("清除选择", "有选中的要素", "清空选择集；不修改数据")},
        {"select_all", spec("全选", "有活动矢量图层", "全选要素；只改选择集，不改数据")},
        {"invert_selection", spec("反选", "有选中的要素", "反选要素；只改选择集，不改数据")},
        {"toggle_editing", spec(
             "开始编辑", "活动矢量图层可写且通过角色门禁（RAW/冻结/锁定不可编辑）",
             "开启/结束编辑会话（结束即保存）", true)},
        {"save_edits", spec(
             "保存编辑", "编辑会话中有未保存修改",
             "提交本会话修改到图层（生成会话撤销记录）", true, true)},
        {"rollback", spec(
             "回滚", "编辑会话中有可回滚修改",
             "丢弃本会话全部未保存修改", true)},
        {"add_point", spec(
             "添加点", "编辑会话中 + 点图层 + 角色门禁通过",
             "在画布采点写入活动图层", true)},
        {"add_line", spec(
             "添加线", "编辑会话中 + 线图层 + 角色门禁通过",
             "在画布采线写入活动图层", true)},
        {"add_polygon", spec(
             "添加面", "编辑会话中 + 面图层 + 角色门禁通过",
             "在画布采面写入活动图层", true)},
        {"move_feature", spec(
             "移动要素", "编辑会话中 + 已选中要素",
             "拖动改变要素位置", true)},
        {"vertex", spec(
             "节点编辑", "编辑会话中 + 已选中要素",
             "增删移要素节点", true)},
        {"delete_selected", spec(
             "删除所选", "编辑会话中 + 已选中要素",
             "删除选中要素（会话内可撤销）", true)},
        {"reshape", spec(
             "重塑", "原生 QGIS 画布 + 线/面图层 + 恰好选中 1 个要素 + 编辑会话",
             "用数字化线重塑选中要素边界（QGIS 原生算子）", true)},
        {"split", spec(
             "分割", "编辑会话中的面图层 + 选中多边形 + 选中的切割线",
             "沿切割线分割多边形（QGIS/shapely 双引擎）", true)},
        {"merge", spec(
             "合并", "同一可编辑面图层至少选中 2 个兼容多边形 + 无拓扑错误",
             "合并选中面要素（QGIS/shapely 双引擎）", true)},
        {"repair_geometry", spec(
             "修复几何", "可写面图层 + 角色门禁通过",
             "对面图层执行 make-valid 修复（可撤销）", true)},
        {"duplicate_selected", spec(
             "复制要素", "编辑会话中 + 已选中要素",
             "复制选中要素（几何+属性，新要素 id，可撤销）", true)},
        {"add_ring", spec(
             "添加内环", "原生画布 + 面图层 + 恰好选中 1 个面要素 + 编辑会话",
             "在选中面要素内数字化一个内环（洞）", true)},
        {"add_part", spec(
             "添加部件", "原生画布 + 恰好选中 1 个要素 + 编辑会话",
             "为选中要素数字化并附加部件（单部件自动升多部件）", true)},
        {"explode_multipart", spec(
             "拆分多部件", "编辑会话中 + 选中至少一个多部件要素",
             "把多部件要素拆分为单部件要素（属性全继承）", true)},
        {"collect_multipart", spec(
             "组合多部件", "编辑会话中 + ≥2 个同类型单部件要素 + 无拓扑错误",
             "把选中单部件要素组合为一个多部件要素（不融合边界）", true)},
        {"undo", spec("撤销", "编辑会话中有可撤销操作", "撤销上一步编辑", true)},
        {"redo", spec("重做", "编辑会话中有可重做操作", "重做被撤销的编辑", true)},
        {"snapping", spec(
             "捕捉", "有活动图层",
             "开关采点/编辑捕捉（endpoint/intersection 由桥能力决定）")},
        {"avoid_intersections", spec(
             "避免重叠", "有活动图层",
             "编辑时裁掉与目标层重叠的部分（QGIS avoid overlap；默认开）", true)},
        {"tracing", spec(
             "追踪", "原生画布 + 捕捉引擎可用",
             "采点时沿既有边/已有要素的边继续（点取交点自动加点）")},
        {"vertex_scope", spec(
             "顶点范围", "编辑会话中 + 原生画布",
             "节点工具的作用范围：全部层（勾选）或当前层（未勾选）")},
        {"fault_cut", spec(
             "断层切割", "面图层编辑会话中 + 原生画布",
             "数字化切割线，把面沿断层截断（C++ 守恒校验）", true)},
        {"boundary_reshape", spec(
             "共边重塑", "面图层编辑会话中 + 恰好选中两个相邻要素 + 原生画布",
             "数字化新界线联动重塑两面的共享弧（守恒校验失败零变更）", true)},
        {"delete_ring", spec(
             "删除内环", "面图层编辑会话中 + 选中一个要素",
             "右键内环定位 → 删除该内环", true)},
        {"delete_part", spec(
             "删除部件", "多部件要素编辑会话中 + 选中一个要素",
             "右键部件定位 → 删除该部件", true)},
        {"reverse_line", spec(
             "反转方向", "编辑会话中 + 选中要素",
             "反转所选线/环的方向", true)},
        {"simplify_feature", spec(
             "简化要素", "编辑会话中 + 选中要素",
             "按容差抽稀所选要素几何（Visvalingam/Douglas-Peucker）", true)},
        {"smooth_feature", spec(
             "平滑要素", "编辑会话中 + 选中要素",
             "平滑所选要素几何（Chaikin）", true)},
        {"offset_curve", spec(
             "偏移曲线", "编辑会话中 + 选中要素",
             "按距离偏移所选线", true)},
        {"rotate_feature", spec(
             "旋转要素", "编辑会话中 + 选中要素",
             "绕选集质心旋转所选要素", true)},
        {"scale_feature", spec(
             "缩放要素", "编辑会话中 + 选中要素",
             "绕选集质心缩放所选要素", true)},
        {"cut_features", spec(
             "剪切", "选中要素 + 编辑会话",
             "剪切所选要素到内部剪贴板", true)},
        {"copy_features", spec(
             "复制", "选中要素",
             "复制所选要素到内部剪贴板")},
        {"paste_features", spec(
             "粘贴", "编辑会话中",
             "把内部剪贴板粘贴到活动图层（字段按 schema 映射）", true)},
        {"add_rectangle", spec(
             "添加矩形", "面图层编辑会话中",
             "两次左键定对角，自动闭合矩形面", true)},
        {"add_circle", spec(
             "添加圆", "面图层编辑会话中",
             "圆心 + 半径点，64 边近似圆面", true)},
        {"snap_geometries", spec(
             "吸附对齐", "编辑会话中 + 选中要素",
             "把选中要素顶点逐个吸附到捕捉命中处", true)},
        {"add_arc", spec(
             "添加圆弧", "线图层编辑会话中",
             "起点 + 过弧点 + 终点三点定圆弧（退化回落折线）", true)},
        {"add_regular_polygon", spec(
             "添加正多边形", "面图层编辑会话中",
             "中心 + 半径点，默认 6 边", true)},
        {"trim_line", spec(
             "修剪线", "线图层编辑会话中 + 选中要素",
             "按边界裁剪所选线（保留内部/外部）", true)},
        {"extend_line", spec(
             "延伸线", "线图层编辑会话中 + 选中要素",
             "把所选线端点沿方向延伸到边界", true)},
        {"fill_ring", spec(
             "填充内环", "面图层编辑会话中 + 选中一个要素",
             "右键内环定位 → 环转面（属性克隆，原面去环）", true)},
        {"change_facies", spec(
             "更改相", "相带图层 + 选中要素（编辑中亦可）",
             "弹出相列表（可细化亚相/微相）→ 确定即改所选要素的相属性与标注", true)},
        {"add_ellipse", spec(
             "添加椭圆", "面图层编辑会话中",
             "中心 + 长半轴点 + 短半轴点", true)},
        {"add_sector", spec(
             "添加扇形", "面图层编辑会话中",
             "中心 + 起角点 + 止角点（逆时针扫过，起止同方位 = 整圆）", true)},
        {"topology", spec(
             "拓扑编辑", "有活动图层 + 工程 CRS 有效",
             "开关拓扑编辑（编辑期联动 + 保存时校验）", true)},
        {"cancel", spec("取消", "无", "取消当前工具/Esc 数字化", false, false, false, kAll, kAnyLayer)},
        {"layer_new", spec("新建图层", "已打开工程", "新建空白矢量图层（按模板）", true)},
        {"reference_import", spec(
             "导入参考图层", "已打开工程",
             "导入外部 GDAL 参考层（只读；不修改源文件）", false, false, false, kAll, kAnyLayer)},
        {"layer_properties", spec(
             "图层属性", "有活动图层", "打开图层属性/符号编辑", false, false, false, kAll, kAnyLayer)},
        {"attribute_table", spec(
             "属性表", "有活动图层", "打开只读/编辑属性表", false, false, false, kAll, kAnyLayer)},
        {"layer_zoom", spec(
             "缩放到图层", "有活动图层", "视图缩放到图层范围", false, false, false, kAll, kAnyLayer)},
        {"layer_export", spec(
             "导出图层", "有活动图层", "导出图层为 GeoJSON/Shapefile", false, false, false, kAll, kAnyLayer)},
        {"symbology", spec(
             "符号系统", "有活动图层", "打开符号系统设置（不改几何数据）", false, false, false, kAll, kAnyLayer)},
        {"style_manager", spec(
             "样式库", "QGIS 原生后端 + 有活动图层",
             "打开 QGIS 原生样式库管理", false, false, false, kAll, kAnyLayer)},
        {"factor_workbench", spec(
             "单因素工作台", "阶段② 约束与因素",
             "打开单因素图生成工作台（后台任务）", false, false, true, "② 约束与因素", kAnyLayer)},
        {"factor_overlay", spec(
             "叠加等值线", "阶段② 约束与因素",
             "把因素结果叠加为参考层", true, false, false, "② 约束与因素", kAnyLayer)},
        {"qa_run", spec(
             "运行 QC", "已打开工程", "运行图面质量检查（只读诊断）", false, false, false, kAll, kAnyLayer)},
        {"map_product_assemble", spec(
             "生成成果", "阶段③ 综合编图",
             "组装综合编图成果（生成新版本工件）", true, true, true, "③ 综合编图", kAnyLayer)},
        {"map_export", spec(
             "导出图面", "阶段③ 综合编图",
             "进入图面组装与导出（review 页）", false, false, false, "③ 综合编图", kAnyLayer)},
    };
    return help;
}

const ToolHelpSpec* tool_help_for(const std::string& tool_id) {
    const auto it = tool_help().find(tool_id);
    return it != tool_help().end() ? &it->second : nullptr;
}

std::string tool_label(const std::string& tool_id) {
    const auto it = tool_labels().find(tool_id);
    return it != tool_labels().end() ? it->second : tool_id;
}

std::string tool_shortcut(const std::string& tool_id) {
    const auto it = tool_shortcuts().find(tool_id);
    return it != tool_shortcuts().end() ? it->second : std::string();
}

}  // namespace pwb::ui_workstation
