#pragma once

// Port of paleo_workbench/ui/workstation/layer_decorations.py (UI-13):
// 图层呈现态聚合（V7 goal §7）：树/检查器共用的装饰真源。
//
// 设计约束：
// * 纯数据：不 import Qt——呈现态的计算可全量单测；
// * 不建第二权威：输入全部来自既有权威的结论（freshness / membership
//   成熟度 / VectorEditSession 会话态）；本模块只定义聚合与呈现次序；
// * 词汇单一：装饰 glyph/label/tone 一律经 pwb::ui_workstation 的
//   state_token（freshness/session/maturity 词表），不另造词；
// * 诚实：未知 = 无装饰；缺失图层（不在编辑注册表）显式「缺失」。
//
// Qt-free (depends on pwb_ui_workstation's Qt-free state_language).

#include <optional>
#include <string>
#include <utility>

#include <pwb/ui_workstation/state_language.hpp>

namespace pwb::ui_composite {

using pwb::ui_workstation::StateToken;

// 一个图层的呈现信号集（全部默认 false/nullopt = 干净）。
struct LayerPresentationState {
    bool editing = false;
    bool dirty = false;            // 会话有未保存修改（undo 栈非空）
    bool stale = false;
    bool missing_input = false;    // 新鲜度：输入缺失（error 级）
    bool superseded = false;       // 新鲜度：已被取代
    bool degraded = false;         // 数据源降级（参考图层刷新失败等）
    // raw/draft/reviewed/frozen/published
    std::optional<std::string> maturity;
    bool missing = false;          // 图层不在编辑注册表（被删除/未落盘）

    bool operator==(const LayerPresentationState&) const = default;
};

// 主装饰（状态列单信号；nullopt = 干净无装饰）。返回 (kind, token) —
// kind ∈ missing/dirty/editing/missing_input/superseded/stale/degraded/
// frozen/published/reviewed，按装饰优先级前者胜出。
std::optional<std::pair<std::string, StateToken>> primary_decoration(
    const LayerPresentationState& state);

// 主装饰的词汇 token（glyph+label+tone）。
std::optional<StateToken> decoration_token(
    const LayerPresentationState& state);

// hover 摘要：全部信号（非仅主信号）拼为「·」分隔文本。
std::string decoration_summary_text(const LayerPresentationState& state);

// 组级真实聚合（stale/error/running/pending/published 计数；计数来自
// group_summary + 任务/成熟度权威，本结构只承载与呈现）。
struct GroupPresentationSummary {
    std::string group_id;
    std::string title;
    int layers = 0;
    int stale = 0;
    int errors = 0;
    int running = 0;
    int pending = 0;
    int frozen = 0;
    int published = 0;

    bool has_problems() const { return stale > 0 || errors > 0; }
    std::string summary_text() const;

    bool operator==(const GroupPresentationSummary&) const = default;
};

// 从权威结论构造呈现态（宿主适配器的规范入口）。
// freshness_status 为 FreshnessStatus 值（"" = 未知 → 无新鲜度信号）；
// session_undo_depth>0 视为 dirty。
LayerPresentationState presentation_state(
    bool editing = false, int session_undo_depth = 0,
    const std::string& freshness_status = "",
    const std::optional<std::string>& maturity = std::nullopt,
    bool missing = false, bool degraded = false);

}  // namespace pwb::ui_composite
