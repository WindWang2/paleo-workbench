#pragma once

// Port of paleo_workbench/mapping/merge_attributes.py (UI-13): 合并属性
// 计划（拓扑编辑迁移 M3 §4 无缝合并）。
//
// 对话框预填「面积最大要素」属性，并标出字段冲突（相分类字段优先）。
// 纯逻辑：无 Qt、无桥。

#include <string>
#include <vector>

#include <pwb/domain/json.hpp>

namespace pwb::ui_composite {

using pwb::domain::Json;

// polygon_area: 多边形面积（绝对 shoelace；MultiPolygon 累加外环）。
double polygon_area(const Json& geometry);

// plan_merge_attributes: 预填最大面积要素属性，并列出字段冲突。
//
// records 项形如 {"id", "geometry", "properties"}。返回
// {"target_id", "attributes", "conflicts", "facies_fields"}；conflicts
// 为字段 → 互异值列表（出现顺序）。
Json plan_merge_attributes(
    const std::vector<Json>& records,
    const std::vector<std::string>& facies_fields = {"facies"});

}  // namespace pwb::ui_composite
