#pragma once

// Port of paleo_workbench/mapping_workspace/capture_spec.py (UI-13):
// GeologicalCaptureSpec — 角色驱动的捕获语义（V9 W9，Goal §6/§12）。
//
// 用户选择「物源方向线」这类地质捕获目标时，Paleo 负责语义（LayerRole、
// 阶段绑定、模板字段默认值、捕捉推荐、拓扑提示），QGIS/会话层负责几何
// 捕获本身。本模块是这一分工的单一派生点：
// role → (template_key, snapping profile, 拓扑提示, 约束语义)。
//
// 不做的事（防第二真源）：
// * 不复制 GeoTemplate 的字段 schema——template_key 指回模板注册表，
//   默认属性由模板 field_defaults() 派生；
// * 不新建 ToolAvailability/第二门禁；
// * 不替代 stage membership 的角色权威。
//
// Qt-free.

#include <optional>
#include <string>

#include <pwb/ui_composite/snapping_profiles.hpp>

namespace pwb::ui_composite {

// 一个角色目标的捕获语义（Paleo 语义层；几何执行归 QGIS/会话）。
struct GeologicalCaptureSpec {
    std::string role;                        // LayerRole 值
    std::string geometry_kind;               // "point" | "line" | "polygon"
    std::string template_key;                // GeoTemplate 键（"" = 无模板）
    const SnappingProfile* snapping_profile = nullptr;
    // 拓扑编辑建议（推荐值；开闭仍由用户/阶段状态决定）。
    bool recommend_topological_editing = false;
    std::optional<std::string> constraint_kind;  // ConstraintKind 值

    std::string role_label() const;

    bool operator==(const GeologicalCaptureSpec&) const = default;
};

// 角色 → 捕获语义；无编辑语义/未知角色返回 nullptr（不猜）。
const GeologicalCaptureSpec* capture_spec_for_role(
    const std::string& role_value);

}  // namespace pwb::ui_composite
