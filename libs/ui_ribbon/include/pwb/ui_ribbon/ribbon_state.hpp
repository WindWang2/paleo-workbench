#pragma once

// UI-18 — Ribbon 三模式状态机 + 禁用原因通道 (Qt-free core).
//
// Three modes (R:21-23, 设计规范 docs/ui-redesign/
// qt-ribbon-workspaces-2026-09-21/README.md 层次与尺寸):
//   * Standard — 命令带目标 76–96 逻辑像素（不含标签行），主按钮 32px
//     图标 + 文字在下（最多两行），次级动作 16–20px，组名在底部；
//   * Compact  — 命令带 40–48 逻辑像素，小图标 + 文字在侧，空间不足时
//     次级动作进组内溢出菜单。禁止不断缩小文字（C3）；
//   * Collapsed— 只保留标签行；点击标签临时展开，选择命令或 Esc 后收回。
//
// The model is pure state (no Qt): the RibbonBar Qt shell projects it onto
// widgets. True-change setters return whether anything actually moved —
// the same contract as ThemeService/StageFlowController.

#include <functional>
#include <string>

namespace pwb::ui_ribbon {

enum class RibbonMode { Standard, Compact, Collapsed };

// 命令带高度区间（逻辑像素，不含标签行）。Collapsed 不带命令带。
inline constexpr int kStandardBandMinHeight = 76;
inline constexpr int kStandardBandMaxHeight = 96;
inline constexpr int kCompactBandMinHeight = 40;
inline constexpr int kCompactBandMaxHeight = 48;

struct RibbonModeMetrics {
    int min_height = 0;
    int max_height = 0;
};

RibbonModeMetrics metrics_for(RibbonMode mode);

class RibbonModeState {
public:
    // Collapsed wins over compact: a collapsed ribbon shows no band at
    // all, and the compact preference survives the collapse (re-expanding
    // restores it).
    RibbonMode mode() const {
        return collapsed_ ? RibbonMode::Collapsed
                          : (compact_ ? RibbonMode::Compact
                                      : RibbonMode::Standard);
    }
    bool compact() const { return compact_; }
    bool collapsed() const { return collapsed_; }

    bool set_compact(bool on);
    bool set_collapsed(bool on);
    bool toggle_collapsed();
    bool toggle_compact();

    // Temporary expansion while collapsed (R:23): clicking a tab shows
    // the band until a command runs or Esc dismisses it. Only meaningful
    // when collapsed(); setting it while expanded is ignored.
    bool temporarily_expanded() const { return temporarily_expanded_; }
    void set_temporarily_expanded(bool on);

    // The mode the shell must realize right now.
    RibbonMode effective_mode() const {
        if (!collapsed_) return compact_ ? RibbonMode::Compact
                                         : RibbonMode::Standard;
        return temporarily_expanded_
                   ? (compact_ ? RibbonMode::Compact : RibbonMode::Standard)
                   : RibbonMode::Collapsed;
    }
    bool band_visible() const {
        return effective_mode() != RibbonMode::Collapsed;
    }

private:
    bool compact_ = false;
    bool collapsed_ = false;
    bool temporarily_expanded_ = false;
};

// ---------------------------------------------------------------------------
// 禁用原因通道 — the host injects the evaluator (typically a lambda over
// the CommandRegistry availability verdicts); this library never links
// CommandRegistry, so the core stays Qt-free with zero link deps.
// ---------------------------------------------------------------------------

struct CommandState {
    bool enabled = true;
    std::string reason;  // non-empty only when !enabled (fail-closed reason)
};

using CommandEvaluator =
    std::function<CommandState(const std::string& command_id)>;

// Resolve one command's availability through an injected evaluator.
// Without an evaluator the command is enabled: the channel is additive
// (the host QAction's own enabled state stays authoritative — D4), so an
// unwired chrome never fabricates a gate.
CommandState evaluate_command(const CommandEvaluator& evaluator,
                              const std::string& command_id);

}  // namespace pwb::ui_ribbon
