#pragma once

// Port of paleo_workbench/mapping_workspace/snapping_profiles.py (UI-13):
// per-LayerRole recommended snapping configuration with rationale.
//
// 推荐 ≠ 硬编码真值：profile 给出可解释的默认捕捉模式/容差/拓扑提示，
// 供 SnappingSettingsDialog 预填与 GeologicalCaptureSpec 应用——用户可
// 覆盖，覆盖后即用户配置（SnappingService 既有 per-layer 覆盖通道）。
//
// 模式词表 = SnappingService.modes 既有词汇（vertex/segment/midpoint/
// endpoint/intersection/reference/grid）——不发明第二套模式语言。
// Qt-free.

#include <optional>
#include <set>
#include <string>

namespace pwb::ui_composite {

// 一个角色类别的推荐捕捉配置（解释先行，用户可覆盖）。
struct SnappingProfile {
    // 代表角色（profile 的归属标注；按簇聚合）。
    std::string role;
    // 推荐模式集（SnappingService.modes 词表）。
    std::set<std::string> modes;
    // 推荐像素容差（QGIS 桌面默认 12px 上下浮动）。
    double tolerance_px = 10.0;
    // 是否建议开启拓扑编辑（共享节点传播 + 保存校验）。
    bool topological = false;
    // 推荐理由（呈现给用户的解释，不是内部注释）。
    std::string rationale;

    bool operator==(const SnappingProfile&) const = default;
};

// 角色 → 推荐 profile；无编辑语义/未知角色返回 nullopt（不猜）。
// RAW 保护角色（原始相图/模型结果）不可编辑——推荐无意义，返回 nullopt。
const SnappingProfile* recommended_profile_for_role(
    const std::string& role_value);

// profile 的一句话呈现（对话框/状态条用）。
std::string profile_summary(const SnappingProfile& profile);

}  // namespace pwb::ui_composite
