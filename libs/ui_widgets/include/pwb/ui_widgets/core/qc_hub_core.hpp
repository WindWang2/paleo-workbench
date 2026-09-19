#pragma once

// UI-02 — QC hub pure logic, ported from the Qt-free halves of
// paleo_workbench/ui/components/interactive_qc_hub.py and the
// QuickFixAction metadata of paleo_workbench/mapping/qc_quickfix.py.
//
// The action *implementations* (shapely geometry) stay document-domain —
// the C++ side carries the action registry metadata (id/title/description/
// rules) and the host injects availability/apply gates.

#include <array>
#include <functional>
#include <map>
#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace pwb::ui_widgets::core {

// D9 pan timing + focus pad (frozen values).
inline constexpr int kPanDurationMs = 180;
inline constexpr int kPanTickMs = 20;
inline constexpr double kFocusPad = 0.10;

// bbox pad outward (matches the _zoom 10% pad semantics).
[[nodiscard]] std::array<double, 4> padded_bbox(
    const std::vector<double>& bbox, double pad = kFocusPad);

// cubic ease-in-out over [0,1] (clamped input).
[[nodiscard]] double ease_in_out(double t);

// Quick-fix action metadata (registry entry; availability/apply are
// host-injected gates — geometry stays in the document domain).
struct QuickFixActionMeta {
    std::string action_id;
    std::string title;
    std::string description;
    std::vector<std::string> rules;
};

// The two frozen registry entries (sliver_merge, tangent_close) with their
// rule sets — preserves the rule -> action mapping; availability/apply are
// provided by the host fix gate.
[[nodiscard]] const std::vector<QuickFixActionMeta>& quick_fix_registry();

// actions_for_rule: registry entries whose rules contain `rule` (order
// preserved).
[[nodiscard]] std::vector<QuickFixActionMeta> actions_for_rule(
    const std::string& rule,
    const std::vector<QuickFixActionMeta>& registry = quick_fix_registry());

}  // namespace pwb::ui_widgets::core
