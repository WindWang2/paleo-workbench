#pragma once

// Port of paleo_workbench/ui/workstation/attribute_schema.py (UI-13):
// attribute-table field descriptors — QGIS provider schema consumption
// (V9 W5).
//
// 「一层在属性表里如何呈现/编辑」收敛为单一派生：
// 1. 字段元数据（AttributeFieldMeta）——图层有角色时取
//    GeologicalLayerSpec（与镜像 fields_json 同一权威）；无角色回落模
//    板 schema；额外属性键以 text 附加。
// 2. QGIS provider parity（qgis_schema_parity）——发布后的
//    mirror_layer_schema_json（QGIS 真实 QgsFields）与派生描述比对，
//    给出 synced/drift/unavailable 三态与差异明细。
//
// 不做的（防第二真源）：不复制 spec 字段值语义（校验在写入路径经会
// 话/schema 执行）；不发明 QGIS 之外的控件词表（ValueMap/Range/
// CheckBox 与 qgis_layer_schema 推断同词）。
//
// Qt-free.

#include <functional>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/ui_composite/vector_layer.hpp>

namespace pwb::ui_composite {

using pwb::domain::Json;

// 属性表一列的呈现/编辑元数据（spec→模板→额外键 单一派生）。
struct AttributeFieldMeta {
    std::string key;
    std::string label;
    std::string kind;                        // text/int/real/bool/datetime
    std::vector<std::string> choices;
    bool required = false;
    bool unique = false;
    std::string expression;
    std::optional<std::pair<double, double>> value_range;
    // QGIS 控件词汇（ValueMap/Range/CheckBox…）
    std::string editor_widget;
    // 来源标记：spec（角色权威）/ template（模板）/ extra（要素属性键）。
    std::string origin = "template";

    bool numeric() const { return kind == "int" || kind == "real"; }

    bool operator==(const AttributeFieldMeta&) const = default;
};

// 控制器鸭子类型注入面（CompositeEditController 需要的三个读口）。
// role_of_layer: layer_id → LayerRole 值（"" = 无角色）。
// layer_schema:  layer_id → 模板 schema dict。
// layer:       layer_id → VectorLayer*（nullopt = 未注册）。
struct AttributeLayerSource {
    std::function<std::string(const std::string&)> role_of_layer;
    std::function<Json(const std::string&)> layer_schema;
    std::function<const VectorLayer*(const std::string&)> layer;
};

// 一层属性表的列元数据（spec 优先 → 模板 → 额外键；额外键不变 spec
// 序）。空结果回落单列 {"id","ID","text",origin=extra}。
std::vector<AttributeFieldMeta> field_descriptors_for_layer(
    const AttributeLayerSource& source, const std::string& layer_id);

// mirror_layer_schema_json probe: layer_id → {"exists": bool,
// "fields": [{"name": ...}]} payload（QGIS 侧事实）。未安装 probe = 旧
// 桥/回退画布（unavailable）。
using MirrorSchemaProbe = std::function<Json(const std::string&)>;

// QGIS provider schema 与派生描述的比对（呈现标注用）。
// 返回 (state, detail)：state ∈ synced/drift/unavailable。数据权威仍
// 是 Python 会话——drift 只呈现（字段级差异进 detail），不阻塞编辑。
std::pair<std::string, std::string> qgis_schema_parity(
    const MirrorSchemaProbe& probe, const std::string& layer_id,
    const std::vector<AttributeFieldMeta>& descriptors);

}  // namespace pwb::ui_composite
