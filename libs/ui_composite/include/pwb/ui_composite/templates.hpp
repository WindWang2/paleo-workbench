#pragma once

// Port of the template vocabulary + EditTargetSnapshot from
// paleo_workbench/ui/workstation/composite_editing.py (UI-13).
//
// GeoTemplate is the data-driven starting point for professional
// digitizing (QGIS「新建 Shapefile 图层」的地质版): role + geometry kind
// + field schema + default style. Attribute table / layer properties /
// validation all derive from the schema — nothing is hardcoded into UI
// widget trees.
//
// EditTargetSnapshot is the V11 five-target model (07-active-edit-state)
// read-only snapshot; the invariant (pinned by test_edit_targets_v11):
// with no gesture in flight all four layer targets coincide; while a
// capture gesture runs, tool/edit targets lock to the session layer and
// the UI must present the divergence.
//
// Qt-free; serialization uses pwb::domain::Json.

#include <map>
#include <optional>
#include <set>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/ui_composite/map_styles.hpp>

namespace pwb::ui_composite {

using pwb::domain::Json;

// Geometry-kind vocabulary for user vector layers.
inline const std::vector<std::string>& geometry_kinds() {
    static const std::vector<std::string> kinds = {"point", "line",
                                                   "polygon"};
    return kinds;
}

const std::map<std::string, std::string>& geometry_kind_labels();

// 地质图层字段描述：数据驱动的可扩展 schema。
// kind ∈ text / number / choice；choice 字段携带候选值。default 是新要
// 素的初始属性值；required 驱动属性校验（标记缺失，不阻断数字化）。
struct TemplateField {
    std::string name;
    std::string label;
    std::string kind = "text";  // "text" | "number" | "choice"
    std::vector<std::string> choices;
    Json default_value;
    bool required = false;

    Json to_dict() const;
    // Strict-ish parse: non-object or missing name → throws
    // std::invalid_argument (Python ValueError parity); unknown kinds
    // fall back to "text"; choice without choices degrades to "text".
    static TemplateField from_dict(const Json& data);

    bool operator==(const TemplateField&) const = default;
};

Json fields_to_schema(const std::vector<TemplateField>& fields);
// Tolerant schema → fields (unparseable entries skipped).
std::vector<TemplateField> schema_fields(const Json& schema);

// 地质矢量图层模板：角色 + 几何类型 + 字段 schema + 默认样式。
struct GeoTemplate {
    std::string key;
    std::string label;
    std::string kind;
    VectorStyle style;
    std::vector<TemplateField> fields;

    // name → default for fields with a non-empty default.
    Json field_defaults() const;

    bool operator==(const GeoTemplate&) const = default;
};

// 新建矢量图层的地质模板（注册表顺序 = GEO_TEMPLATES tuple 顺序）。
const std::vector<GeoTemplate>& geo_templates();

const GeoTemplate* template_by_key(const std::string& key);

// 相带模板家族（分级变体，词表驱动字段 + 捕获后标注流）。
const std::set<std::string>& facies_template_keys();

// 相带模板键 → 图层级解释深度（"facies"|"sub_facies"|"micro_facies"）；
// 非相带模板返回 nullopt。
std::optional<std::string> facies_template_level(
    const std::string& template_key);

// 控制器模板注册表里的图层是否属于相带家族。
bool is_facies_template_layer(
    const std::map<std::string, std::string>& templates,
    const std::string& layer_id);

// 相带家族判定（V12 任务3：模板或角色任一命中）。模板注册表覆盖手绘/
// 旧相图层；科学角色覆盖预测/草稿/综合相这类无模板键的相图层。换相
// 门禁与画布要素右键菜单共用本函数，杜绝两套「相带」定义分叉。
bool is_facies_family_layer(
    const std::map<std::string, std::string>& templates,
    const std::string& layer_id, const std::string& role_value = "");

// V11 五目标模型的只读快照（见类型注释上方总述）。
struct EditTargetSnapshot {
    // QGIS 树选中节点（信息性；来自面板回写）。
    std::optional<std::string> selected_tree_node;
    // 画布/面板的当前图层（原生 select/identify 目标）。
    std::optional<std::string> active_map_layer;
    // 唯一编辑目标（捕获手势进行中 = 会话层；否则跟随活动图层）。
    std::optional<std::string> edit_target_layer;
    // 活动工具实际写入层（会话工具持有会话时 = 该会话的图层）。
    std::optional<std::string> tool_target_layer;
    // 属性表/选择集上下文（当前 = 活动图层）。
    std::optional<std::string> selection_layer;

    bool divergent() const {
        return tool_target_layer != active_map_layer;
    }

    bool operator==(const EditTargetSnapshot&) const = default;
};

}  // namespace pwb::ui_composite
